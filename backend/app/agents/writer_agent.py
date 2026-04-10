import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("writer_agent")

WRITER_CHANNELS = ["email", "whatsapp"]
WRITER_BATCH_SIZE = 3
MAX_WRITE_RETRIES = 2


def run_writer(job_id: str, client_id: str, user_id: str,
               campaign_id: str, db) -> dict:
    from ..models import AgentJobDB, AgentJobItemDB, CampaignDB, ClientDB, PromptVersionDB
    from ..services.redis_service import consume_from_queue, publish_to_queue
    from ..services.ab_testing_service import get_active_test

    leads_written = 0
    messages_generated = 0
    judge_rewrites = 0
    quality_failures = 0

    camp = db.query(CampaignDB).filter(CampaignDB.id == campaign_id).first()
    client = db.query(ClientDB).filter(ClientDB.id == client_id).first() if client_id else None
    client_config = {}
    if client:
        client_config = dict(client.tone_config or {})
        client_config["email_domain"] = client.email_domain or ""

    active_test = None
    try:
        active_test = get_active_test(client_id, campaign_id, db)
    except Exception:
        pass

    recent_messages = []
    try:
        from ..models import MessageLogDB
        logs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.status == "sent"
        ).order_by(MessageLogDB.sent_at.desc()).limit(50).all()
        recent_messages = [l.message for l in logs if l.message]
    except Exception:
        pass

    batch = []
    while True:
        item = consume_from_queue(f"writer_queue:{job_id}", timeout=30)
        if item is None:
            if batch:
                r = _process_writer_batch(
                    batch, job_id, client_id, user_id, campaign_id,
                    camp, client_config, active_test, recent_messages, db
                )
                leads_written += r["leads_written"]
                messages_generated += r["messages_generated"]
                judge_rewrites += r["judge_rewrites"]
                quality_failures += r["quality_failures"]
            break
        batch.append(item)
        if len(batch) >= WRITER_BATCH_SIZE:
            r = _process_writer_batch(
                batch, job_id, client_id, user_id, campaign_id,
                camp, client_config, active_test, recent_messages, db
            )
            leads_written += r["leads_written"]
            messages_generated += r["messages_generated"]
            judge_rewrites += r["judge_rewrites"]
            quality_failures += r["quality_failures"]
            batch = []

            job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
            if job:
                job.leads_written = leads_written
                db.commit()

    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    if job:
        job.writer_status = "complete"
        job.leads_written = leads_written
        db.commit()

    logger.info({
        "event": "writer_complete",
        "job_id": job_id,
        "leads_written": leads_written,
        "messages_generated": messages_generated,
        "judge_rewrites": judge_rewrites,
        "quality_failures": quality_failures,
    })

    return {
        "leads_written": leads_written,
        "messages_generated": messages_generated,
        "judge_rewrites": judge_rewrites,
        "quality_failures": quality_failures,
    }


def _process_writer_batch(batch, job_id, client_id, user_id, campaign_id,
                           camp, client_config, active_test, recent_messages, db):
    leads_written = 0
    messages_generated = 0
    judge_rewrites = 0
    quality_failures = 0

    def process_single(item):
        return _write_for_lead(item, job_id, client_id, user_id, campaign_id,
                               camp, client_config, active_test, recent_messages, db)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(process_single, item): item for item in batch}
        for future in as_completed(futures):
            try:
                r = future.result()
                leads_written += r.get("leads_written", 0)
                messages_generated += r.get("messages_generated", 0)
                judge_rewrites += r.get("judge_rewrites", 0)
                quality_failures += r.get("quality_failures", 0)
            except Exception as e:
                logger.error({"event": "writer_thread_error", "error": str(e)})

    return {
        "leads_written": leads_written,
        "messages_generated": messages_generated,
        "judge_rewrites": judge_rewrites,
        "quality_failures": quality_failures,
    }


def _write_for_lead(item, job_id, client_id, user_id, campaign_id,
                     camp, client_config, active_test, recent_messages, db):
    from ..models import LeadDB, AgentJobItemDB
    from ..services.redis_service import publish_to_queue
    from ..services.agent_service import _generate_with_quality_gate
    from ..services.ab_testing_service import assign_variant

    lead_id = item.get("lead_id")
    react_result = item.get("react_result", {})
    memory_context = item.get("memory_context", "")
    reflection_context = item.get("reflection_context", "")

    lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
    if not lead:
        return {"leads_written": 0, "messages_generated": 0, "judge_rewrites": 0, "quality_failures": 0}

    channels = lead.contact_channels or WRITER_CHANNELS
    ab_test_id = None
    ab_test_variant = None
    if active_test:
        try:
            ab_test_id = active_test.id
            ab_test_variant = assign_variant(active_test.id, 0, db)
        except Exception:
            pass

    email_msg = ""
    wa_msg = ""
    _judge_rewrites = 0
    _quality_failures = 0
    _msgs_generated = 0

    if "email" in channels and camp:
        try:
            msg, quality, attempt = _generate_with_quality_gate(
                lead, camp, "email",
                client_id=client_id,
                client_config=client_config,
                recent_messages=recent_messages,
                db=db,
                job_id=job_id,
                reflection_context=reflection_context,
                memory_context=memory_context,
                ab_test_id=ab_test_id,
                ab_test_variant=ab_test_variant,
            )
            if attempt == 2:
                _judge_rewrites += 1
            if attempt == 0:
                _quality_failures += 1
            else:
                email_msg = msg or ""
                _msgs_generated += 1
        except Exception as e:
            logger.error({"event": "email_gen_failed", "lead_id": lead_id, "error": str(e)})

    if "whatsapp" in channels and camp:
        try:
            msg, quality, attempt = _generate_with_quality_gate(
                lead, camp, "whatsapp",
                client_id=client_id,
                client_config=client_config,
                recent_messages=recent_messages,
                db=db,
                job_id=job_id,
                reflection_context=reflection_context,
                memory_context=memory_context,
                ab_test_id=ab_test_id,
                ab_test_variant=ab_test_variant,
            )
            if attempt == 2:
                _judge_rewrites += 1
            if attempt == 0:
                _quality_failures += 1
            else:
                wa_msg = msg or ""
                _msgs_generated += 1
        except Exception as e:
            logger.error({"event": "wa_gen_failed", "lead_id": lead_id, "error": str(e)})

    if not email_msg and not wa_msg:
        return {"leads_written": 0, "messages_generated": 0, "judge_rewrites": _judge_rewrites, "quality_failures": _quality_failures}

    item_record = AgentJobItemDB(
        job_id=job_id,
        client_id=client_id,
        lead_id=lead.id,
        lead_name=lead.name,
        lead_company=lead.company,
        lead_email=lead.email,
        lead_whatsapp=lead.whatsapp,
        fit_score=lead.fit_score,
        email_message=email_msg,
        whatsapp_message=wa_msg,
        status="pending_writer_review",
    )
    db.add(item_record)
    db.commit()
    db.refresh(item_record)

    publish_to_queue(f"delivery_queue:{job_id}", {
        "item_id": item_record.id,
        "job_id": job_id,
        "client_id": client_id,
    })

    return {
        "leads_written": 1,
        "messages_generated": _msgs_generated,
        "judge_rewrites": _judge_rewrites,
        "quality_failures": _quality_failures,
    }


def get_writer_status(job_id: str, db) -> dict:
    from ..models import AgentJobDB
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    if not job or job.writer_status is None:
        return {"status": "not_started", "leads_written": 0, "messages_generated": 0}
    return {
        "status": job.writer_status,
        "leads_written": job.leads_written or 0,
        "messages_generated": job.leads_written or 0,
    }
