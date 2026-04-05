import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import ConversationDB, LeadDB, MessageLogDB, UserDB
from ..schemas import OutreachReq
from ..utils import _gc, _gl, _ld2
from ..services.groq_service import ai_message

logger = logging.getLogger("messages")

router = APIRouter(prefix="/outreach", tags=["outreach"])
approval_router = APIRouter(prefix="/messages", tags=["approval"])


# ── Existing outreach endpoints ───────────────────────────────────────────────

@router.post("/preview")
def preview(req: OutreachReq, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    l = _gl(req.lead_id, cu.id, db)
    c = _gc(req.campaign_id, cu.id, db)
    return {"success": True, "message": ai_message(l, c, req.channel), "channel": req.channel}


@router.post("/send")
def send(req: OutreachReq, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    from ..services.email_service import send_email, can_send_email
    l = _gl(req.lead_id, cu.id, db)
    c = _gc(req.campaign_id, cu.id, db)

    if l.do_not_contact:
        raise HTTPException(400, "Lead is marked do_not_contact")
    if req.channel == "email" and not l.email_verified:
        raise HTTPException(400, "Lead email is not verified")
    if req.channel == "email" and cu.client_id and not can_send_email(cu.client_id):
        raise HTTPException(429, "Daily email send limit reached (warm-up)")

    msg = ai_message(l, c, req.channel)
    subject = "Following up"
    body = msg
    if msg.startswith("Subject:"):
        lines = msg.split("\n", 2)
        subject = lines[0].replace("Subject:", "").strip()
        body = lines[2].strip() if len(lines) > 2 else msg

    sendgrid_result = {"success": False, "message_id": None}
    status = "simulated"

    if req.channel == "email" and l.email:
        from_email = f"hello@{c.target_industry.lower().replace(' ', '')}.com"
        sendgrid_result = send_email(
            to_email=l.email, subject=subject,
            body_html=body.replace("\n", "<br>"), body_text=body,
            from_email=from_email, from_name=cu.name or "Sales Team",
            client_id=cu.client_id, lead_id=l.id, campaign_id=c.id
        )
        status = "sent" if sendgrid_result.get("success") else "failed"

    log = MessageLogDB(
        user_id=cu.id, client_id=cu.client_id, lead_id=l.id,
        campaign_id=c.id, channel=req.channel, message=msg,
        status=status, sendgrid_message_id=sendgrid_result.get("message_id"),
        approval_status="approved", approved_by=cu.name or cu.id,
        approved_at=datetime.utcnow()
    )
    db.add(log)
    db.add(ConversationDB(lead_id=l.id, client_id=cu.client_id, role="assistant", content=msg))
    l.status = "contacted"
    l.last_contacted = datetime.utcnow()
    l.follow_up_day = 0
    c.sent_count += 1
    db.commit()
    return {"success": True, "message": msg, "status": status, "sendgrid": sendgrid_result}


@router.post("/bulk")
def bulk(campaign_id: str, channel: str = "email", db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    c = _gc(campaign_id, cu.id, db)
    leads = db.query(LeadDB).filter(LeadDB.user_id == cu.id, LeadDB.status.in_(["new", "enriched"])).all()
    results = []
    for l in leads:
        if l.fit_score > 0 and l.fit_score < 5:
            continue
        msg = ai_message(l, c, channel)
        db.add(MessageLogDB(user_id=cu.id, client_id=cu.client_id, lead_id=l.id, campaign_id=c.id, channel=channel, message=msg))
        db.add(ConversationDB(lead_id=l.id, client_id=cu.client_id, role="assistant", content=msg))
        l.status = "contacted"
        l.last_contacted = datetime.utcnow()
        l.follow_up_day = 0
        results.append({"lead_id": l.id, "lead_name": l.name})
    c.sent_count += len(results)
    db.commit()
    return {"success": True, "processed": len(results), "results": results}


@router.get("/log")
def log(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    logs = db.query(MessageLogDB).filter(MessageLogDB.user_id == cu.id).order_by(MessageLogDB.sent_at.desc()).limit(100).all()
    return {"log": [_ld2(l) for l in logs], "total": len(logs)}


# ── Approval queue endpoints ───────────────────────────────────────────────────

@approval_router.get("/pending")
def get_pending(
    campaign_id: str = None,
    channel: str = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user)
):
    """Get paginated pending-approval messages with lead data."""
    try:
        query = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == cu.client_id,
            MessageLogDB.approval_status == "pending_approval"
        )
        if campaign_id:
            query = query.filter(MessageLogDB.campaign_id == campaign_id)
        if channel:
            query = query.filter(MessageLogDB.channel == channel)

        total = query.count()
        messages = query.order_by(MessageLogDB.sent_at.desc()).offset((page - 1) * limit).limit(limit).all()

        result = []
        for msg in messages:
            lead = db.query(LeadDB).filter(LeadDB.id == msg.lead_id).first()
            entry = _ld2(msg)
            entry["lead_name"] = lead.name if lead else ""
            entry["lead_company"] = lead.company if lead else ""
            entry["lead_fit_score"] = lead.fit_score if lead else 0
            entry["lead_industry"] = lead.industry if lead else ""
            result.append(entry)

        # Stats
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        approved_today = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == cu.client_id,
            MessageLogDB.approval_status == "approved",
            MessageLogDB.approved_at >= today_start
        ).count()
        rejected_today = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == cu.client_id,
            MessageLogDB.approval_status == "rejected",
            MessageLogDB.approved_at >= today_start
        ).count()
        waiting_to_send = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == cu.client_id,
            MessageLogDB.approval_status == "approved",
            MessageLogDB.status == "pending"
        ).count()
        scores = [m.quality_gate_score for m in db.query(MessageLogDB).filter(
            MessageLogDB.client_id == cu.client_id,
            MessageLogDB.quality_gate_score != None
        ).limit(100).all()]
        avg_quality = round(sum(scores) / len(scores), 1) if scores else 0

        return {
            "messages": result,
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit,
            "stats": {
                "pending": total,
                "approved_today": approved_today,
                "rejected_today": rejected_today,
                "waiting_to_send": waiting_to_send,
                "avg_quality_score": avg_quality
            }
        }
    except Exception as e:
        logger.error({"event": "get_pending_error", "error": str(e), "ts": datetime.utcnow().isoformat()})
        raise HTTPException(500, str(e))


@approval_router.put("/{message_id}/approve")
def approve_message(message_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    try:
        msg = db.query(MessageLogDB).filter(
            MessageLogDB.id == message_id,
            MessageLogDB.client_id == cu.client_id
        ).first()
        if not msg:
            raise HTTPException(404, "Message not found")

        msg.approval_status = "approved"
        msg.approved_by = cu.name or cu.id
        msg.approved_at = datetime.utcnow()
        msg.status = "pending"  # ready to send
        db.commit()

        # Trigger send via Celery if available
        try:
            from ..tasks.celery_app import celery
            celery.send_task("app.tasks.agent_tasks.send_approved_message",
                             args=[message_id, msg.lead_id, cu.client_id])
        except Exception:
            pass  # Celery not running — send will happen on next worker cycle

        return {"success": True, "message_id": message_id, "status": "approved"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "approve_error", "message_id": message_id, "error": str(e)})
        raise HTTPException(500, str(e))


@approval_router.put("/{message_id}/edit")
def edit_and_approve(
    message_id: str,
    body: dict,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user)
):
    try:
        msg = db.query(MessageLogDB).filter(
            MessageLogDB.id == message_id,
            MessageLogDB.client_id == cu.client_id
        ).first()
        if not msg:
            raise HTTPException(404, "Message not found")

        new_text = body.get("message", "").strip()
        if not new_text:
            raise HTTPException(400, "Message text cannot be empty")

        msg.message = new_text
        msg.approval_status = "approved"
        msg.approved_by = cu.name or cu.id
        msg.approved_at = datetime.utcnow()
        msg.status = "pending"
        db.commit()
        return {"success": True, "message_id": message_id, "status": "approved_edited"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "edit_approve_error", "message_id": message_id, "error": str(e)})
        raise HTTPException(500, str(e))


@approval_router.put("/{message_id}/reject")
def reject_message(
    message_id: str,
    body: dict,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user)
):
    try:
        msg = db.query(MessageLogDB).filter(
            MessageLogDB.id == message_id,
            MessageLogDB.client_id == cu.client_id
        ).first()
        if not msg:
            raise HTTPException(404, "Message not found")

        msg.approval_status = "rejected"
        msg.approved_by = cu.name or cu.id
        msg.approved_at = datetime.utcnow()
        msg.rejection_reason = body.get("reason", "")
        msg.status = "rejected"
        db.commit()
        return {"success": True, "message_id": message_id, "status": "rejected"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "reject_error", "message_id": message_id, "error": str(e)})
        raise HTTPException(500, str(e))


@approval_router.post("/approve-batch")
def approve_batch(body: dict, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    try:
        ids = body.get("message_ids", [])
        if not ids:
            raise HTTPException(400, "No message IDs provided")

        approved = 0
        for mid in ids:
            msg = db.query(MessageLogDB).filter(
                MessageLogDB.id == mid,
                MessageLogDB.client_id == cu.client_id,
                MessageLogDB.approval_status == "pending_approval"
            ).first()
            if msg:
                msg.approval_status = "approved"
                msg.approved_by = cu.name or cu.id
                msg.approved_at = datetime.utcnow()
                msg.status = "pending"
                approved += 1

        db.commit()
        return {"success": True, "approved": approved, "total": len(ids)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "batch_approve_error", "error": str(e)})
        raise HTTPException(500, str(e))
