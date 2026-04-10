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


def _generate_with_quality_gate(lead, camp, channel, follow_up=0, client_id=client_id,
                                   reflection_context=reflection_context,
                                   memory_context=memory_context,
                                   ab_test_id=ab_test_id,
                                   ab_test_variant=ab_test_variant)

    """
    Generate a message and run the quality gate.
    Returns: (message_text, quality_result, passed_on_attempt)
    attempt: 1 = passed first time, 2 = passed after regen, 0 = failed permanently
    """
    # Attempt 1 — generate
    gen_result = generate_message(lead, camp, channel, follow_up=0, client_id=client_id,
                                   reflection_context=reflection_context,
                                   memory_context=memory_context,
                                   ab_test_id=ab_test_id,
                                   ab_test_variant=ab_test_variant)

    message_text = gen_result.get("message", "")

    # ── LLM-as-judge evaluation ───────────────────────────────────────────────
    try:
        from .llm_judge_service import judge_and_maybe_fix, save_judge_result
        language = client_config.get("language", "en") if client_config else "en"
        judge_outcome = judge_and_maybe_fix(
            message_text, lead, camp, channel, language,
            client_config, client_id, allow_rewrite=True
        )
        _judge_result = judge_outcome.get("judge_result")
        if not judge_outcome.get("judge_skipped"):
            save_judge_result(
                client_id, lead.id, job_id, channel,
                _judge_result or {},
                judge_outcome.get("was_rewritten", False),
                judge_outcome.get("passed", False),
                db
            )
        if judge_outcome.get("was_rewritten"):
            logger.info({"event": "judge_rewrote_message", "lead_id": lead.id, "channel": channel,
                         "original_score": judge_outcome.get("original_score"),
                         "final_score": judge_outcome.get("final_score")})
            message_text = judge_outcome["message"]
        elif not judge_outcome.get("judge_skipped") and not judge_outcome.get("passed") \
                and judge_outcome.get("rewrite_attempted"):
            logger.warning({"event": "judge_permanent_failure", "lead_id": lead.id, "channel": channel})
            return None, {"passed": False, "score": 0, "issues": ["judge_permanent_failure"]}, 0
    except Exception as _je:
        logger.error({"event": "judge_exception", "lead_id": getattr(lead, "id", ""), "error": str(_je)})

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
        # ── Reflexion: load context from past failures ────────────────────
        reflection_context = ""
        try:
            from .reflexion_service import build_reflection_context
            reflection_context = build_reflection_context(user.client_id, req.industry, db)
            if reflection_context:
                logger.info({"event": "reflexion_context_loaded", "job_id": job_id})
        except Exception as _re:
            logger.warning(f"reflexion context load failed (non-blocking): {_re}")
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

            # A/B test assignment
            _ab_test_id = None
            _ab_variant_email = None
            _ab_variant_wa = None
            try:
                from .ab_testing_service import get_active_test, assign_variant
                _ab_test = get_active_test(user.client_id, camp.id, db)
                if _ab_test:
                    _ab_test_id = _ab_test.id
                    _ab_variant_email = assign_variant(_ab_test.id, job.total_leads * 2, db)
                    _ab_variant_wa = assign_variant(_ab_test.id, job.total_leads * 2 + 1, db)
            except Exception as _ab_err:
                logger.warning(f"AB test assignment failed (non-blocking): {_ab_err}")
 ""

            # ── Memory: build context for this lead ───────────────────────
            memory_context = ""
            try:
                from .memory_service import build_memory_context
                memory_context = build_memory_context(user.client_id, lead.id, req.industry, job_id, db)
            except Exception as _me:
                logger.warning(f"memory context load failed (non-blocking): {_me}")

            # ── A/B Test: assign variant if active test exists ────────────────
            ab_test_id = None
            ab_test_variant = None
            try:
                from .ab_testing_service import get_active_test, assign_variant
                active_test = get_active_test(user.client_id, camp.id, db)
                if active_test:
                    ab_test_id = active_test.id
                    ab_test_variant = assign_variant(active_test.id, job.total_leads, db)
            except Exception as _ab:
                logger.warning(f"ab test assignment failed (non-blocking): {_ab}")

            if "email" in channels:
                msg, quality, attempt = _generate_with_quality_gate(
                    lead, camp, "email", user.client_id, client_config, recent_messages, db, job_id,
                    reflection_context=reflection_context,
                    memory_context=memory_context,
                    ab_test_id=ab_test_id,
                    ab_test_variant=ab_test_variant
                )
                if attempt == 0:
                    logger.warning({"event": "email_msg_failed_quality", "lead_id": lead.id})
                else:
                    email_msg = msg or ""
                    try:
                        from .memory_service import store_episodic_outcome
                        store_episodic_outcome(user.client_id, lead.id, "generated", "email", email_msg, db)
                    except Exception:
                        pass

                    recent_messages.append(email_msg)

            if "whatsapp" in channels:
                msg, quality, attempt = _generate_with_quality_gate(
                    lead, camp, "whatsapp", user.client_id, client_config, recent_messages, db, job_id,
                    reflection_context=reflection_context, memory_context=memory_context,
                    ab_test_id=ab_test_id,
                    ab_test_variant=ab_test_variant
                )

                if attempt == 0:
                    logger.warning({"event": "wa_msg_failed_quality", "lead_id": lead.id})
                else:
                    wa_msg = msg or ""
                    try:
                        from .memory_service import store_episodic_outcome
                        store_episodic_outcome(user.client_id, lead.id, "generated", "whatsapp", wa_msg, db)
                    except Exception:
                        pass

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

            # Store A/B variant in message log entries
            if _ab_test_id:
                try:
                    from ..models import MessageLogDB
                    logs = db.query(MessageLogDB).filter(
                        MessageLogDB.lead_id == lead.id,
                        MessageLogDB.client_id == user.client_id,
                    ).order_by(MessageLogDB.sent_at.desc()).limit(2).all()
                    for log in logs:
                        log.ab_test_id = _ab_test_id
                        log.ab_test_variant = _ab_variant_email if log.channel == "email" else _ab_variant_wa
                    db.commit()
                except Exception:
                    pass


        job.status = "pending_approval"
        # ── Reflexion: analyze failures and store insights ────────────────
        try:
            from .reflexion_service import analyze_job_failures, generate_reflection, save_reflection
            failures = analyze_job_failures(job_id, user.client_id, db)
            if failures:
                camp_context = {"industry": req.industry, "tone": getattr(camp, "tone", "professional")}
                reflection = generate_reflection(failures, camp_context, user.client_id)
                if reflection:
                    rid = save_reflection(user.client_id, job_id, reflection, db, industry=req.industry)
                    logger.info({"event": "reflexion_saved", "job_id": job_id, "reflection_id": rid,
                                 "rejected": failures.get("rejected_count", 0)})
        except Exception as _re:
            logger.warning(f"reflexion analysis failed (non-blocking): {_re}")

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

def run_multi_agent_job_entry(user_id: str, req, db) -> str:
    """New entry point for multi-agent mode. Creates job and launches orchestrator."""
    from ..models import AgentJobDB
    job = AgentJobDB(
        user_id=user_id,
        client_id=None,  # set from user below
        campaign_id=req.campaign_id,
        industry=req.industry,
        source_url=req.source_url or "",
        status="running",
    )
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if user:
        job.client_id = user.client_id
    db.add(job)
    db.commit()
    db.refresh(job)

    import threading
    def _launch():
        _db = SessionLocal()
        try:
            from ..agents.orchestrator import run_multi_agent_job
            run_multi_agent_job(job.id, user_id, req, _db)
        finally:
            _db.close()

    threading.Thread(target=_launch, daemon=True).start()
    return job.id
