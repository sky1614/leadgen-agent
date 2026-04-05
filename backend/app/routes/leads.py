import csv
import io
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import LeadDB, ScrapedSourceDB, UserDB
from ..schemas import AutoGenReq, LeadCreate, PlacesSearchReq, ApolloSearchReq, ScrapeReq
from ..utils import _chk, _gl, _ld, make_fingerprint
from ..services.scraper_service import (
    SAMPLE_LEADS,
    scrape_url,
    search_osm_businesses,
    search_apollo,
)
from ..services.groq_service import ai_enrich

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("")
def get_leads(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    leads = db.query(LeadDB).filter(LeadDB.user_id == cu.id).all()
    return {"leads": [_ld(l) for l in leads], "total": len(leads)}


@router.post("")
def create_lead(lead: LeadCreate, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    _chk(cu)
    fp = make_fingerprint(lead.name, lead.company, lead.email or "", lead.whatsapp or "")
    ex = db.query(LeadDB).filter(LeadDB.fingerprint == fp, LeadDB.user_id == cu.id).first()
    if ex:
        return {"success": False, "duplicate": True, "existing_id": ex.id, "message": "Duplicate lead detected"}
    l = LeadDB(user_id=cu.id, client_id=cu.client_id, fingerprint=fp, **lead.dict())
    db.add(l)
    cu.leads_used += 1
    db.commit()
    db.refresh(l)
    return {"success": True, "lead_id": l.id, "lead": _ld(l)}


@router.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    added, dups, skipped = [], 0, 0
    for row in reader:
        if cu.leads_used >= cu.leads_limit:
            skipped += 1
            continue
        n = row.get("name", row.get("Name", ""))
        co = row.get("company", row.get("Company", ""))
        em = row.get("email", row.get("Email", ""))
        wa = row.get("whatsapp", row.get("phone", row.get("Phone", "")))
        fp = make_fingerprint(n, co, em, wa)
        if db.query(LeadDB).filter(LeadDB.fingerprint == fp, LeadDB.user_id == cu.id).first():
            dups += 1
            continue
        l = LeadDB(
            user_id=cu.id, client_id=cu.client_id, fingerprint=fp, name=n, company=co, email=em, whatsapp=wa,
            industry=row.get("industry", row.get("Industry", "")),
            role=row.get("role", row.get("Role", row.get("title", ""))),
            website=row.get("website", row.get("Website", "")),
            notes=row.get("notes", row.get("Notes", "")),
            source="csv"
        )
        db.add(l)
        cu.leads_used += 1
        added.append(l.id)
    db.commit()
    return {"success": True, "imported": len(added), "duplicates_skipped": dups, "limit_skipped": skipped}


@router.post("/scrape")
def scrape(req: ScrapeReq, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    scraped = scrape_url(req.url, req.industry or "")
    added, dups = [], 0
    for ld in scraped:
        if cu.leads_used >= cu.leads_limit:
            break
        fp = make_fingerprint(ld.get("name", ""), ld.get("company", ""), ld.get("email", ""), ld.get("whatsapp", ""))
        if db.query(LeadDB).filter(LeadDB.fingerprint == fp, LeadDB.user_id == cu.id).first():
            dups += 1
            continue
        l = LeadDB(
            user_id=cu.id, client_id=cu.client_id, fingerprint=fp, source="scrape",
            **{k: v for k, v in ld.items() if k in ["name", "company", "email", "whatsapp", "industry", "role", "website", "notes"]}
        )
        db.add(l)
        cu.leads_used += 1
        added.append(l.id)
    if req.schedule and req.schedule != "none":
        db.add(ScrapedSourceDB(user_id=cu.id, url=req.url, industry=req.industry or "", schedule=req.schedule))
    db.commit()
    return {"success": True, "scraped": len(added), "duplicates_skipped": dups,
            "leads": [_ld(db.query(LeadDB).get(i)) for i in added]}


@router.post("/auto-generate")
def auto_generate(req: AutoGenReq, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    pool = SAMPLE_LEADS.get(req.industry)
    if not pool:
        all_leads = [l for group in SAMPLE_LEADS.values() for l in group]
        pool = all_leads
    sample = pool[:min(req.count, len(pool))]
    added, dups = [], 0
    for ld in sample:
        if cu.leads_used >= cu.leads_limit:
            break
        fp = make_fingerprint(ld["name"], ld["company"], ld["email"], ld.get("whatsapp", ""))
        if db.query(LeadDB).filter(LeadDB.fingerprint == fp, LeadDB.user_id == cu.id).first():
            dups += 1
            continue
        l = LeadDB(user_id=cu.id, client_id=cu.client_id, fingerprint=fp, source="auto", **{k: v for k, v in ld.items()})
        db.add(l)
        cu.leads_used += 1
        added.append(l.id)
    db.commit()
    return {
        "success": True, "added": len(added), "duplicates_skipped": dups,
        "available_industries": list(SAMPLE_LEADS.keys()),
        "leads": [_ld(db.query(LeadDB).get(i)) for i in added]
    }


@router.get("/industries")
def get_industries():
    return {"industries": list(SAMPLE_LEADS.keys())}


@router.post("/search-places")
def search_places(req: PlacesSearchReq, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    raw = search_osm_businesses(req.industry, req.city, req.count)
    added, dups = [], 0
    for ld in raw:
        if cu.leads_used >= cu.leads_limit:
            break
        fp = make_fingerprint(ld["name"], ld["company"], ld["email"], ld["whatsapp"])
        if db.query(LeadDB).filter(LeadDB.fingerprint == fp, LeadDB.user_id == cu.id).first():
            dups += 1
            continue
        l = LeadDB(
            user_id=cu.id, client_id=cu.client_id, fingerprint=fp, source="openstreetmap", industry=req.industry,
            **{k: v for k, v in ld.items() if k in ["name", "company", "email", "whatsapp", "role", "website", "notes"]}
        )
        db.add(l)
        cu.leads_used += 1
        added.append(l.id)
    db.commit()
    return {
        "success": True, "found": len(raw), "added": len(added), "duplicates_skipped": dups,
        "leads": [_ld(db.query(LeadDB).get(i)) for i in added]
    }


@router.post("/search-apollo")
def apollo_search(req: ApolloSearchReq, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    if not os.getenv("APOLLO_API_KEY", ""):
        raise HTTPException(400, "Apollo API key not configured")
    raw = search_apollo(req.industry, req.city, req.count)
    added, dups = [], 0
    for ld in raw:
        if cu.leads_used >= cu.leads_limit:
            break
        fp = make_fingerprint(ld["name"], ld["company"], ld["email"], ld["whatsapp"])
        if db.query(LeadDB).filter(LeadDB.fingerprint == fp, LeadDB.user_id == cu.id).first():
            dups += 1
            continue
        l = LeadDB(
            user_id=cu.id, client_id=cu.client_id, fingerprint=fp, source="apollo",
            **{k: v for k, v in ld.items() if k in ["name", "company", "email", "whatsapp", "industry", "role", "website", "notes"]}
        )
        db.add(l)
        cu.leads_used += 1
        added.append(l.id)
    db.commit()
    return {
        "success": True, "found": len(raw), "added": len(added), "duplicates_skipped": dups,
        "leads": [_ld(db.query(LeadDB).get(i)) for i in added]
    }


@router.post("/{lead_id}/enrich")
def enrich(lead_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    import json
    l = _gl(lead_id, cu.id, db)
    e = ai_enrich(l)
    l.enrichment_json = json.dumps(e)
    l.fit_score = e.get("fit_score", 5)
    if l.fit_score < 5:
        l.status = "skipped"
        db.commit()
        return {"success": True, "enrichment": e, "auto_skipped": True,
                "message": f"Auto-skipped — score {l.fit_score}/10 below threshold"}
    l.status = "enriched"
    db.commit()
    return {"success": True, "enrichment": e, "auto_skipped": False}


@router.delete("/{lead_id}")
def del_lead(lead_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    l = _gl(lead_id, cu.id, db)
    db.delete(l)
    cu.leads_used = max(0, cu.leads_used - 1)
    db.commit()
    return {"success": True}


@router.get("/export/csv")
def export(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    leads = db.query(LeadDB).filter(LeadDB.user_id == cu.id).all()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["name", "company", "email", "whatsapp", "industry", "role", "website", "status", "fit_score", "source", "created_at"])
    for l in leads:
        w.writerow([l.name, l.company, l.email, l.whatsapp, l.industry, l.role, l.website, l.status, l.fit_score, l.source, l.created_at])
    out.seek(0)
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads.csv"})


@router.get("/{lead_id}/memory")
def memory(lead_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    from ..models import ConversationDB
    l = _gl(lead_id, cu.id, db)
    convs = db.query(ConversationDB).filter(ConversationDB.lead_id == lead_id).order_by(ConversationDB.created_at).all()
    return {"lead": _ld(l), "conversation": [{"role": c.role, "content": c.content, "at": str(c.created_at)} for c in convs]}

@router.post("/{lead_id}/verify")
def verify_lead(lead_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    from ..services.verification_service import verify_lead_contacts
    _gl(lead_id, cu.id, db)  # check ownership
    result = verify_lead_contacts(lead_id)
    return {"success": True, "verification": result}
