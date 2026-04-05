import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta

from ..config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET

logger = logging.getLogger("payment_service")

# ── Plan definitions ──────────────────────────────────────────────────────────
PLANS = {
    "starter": {
        "monthly":   {"amount": 1500000, "interval": 1,  "period": "monthly"},   # ₹15,000
        "quarterly": {"amount": 4050000, "interval": 3,  "period": "monthly"},   # ₹40,500
    },
    "growth": {
        "monthly":   {"amount": 3500000, "interval": 1,  "period": "monthly"},   # ₹35,000
        "quarterly": {"amount": 9450000, "interval": 3,  "period": "monthly"},   # ₹94,500
    },
    "pro": {
        "monthly":   {"amount": 7500000, "interval": 1,  "period": "monthly"},   # ₹75,000
        "quarterly": {"amount": 20250000, "interval": 3, "period": "monthly"},   # ₹2,02,500
    },
}

# Lead / message caps per plan
PLAN_LIMITS = {
    "trial":    {"leads": 100,   "emails": 50,    "wa": 50},
    "starter":  {"leads": 500,   "emails": 1000,  "wa": 1000},
    "growth":   {"leads": 2000,  "emails": 5000,  "wa": 5000},
    "pro":      {"leads": 10000, "emails": 20000, "wa": 20000},
    "enterprise": {"leads": 99999, "emails": 99999, "wa": 99999},
}

TRIAL_DAYS = 7
GRACE_DAYS = 7


def _rz_client():
    """Returns a Razorpay client or None if keys are not configured."""
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        return None
    try:
        import razorpay
        return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    except Exception as e:
        logger.error(json.dumps({"event": "razorpay_init_error", "error": str(e),
                                 "timestamp": datetime.utcnow().isoformat()}))
        return None


# ── 1. Create or retrieve Razorpay plan ID ────────────────────────────────────
def get_or_create_razorpay_plan(tier: str, billing_cycle: str = "monthly") -> str:
    """Returns Razorpay plan_id string. Creates if not exists."""
    rz = _rz_client()
    if not rz:
        return f"plan_mock_{tier}_{billing_cycle}"

    plan_def = PLANS.get(tier, {}).get(billing_cycle)
    if not plan_def:
        raise ValueError(f"Unknown plan tier or cycle: {tier}/{billing_cycle}")

    plan_name = f"LeadGen AI {tier.title()} {'Monthly' if billing_cycle=='monthly' else 'Quarterly'}"

    try:
        existing = rz.plan.all({"count": 100})
        for p in existing.get("items", []):
            if p.get("item", {}).get("name") == plan_name:
                return p["id"]

        plan = rz.plan.create({
            "period": plan_def["period"],
            "interval": plan_def["interval"],
            "item": {
                "name": plan_name,
                "amount": plan_def["amount"],
                "currency": "INR",
                "description": f"{plan_name} plan",
            }
        })
        logger.info(json.dumps({"event": "razorpay_plan_created", "plan_id": plan["id"],
                                "tier": tier, "timestamp": datetime.utcnow().isoformat()}))
        return plan["id"]
    except Exception as e:
        logger.error(json.dumps({"event": "razorpay_plan_error", "error": str(e),
                                 "tier": tier, "timestamp": datetime.utcnow().isoformat()}))
        raise


# ── 2. Create subscription ────────────────────────────────────────────────────
def create_subscription(client_id: str, tier: str, billing_cycle: str = "monthly",
                         contact_email: str = None, contact_name: str = None) -> dict:
    """Creates Razorpay subscription and stores in DB. Returns checkout details."""
    from ..database import SessionLocal
    from ..models import ClientDB, SubscriptionDB

    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client:
            return {"error": "Client not found"}

        # Check existing active subscription
        existing = db.query(SubscriptionDB).filter(
            SubscriptionDB.client_id == client_id,
            SubscriptionDB.status.in_(["active", "authenticated", "created"])
        ).first()
        if existing:
            return {"error": "Client already has an active subscription",
                    "subscription_id": existing.id}

        rz = _rz_client()
        now = datetime.utcnow()

        if rz:
            try:
                plan_id = get_or_create_razorpay_plan(tier, billing_cycle)
                rz_sub = rz.subscription.create({
                    "plan_id": plan_id,
                    "total_count": 12 if billing_cycle == "monthly" else 4,
                    "quantity": 1,
                    "notes": {
                        "client_id": client_id,
                        "tier": tier,
                        "billing_cycle": billing_cycle,
                    },
                    "notify_info": {
                        "notify_phone": "",
                        "notify_email": contact_email or "",
                    } if contact_email else {},
                })
                rz_sub_id = rz_sub["id"]
                short_url = rz_sub.get("short_url", "")
            except Exception as e:
                logger.error(json.dumps({"event": "razorpay_subscription_error",
                                         "error": str(e), "client_id": client_id,
                                         "timestamp": now.isoformat()}))
                return {"error": f"Razorpay error: {str(e)}"}
        else:
            # Simulated mode when keys not configured
            rz_sub_id = f"sub_mock_{client_id[:8]}"
            short_url = ""

        trial_end = now + timedelta(days=TRIAL_DAYS)

        sub = SubscriptionDB(
            client_id=client_id,
            razorpay_subscription_id=rz_sub_id,
            plan_tier=tier,
            billing_cycle=billing_cycle,
            status="created",
            trial_end=trial_end,
            created_at=now,
        )
        db.add(sub)

        # Activate trial immediately
        client.plan_tier = "trial"
        client.is_active = True
        limits = PLAN_LIMITS["trial"]
        client.monthly_lead_cap  = limits["leads"]
        client.monthly_email_cap = limits["emails"]
        client.monthly_wa_cap    = limits["wa"]
        db.commit()
        db.refresh(sub)

        logger.info(json.dumps({"event": "subscription_created", "client_id": client_id,
                                "tier": tier, "rz_sub_id": rz_sub_id,
                                "timestamp": now.isoformat()}))

        return {
            "success": True,
            "subscription_db_id": sub.id,
            "razorpay_subscription_id": rz_sub_id,
            "checkout_url": short_url,
            "razorpay_key_id": RAZORPAY_KEY_ID,
            "trial_end": trial_end.isoformat(),
            "tier": tier,
            "billing_cycle": billing_cycle,
            "simulated": rz is None,
        }
    except Exception as e:
        db.rollback()
        logger.error(json.dumps({"event": "create_subscription_fatal", "client_id": client_id,
                                 "error": str(e), "timestamp": datetime.utcnow().isoformat()}))
        return {"error": str(e)}
    finally:
        db.close()


# ── 3. Activate client after confirmed payment ────────────────────────────────
def activate_client(client_id: str, tier: str, period_start: datetime,
                    period_end: datetime, rz_sub_id: str = None):
    from ..database import SessionLocal
    from ..models import ClientDB, SubscriptionDB

    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client:
            logger.error(json.dumps({"event": "activate_client_not_found",
                                     "client_id": client_id}))
            return False

        client.plan_tier = tier
        client.is_active = True
        limits = PLAN_LIMITS.get(tier, PLAN_LIMITS["starter"])
        client.monthly_lead_cap  = limits["leads"]
        client.monthly_email_cap = limits["emails"]
        client.monthly_wa_cap    = limits["wa"]

        if rz_sub_id:
            sub = db.query(SubscriptionDB).filter(
                SubscriptionDB.razorpay_subscription_id == rz_sub_id
            ).first()
            if sub:
                sub.status = "active"
                sub.current_period_start = period_start
                sub.current_period_end = period_end
                sub.grace_period_end = None

        db.commit()
        logger.info(json.dumps({"event": "client_activated", "client_id": client_id,
                                "tier": tier, "timestamp": datetime.utcnow().isoformat()}))
        return True
    except Exception as e:
        db.rollback()
        logger.error(json.dumps({"event": "activate_client_error", "client_id": client_id,
                                 "error": str(e), "timestamp": datetime.utcnow().isoformat()}))
        return False
    finally:
        db.close()


# ── 4. Handle failed payment — start grace period ─────────────────────────────
def handle_payment_failure(client_id: str, rz_sub_id: str = None, reason: str = ""):
    from ..database import SessionLocal
    from ..models import ClientDB, SubscriptionDB

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        grace_end = now + timedelta(days=GRACE_DAYS)

        if rz_sub_id:
            sub = db.query(SubscriptionDB).filter(
                SubscriptionDB.razorpay_subscription_id == rz_sub_id
            ).first()
            if sub:
                sub.grace_period_end = grace_end

        db.commit()
        logger.warning(json.dumps({"event": "payment_failed", "client_id": client_id,
                                   "reason": reason, "grace_until": grace_end.isoformat(),
                                   "timestamp": now.isoformat()}))

        # Send reminder email
        _send_payment_reminder(client_id, grace_end)
        return grace_end
    except Exception as e:
        db.rollback()
        logger.error(json.dumps({"event": "handle_failure_error", "error": str(e)}))
    finally:
        db.close()


def _send_payment_reminder(client_id: str, grace_end: datetime):
    from ..database import SessionLocal
    from ..models import ClientDB, UserDB
    from ..services.email_service import send_email

    db = SessionLocal()
    try:
        user = db.query(UserDB).filter(UserDB.client_id == client_id).first()
        if not user or not user.email:
            return
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        client_name = client.name if client else "your account"

        send_email(
            to_email=user.email,
            subject="Action Required: Payment Failed — LeadGen AI",
            body_html=f"""<p>Hi,</p>
<p>We were unable to process your payment for <strong>{client_name}</strong>.</p>
<p>Your account will remain active until <strong>{grace_end.strftime('%B %d, %Y')}</strong>
(grace period). Please update your payment method to avoid service interruption.</p>
<p><a href="{__import__('os').getenv('WEBHOOK_BASE_URL','')}/payments/portal/{client_id}">
Update Payment Method →</a></p>""",
            body_text=f"Payment failed for {client_name}. Grace period ends {grace_end.strftime('%B %d, %Y')}.",
            from_email="billing@leadgenai.in",
            from_name="LeadGen AI Billing",
            client_id=client_id,
        )
    except Exception as e:
        logger.error(json.dumps({"event": "payment_reminder_email_error", "error": str(e)}))
    finally:
        db.close()


# ── 5. Cancel subscription ────────────────────────────────────────────────────
def cancel_subscription(client_id: str, rz_sub_id: str, at_period_end: bool = True):
    from ..database import SessionLocal
    from ..models import ClientDB, SubscriptionDB

    db = SessionLocal()
    try:
        rz = _rz_client()
        if rz and not rz_sub_id.startswith("sub_mock"):
            try:
                rz.subscription.cancel(rz_sub_id, {"cancel_at_cycle_end": 1 if at_period_end else 0})
            except Exception as e:
                logger.error(json.dumps({"event": "razorpay_cancel_error", "error": str(e)}))

        sub = db.query(SubscriptionDB).filter(
            SubscriptionDB.razorpay_subscription_id == rz_sub_id
        ).first()
        if sub:
            sub.status = "cancelled"
            sub.cancelled_at = datetime.utcnow()
            if not at_period_end:
                client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
                if client:
                    client.is_active = False

        db.commit()
        logger.info(json.dumps({"event": "subscription_cancelled", "client_id": client_id,
                                "at_period_end": at_period_end,
                                "timestamp": datetime.utcnow().isoformat()}))
        return {"success": True}
    except Exception as e:
        db.rollback()
        logger.error(json.dumps({"event": "cancel_subscription_error", "error": str(e)}))
        return {"error": str(e)}
    finally:
        db.close()


# ── 6. Log payment ────────────────────────────────────────────────────────────
def log_payment(client_id: str, rz_payment_id: str, rz_invoice_id: str,
                amount_paise: int, status: str, period_start: datetime = None,
                period_end: datetime = None, failure_reason: str = None):
    from ..database import SessionLocal
    from ..models import PaymentDB

    db = SessionLocal()
    try:
        p = PaymentDB(
            client_id=client_id,
            razorpay_payment_id=rz_payment_id,
            razorpay_invoice_id=rz_invoice_id,
            amount_paise=amount_paise,
            status=status,
            period_start=period_start,
            period_end=period_end,
            failure_reason=failure_reason,
            invoice_json=json.dumps({
                "payment_id": rz_payment_id,
                "invoice_id": rz_invoice_id,
                "amount_inr": amount_paise / 100,
                "status": status,
                "period": f"{period_start} — {period_end}" if period_start else "",
            }),
        )
        db.add(p)
        db.commit()
        logger.info(json.dumps({"event": "payment_logged", "client_id": client_id,
                                "payment_id": rz_payment_id, "status": status,
                                "amount_inr": amount_paise / 100,
                                "timestamp": datetime.utcnow().isoformat()}))
    except Exception as e:
        db.rollback()
        logger.error(json.dumps({"event": "log_payment_error", "error": str(e)}))
    finally:
        db.close()


# ── 7. Webhook signature verification ────────────────────────────────────────
def verify_razorpay_webhook(body: bytes, signature: str) -> bool:
    if not RAZORPAY_WEBHOOK_SECRET:
        return True  # skip in dev
    try:
        expected = hmac.new(
            RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


# ── 8. Get invoices for a client ──────────────────────────────────────────────
def get_client_invoices(client_id: str) -> list:
    from ..database import SessionLocal
    from ..models import PaymentDB

    db = SessionLocal()
    try:
        payments = db.query(PaymentDB).filter(
            PaymentDB.client_id == client_id,
            PaymentDB.status == "captured"
        ).order_by(PaymentDB.created_at.desc()).all()

        return [
            {
                "id": p.id,
                "razorpay_payment_id": p.razorpay_payment_id,
                "amount_inr": p.amount_paise / 100,
                "status": p.status,
                "period_start": p.period_start.isoformat() if p.period_start else None,
                "period_end": p.period_end.isoformat() if p.period_end else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in payments
        ]
    finally:
        db.close()


# ── 9. Deactivate clients whose grace period has expired ──────────────────────
def deactivate_expired_grace_periods():
    from ..database import SessionLocal
    from ..models import ClientDB, SubscriptionDB

    db = SessionLocal()
    now = datetime.utcnow()
    deactivated = 0
    try:
        expired_subs = db.query(SubscriptionDB).filter(
            SubscriptionDB.grace_period_end < now,
            SubscriptionDB.status == "active",
        ).all()
        for sub in expired_subs:
            client = db.query(ClientDB).filter(ClientDB.id == sub.client_id).first()
            if client:
                client.is_active = False
                deactivated += 1
            sub.status = "paused"
        db.commit()
        logger.info(json.dumps({"event": "grace_period_deactivations",
                                "count": deactivated, "timestamp": now.isoformat()}))
        return deactivated
    except Exception as e:
        db.rollback()
        logger.error(json.dumps({"event": "grace_deactivation_error", "error": str(e)}))
        return 0
    finally:
        db.close()
