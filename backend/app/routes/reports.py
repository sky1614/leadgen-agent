import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import UserDB, ClientDB, WeeklyReportDB

logger = logging.getLogger("reports")
router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/weekly/{client_id}", response_class=HTMLResponse)
def preview_report(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    """Preview the weekly report HTML for a client."""
    try:
        if cu.client_id and cu.client_id != client_id and cu.role != "superadmin":
            raise HTTPException(403, "Access denied")

        from ..tasks.report_tasks import generate_weekly_report
        result = generate_weekly_report(client_id)
        if "error" in result:
            raise HTTPException(500, result["error"])
        return HTMLResponse(content=result["html_content"])
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "report_preview_error", "client_id": client_id, "error": str(e)})
        raise HTTPException(500, str(e))


@router.post("/weekly/{client_id}/send")
def send_report_now(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    """Send the weekly report immediately for a client."""
    try:
        if cu.client_id and cu.client_id != client_id and cu.role != "superadmin":
            raise HTTPException(403, "Access denied")

        from ..tasks.report_tasks import send_report_for_client
        task = send_report_for_client.delay(client_id)
        return {"success": True, "task_id": task.id, "message": "Report queued for sending"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "report_send_error", "client_id": client_id, "error": str(e)})
        raise HTTPException(500, str(e))


@router.get("/history")
def report_history(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    """Get past report history for current client."""
    try:
        logs = db.query(WeeklyReportDB).filter(
            WeeklyReportDB.client_id == cu.client_id
        ).order_by(WeeklyReportDB.created_at.desc()).limit(12).all()

        return {
            "reports": [
                {
                    "id": r.id,
                    "week_start": str(r.week_start),
                    "week_end": str(r.week_end),
                    "sent_to": r.sent_to,
                    "sent_at": str(r.sent_at) if r.sent_at else None,
                    "status": r.status
                }
                for r in logs
            ]
        }
    except Exception as e:
        logger.error({"event": "report_history_error", "error": str(e)})
        raise HTTPException(500, str(e))
