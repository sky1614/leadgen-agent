import json
from datetime import date, datetime

from .celery_app import celery
from ..database import SessionLocal
from ..models import ClientDB, UserDB, CampaignDB, LeadDB, AgentJobDB, AgentJobItemDB
from ..services.groq_service import ai_enrich, ai_message
from ..services.scraper_service import SAMPLE_LEADS
from ..utils import make_fingerprint


def _is_blackout(client: ClientDB) -> bool:
    try:
        from ..services.cultural_service import is_blackout_date
        result = is_blackout_date(date.today(), client.id)
        return result["is_blackout"] and result["type"] == "full_blackout"
    except Exception:
        today = date.today().isoformat()
        return today in (client.festival_blackout_dates or [])

@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def run_agent_for_client(self, client_id: str):
    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id, ClientDB.is_active == True).first()
        if not client:
            return {"skipped": True, "reason": "client not found or inactive"}

        # Festival blackout check
        if _is_blackout(client):
            return {"skipped": True, "reason": "festival blackout date"}

        # Get first user of this client
        user = db.query(UserDB).filter(UserDB.client_id == client_id).first()
        if not user:
            return {"skipped": True, "reason": "no user found for client"}

        # Check monthly lead cap
        if user.leads_used >= user.leads_limit:
            return {"skipped": True, "reason": "monthly lead cap reached"}

        # Get active campaign
        camp = db.query(CampaignDB).filter(
            CampaignDB.client_id == client_id,
            CampaignDB.status == "active"
        ).first()
        if not camp:
            return {"skipped": True, "reason": "no active campaign"}

        # Create agent job
        job = AgentJobDB(
            user_id=user.id, client_id=client_id,
            campaign_id=camp.id, industry=client.industry or "SaaS",
            source_url="", status="running"
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        raw_leads = SAMPLE_LEADS.get(client.industry or "SaaS", [])
        processed = 0

        # ── Reflexion: load context ───────────────────────────────────────
        reflection_context = ""
        try:
            from ..services.reflexion_service import build_reflection_context
            reflection_context = build_reflection_context(client_id, client.industry or "SaaS", db)
        except Exception as _re:
            print(f"REFLEXION context load non-blocking error: {_re}")

        for ld in raw_leads:
            if user.leads_used >= user.leads_limit:
                break

            fp = make_fingerprint(ld.get("name", ""), ld.get("company", ""), ld.get("email", ""), ld.get("whatsapp", ""))
            existing = db.query(LeadDB).filter(LeadDB.fingerprint == fp, LeadDB.client_id == client_id).first()
            if existing:
                lead = existing
            else:
                lead = LeadDB(
                    user_id=user.id, client_id=client_id, fingerprint=fp, source="agent_auto",
                    **{k: v for k, v in ld.items() if k in ["name", "company", "email", "whatsapp", "industry", "role", "website", "notes"]}
                )
                db.add(lead)
                user.leads_used += 1
                db.commit()
                db.refresh(lead)

            enrichment = ai_enrich(lead)
            lead.enrichment_json = json.dumps(enrichment)
            lead.fit_score = enrichment.get("fit_score", 5)
            if lead.fit_score < 5:
                lead.status = "skipped"
                db.commit()
                continue

            lead.status = "enriched"
            db.commit()

            from ..services.groq_service import generate_message
            email_msg = generate_message(lead, camp, "email", client_id=client_id,
                                         reflection_context=reflection_context).get("message", "")
            wa_msg = generate_message(lead, camp, "whatsapp", client_id=client_id,
                                      reflection_context=reflection_context).get("message", "")


            item = AgentJobItemDB(
                job_id=job.id, client_id=client_id,
                lead_id=lead.id, lead_name=lead.name,
                lead_company=lead.company, lead_email=lead.email,
                lead_whatsapp=lead.whatsapp, fit_score=lead.fit_score,
                email_message=email_msg, whatsapp_message=wa_msg
            )
            db.add(item)
            job.total_leads += 1
            processed += 1
            db.commit()

        job.status = "pending_approval"
        
        # ── Autonomous loop: trigger post-run evaluation ──────────────────
        try:
            import threading as _threading
            from ..database import SessionLocal as _SL
            from ..services.autonomous_loop import run_autonomous_evaluation as _eval

            def _bg_eval():
                _db = _SL()
                try:
                    _eval(client_id, _db)
                except Exception as _e:
                    print(f"AUTONOMOUS LOOP bg eval error: {_e}")
                finally:
                    _db.close()

            _threading.Thread(target=_bg_eval, daemon=True).start()
        except Exception as _ae:
            print(f"AUTONOMOUS LOOP trigger failed (non-blocking): {_ae}")

        # ── Reflexion: analyze and store ─────────────────────────────────
        try:
            from ..services.reflexion_service import analyze_job_failures, generate_reflection, save_reflection
            failures = analyze_job_failures(job.id, client_id, db)
            if failures:
                camp_ctx = {"industry": client.industry or "SaaS", "tone": getattr(camp, "tone", "professional")}
                reflection = generate_reflection(failures, camp_ctx, client_id)
                if reflection:
                    save_reflection(client_id, job.id, reflection, db, industry=client.industry or "SaaS")
        except Exception as _re:
            print(f"REFLEXION non-blocking error: {_re}")
        db.commit()
        return {"success": True, "client_id": client_id, "leads_processed": processed}

    except Exception as exc:
        print(f"AGENT TASK ERROR for client {client_id}: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"error": str(exc), "client_id": client_id}
    finally:
        db.close()


@celery.task
def run_all_agents():
    db = SessionLocal()
    try:
        clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
        for client in clients:
            run_agent_for_client.delay(client.id)
        return {"dispatched": len(clients)}
    finally:
        db.close()


@celery.task
def weekly_report():
    """Deprecated — use report_tasks.send_weekly_reports instead."""
    from .report_tasks import send_weekly_reports
    return send_weekly_reports()

@celery.task(bind=True, max_retries=3)
def verify_unverified_leads(self, client_id: str):
    from ..database import SessionLocal
    from ..models import LeadDB
    from ..services.verification_service import verify_lead_contacts
    db = SessionLocal()
    try:
        leads = db.query(LeadDB).filter(
            LeadDB.client_id == client_id,
            LeadDB.email_verified == None
        ).limit(50).all()

        verified = 0
        for lead in leads:
            try:
                verify_lead_contacts(lead.id)
                verified += 1
            except Exception as e:
                print(f"VERIFY ERROR for lead {lead.id}: {e}")

        return {"client_id": client_id, "verified": verified}
    except Exception as exc:
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"error": str(exc)}
    finally:
        db.close()
