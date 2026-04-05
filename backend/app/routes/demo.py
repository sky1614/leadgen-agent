import logging
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("demo_routes")
router = APIRouter(prefix="/demo", tags=["demo"])


class DemoCreateRequest(BaseModel):
    prospect_name: str
    industry: str
    city: str
    target_description: str
    requester_email: Optional[str] = None
    requester_phone: Optional[str] = None


@router.post("/create")
def create_demo(req: DemoCreateRequest):
    """Create a new demo — no auth required (public endpoint)."""
    try:
        from ..services.demo_service import create_demo as _create
        demo_id = _create(
            prospect_name=req.prospect_name,
            industry=req.industry,
            city=req.city,
            target_description=req.target_description,
            requester_email=req.requester_email,
            requester_phone=req.requester_phone,
        )
        return {
            "demo_id": demo_id,
            "message": "Demo created. Call POST /demo/{demo_id}/run to start the pipeline.",
            "report_url": f"/demo/{demo_id}/report",
        }
    except Exception as e:
        logger.error(json.dumps({
            "event": "create_demo_error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }))
        raise HTTPException(500, f"Failed to create demo: {str(e)}")


@router.post("/{demo_id}/run")
def run_demo(demo_id: str):
    """Run the full demo pipeline synchronously and return summary."""
    try:
        from ..services.demo_service import run_demo_pipeline
        result = run_demo_pipeline(demo_id)
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(json.dumps({
            "event": "run_demo_error",
            "demo_id": demo_id,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }))
        raise HTTPException(500, f"Pipeline error: {str(e)}")


@router.get("/{demo_id}/report", response_class=HTMLResponse)
def demo_report(demo_id: str):
    """Returns the HTML report for a demo. Publicly accessible via unique URL."""
    try:
        from ..services.demo_service import generate_demo_report
        html = generate_demo_report(demo_id)
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(json.dumps({
            "event": "demo_report_error",
            "demo_id": demo_id,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }))
        raise HTTPException(500, f"Report generation error: {str(e)}")


@router.get("/{demo_id}/leads")
def demo_leads(demo_id: str):
    """List all leads found during the demo with scores."""
    try:
        from ..database import SessionLocal
        from ..models import DemoDB, LeadDB

        db = SessionLocal()
        try:
            demo = db.query(DemoDB).filter(DemoDB.id == demo_id).first()
            if not demo:
                raise HTTPException(404, "Demo not found")

            leads = db.query(LeadDB).filter(
                LeadDB.client_id == demo.demo_client_id
            ).order_by(LeadDB.fit_score.desc()).all()

            return {
                "demo_id": demo_id,
                "status": demo.status,
                "total": len(leads),
                "leads": [
                    {
                        "id": l.id,
                        "name": l.name,
                        "company": l.company,
                        "email": l.email,
                        "role": l.role,
                        "fit_score": l.fit_score,
                        "email_verified": l.email_verified,
                        "industry": l.industry,
                    }
                    for l in leads
                ],
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{demo_id}/status")
def demo_status(demo_id: str):
    """Check current status of a demo."""
    try:
        from ..database import SessionLocal
        from ..models import DemoDB

        db = SessionLocal()
        try:
            demo = db.query(DemoDB).filter(DemoDB.id == demo_id).first()
            if not demo:
                raise HTTPException(404, "Demo not found")
            return {
                "demo_id": demo.id,
                "prospect_name": demo.prospect_name,
                "industry": demo.industry,
                "city": demo.city,
                "status": demo.status,
                "leads_found": demo.leads_found,
                "leads_verified": demo.leads_verified,
                "messages_generated": demo.messages_generated,
                "avg_score": demo.avg_score,
                "report_viewed": demo.report_viewed,
                "converted_to_paid": demo.converted_to_paid,
                "created_at": demo.created_at.isoformat() if demo.created_at else None,
                "expires_at": demo.expires_at.isoformat() if demo.expires_at else None,
                "completed_at": demo.completed_at.isoformat() if demo.completed_at else None,
            }
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
