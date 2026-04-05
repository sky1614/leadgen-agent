import logging
from datetime import datetime, timedelta

from .celery_app import celery
from ..database import SessionLocal
from ..models import ClientDB, UserDB, LeadDB, MessageLogDB, WeeklyReportDB

logger = logging.getLogger("report_tasks")


def _week_bounds():
    """Return (week_start, week_end) for the past 7 days (Mon–Sun)."""
    now = datetime.utcnow()
    week_end = now
    week_start = now - timedelta(days=7)
    return week_start, week_end


def _prev_week_bounds():
    now = datetime.utcnow()
    week_end = now - timedelta(days=7)
    week_start = now - timedelta(days=14)
    return week_start, week_end


def _pct(num, denom):
    if not denom:
        return "0%"
    return f"{round(num / denom * 100, 1)}%"


def _bar(pct_float, width=120):
    """Returns CSS bar HTML for given percentage (0–100)."""
    color = "#00e5a0" if pct_float >= 40 else "#f5a623" if pct_float >= 20 else "#7c5cfc"
    return f'<div style="background:#2a2a38;border-radius:4px;height:8px;width:{width}px;overflow:hidden"><div style="background:{color};height:8px;width:{min(pct_float,100):.0f}%;border-radius:4px"></div></div>'


def generate_weekly_report(client_id: str) -> dict:
    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client:
            return {"error": "client not found"}

        week_start, week_end = _week_bounds()
        prev_start, prev_end = _prev_week_bounds()

        # ── This week stats ────────────────────────────────────────────────
        new_leads = db.query(LeadDB).filter(
            LeadDB.client_id == client_id,
            LeadDB.created_at >= week_start
        ).count()

        all_leads = db.query(LeadDB).filter(LeadDB.client_id == client_id).all()
        pipeline = {}
        for lead in all_leads:
            s = lead.status or "new"
            pipeline[s] = pipeline.get(s, 0) + 1

        top_leads = sorted(
            [l for l in all_leads if l.fit_score and l.fit_score >= 6],
            key=lambda x: x.fit_score, reverse=True
        )[:5]

        messages_this_week = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.sent_at >= week_start
        ).all()

        emails = [m for m in messages_this_week if m.channel == "email"]
        wa_msgs = [m for m in messages_this_week if m.channel == "whatsapp"]

        email_sent = len(emails)
        email_opened = sum(1 for m in emails if m.opened_at)
        email_clicked = sum(1 for m in emails if m.clicked_at)
        email_bounced = sum(1 for m in emails if m.bounced)
        wa_sent = len(wa_msgs)
        wa_delivered = sum(1 for m in wa_msgs if m.delivered_at)
        wa_read = sum(1 for m in wa_msgs if m.opened_at)

        meetings_booked = db.query(LeadDB).filter(
            LeadDB.client_id == client_id,
            LeadDB.status == "meeting_booked",
            LeadDB.last_contacted >= week_start
        ).count()

        contacted_this_week = db.query(LeadDB).filter(
            LeadDB.client_id == client_id,
            LeadDB.last_contacted >= week_start
        ).count()

        # ── Previous week for comparison ───────────────────────────────────
        prev_leads = db.query(LeadDB).filter(
            LeadDB.client_id == client_id,
            LeadDB.created_at >= prev_start,
            LeadDB.created_at < prev_end
        ).count()
        prev_msgs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.sent_at >= prev_start,
            MessageLogDB.sent_at < prev_end
        ).count()

        def _trend(curr, prev):
            if prev == 0:
                return "first_week" if curr == 0 else "▲ first data"
            delta = curr - prev
            pct = round(abs(delta) / prev * 100)
            return f"{'▲' if delta >= 0 else '▼'} {pct}% vs last week"

        stats = {
            "client_name": client.name or "Client",
            "week_label": f"{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}",
            "new_leads": new_leads,
            "contacted": contacted_this_week,
            "meetings_booked": meetings_booked,
            "email_sent": email_sent,
            "email_opened": email_opened,
            "email_open_rate": round(email_opened / email_sent * 100, 1) if email_sent else 0,
            "email_clicked": email_clicked,
            "email_bounced": email_bounced,
            "wa_sent": wa_sent,
            "wa_delivered": wa_delivered,
            "wa_read": wa_read,
            "pipeline": pipeline,
            "top_leads": [{"name": l.name, "company": l.company, "score": l.fit_score, "status": l.status} for l in top_leads],
            "trend_leads": _trend(new_leads, prev_leads),
            "trend_msgs": _trend(email_sent + wa_sent, prev_msgs),
            "has_activity": (email_sent + wa_sent + new_leads) > 0,
        }

        html = _build_html(stats, client)
        return {"html_content": html, "stats": stats}

    except Exception as e:
        logger.error({"event": "generate_report_error", "client_id": client_id, "error": str(e), "ts": datetime.utcnow().isoformat()})
        return {"error": str(e)}
    finally:
        db.close()


def _build_html(s: dict, client) -> str:
    open_pct = s["email_open_rate"]
    delivered_pct = round(s["wa_delivered"] / s["wa_sent"] * 100, 1) if s["wa_sent"] else 0
    read_pct = round(s["wa_read"] / s["wa_sent"] * 100, 1) if s["wa_sent"] else 0

    no_activity_banner = ""
    if not s["has_activity"]:
        no_activity_banner = '<div style="background:#2a2a38;border-left:3px solid #f5a623;padding:12px 16px;border-radius:6px;margin-bottom:24px;color:#f5a623;font-size:13px">⚠ No activity this week — agent was paused or no leads were available. The system is alive and will resume automatically.</div>'

    pipeline_rows = "".join(
        f'<tr><td style="padding:8px 12px;color:#e8e8f0;font-size:13px">{status.replace("_"," ").title()}</td><td style="padding:8px 12px;color:#7c5cfc;font-family:monospace;font-size:13px">{count}</td></tr>'
        for status, count in sorted(s["pipeline"].items(), key=lambda x: x[1], reverse=True)
    ) or '<tr><td colspan="2" style="padding:12px;color:#6b6b80;font-size:13px">No leads in pipeline</td></tr>'

    top_lead_rows = "".join(
        f'<tr><td style="padding:8px 12px;color:#e8e8f0;font-size:13px">{l["name"]}</td><td style="padding:8px 12px;color:#6b6b80;font-size:12px">{l["company"]}</td><td style="padding:8px 12px;color:#00e5a0;font-family:monospace;font-size:13px">{l["score"]}/10</td><td style="padding:8px 12px;font-size:11px"><span style="background:rgba(0,229,160,.12);color:#00e5a0;padding:2px 8px;border-radius:10px">{l["status"].replace("_"," ").title()}</span></td></tr>'
        for l in s["top_leads"]
    ) or '<tr><td colspan="4" style="padding:12px;color:#6b6b80;font-size:13px">No high-score leads yet</td></tr>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Weekly Report — {s['client_name']}</title></head>
<body style="margin:0;padding:0;background:#0a0a0f;font-family:'DM Sans',Arial,sans-serif;color:#e8e8f0">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f;padding:32px 16px">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">

  <!-- Header -->
  <tr><td style="background:#111118;border:1px solid #2a2a38;border-radius:12px 12px 0 0;padding:28px 32px">
    <div style="font-size:22px;font-weight:800;letter-spacing:-0.5px">Lead<span style="color:#7c5cfc">Gen</span> AI</div>
    <div style="color:#6b6b80;font-size:11px;font-family:monospace;margin-top:4px">WEEKLY PERFORMANCE REPORT</div>
    <div style="color:#6b6b80;font-size:13px;margin-top:8px">{s['week_label']} · {s['client_name']}</div>
  </td></tr>

  <!-- No activity banner -->
  <tr><td style="background:#111118;border-left:1px solid #2a2a38;border-right:1px solid #2a2a38;padding:0 32px">
    {no_activity_banner}
  </td></tr>

  <!-- Big 3 KPIs -->
  <tr><td style="background:#111118;border-left:1px solid #2a2a38;border-right:1px solid #2a2a38;padding:0 32px 24px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td width="33%" style="text-align:center;padding:16px;background:#18181f;border-radius:10px">
        <div style="font-size:36px;font-weight:800;color:#7c5cfc">{s['new_leads']}</div>
        <div style="font-size:11px;color:#6b6b80;font-family:monospace;margin-top:4px">LEADS FOUND</div>
        <div style="font-size:11px;color:#6b6b80;margin-top:4px">{s['trend_leads']}</div>
      </td>
      <td width="4%"></td>
      <td width="33%" style="text-align:center;padding:16px;background:#18181f;border-radius:10px">
        <div style="font-size:36px;font-weight:800;color:#00e5a0">{s['contacted']}</div>
        <div style="font-size:11px;color:#6b6b80;font-family:monospace;margin-top:4px">CONTACTED</div>
        <div style="font-size:11px;color:#6b6b80;margin-top:4px">{s['trend_msgs']}</div>
      </td>
      <td width="4%"></td>
      <td width="33%" style="text-align:center;padding:16px;background:#18181f;border-radius:10px">
        <div style="font-size:36px;font-weight:800;color:#f5a623">{s['meetings_booked']}</div>
        <div style="font-size:11px;color:#6b6b80;font-family:monospace;margin-top:4px">MEETINGS BOOKED</div>
        <div style="font-size:11px;color:#6b6b80;margin-top:4px">this week</div>
      </td>
    </tr></table>
  </td></tr>

  <!-- Email stats -->
  <tr><td style="background:#111118;border-left:1px solid #2a2a38;border-right:1px solid #2a2a38;padding:0 32px 24px">
    <div style="font-size:13px;font-weight:700;margin-bottom:14px;color:#e8e8f0">📧 Email Performance</div>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#6b6b80;width:100px">Sent</td>
        <td style="padding:6px 0">{_bar(100 if s['email_sent'] else 0)}</td>
        <td style="padding:6px 0 6px 12px;font-size:12px;color:#e8e8f0;font-family:monospace">{s['email_sent']}</td>
      </tr>
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#6b6b80">Opened</td>
        <td style="padding:6px 0">{_bar(open_pct)}</td>
        <td style="padding:6px 0 6px 12px;font-size:12px;color:#00e5a0;font-family:monospace">{s['email_opened']} ({_pct(s['email_opened'], s['email_sent'])})</td>
      </tr>
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#6b6b80">Clicked</td>
        <td style="padding:6px 0">{_bar(round(s['email_clicked']/s['email_sent']*100,1) if s['email_sent'] else 0)}</td>
        <td style="padding:6px 0 6px 12px;font-size:12px;color:#7c5cfc;font-family:monospace">{s['email_clicked']} ({_pct(s['email_clicked'], s['email_sent'])})</td>
      </tr>
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#6b6b80">Bounced</td>
        <td style="padding:6px 0">{_bar(round(s['email_bounced']/s['email_sent']*100,1) if s['email_sent'] else 0)}</td>
        <td style="padding:6px 0 6px 12px;font-size:12px;color:#ff6b6b;font-family:monospace">{s['email_bounced']} ({_pct(s['email_bounced'], s['email_sent'])})</td>
      </tr>
    </table>
  </td></tr>

  <!-- WhatsApp stats -->
  <tr><td style="background:#111118;border-left:1px solid #2a2a38;border-right:1px solid #2a2a38;padding:0 32px 24px">
    <div style="font-size:13px;font-weight:700;margin-bottom:14px;color:#e8e8f0">💬 WhatsApp Performance</div>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#6b6b80;width:100px">Sent</td>
        <td style="padding:6px 0">{_bar(100 if s['wa_sent'] else 0)}</td>
        <td style="padding:6px 0 6px 12px;font-size:12px;color:#e8e8f0;font-family:monospace">{s['wa_sent']}</td>
      </tr>
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#6b6b80">Delivered</td>
        <td style="padding:6px 0">{_bar(delivered_pct)}</td>
        <td style="padding:6px 0 6px 12px;font-size:12px;color:#00e5a0;font-family:monospace">{s['wa_delivered']} ({_pct(s['wa_delivered'], s['wa_sent'])})</td>
      </tr>
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#6b6b80">Read</td>
        <td style="padding:6px 0">{_bar(read_pct)}</td>
        <td style="padding:6px 0 6px 12px;font-size:12px;color:#7c5cfc;font-family:monospace">{s['wa_read']} ({_pct(s['wa_read'], s['wa_sent'])})</td>
      </tr>
    </table>
  </td></tr>

  <!-- Pipeline -->
  <tr><td style="background:#111118;border-left:1px solid #2a2a38;border-right:1px solid #2a2a38;padding:0 32px 24px">
    <div style="font-size:13px;font-weight:700;margin-bottom:14px;color:#e8e8f0">⚡ Pipeline Breakdown</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #2a2a38;border-radius:8px;overflow:hidden">
      <tr style="background:#18181f"><th style="padding:8px 12px;text-align:left;font-size:11px;color:#6b6b80;font-family:monospace">STATUS</th><th style="padding:8px 12px;text-align:left;font-size:11px;color:#6b6b80;font-family:monospace">COUNT</th></tr>
      {pipeline_rows}
    </table>
  </td></tr>

  <!-- Top leads -->
  <tr><td style="background:#111118;border-left:1px solid #2a2a38;border-right:1px solid #2a2a38;padding:0 32px 24px">
    <div style="font-size:13px;font-weight:700;margin-bottom:14px;color:#e8e8f0">🔥 Top 5 Hottest Leads</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #2a2a38;border-radius:8px;overflow:hidden">
      <tr style="background:#18181f">
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#6b6b80;font-family:monospace">NAME</th>
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#6b6b80;font-family:monospace">COMPANY</th>
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#6b6b80;font-family:monospace">SCORE</th>
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#6b6b80;font-family:monospace">STATUS</th>
      </tr>
      {top_lead_rows}
    </table>
  </td></tr>

  <!-- CTA + Footer -->
  <tr><td style="background:#18181f;border:1px solid #2a2a38;border-top:none;border-radius:0 0 12px 12px;padding:24px 32px;text-align:center">
    <div style="font-size:13px;color:#6b6b80;margin-bottom:16px">Questions about this report? Reply directly to this email.</div>
    <a href="mailto:support@leadgenai.com" style="background:#7c5cfc;color:#fff;text-decoration:none;padding:10px 24px;border-radius:8px;font-size:13px;font-weight:600">Reply with feedback →</a>
    <div style="margin-top:20px;font-size:11px;color:#3a3a50">This report was auto-generated by LeadGen AI Agent · <a href="#" style="color:#6b6b80">Unsubscribe from reports</a></div>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _send_report_email(to_email: str, client_name: str, html_content: str, client_id: str = None) -> dict:
    from ..config import SENDGRID_API_KEY
    if not SENDGRID_API_KEY:
        logger.info({"event": "report_email_simulated", "to": to_email})
        return {"success": True, "simulated": True}
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, To, Content
        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        message = Mail(
            from_email=Email("reports@leadgenai.com", "LeadGen AI"),
            to_emails=To(to_email),
            subject=f"📊 Weekly Report — {client_name}",
        )
        message.content = [Content("text/html", html_content)]
        resp = sg.send(message)
        return {"success": resp.status_code < 300, "status_code": resp.status_code}
    except Exception as e:
        logger.error({"event": "report_email_error", "to": to_email, "error": str(e), "ts": datetime.utcnow().isoformat()})
        return {"success": False, "error": str(e)}


@celery.task(bind=True, max_retries=2)
def send_report_for_client(self, client_id: str):
    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id, ClientDB.is_active == True).first()
        if not client:
            return {"skipped": True, "reason": "client not found"}

        user = db.query(UserDB).filter(UserDB.client_id == client_id).first()
        if not user or not user.email:
            return {"skipped": True, "reason": "no user email"}

        result = generate_weekly_report(client_id)
        if "error" in result:
            return {"error": result["error"]}

        html = result["html_content"]
        stats = result["stats"]

        send_result = _send_report_email(user.email, client.name or "Client", html, client_id)

        week_start, week_end = _week_bounds()
        import json
        report_log = WeeklyReportDB(
            client_id=client_id,
            week_start=week_start,
            week_end=week_end,
            stats_json=json.dumps(stats),
            sent_to=user.email,
            sent_at=datetime.utcnow() if send_result.get("success") else None,
            status="sent" if send_result.get("success") else "failed"
        )
        db.add(report_log)
        db.commit()

        logger.info({"event": "weekly_report_sent", "client_id": client_id, "to": user.email, "success": send_result.get("success")})
        return {"success": True, "client_id": client_id, "sent_to": user.email, "stats": stats}

    except Exception as exc:
        logger.error({"event": "send_report_error", "client_id": client_id, "error": str(exc)})
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"error": str(exc)}
    finally:
        db.close()


@celery.task
def send_weekly_reports():
    """Celery Beat entry point — runs every Monday 9 AM IST."""
    db = SessionLocal()
    try:
        clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
        for client in clients:
            send_report_for_client.delay(client.id)
        logger.info({"event": "weekly_reports_dispatched", "count": len(clients)})
        return {"dispatched": len(clients)}
    finally:
        db.close()
