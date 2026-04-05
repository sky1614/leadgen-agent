import json
import logging

from ..database import SessionLocal
from ..models import AgentJobDB, AgentJobItemDB, LeadDB, CampaignDB, UserDB, QualityLogDB
from ..schemas import AgentRunReq
from .groq_service import ai_enrich, generate_message
from .scraper_service import scrape_url, SAMPLE_LEADS
from .verification_service import verify_lead_contacts
from .quality_gate import check_message_quality, build_fix_prompt
from ..utils import make_fingerprint

logger = logging.getLogger("agent_service")


def _get_client_config(client_id: str, db) -> dict:
    if not client_id:
        return {}
    try:
        from ..models import ClientDB
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if client:
            cfg = dict(client.tone_config or {})
            cfg["email_domain"] = client.email_domain or ""
            return cfg
    except Exception:
        pass
    return {}


def _get_recent_messages(client_id: str, db, limit: int = 50) -> list:
    try:
        from ..models import MessageLogDB
        logs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.status == "sent"
        ).order_by(MessageLogDB.sent_at.desc()).limit(limit).all()
        return [l.message for l in logs if l.message]
    except Exception:
        return []


def _generate_with_quality_gate(lead, camp, channel: str, client_id: str,
                                  client_config: dict, recent_messages: list,
                                  db, job_id: str = None) -> tuple:
    """
    Generate a message and run the quality gate.
    Returns: (message_text, quality_result, passed_on_attempt)
    attempt: 1 = passed first time, 2 = passed after regen, 0 = failed permanently
    """
    # Attempt 1 — generate
    gen_result = generate_message(lead, camp, channel, follow_up=0, client_id=client_id)
    message_text = gen_result.get("message", "")

    quality = check_message_quality(
        message_text=message_text,
        lead_data=lead,
        client_config=client_config,
        channel=channel,
        recent_messages=recent_messages
    )

    if quality["passed"]:
        _log_quality(db, client_id, lead.id, job_id, channel, quality, attempt=1)
        return message_text, quality, 1

    issue_count = len(quality["issues"])
    logger.warning({
        "event": "quality_gate_failed_attempt1",
        "lead_id": lead.id,
        "channel": channel,
        "issues": quality["issues"],
        "score": quality["score"]
    })

    # If 2+ issues → don't retry, fail permanently
    if issue_count >= 2:
        _log_quality(db, client_id, lead.id, job_id, channel, quality, attempt=0)
        return None, quality, 0

    # Attempt 2 — regenerate with fix instructions
    try:
        from .groq_service import generate_ai
        enrichment = json.loads(lead.enrichment_json or "{}")
        fu = ["", "Day 3 follow-up.", "Final Day 7 follow-up."]
        base_prompt = f"""Write B2B {channel} outreach.
Product: {camp.product_description} | Industry: {camp.target_industry} | Tone: {camp.tone}
Lead: {lead.name}, {lead.company}, {lead.role} | Icebreaker: {enrichment.get('icebreaker', '')}
{"Keep under 150 words, conversational" if channel == "whatsapp" else "Include Subject: line, body under 250 words"}
Write ONLY the message."""

        fix_prompt = build_fix_prompt(base_prompt, quality["issues"])
        regen = generate_ai(fix_prompt, task_type="message_regen", client_id=client_id)
        regen_text = regen.get("text", "")

        regen_quality = check_message_quality(
            message_text=regen_text,
            lead_data=lead,
            client_config=client_config,
            channel=channel,
            recent_messages=recent_messages
        )

        if regen_quality["passed"]:
            _log_quality(db, client_id, lead.id, job_id, channel, regen_quality, attempt=2)
            return regen_text, regen_quality, 2
        else:
            logger.warning({
                "event": "quality_gate_failed_attempt2",
                "lead_id": lead.id,
                "channel": channel,
                "issues": regen_quality["issues"]
            })
            _log_quality(db, client_id, lead.id, job_id, channel, regen_quality, attempt=0)
            return None, regen_quality, 0

    except Exception as e:
        logger.error({"event": "regen_error", "lead_id": lead.id, "error": str(e)})
        _log_quality(db, client_id, lead.id, job_id, channel, quality, attempt=0)
        return None, quality, 0


def _log_quality(db, client_id: str, lead_id: str, job_id: str,
                  channel: str, quality: dict, attempt: int):
    try:
        log = QualityLogDB(
            client_id=client_id,
            lead_id=lead_id,
            job_id=job_id,
            channel=channel,
            passed=(attempt == 1),
            passed_after_regen=(attempt == 2),
            failed_permanently=(attempt == 0),
            quality_score=quality.get("score", 0.0),
            issues_json=json.dumps(quality.get("issues", []))
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error({"event": "quality_log_write_error", "error": str(e)})


def run_agent_job(job_id: str, user_id: str, req: AgentRunReq):
    db = SessionLocal()
    try:
        job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
        user = db.query(UserDB).filter(UserDB.id == user_id).first()
        camp = db.query(CampaignDB).filter(CampaignDB.id == req.campaign_id).first()
        if not camp:
            job.status = "error"
            db.commit()
            return

        client_config = _get_client_config(user.client_id, db)
        recent_messages = _get_recent_messages(user.client_id, db)

        raw_leads = scrape_url(req.source_url, req.industry) if req.source_url else SAMPLE_LEADS.get(req.industry, [])
        raw_leads = raw_leads[:req.count]

        for ld in raw_leads:
            if user.leads_used >= user.leads_limit:
                break

            fp = make_fingerprint(ld.get("name", ""), ld.get("company", ""), ld.get("email", ""), ld.get("whatsapp", ""))
            existing = db.query(LeadDB).filter(LeadDB.fingerprint == fp, LeadDB.user_id == user_id).first()
            if existing:
                lead = existing
            else:
                lead = LeadDB(
                    user_id=user_id, client_id=user.client_id, fingerprint=fp, source="agent",
                    **{k: v for k, v in ld.items() if k in ["name", "company", "email", "whatsapp", "industry", "role", "website", "notes"]}
                )
                db.add(lead)
                user.leads_used += 1
                db.commit()
                db.refresh(lead)

            # ── Step 1: Verify contacts ───────────────────────────────────────
            verification = verify_lead_contacts(lead.id)
            if lead.status == "uncontactable":
                logger.info({"event": "lead_skipped_uncontactable", "lead_id": lead.id, "name": lead.name})
                continue

            channels = verification.get("contact_channels", ["email", "whatsapp"])
            if not channels:
                continue

            # ── Step 2: AI enrichment + scoring ──────────────────────────────
            enrichment = ai_enrich(lead)
            lead.enrichment_json = json.dumps(enrichment)
            lead.fit_score = enrichment.get("fit_score", 5)
            if lead.fit_score < 5:
                lead.status = "skipped"
                db.commit()
                continue
            lead.status = "enriched"
            db.commit()

            # ── Step 3: Generate messages with quality gate ───────────────────
            email_msg = ""
            wa_msg = ""

            if "email" in channels:
                msg, quality, attempt = _generate_with_quality_gate(
                    lead, camp, "email", user.client_id, client_config, recent_messages, db, job_id
                )
                if attempt == 0:
                    logger.warning({"event": "email_msg_failed_quality", "lead_id": lead.id})
                else:
                    email_msg = msg or ""
                    recent_messages.append(email_msg)

            if "whatsapp" in channels:
                msg, quality, attempt = _generate_with_quality_gate(
                    lead, camp, "whatsapp", user.client_id, client_config, recent_messages, db, job_id
                )
                if attempt == 0:
                    logger.warning({"event": "wa_msg_failed_quality", "lead_id": lead.id})
                else:
                    wa_msg = msg or ""
                    recent_messages.append(wa_msg)

            # Skip lead if BOTH messages failed quality gate
            if not email_msg and not wa_msg:
                logger.warning({"event": "lead_skipped_quality_gate", "lead_id": lead.id, "name": lead.name})
                lead.status = "skipped"
                db.commit()
                continue

            item = AgentJobItemDB(
                job_id=job_id, client_id=user.client_id,
                lead_id=lead.id, lead_name=lead.name,
                lead_company=lead.company, lead_email=lead.email,
                lead_whatsapp=lead.whatsapp, fit_score=lead.fit_score,
                email_message=email_msg, whatsapp_message=wa_msg
            )
            db.add(item)
            job.total_leads += 1
            db.commit()

        job.status = "pending_approval"
        db.commit()

    except Exception as e:
        logger.error({"event": "agent_job_error", "job_id": job_id, "error": str(e)})
        try:
            job.status = "error"
            db.commit()
        except Exception:
            pass
    finally:
        db.close()
