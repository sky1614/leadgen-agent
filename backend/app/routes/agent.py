from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import AgentJobDB, AgentJobItemDB, CampaignDB, ConversationDB, LeadDB, MessageLogDB, UserDB
from ..schemas import AgentRunReq
from ..services.agent_service import run_agent_job

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run")
def agent_run(req: AgentRunReq, background_tasks: BackgroundTasks,
              db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    job = AgentJobDB(user_id=cu.id, client_id=cu.client_id, campaign_id=req.campaign_id, industry=req.industry, source_url=req.source_url or "")
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(run_agent_job, job.id, cu.id, req)
    return {"success": True, "job_id": job.id, "message": "Agent is running. Poll /agent/jobs/{job_id} for status."}


@router.get("/jobs")
def get_agent_jobs(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    jobs = db.query(AgentJobDB).filter(AgentJobDB.user_id == cu.id).order_by(AgentJobDB.created_at.desc()).all()
    return {"jobs": [{"id": j.id, "industry": j.industry, "status": j.status,
                      "total_leads": j.total_leads, "created_at": str(j.created_at)} for j in jobs]}


@router.get("/jobs/{job_id}")
def get_agent_job(job_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id, AgentJobDB.user_id == cu.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    items = db.query(AgentJobItemDB).filter(AgentJobItemDB.job_id == job_id).all()
    return {
        "job": {"id": job.id, "industry": job.industry, "status": job.status,
                "total_leads": job.total_leads, "created_at": str(job.created_at)},
        "items": [{"id": i.id, "lead_id": i.lead_id, "lead_name": i.lead_name,
                   "lead_company": i.lead_company, "lead_email": i.lead_email,
                   "lead_whatsapp": i.lead_whatsapp, "fit_score": i.fit_score,
                   "email_message": i.email_message, "whatsapp_message": i.whatsapp_message,
                   "status": i.status} for i in items]
    }


@router.post("/jobs/{job_id}/approve")
def approve_agent_job(job_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id, AgentJobDB.user_id == cu.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    items = db.query(AgentJobItemDB).filter(AgentJobItemDB.job_id == job_id, AgentJobItemDB.status == "pending").all()
    camp = db.query(CampaignDB).filter(CampaignDB.id == job.campaign_id).first()
    for item in items:
        lead = db.query(LeadDB).filter(LeadDB.id == item.lead_id).first()
        if not lead:
            continue
        db.add(MessageLogDB(user_id=cu.id, lead_id=lead.id, campaign_id=job.campaign_id,
                            channel="email", message=item.email_message))
        db.add(ConversationDB(lead_id=lead.id, role="assistant", content=item.email_message))
        lead.status = "contacted"
        lead.last_contacted = datetime.utcnow()
        lead.follow_up_day = 0
        item.status = "approved"
        if camp:
            camp.sent_count += 1
    job.status = "approved"
    db.commit()
    return {"success": True, "approved": len(items)}


@router.delete("/jobs/{job_id}/items/{item_id}")
def reject_agent_item(job_id: str, item_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    item = db.query(AgentJobItemDB).filter(AgentJobItemDB.id == item_id, AgentJobItemDB.job_id == job_id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    item.status = "rejected"
    db.commit()
    return {"success": True}
