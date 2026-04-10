import json
import logging

logger = logging.getLogger("scorer_agent")

SCORER_MIN_FIT_SCORE = 5
SCORER_BATCH_SIZE = 5
VERIFICATION_ENABLED = True

def run_scorer(job_id: str, client_id: str, user_id: str, db) -> dict:
    from ..models import AgentJobDB, LeadDB
    from ..services.redis_service import consume_from_queue, publish_to_queue
    from ..services.verification_service import verify_lead_contacts
    from ..services.groq_service import ai_enrich

    leads_scored = 0
    leads_skipped = 0
    leads_sent_to_writer = 0

    batch = []
    while True:
        item = consume_from_queue(f"scorer_queue:{job_id}", timeout=30)
        if item is None:
            if batch:
                _process_scorer_batch(
                    batch, job_id, client_id, user_id, db,
                    leads_scored, leads_skipped, leads_sent_to_writer
                )
            break
        batch.append(item)
        if len(batch) >= SCORER_BATCH_SIZE:
            r = _process_scorer_batch(
                batch, job_id, client_id, user_id, db,
                0, 0, 0
            )
            leads_scored += r["leads_scored"]
            leads_skipped += r["leads_skipped"]
            leads_sent_to_writer += r["leads_sent_to_writer"]
            batch = []

            job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
            if job:
                job.leads_scored = leads_scored
                db.commit()

    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    if job:
        job.scorer_status = "complete"
        job.leads_scored = leads_scored
        db.commit()

    logger.info({
        "event": "scorer_complete",
        "job_id": job_id,
        "leads_scored": leads_scored,
        "leads_skipped": leads_skipped,
        "leads_sent_to_writer": leads_sent_to_writer,
    })

    return {
        "leads_scored": leads_scored,
        "leads_skipped": leads_skipped,
        "leads_sent_to_writer": leads_sent_to_writer,
    }


def _process_scorer_batch(batch, job_id, client_id, user_id, db,
                           leads_scored, leads_skipped, leads_sent_to_writer):
    from ..models import LeadDB
    from ..services.redis_service import publish_to_queue
    from ..services.verification_service import verify_lead_contacts
    from ..services.groq_service import ai_enrich

    for item in batch:
        lead_id = item.get("lead_id")
        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
        if not lead:
            leads_skipped += 1
            continue

        # STEP 2 — Verification
        if VERIFICATION_ENABLED:
            try:
                verify_lead_contacts(lead.id)
                db.refresh(lead)
                if lead.status == "uncontactable":
                    publish_to_queue(f"writer_skip:{job_id}", {"lead_id": lead.id, "reason": "uncontactable"})
                    leads_skipped += 1
                    continue
            except Exception as e:
                logger.warning({"event": "verification_failed", "lead_id": lead_id, "error": str(e)})

        # STEP 3 — ReAct reasoning
        memory_context = ""
        reflection_context = ""
        react_result = {}
        try:
            from ..services.memory_service import build_memory_context
            memory_context = build_memory_context(client_id, lead.id, lead.industry or "", job_id, db)
        except Exception as e:
            logger.warning({"event": "memory_context_failed", "lead_id": lead_id, "error": str(e)})

        try:
            from ..services.reflexion_service import build_reflection_context
            reflection_context = build_reflection_context(client_id, lead.industry or "", db)
        except Exception as e:
            logger.warning({"event": "reflection_context_failed", "lead_id": lead_id, "error": str(e)})

        try:
            from ..services.react_service import reason_about_lead
            react_result = reason_about_lead(lead, client_id, job_id, db)
            if react_result.get("decision") == "skip" and react_result.get("confidence", 0) >= 0.8:
                lead.status = "skipped"
                db.commit()
                publish_to_queue(f"writer_skip:{job_id}", {"lead_id": lead.id, "reason": "react_skip"})
                leads_skipped += 1
                continue
        except Exception as e:
            logger.warning({"event": "react_failed", "lead_id": lead_id, "error": str(e)})

        # STEP 4 — AI enrichment
        try:
            enrichment = ai_enrich(lead, client_id=client_id)
            lead.enrichment_json = json.dumps(enrichment)
            lead.fit_score = enrichment.get("fit_score", 5)
            if lead.fit_score < SCORER_MIN_FIT_SCORE:
                lead.status = "skipped"
                db.commit()
                publish_to_queue(f"writer_skip:{job_id}", {"lead_id": lead.id, "reason": "low_fit_score"})
                leads_skipped += 1
                continue
            lead.status = "enriched"
            db.commit()
        except Exception as e:
            logger.error({"event": "enrichment_failed", "lead_id": lead_id, "error": str(e)})
            leads_skipped += 1
            continue

        # STEP 5 — Publish to writer queue
        publish_to_queue(f"writer_queue:{job_id}", {
            "lead_id": lead.id,
            "job_id": job_id,
            "client_id": client_id,
            "user_id": user_id,
            "react_result": react_result,
            "memory_context": memory_context,
            "reflection_context": reflection_context,
        })
        leads_scored += 1
        leads_sent_to_writer += 1

    return {
        "leads_scored": leads_scored,
        "leads_skipped": leads_skipped,
        "leads_sent_to_writer": leads_sent_to_writer,
    }


def get_scorer_status(job_id: str, db) -> dict:
    from ..models import AgentJobDB
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    if not job or job.scorer_status is None:
        return {"status": "not_started", "leads_scored": 0}
    return {"status": job.scorer_status, "leads_scored": job.leads_scored or 0}
