from datetime import datetime, timedelta
from ..database import SessionLocal
from ..models import ClientDB, LeadDB, MessageLogDB, UserDB


def calculate_client_health(client_id: str) -> dict:
    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client:
            return {"error": "Client not found"}

        now = datetime.utcnow()
        window = now - timedelta(days=30)

        # ── Pull raw data ──────────────────────────────────────────────────────
        logs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.sent_at >= window
        ).all()

        emails_sent   = [l for l in logs if l.channel == "email"]
        total_emails  = len(emails_sent)
        total_wa      = len([l for l in logs if l.channel == "whatsapp"])
        bounced       = sum(1 for l in emails_sent if l.bounced)
        opened        = sum(1 for l in emails_sent if l.opened_at)
        clicked       = sum(1 for l in emails_sent if l.clicked_at)
        spam_reports  = sum(1 for l in logs if l.spam_reported)

        leads = db.query(LeadDB).filter(
            LeadDB.client_id == client_id,
            LeadDB.last_contacted >= window
        ).all() if window else []
        replied = sum(1 for l in leads if l.status in ["replied", "meeting_booked"])
        meetings = sum(1 for l in leads if l.status == "meeting_booked")

        # ── 7 health components (0–100 each) ──────────────────────────────────
        scores = {}

        # 1. Reply rate (replied / leads contacted)
        contacted = max(len(leads), 1)
        reply_rate = replied / contacted
        scores["reply_rate"] = min(100, round(reply_rate * 500))   # 20% → 100

        # 2. Meetings booked
        meeting_rate = meetings / contacted
        scores["meetings_booked"] = min(100, round(meeting_rate * 2000))  # 5% → 100

        # 3. Email open rate
        if total_emails:
            open_rate = opened / total_emails
            scores["email_open_rate"] = min(100, round(open_rate * 250))  # 40% → 100
        else:
            scores["email_open_rate"] = 50  # neutral when no data

        # 4. Bounce rate (lower is better)
        if total_emails:
            bounce_pct = bounced / total_emails
            scores["bounce_rate"] = max(0, round(100 - bounce_pct * 500))  # 20% → 0
        else:
            scores["bounce_rate"] = 100

        # 5. Agent uptime — did agent run in last 3 days?
        from ..models import AgentJobDB
        recent_job = db.query(AgentJobDB).filter(
            AgentJobDB.client_id == client_id,
            AgentJobDB.created_at >= now - timedelta(days=3)
        ).first()
        scores["agent_uptime"] = 100 if recent_job else 0

        # 6. Days since last login
        user = db.query(UserDB).filter(UserDB.client_id == client_id).first()
        if user and user.created_at:
            # Proxy: use latest message log as activity signal
            latest_log = db.query(MessageLogDB).filter(
                MessageLogDB.client_id == client_id
            ).order_by(MessageLogDB.sent_at.desc()).first()
            if latest_log:
                days_idle = (now - latest_log.sent_at).days
                scores["last_login"] = max(0, 100 - days_idle * 10)  # 10 days idle → 0
            else:
                scores["last_login"] = 0
        else:
            scores["last_login"] = 50

        # 7. WA quality rating (from wa_tasks health log or default 100)
        try:
            from ..services.whatsapp_service import get_wa_quality_rating
            rating = get_wa_quality_rating(client_id)
            wa_map = {"GREEN": 100, "YELLOW": 60, "RED": 20}
            scores["wa_quality"] = wa_map.get(rating, 70)
        except Exception:
            scores["wa_quality"] = 70  # neutral default

        # ── Overall score (weighted average) ──────────────────────────────────
        weights = {
            "reply_rate": 0.25,
            "meetings_booked": 0.15,
            "email_open_rate": 0.15,
            "bounce_rate": 0.20,
            "agent_uptime": 0.10,
            "last_login": 0.05,
            "wa_quality": 0.10,
        }
        overall = round(sum(scores[k] * weights[k] for k in weights))

        # ── Status label ──────────────────────────────────────────────────────
        if overall >= 75:
            status = "healthy"
        elif overall >= 50:
            status = "warning"
        else:
            status = "critical"

        # ── Alerts / auto-fixes ───────────────────────────────────────────────
        alerts = []
        actions_taken = []

        if total_emails and bounced / total_emails > 0.15:
            alerts.append("High bounce rate (>15%) — re-verifying leads")
            _auto_reverify_leads(client_id, db)
            actions_taken.append("triggered_reverification")

        if reply_rate < 0.02 and contacted > 10:
            alerts.append("Very low reply rate — flagging for A/B test")
            actions_taken.append("flagged_for_ab_test")

        if spam_reports > 3:
            alerts.append(f"{spam_reports} spam reports in last 30 days — review templates")

        if scores["agent_uptime"] == 0:
            alerts.append("Agent has not run in 3+ days — check Celery workers")

        return {
            "client_id": client_id,
            "overall_score": overall,
            "status": status,
            "scores": scores,
            "alerts": alerts,
            "actions_taken": actions_taken,
            "stats": {
                "emails_sent": total_emails,
                "wa_sent": total_wa,
                "bounced": bounced,
                "opened": opened,
                "clicked": clicked,
                "replied": replied,
                "meetings": meetings,
            },
            "computed_at": now.isoformat(),
        }
    finally:
        db.close()


def _auto_reverify_leads(client_id: str, db) -> None:
    """Mark bounced-email leads for re-verification."""
    try:
        bounced_lead_ids = {
            l.lead_id for l in db.query(MessageLogDB).filter(
                MessageLogDB.client_id == client_id,
                MessageLogDB.bounced == True
            ).all() if l.lead_id
        }
        if bounced_lead_ids:
            db.query(LeadDB).filter(
                LeadDB.id.in_(list(bounced_lead_ids)),
                LeadDB.client_id == client_id
            ).update({"email_verified": None, "verification_date": None}, synchronize_session=False)
            db.commit()
    except Exception as e:
        print(f"AUTO-REVERIFY ERROR: {e}")
