import hashlib
import json
from datetime import datetime, timedelta

from fastapi import HTTPException
from passlib.context import CryptContext
from jose import JWTError, jwt

from .config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def make_fingerprint(name: str, company: str, email: str = "", whatsapp: str = "") -> str:
    raw = f"{name.lower().strip()}{company.lower().strip()}{email.lower().strip()}{whatsapp.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


def _user_dict(u) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "plan": u.plan,
        "leads_used": u.leads_used,
        "leads_limit": u.leads_limit
    }


def _ld(l) -> dict:
    return {
        "id": l.id,
        "name": l.name,
        "company": l.company,
        "email": l.email,
        "whatsapp": l.whatsapp,
        "industry": l.industry,
        "role": l.role,
        "website": l.website,
        "notes": l.notes,
        "source": l.source,
        "status": l.status,
        "fit_score": l.fit_score,
        "enrichment": json.loads(l.enrichment_json or "{}"),
        "created_at": str(l.created_at),
        "last_contacted": str(l.last_contacted) if l.last_contacted else None,
        "follow_up_day": l.follow_up_day
    }


def _cd(c) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "product_description": c.product_description,
        "target_industry": c.target_industry,
        "tone": c.tone,
        "channel": c.channel,
        "status": c.status,
        "sent_count": c.sent_count,
        "created_at": str(c.created_at)
    }


def _ld2(l) -> dict:
    return {
        "id": l.id,
        "lead_id": l.lead_id,
        "campaign_id": l.campaign_id,
        "channel": l.channel,
        "message": l.message,
        "status": l.status,
        "follow_up_number": l.follow_up_number,
        "sent_at": str(l.sent_at),
        "approval_status": l.approval_status or "pending_approval",
        "approved_by": l.approved_by,
        "approved_at": str(l.approved_at) if l.approved_at else None,
        "rejection_reason": l.rejection_reason,
        "quality_gate_score": l.quality_gate_score,
        "quality_gate_issues": l.quality_gate_issues or [],
    }

def _gl(lid: str, uid: str, db):
    from .models import LeadDB
    l = db.query(LeadDB).filter(LeadDB.id == lid, LeadDB.user_id == uid).first()
    if not l:
        raise HTTPException(404, "Lead not found")
    return l


def _gc(cid: str, uid: str, db):
    from .models import CampaignDB
    c = db.query(CampaignDB).filter(CampaignDB.id == cid, CampaignDB.user_id == uid).first()
    if not c:
        raise HTTPException(404, "Campaign not found")
    return c


def _chk(u):
    if u.leads_used >= u.leads_limit:
        raise HTTPException(403, f"Lead limit reached ({u.leads_limit}). Upgrade plan.")
