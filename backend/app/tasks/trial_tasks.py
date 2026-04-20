import logging
from datetime import datetime, timedelta
from .celery_app import celery
from ..database import SessionLocal
from ..models import UserDB, LeadDB, MessageLogDB

logger = logging.getLogger("trial_tasks")


def _send_trial_email(to_email: str, user_name: str, stats: dict) -> dict:
    from ..config import SENDGRID_API_KEY
    if not SENDGRID_API_KEY:
        logger.info({"event": "trial_reminder_simulated", "to": to_email})
        return {"success": True, "simulated": True}
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, To, Content
        sg   = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        html = _build_reminder_html(user_name, stats)
        msg  = Mail(
            from_email=Email("hello@leadgenai.in", "LeadGen AI"),
            to_emails=To(to_email),
            subject="⏰ Your LeadGen AI trial ends tomorrow — here's what happened",
        )
        msg.content = [Content("text/html", html)]
        resp = sg.send(msg)
        return {"success": resp.status_code < 300}
    except Exception as e:
        logger.error({"event": "trial_reminder_error", "to": to_email, "error": str(e)})
        return {"success": False, "error": str(e)}


def _build_reminder_html(name: str, stats: dict) -> str:
    leads    = stats.get("leads", 0)
    messages = stats.get("messages", 0)
    replies  = stats.get("replies", 0)
    return f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:40px 20px;">
<table width="520" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb;">

  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#7c5cfc,#9d7cfc);padding:32px;text-align:center;">
    <div style="font-size:36px;margin-bottom:8px;">⏰</div>
    <h1 style="color:#fff;font-size:22px;font-weight:800;margin:0;line-height:1.3;">Your trial ends tomorrow,<br>{name.split()[0]}!</h1>
  </td></tr>

  <!-- Stats -->
  <tr><td style="padding:28px 32px 0;">
    <p style="font-size:15px;color:#374151;margin:0 0 20px;">Here's what your AI agent accomplished in 6 days:</p>
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="text-align:center;background:#f5f3ff;border-radius:10px;padding:16px;">
        <div style="font-size:32px;font-weight:800;color:#7c5cfc;">{leads}</div>
        <div style="font-size:12px;color:#6b7280;margin-top:4px;">Leads Found</div>
      </td>
      <td width="12"></td>
      <td style="text-align:center;background:#f5f3ff;border-radius:10px;padding:16px;">
        <div style="font-size:32px;font-weight:800;color:#7c5cfc;">{messages}</div>
        <div style="font-size:12px;color:#6b7280;margin-top:4px;">Messages Sent</div>
      </td>
      <td width="12"></td>
      <td style="text-align:center;background:#f5f3ff;border-radius:10px;padding:16px;">
        <div style="font-size:32px;font-weight:800;color:#7c5cfc;">{replies}</div>
        <div style="font-size:12px;color:#6b7280;margin-top:4px;">Replies Received</div>
      </td>
    </tr>
    </table>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:24px 32px;">
    <p style="font-size:14px;color:#374151;line-height:1.7;margin:0 0 20px;">
      Your AI agent has been working hard. Don't let the momentum stop — 
      continue with a paid plan and keep getting qualified meetings every month.
    </p>
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;border-radius:10px;padding:16px;margin-bottom:20px;">
    <tr><td>
      <div style="font-size:12px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px;">What continues with a paid plan</div>
      <div style="font-size:14px;color:#374151;line-height:1.9;">
        ✓ &nbsp;Daily AI agent runs<br>
        ✓ &nbsp;Unlimited lead sourcing<br>
        ✓ &nbsp;Email + WhatsApp outreach<br>
        ✓ &nbsp;Auto follow-ups &amp; reply tracking
      </div>
    </td></tr>
    </table>
    <div style="text-align:center;background:linear-gradient(135deg,#f5f3ff,#ede9fe);border-radius:10px;padding:16px;margin-bottom:24px;">
      <div style="font-size:13px;color:#6b7280;">Starting at</div>
      <div style="font-size:32px;font-weight:800;color:#7c5cfc;">₹15,000<span style="font-size:15px;font-weight:500;color:#6b7280;">/month</span></div>
    </div>
    <a href="http://localhost:3000/index.html" style="display:block;text-align:center;background:linear-gradient(135deg,#7c5cfc,#9d7cfc);color:#fff;text-decoration:none;padding:14px 28px;border-radius:10px;font-size:15px;font-weight:700;">
      Continue with LeadGen AI →
    </a>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:20px 32px;border-top:1px solid #f3f4f6;text-align:center;">
    <p style="font-size:12px;color:#9ca3af;margin:0;">LeadGen AI · Made in India 🇮🇳</p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


@celery.task
def send_trial_day6_reminders():
    """Runs daily 10 AM IST — sends reminder to users whose trial ends tomorrow."""
    db = SessionLocal()
    try:
        now         = datetime.utcnow()
        window_start = now + timedelta(hours=18)   # ~18h from now
        window_end   = now + timedelta(hours=30)   # ~30h from now
        users = db.query(UserDB).filter(
            UserDB.trial_ends_at >= window_start,
            UserDB.trial_ends_at <= window_end,
            UserDB.is_active == True
        ).all()

        sent = 0
        for user in users:
            if not user.email:
                continue
            # Fetch their stats
            leads    = db.query(LeadDB).filter(LeadDB.user_id == user.id).count()
            messages = db.query(MessageLogDB).filter(
                MessageLogDB.user_id == user.id,
                MessageLogDB.status == "sent"
            ).count()
            replies  = db.query(MessageLogDB).filter(
                MessageLogDB.user_id == user.id,
                MessageLogDB.status == "replied"
            ).count()
            stats = {"leads": leads, "messages": messages, "replies": replies}
            result = _send_trial_email(user.email, user.name or "there", stats)
            if result.get("success"):
                sent += 1
            logger.info({"event": "trial_reminder_sent", "user": user.email, "stats": stats})

        return {"sent": sent, "checked": len(users)}
    except Exception as e:
        logger.error({"event": "trial_reminder_error", "error": str(e)})
        return {"error": str(e)}
    finally:
        db.close()