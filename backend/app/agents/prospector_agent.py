import difflib
import json
import logging
import uuid
from datetime import datetime

logger = logging.getLogger("prospector_agent")

PROSPECTOR_BATCH_SIZE = 10
PROSPECTOR_MAX_SOURCES = 3
DEDUP_SIMILARITY_THRESHOLD = 0.85


def run_prospector(job_id: str, client_id: str, user_id: str,
                   industry: str, city: str, count: int,
                   source_url: str, db) -> dict:
    from ..models import AgentJobDB, LeadDB, UserDB
    from ..utils import make_fingerprint
    from ..services.scraper_service import scrape_url, search_leads, search_osm_businesses
    from ..services.redis_service import publish_to_queue

    leads_found = 0
    leads_skipped_dedup = 0
    leads_skipped_cap = 0

    # STEP 1 — Source selection
    raw_leads = []
    if source_url:
        raw_leads = scrape_url(source_url, industry)
    else:
        raw_leads = search_leads(client_id, industry, city, count)
        if len(raw_leads) < 5:
            supplemental = search_osm_businesses(industry, city, count=count - len(raw_leads))
            raw_leads = raw_leads + supplemental

    raw_leads = raw_leads[:count]

    # STEP 2 — Semantic deduplication
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    existing_leads = db.query(LeadDB).filter(LeadDB.user_id == user_id).all()
    existing_companies = [l.company or "" for l in existing_leads]
    existing_fps = {l.fingerprint for l in existing_leads if l.fingerprint}

    new_leads_data = []
    for ld in raw_leads:
        fp = make_fingerprint(
            ld.get("name", ""), ld.get("company", ""),
            ld.get("email", ""), ld.get("whatsapp", "")
        )
        if fp in existing_fps:
            leads_skipped_dedup += 1
            continue
        company_name = ld.get("company", "")
        skip = False
        for existing_company in existing_companies:
            ratio = difflib.SequenceMatcher(None, company_name.lower(), existing_company.lower()).ratio()
            if ratio > DEDUP_SIMILARITY_THRESHOLD:
                leads_skipped_dedup += 1
                skip = True
                break
        if not skip:
            new_leads_data.append((ld, fp))

    # STEP 3 — Lead creation
    created_lead_ids = []
    for ld, fp in new_leads_data:
        if user.leads_used >= user.leads_limit:
            leads_skipped_cap += 1
            continue
        lead = LeadDB(
            user_id=user_id,
            client_id=client_id,
            fingerprint=fp,
            source="multi_agent_prospector",
            status="prospected",
            **{k: v for k, v in ld.items() if k in [
                "name", "company", "email", "whatsapp",
                "industry", "role", "website", "notes"
            ]}
        )
        db.add(lead)
        user.leads_used += 1
        db.commit()
        db.refresh(lead)
        created_lead_ids.append(lead.id)
        leads_found += 1

    # STEP 4 — Publish to Redis queue
    queue_key = f"scorer_queue:{job_id}"
    for lead_id in created_lead_ids:
        publish_to_queue(queue_key, {
            "lead_id": lead_id,
            "job_id": job_id,
            "client_id": client_id,
            "user_id": user_id,
        })

    # STEP 5 — Update AgentJobDB
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    if job:
        job.prospector_status = "complete"
        job.leads_found = leads_found
        db.commit()

    logger.info({
        "event": "prospector_complete",
        "job_id": job_id,
        "leads_found": leads_found,
        "leads_skipped_dedup": leads_skipped_dedup,
        "leads_skipped_cap": leads_skipped_cap,
    })

    return {
        "leads_found": leads_found,
        "leads_skipped_dedup": leads_skipped_dedup,
        "leads_skipped_cap": leads_skipped_cap,
        "queue_key": queue_key,
    }


def get_prospector_status(job_id: str, db) -> str:
    from ..models import AgentJobDB
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    if not job or job.prospector_status is None:
        return "not_started"
    return job.prospector_status
