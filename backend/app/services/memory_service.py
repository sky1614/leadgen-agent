import json
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger("memory_service")

WORKING_MEMORY_TTL_HOURS = 24
EPISODIC_MEMORY_TTL_DAYS = 90
SEMANTIC_MEMORY_TTL_DAYS = 180

_PAIN_POINT_KEYWORDS = [
    "scaling", "growth", "revenue", "leads", "sales", "automation",
    "cost", "time", "efficiency", "conversion", "pipeline", "outreach"
]


def get_working_memory(client_id: str, job_id: str, db) -> dict:
    try:
        from ..models import AgentJobItemDB, QualityLogDB, MessageLogDB

        items = db.query(AgentJobItemDB).filter(
            AgentJobItemDB.job_id == job_id
        ).all()

        scores = [i.fit_score for i in items if i.fit_score]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        channels_used = []
        for item in items:
            if item.email_message:
                channels_used.append("email")
            if item.whatsapp_message:
                channels_used.append("whatsapp")
        channels_used = list(set(channels_used))

        quality_logs = db.query(QualityLogDB).filter(
            QualityLogDB.job_id == job_id
        ).all()
        passed = sum(1 for q in quality_logs if q.passed or q.passed_after_regen)
        pass_rate = round(passed / len(quality_logs), 2) if quality_logs else 0.0

        logs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
        ).order_by(MessageLogDB.sent_at.desc()).limit(5).all()
        messages_generated = [l.message[:200] for l in logs if l.message]

        return {
            "current_job_id": job_id,
            "leads_processed": len(items),
            "avg_score_this_run": avg_score,
            "channels_used": channels_used,
            "quality_pass_rate": pass_rate,
            "messages_generated": messages_generated,
        }
    except Exception as e:
        logger.warning(f"get_working_memory failed: {e}")
        return {}


def get_episodic_memory(client_id: str, lead_id: str, db):
    try:
        from ..models import ConversationDB, MessageLogDB, LeadDB

        convos = db.query(ConversationDB).filter(
            ConversationDB.lead_id == lead_id
        ).order_by(ConversationDB.created_at.asc()).all()

        logs = db.query(MessageLogDB).filter(
            MessageLogDB.lead_id == lead_id
        ).order_by(MessageLogDB.sent_at.asc()).all()

        if not convos and not logs:
            return None

        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()

        last_contact = max(
            ([l.sent_at for l in logs if l.sent_at] + [datetime.utcnow() - timedelta(days=999)]),
            default=None
        )
        days_ago = (datetime.utcnow() - last_contact).days if last_contact else 999

        channels_tried = list(set(l.channel for l in logs if l.channel))
        replied_before = any(l.status == "replied" for l in logs) or (lead and lead.status == "replied")
        opened_before = any(l.opened_at is not None for l in logs)
        bounced_before = any(l.bounced for l in logs)

        last_msg = logs[-1].message[:100] if logs and logs[-1].message else ""

        statuses = []
        if lead:
            for l in logs:
                if l.status and (not statuses or statuses[-1] != l.status):
                    statuses.append(l.status)

        return {
            "total_touchpoints": len(logs) + len(convos),
            "last_contact_days_ago": days_ago,
            "channels_tried": channels_tried,
            "replied_before": replied_before,
            "opened_before": opened_before,
            "bounced_before": bounced_before,
            "last_message_summary": last_msg,
            "lead_status_journey": statuses,
        }
    except Exception as e:
        logger.warning(f"get_episodic_memory failed: {e}")
        return None


def get_semantic_memory(client_id: str, industry: str, db) -> dict:
    _defaults = {
        "best_performing_channel": "email",
        "best_performing_day": "Tuesday",
        "best_message_length": 150,
        "top_pain_points": [],
        "worst_performing_tone_patterns": [],
    }
    try:
        from ..models import MessageLogDB, LeadDB

        cutoff = datetime.utcnow() - timedelta(days=90)
        logs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.sent_at >= cutoff,
        ).all()

        if len(logs) < 10:
            return _defaults

        lead_ids = list(set(l.lead_id for l in logs if l.lead_id))
        leads_map = {}
        if lead_ids:
            leads = db.query(LeadDB).filter(
                LeadDB.id.in_(lead_ids),
                LeadDB.industry == industry,
            ).all()
            leads_map = {l.id: l for l in leads}

        industry_logs = [l for l in logs if l.lead_id in leads_map]
        if len(industry_logs) < 10:
            industry_logs = logs  # fall back to all logs

        replied_logs = [l for l in industry_logs if l.status == "replied"]

        # Best channel
        channel_replies = {}
        channel_totals = {}
        for l in industry_logs:
            ch = l.channel or "email"
            channel_totals[ch] = channel_totals.get(ch, 0) + 1
            if l.status == "replied":
                channel_replies[ch] = channel_replies.get(ch, 0) + 1
        best_channel = max(channel_replies, key=lambda c: channel_replies[c] / max(channel_totals.get(c, 1), 1), default="email")

        # Best day
        day_replies = {}
        for l in replied_logs:
            if l.sent_at:
                day = l.sent_at.strftime("%A")
                day_replies[day] = day_replies.get(day, 0) + 1
        best_day = max(day_replies, key=day_replies.get, default="Tuesday")

        # Best message length
        reply_lengths = [len((l.message or "").split()) for l in replied_logs if l.message]
        best_length = int(sum(reply_lengths) / len(reply_lengths)) if reply_lengths else 150

        # Top pain points from enrichment
        pain_counter = {}
        for l in replied_logs:
            lead = leads_map.get(l.lead_id)
            if lead and lead.enrichment_json:
                try:
                    enr = json.loads(lead.enrichment_json)
                    for pp in enr.get("pain_points", []):
                        pain_counter[pp] = pain_counter.get(pp, 0) + 1
                except Exception:
                    pass
        top_pain_points = sorted(pain_counter, key=pain_counter.get, reverse=True)[:5]

        # Worst patterns
        bad_logs = [l for l in industry_logs if l.bounced or l.spam_reported]
        worst_patterns = list(set((l.message or "")[:50] for l in bad_logs if l.message))[:5]

        return {
            "best_performing_channel": best_channel,
            "best_performing_day": best_day,
            "best_message_length": best_length,
            "top_pain_points": top_pain_points,
            "worst_performing_tone_patterns": worst_patterns,
        }
    except Exception as e:
        logger.warning(f"get_semantic_memory failed: {e}")
        return _defaults


def build_memory_context(client_id: str, lead_id: str, industry: str, job_id: str, db) -> str:
    try:
        working = get_working_memory(client_id, job_id, db)
        episodic = get_episodic_memory(client_id, lead_id, db)
        semantic = get_semantic_memory(client_id, industry, db)

        if not working and not episodic and not semantic:
            return ""

        w_leads = working.get("leads_processed", 0)
        w_score = working.get("avg_score_this_run", 0)
        w_pass = round(working.get("quality_pass_rate", 0) * 100, 1)

        if episodic:
            e_touch = episodic.get("total_touchpoints", 0)
            e_days = episodic.get("last_contact_days_ago", 0)
            e_replied = episodic.get("replied_before", False)
            e_opened = episodic.get("opened_before", False)
            e_summary = episodic.get("last_message_summary", "")
            episodic_block = f"""EPISODIC (this lead):
- {e_touch} past touchpoints
- Last contacted {e_days} days ago
- Previously replied: {e_replied}
- Previously opened: {e_opened}
- Last message was: {e_summary}"""
        else:
            episodic_block = "EPISODIC (this lead):\n- First contact with this lead"

        s_channel = semantic.get("best_performing_channel", "email")
        s_day = semantic.get("best_performing_day", "Tuesday")
        s_length = semantic.get("best_message_length", 150)
        s_pain = semantic.get("top_pain_points", [])

        return f"""MEMORY CONTEXT:

WORKING (this session):
- Processed {w_leads} leads so far
- Avg fit score this run: {w_score}
- Quality pass rate: {w_pass}%

{episodic_block}

SEMANTIC (industry patterns):
- Best channel for {industry}: {s_channel}
- Best send day: {s_day}
- Optimal message length: {s_length} words
- Pain points that resonate: {s_pain}

Use this context to improve this message."""
    except Exception as e:
        logger.warning(f"build_memory_context failed: {e}")
        return ""


def store_episodic_outcome(client_id: str, lead_id: str, outcome: str,
                            channel: str, message_text: str, db=None):
    def _store():
        _db = None
        try:
            from ..database import SessionLocal
            from ..models import EpisodicMemoryDB, LeadDB
            _db = SessionLocal()

            lead = _db.query(LeadDB).filter(LeadDB.id == lead_id).first()
            lead_name = (lead.name or "").lower() if lead else ""
            lead_company = (lead.company or "").lower() if lead else ""
            msg_lower = (message_text or "").lower()

            had_name = bool(lead_name and lead_name.split()[0] in msg_lower) if lead_name else False
            had_company = bool(lead_company and lead_company in msg_lower) if lead_company else False
            had_pain_point = any(kw in msg_lower for kw in _PAIN_POINT_KEYWORDS)

            record = EpisodicMemoryDB(
                client_id=client_id,
                lead_id=lead_id,
                outcome=outcome,
                channel=channel,
                message_length=len(message_text.split()) if message_text else 0,
                had_name=had_name,
                had_company=had_company,
                had_pain_point=had_pain_point,
            )
            _db.add(record)
            _db.commit()
        except Exception as e:
            logger.warning(f"store_episodic_outcome thread failed: {e}")
        finally:
            if _db:
                _db.close()

    if db is not None:
        t = threading.Thread(target=_store, daemon=True)
        t.start()
    else:
        _store()


def store_semantic_pattern(client_id: str, industry: str, pattern_type: str,
                            pattern_value: str, success_rate: float, db=None):
    def _store():
        _db = None
        try:
            from ..database import SessionLocal
            from ..models import SemanticMemoryDB
            _db = SessionLocal()

            existing = _db.query(SemanticMemoryDB).filter(
                SemanticMemoryDB.client_id == client_id,
                SemanticMemoryDB.industry == industry,
                SemanticMemoryDB.pattern_type == pattern_type,
            ).first()

            if existing:
                existing.success_rate = round(
                    (existing.success_rate * existing.sample_count + success_rate) /
                    (existing.sample_count + 1), 4
                )
                existing.sample_count += 1
                existing.last_updated = datetime.utcnow()
            else:
                _db.add(SemanticMemoryDB(
                    client_id=client_id,
                    industry=industry,
                    pattern_type=pattern_type,
                    pattern_value=pattern_value,
                    success_rate=success_rate,
                    sample_count=1,
                ))
            _db.commit()
        except Exception as e:
            logger.warning(f"store_semantic_pattern thread failed: {e}")
        finally:
            if _db:
                _db.close()

    t = threading.Thread(target=_store, daemon=True)
    t.start()
