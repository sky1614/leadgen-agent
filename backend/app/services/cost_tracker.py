import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("cost_tracker")

# ── Constants ─────────────────────────────────────────────────────────────────
USD_TO_INR = 83.5   # update periodically

COSTS_USD = {
    "groq_input":           0.59  / 1_000_000,  # per token
    "groq_output":          0.79  / 1_000_000,
    "openai_input":         0.15  / 1_000_000,
    "openai_output":        0.60  / 1_000_000,
    "sendgrid_email":       0.0,                 # free tier tracked but $0
    "gupshup_wa":           0.006,               # ~₹0.50 = ~$0.006 per message
    "google_places_search": 0.032,               # per request
    "google_places_detail": 0.017,               # per request
    "zerobounce":           0.008,               # per verification
}

PLAN_MONTHLY_BUDGETS_USD = {
    "starter":      5.0,
    "growth":      20.0,
    "professional": 50.0,
    "enterprise":  200.0,
}

ADMIN_ALERT_EMAIL = "admin@leadgenai.com"   # change to your email
TOTAL_INFRA_ALERT_INR = 15_000.0


def _usd_to_inr(usd: float) -> float:
    return round(usd * USD_TO_INR, 4)


def _write_log(client_id: Optional[str], model_used: str, task_type: str,
               input_tokens: int = 0, output_tokens: int = 0,
               units_used: int = 0, cost_usd: float = 0.0):
    """Write cost log asynchronously (non-blocking)."""
    def _do_write():
        try:
            from ..database import SessionLocal
            from ..models import AIUsageDB
            db = SessionLocal()
            db.add(AIUsageDB(
                client_id=client_id,
                model_used=model_used,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=round(cost_usd, 8),
                task_type=task_type,
                units_used=units_used,
                cost_inr=_usd_to_inr(cost_usd)
            ))
            db.commit()
            db.close()
        except Exception as e:
            logger.error({"event": "cost_log_write_error", "error": str(e), "ts": datetime.utcnow().isoformat()})

    t = threading.Thread(target=_do_write, daemon=True)
    t.start()


# ── Public logging helpers (called from each service) ─────────────────────────

def log_groq(client_id: str, input_tokens: int, output_tokens: int, task_type: str = "ai"):
    cost = input_tokens * COSTS_USD["groq_input"] + output_tokens * COSTS_USD["groq_output"]
    _write_log(client_id, "groq", task_type, input_tokens, output_tokens,
               units_used=input_tokens + output_tokens, cost_usd=cost)


def log_openai(client_id: str, input_tokens: int, output_tokens: int, task_type: str = "ai_fallback"):
    cost = input_tokens * COSTS_USD["openai_input"] + output_tokens * COSTS_USD["openai_output"]
    _write_log(client_id, "openai", task_type, input_tokens, output_tokens,
               units_used=input_tokens + output_tokens, cost_usd=cost)


def log_sendgrid(client_id: str, count: int = 1, task_type: str = "email"):
    cost = count * COSTS_USD["sendgrid_email"]
    _write_log(client_id, "sendgrid", task_type, units_used=count, cost_usd=cost)


def log_gupshup(client_id: str, count: int = 1, task_type: str = "whatsapp"):
    cost = count * COSTS_USD["gupshup_wa"]
    _write_log(client_id, "gupshup", task_type, units_used=count, cost_usd=cost)


def log_google_places(client_id: str, searches: int = 0, details: int = 0):
    cost = searches * COSTS_USD["google_places_search"] + details * COSTS_USD["google_places_detail"]
    _write_log(client_id, "google_places", "lead_search",
               units_used=searches + details, cost_usd=cost)


def log_zerobounce(client_id: str, count: int = 1):
    cost = count * COSTS_USD["zerobounce"]
    _write_log(client_id, "zerobounce", "email_verify", units_used=count, cost_usd=cost)


# ── Cost queries ──────────────────────────────────────────────────────────────

def get_client_costs(client_id: str, period: str = "month") -> dict:
    """
    Returns cost breakdown for a client.
    period: 'week' | 'month' | 'all'
    """
    try:
        from ..database import SessionLocal
        from ..models import AIUsageDB
        db = SessionLocal()

        now = datetime.utcnow()
        if period == "week":
            since = now - timedelta(days=7)
        elif period == "month":
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            since = datetime(2000, 1, 1)

        rows = db.query(AIUsageDB).filter(
            AIUsageDB.client_id == client_id,
            AIUsageDB.created_at >= since
        ).all()
        db.close()

        by_service = {}
        total_usd = 0.0
        total_inr = 0.0
        total_units = 0

        for r in rows:
            svc = r.model_used or "unknown"
            if svc not in by_service:
                by_service[svc] = {"calls": 0, "units": 0, "cost_usd": 0.0, "cost_inr": 0.0}
            by_service[svc]["calls"] += 1
            by_service[svc]["units"] += r.units_used or (r.input_tokens + r.output_tokens) or 0
            by_service[svc]["cost_usd"] += r.estimated_cost_usd or 0
            by_service[svc]["cost_inr"] += r.cost_inr or 0
            total_usd += r.estimated_cost_usd or 0
            total_inr += r.cost_inr or 0
            total_units += r.units_used or 0

        # Round
        for svc in by_service:
            by_service[svc]["cost_usd"] = round(by_service[svc]["cost_usd"], 6)
            by_service[svc]["cost_inr"] = round(by_service[svc]["cost_inr"], 2)

        return {
            "client_id": client_id,
            "period": period,
            "total_cost_usd": round(total_usd, 6),
            "total_cost_inr": round(total_inr, 2),
            "total_api_calls": len(rows),
            "total_units": total_units,
            "by_service": by_service
        }
    except Exception as e:
        logger.error({"event": "get_client_costs_error", "client_id": client_id, "error": str(e)})
        return {"error": str(e)}


def get_all_clients_costs(period: str = "month") -> dict:
    """Returns cost summary for all clients (admin)."""
    try:
        from ..database import SessionLocal
        from ..models import AIUsageDB, ClientDB
        db = SessionLocal()

        now = datetime.utcnow()
        if period == "week":
            since = now - timedelta(days=7)
        elif period == "month":
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            since = datetime(2000, 1, 1)

        rows = db.query(AIUsageDB).filter(AIUsageDB.created_at >= since).all()
        clients = {c.id: c.name for c in db.query(ClientDB).all()}
        db.close()

        summary = {}
        for r in rows:
            cid = r.client_id or "unassigned"
            if cid not in summary:
                summary[cid] = {
                    "client_name": clients.get(cid, cid),
                    "total_usd": 0.0,
                    "total_inr": 0.0,
                    "calls": 0
                }
            summary[cid]["total_usd"] += r.estimated_cost_usd or 0
            summary[cid]["total_inr"] += r.cost_inr or 0
            summary[cid]["calls"] += 1

        for cid in summary:
            summary[cid]["total_usd"] = round(summary[cid]["total_usd"], 6)
            summary[cid]["total_inr"] = round(summary[cid]["total_inr"], 2)

        total_infra_inr = sum(v["total_inr"] for v in summary.values())
        clients_list = sorted(summary.values(), key=lambda x: x["total_usd"], reverse=True)

        return {
            "period": period,
            "total_infra_cost_usd": round(sum(v["total_usd"] for v in summary.values()), 4),
            "total_infra_cost_inr": round(total_infra_inr, 2),
            "clients": clients_list,
            "alert": total_infra_inr > TOTAL_INFRA_ALERT_INR
        }
    except Exception as e:
        logger.error({"event": "get_all_costs_error", "error": str(e)})
        return {"error": str(e)}


# ── Cap checks ────────────────────────────────────────────────────────────────

def check_lead_cap(client_id: str) -> dict:
    """Returns {allowed: bool, reason: str}."""
    try:
        from ..database import SessionLocal
        from ..models import ClientDB, LeadDB
        db = SessionLocal()
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client:
            db.close()
            return {"allowed": True}
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = db.query(LeadDB).filter(
            LeadDB.client_id == client_id,
            LeadDB.created_at >= month_start
        ).count()
        db.close()
        cap = client.monthly_lead_cap or 500
        if used >= cap:
            return {"allowed": False, "reason": f"Monthly lead cap reached ({used}/{cap}). Resets on 1st of next month."}
        return {"allowed": True, "used": used, "cap": cap}
    except Exception as e:
        logger.warning({"event": "lead_cap_check_error", "error": str(e)})
        return {"allowed": True}


def check_email_cap(client_id: str) -> dict:
    """Returns {allowed: bool, reason: str}."""
    try:
        from ..database import SessionLocal
        from ..models import ClientDB, MessageLogDB
        db = SessionLocal()
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client:
            db.close()
            return {"allowed": True}
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.channel == "email",
            MessageLogDB.sent_at >= month_start
        ).count()
        db.close()
        cap = client.monthly_email_cap or 1000
        if used >= cap:
            return {"allowed": False, "reason": f"Monthly email cap reached ({used}/{cap}). Resets on 1st of next month."}
        return {"allowed": True, "used": used, "cap": cap}
    except Exception as e:
        logger.warning({"event": "email_cap_check_error", "error": str(e)})
        return {"allowed": True}


def check_wa_cap(client_id: str) -> dict:
    """Returns {allowed: bool, reason: str}."""
    try:
        from ..database import SessionLocal
        from ..models import ClientDB, MessageLogDB
        db = SessionLocal()
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client:
            db.close()
            return {"allowed": True}
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.channel == "whatsapp",
            MessageLogDB.sent_at >= month_start
        ).count()
        db.close()
        cap = client.monthly_wa_cap or 1000
        if used >= cap:
            return {"allowed": False, "reason": f"Monthly WhatsApp cap reached ({used}/{cap}). Resets on 1st of next month."}
        return {"allowed": True, "used": used, "cap": cap}
    except Exception as e:
        logger.warning({"event": "wa_cap_check_error", "error": str(e)})
        return {"allowed": True}


# ── Alert checker (run monthly via Celery or on-demand) ───────────────────────

def check_and_alert(client_id: str = None):
    """Check budgets and send admin alerts if thresholds exceeded."""
    try:
        from ..database import SessionLocal
        from ..models import ClientDB, UserDB

        alerts = []

        if client_id:
            client_ids = [client_id]
        else:
            db = SessionLocal()
            client_ids = [c.id for c in db.query(ClientDB).filter(ClientDB.is_active == True).all()]
            db.close()

        for cid in client_ids:
            costs = get_client_costs(cid, period="month")
            if "error" in costs:
                continue

            db = SessionLocal()
            client = db.query(ClientDB).filter(ClientDB.id == cid).first()
            db.close()
            if not client:
                continue

            plan = getattr(client, "plan_tier", "starter") or "starter"
            budget = PLAN_MONTHLY_BUDGETS_USD.get(plan, 5.0)
            used_pct = costs["total_cost_usd"] / budget * 100 if budget else 0

            if used_pct >= 80:
                alerts.append({
                    "type": "client_budget",
                    "client_id": cid,
                    "client_name": client.name,
                    "used_usd": costs["total_cost_usd"],
                    "budget_usd": budget,
                    "used_pct": round(used_pct, 1)
                })

        # Check total infra cost
        all_costs = get_all_clients_costs(period="month")
        if all_costs.get("total_infra_cost_inr", 0) > TOTAL_INFRA_ALERT_INR:
            alerts.append({
                "type": "total_infra",
                "total_inr": all_costs["total_infra_cost_inr"],
                "threshold_inr": TOTAL_INFRA_ALERT_INR
            })

        if alerts:
            _send_admin_alert(alerts)

        return {"alerts_sent": len(alerts), "alerts": alerts}

    except Exception as e:
        logger.error({"event": "check_and_alert_error", "error": str(e)})
        return {"error": str(e)}


def _send_admin_alert(alerts: list):
    """Send cost alert email to admin."""
    try:
        from ..config import SENDGRID_API_KEY
        if not SENDGRID_API_KEY:
            logger.warning({"event": "cost_alert", "alerts": alerts})
            return

        rows = ""
        for a in alerts:
            if a["type"] == "client_budget":
                rows += f"<li>⚠ <b>{a['client_name']}</b>: ${a['used_usd']:.4f} used of ${a['budget_usd']} budget ({a['used_pct']}%)</li>"
            elif a["type"] == "total_infra":
                rows += f"<li>🚨 Total infra cost: ₹{a['total_inr']:.2f} exceeds ₹{a['threshold_inr']:.0f} threshold</li>"

        html = f"""<h2>LeadGen AI — Cost Alert</h2>
<p>The following cost thresholds have been exceeded:</p>
<ul>{rows}</ul>
<p>Review at your admin dashboard.</p>"""

        from ..services.email_service import send_email
        send_email(
            to_email=ADMIN_ALERT_EMAIL,
            subject="⚠ LeadGen AI Cost Alert",
            body_html=html, body_text=f"Cost alerts: {alerts}",
            from_email="alerts@leadgenai.com", from_name="LeadGen AI Alerts"
        )
        logger.info({"event": "cost_alert_sent", "alert_count": len(alerts)})
    except Exception as e:
        logger.error({"event": "cost_alert_send_error", "error": str(e)})
