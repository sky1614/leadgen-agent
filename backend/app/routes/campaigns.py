from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import CampaignDB, UserDB
from ..schemas import CampaignCreate
from ..utils import _cd

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("")
def get_camps(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    c = db.query(CampaignDB).filter(CampaignDB.user_id == cu.id).all()
    return {"campaigns": [_cd(x) for x in c], "total": len(c)}


@router.post("")
def create_camp(camp: CampaignCreate, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    c = CampaignDB(user_id=cu.id, client_id=cu.client_id, **camp.dict())
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"success": True, "campaign_id": c.id, "campaign": _cd(c)}
