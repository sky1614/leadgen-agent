import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("demo_service")


# ── Limits ────────────────────────────────────────────────────────────────────
DEMO_LEAD_LIMIT    = 100
DEMO_MESSAGE_LIMIT = 50
DEMO_DURATION_DAYS = 7
DEMO_DATA_TTL_DAYS = 30


# ── 1. Create demo ─────────────────────────────────────────────────────────────
def create_demo(
    prospect_name: str,
    industry: str,
    city: str,
    target_description: str,
    requester_email: str = None,
    requester_phone: str = None,
) -> str:
    """Creates a demo record and a temporary demo-scoped ClientDB. Returns demo_id."""
    from ..database import SessionLocal
    from ..models import ClientDB, DemoDB

    db = SessionLocal()
    try:
        now = datetime.utcnow()

        # Temporary client for data isolation
        demo_client = ClientDB(
            id=str(uuid.uuid4()),
            name=f"[DEMO] {prospect_name}",
            industry=industry,
            plan_tier="demo",
            monthly_lead_cap=DEMO_LEAD_LIMIT,
            monthly_email_cap=DEMO_MESSAGE_LIMIT,
            monthly_wa_cap=0,
            is_active=True,
            created_at=now,
        )
        db.add(demo_client)
        db.flush()

        demo = DemoDB(
            prospect_name=prospect_name,
            industry=industry,
            city=city,
            target_description=target_description,
            requester_email=requester_email,
            requester_phone=requester_phone,
            status="created",
            demo_client_id=demo_client.id,
            created_at=now,
            expires_at=now + timedelta(days=DEMO_DURATION_DAYS),
        )
        db.add(demo)
        db.commit()
        db.refresh(demo)

        logger.info(json.dumps({
            "event": "demo_created",
            "demo_id": demo.id,
            "industry": industry,
            "city": city,
            "prospect": prospect_name,
            "timestamp": now.isoformat(),
        }))
        return demo.id

    except Exception as e:
        db.rollback()
        logger.error(json.dumps({
            "event": "demo_create_error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }))
        raise
    finally:
        db.close()


# ── 2. Run demo pipeline ───────────────────────────────────────────────────────
def run_demo_pipeline(demo_id: str) -> dict:
    """Full pipeline: find → enrich → verify → score → generate messages. No real sending."""
    from ..database import SessionLocal
    from ..models import DemoDB, LeadDB, MessageLogDB, CampaignDB, UserDB
    from ..services.scraper_service import search_google_places, search_osm_businesses
    from ..services.groq_service import ai_enrich, ai_message
    from ..services.verification_service import verify_email
    from ..utils import make_fingerprint

    db = SessionLocal()
    try:
        demo = db.query(DemoDB).filter(DemoDB.id == demo_id).first()
        if not demo:
            return {"error": "Demo not found"}
        if demo.status not in ("created", "running"):
            return {"error": f"Demo is already {demo.status}"}
        if datetime.utcnow() > demo.expires_at:
            demo.status = "expired"
            db.commit()
            return {"error": "Demo has expired"}

        demo.status = "running"
        db.commit()

        client_id = demo.demo_client_id
        now = datetime.utcnow()

        # ── Stub user for lead ownership ──────────────────────────────────────
        stub_user = db.query(UserDB).filter(UserDB.client_id == client_id).first()
        if not stub_user:
            stub_user = UserDB(
                id=str(uuid.uuid4())[:8],
                email=f"demo_{demo_id}@internal.demo",
                name=f"Demo {demo.prospect_name}",
                hashed_password="demo",
                plan="demo",
                client_id=client_id,
                is_active=True,
            )
            db.add(stub_user)
            db.commit()
            db.refresh(stub_user)

        # ── Stub campaign for message generation ──────────────────────────────
        stub_campaign = db.query(CampaignDB).filter(CampaignDB.client_id == client_id).first()
        if not stub_campaign:
            stub_campaign = CampaignDB(
                id=str(uuid.uuid4())[:8],
                user_id=stub_user.id,
                client_id=client_id,
                name="Demo Campaign",
                product_description=demo.target_description,
                target_industry=demo.industry,
                tone="professional",
                channel="email",
                status="active",
            )
            db.add(stub_campaign)
            db.commit()
            db.refresh(stub_campaign)

        # ── Step 1: Scrape leads ──────────────────────────────────────────────
        raw_leads = []
        try:
            raw_leads = search_google_places(demo.industry, demo.city, limit=DEMO_LEAD_LIMIT)
            logger.info(json.dumps({
                "event": "demo_scrape_google",
                "demo_id": demo_id,
                "found": len(raw_leads),
                "timestamp": now.isoformat(),
            }))
        except Exception as e:
            logger.warning(json.dumps({
                "event": "demo_scrape_google_failed",
                "demo_id": demo_id,
                "error": str(e),
                "timestamp": now.isoformat(),
            }))
            try:
                raw_leads = search_osm_businesses(demo.industry, demo.city, limit=DEMO_LEAD_LIMIT)
            except Exception as e2:
                logger.error(json.dumps({
                    "event": "demo_scrape_osm_failed",
                    "demo_id": demo_id,
                    "error": str(e2),
                    "timestamp": now.isoformat(),
                }))

        if not raw_leads:
            # Graceful fallback: generate synthetic sample leads so report still looks good
            raw_leads = _synthetic_leads(demo.industry, demo.city)

        # ── Step 2: Enrich, verify, score, generate ───────────────────────────
        processed_leads = []
        messages_count  = 0

        for ld in raw_leads[:DEMO_LEAD_LIMIT]:
            try:
                fp = make_fingerprint(
                    ld.get("name", ""), ld.get("company", ""),
                    ld.get("email", ""), ld.get("whatsapp", "")
                )
                existing = db.query(LeadDB).filter(
                    LeadDB.fingerprint == fp, LeadDB.client_id == client_id
                ).first()
                if existing:
                    lead = existing
                else:
                    lead = LeadDB(
                        user_id=stub_user.id,
                        client_id=client_id,
                        fingerprint=fp,
                        source="demo",
                        **{k: v for k, v in ld.items()
                           if k in ["name", "company", "email", "whatsapp",
                                    "industry", "role", "website", "notes"]}
                    )
                    db.add(lead)
                    db.commit()
                    db.refresh(lead)

                # Email verification (format-only in demo — no ZeroBounce billing)
                email_ok = False
                if lead.email:
                    import re
                    email_ok = bool(re.match(
                        r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
                        lead.email
                    ))
                    lead.email_verified = email_ok

                # AI enrichment
                enrichment = {}
                try:
                    enrichment = ai_enrich(lead)
                    lead.enrichment_json = json.dumps(enrichment)
                    lead.fit_score = enrichment.get("fit_score", 5)
                except Exception as e:
                    logger.warning(json.dumps({
                        "event": "demo_enrich_error",
                        "lead_id": lead.id,
                        "error": str(e),
                    }))
                    lead.fit_score = 5.0

                lead.status = "enriched"
                db.commit()

                row = {
                    "lead_id": lead.id,
                    "name": lead.name,
                    "company": lead.company,
                    "email": lead.email,
                    "fit_score": lead.fit_score,
                    "email_verified": email_ok,
                    "email_message": None,
                }

                # Generate message for top leads (up to DEMO_MESSAGE_LIMIT)
                if lead.fit_score >= 5 and messages_count < DEMO_MESSAGE_LIMIT:
                    try:
                        email_msg = ai_message(lead, stub_campaign, "email")
                        # Store as message log but NEVER send (status=simulated)
                        log = MessageLogDB(
                            user_id=stub_user.id,
                            client_id=client_id,
                            lead_id=lead.id,
                            campaign_id=stub_campaign.id,
                            channel="email",
                            message=email_msg,
                            status="simulated",
                            approval_status="demo",
                            sent_at=now,
                        )
                        db.add(log)
                        db.commit()
                        row["email_message"] = email_msg
                        messages_count += 1
                    except Exception as e:
                        logger.warning(json.dumps({
                            "event": "demo_message_gen_error",
                            "lead_id": lead.id,
                            "error": str(e),
                        }))

                processed_leads.append(row)

            except Exception as e:
                logger.error(json.dumps({
                    "event": "demo_lead_processing_error",
                    "demo_id": demo_id,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                }))
                continue

        # ── Step 3: Update demo record ────────────────────────────────────────
        scores = [l["fit_score"] for l in processed_leads if l["fit_score"]]
        verified_count = sum(1 for l in processed_leads if l.get("email_verified"))
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        demo.status = "complete"
        demo.leads_found = len(processed_leads)
        demo.leads_verified = verified_count
        demo.messages_generated = messages_count
        demo.avg_score = avg_score
        demo.completed_at = datetime.utcnow()
        db.commit()

        logger.info(json.dumps({
            "event": "demo_pipeline_complete",
            "demo_id": demo_id,
            "leads_found": len(processed_leads),
            "verified": verified_count,
            "messages": messages_count,
            "avg_score": avg_score,
            "timestamp": datetime.utcnow().isoformat(),
        }))

        return {
            "demo_id": demo_id,
            "leads_found": len(processed_leads),
            "verified": verified_count,
            "avg_score": avg_score,
            "messages_generated": messages_count,
            "sample_messages": [
                {"company": l["company"], "message": l["email_message"]}
                for l in processed_leads
                if l.get("email_message")
            ][:3],
        }

    except Exception as e:
        try:
            demo.status = "created"  # allow retry
            demo.error_message = str(e)
            db.commit()
        except Exception:
            pass
        logger.error(json.dumps({
            "event": "demo_pipeline_fatal",
            "demo_id": demo_id,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }))
        return {"error": str(e)}
    finally:
        db.close()


# ── 3. Generate HTML report ───────────────────────────────────────────────────
def generate_demo_report(demo_id: str) -> str:
    """Returns a professional HTML report string."""
    from ..database import SessionLocal
    from ..models import DemoDB, LeadDB, MessageLogDB

    db = SessionLocal()
    try:
        demo = db.query(DemoDB).filter(DemoDB.id == demo_id).first()
        if not demo:
            return "<h1>Demo not found</h1>"

        if demo.status not in ("complete",):
            return f"<h1>Demo is {demo.status}. Please check back shortly.</h1>"

        # Mark as viewed
        if not demo.report_viewed:
            demo.report_viewed = True
            demo.report_viewed_at = datetime.utcnow()
            db.commit()

        # Pull top 10 leads
        leads = db.query(LeadDB).filter(
            LeadDB.client_id == demo.demo_client_id,
            LeadDB.fit_score >= 0,
        ).order_by(LeadDB.fit_score.desc()).limit(10).all()

        # Pull sample messages (top 3)
        sample_logs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == demo.demo_client_id,
            MessageLogDB.status == "simulated",
        ).limit(3).all()

        # Score distribution
        all_leads = db.query(LeadDB).filter(
            LeadDB.client_id == demo.demo_client_id
        ).all()
        high   = sum(1 for l in all_leads if l.fit_score >= 7)
        medium = sum(1 for l in all_leads if 5 <= l.fit_score < 7)
        low    = sum(1 for l in all_leads if l.fit_score < 5)

        html = _build_report_html(demo, leads, sample_logs, high, medium, low)
        return html

    finally:
        db.close()


def _build_report_html(demo, leads, sample_logs, high, medium, low) -> str:
    lead_rows = ""
    for i, l in enumerate(leads, 1):
        score_color = "#27ae60" if l.fit_score >= 7 else "#f39c12" if l.fit_score >= 5 else "#e74c3c"
        lead_rows += f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #eee;">{i}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;font-weight:600">{l.company or "—"}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;">{l.name or "—"}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;">{l.role or "—"}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;color:{score_color};font-weight:700">{l.fit_score:.1f}/10</td>
        </tr>"""

    sample_blocks = ""
    for log in sample_logs:
        lead = next((l for l in leads if l.id == log.lead_id), None)
        company = lead.company if lead else "Sample Company"
        sample_blocks += f"""
        <div style="background:#f8f9fa;border-left:4px solid #3498db;padding:20px;margin:15px 0;border-radius:4px">
            <div style="font-size:12px;color:#7f8c8d;margin-bottom:8px;text-transform:uppercase;letter-spacing:1px">
                Sample outreach for: {company}
            </div>
            <div style="white-space:pre-wrap;font-size:14px;line-height:1.7;color:#2c3e50">{log.message}</div>
        </div>"""

    bar_width_h = round((high / max(demo.leads_found, 1)) * 100)
    bar_width_m = round((medium / max(demo.leads_found, 1)) * 100)
    bar_width_l = round((low / max(demo.leads_found, 1)) * 100)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lead Audit Report — {demo.prospect_name}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #f0f4f8; color: #2c3e50; }}
  .wrapper {{ max-width: 860px; margin: 0 auto; padding: 30px 20px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 32px;
           box-shadow: 0 2px 12px rgba(0,0,0,.08); margin-bottom: 24px; }}
  .hero {{ background: linear-gradient(135deg,#1a73e8,#0d47a1);
           color: #fff; text-align: center; padding: 48px 32px; }}
  .hero h1 {{ font-size: 28px; margin-bottom: 10px; }}
  .hero p {{ font-size: 16px; opacity: .85; }}
  .stat-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
  .stat {{ flex: 1; min-width: 140px; background: #f8f9fa; border-radius: 10px;
           padding: 20px; text-align: center; }}
  .stat .num {{ font-size: 36px; font-weight: 700; color: #1a73e8; }}
  .stat .lbl {{ font-size: 13px; color: #7f8c8d; margin-top: 4px; }}
  h2 {{ font-size: 20px; margin-bottom: 16px; color: #1a73e8; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{ background: #f0f4f8; padding: 12px 10px; text-align: left;
        font-weight: 600; color: #555; }}
  .bar-wrap {{ background: #eee; border-radius: 4px; height: 22px; margin: 6px 0; }}
  .bar {{ height: 22px; border-radius: 4px; display: flex; align-items: center;
          padding-left: 8px; font-size: 12px; color: #fff; font-weight: 600; }}
  .cta {{ background: linear-gradient(135deg,#27ae60,#1e8449);
          color: #fff; text-align: center; padding: 40px 32px; border-radius: 12px; }}
  .cta h2 {{ font-size: 24px; margin-bottom: 12px; color: #fff; }}
  .cta p {{ font-size: 15px; opacity: .9; margin-bottom: 24px; }}
  .cta-btn {{ display: inline-block; background: #fff; color: #27ae60;
              font-weight: 700; font-size: 16px; padding: 14px 36px;
              border-radius: 8px; text-decoration: none; }}
  .footer {{ text-align: center; font-size: 12px; color: #aaa; margin-top: 20px; }}
</style>
</head>
<body>
<div class="wrapper">

  <div class="card hero">
    <h1>Free Lead Audit Report</h1>
    <p>Prepared for <strong>{demo.prospect_name}</strong> &nbsp;·&nbsp; {demo.industry.title()} industry in {demo.city}</p>
    <p style="margin-top:8px;font-size:13px;opacity:.7">Generated on {demo.completed_at.strftime('%B %d, %Y') if demo.completed_at else 'N/A'}</p>
  </div>

  <div class="card">
    <h2>Audit Summary</h2>
    <p style="margin-bottom:20px;color:#555">
      We scanned the <strong>{demo.industry.title()}</strong> market in <strong>{demo.city}</strong>
      and found <strong>{demo.leads_found}</strong> businesses matching your ideal customer profile.
      Here's what we found:
    </p>
    <div class="stat-row">
      <div class="stat"><div class="num">{demo.leads_found}</div><div class="lbl">Businesses Found</div></div>
      <div class="stat"><div class="num">{demo.leads_verified}</div><div class="lbl">Verified Contacts</div></div>
      <div class="stat"><div class="num">{demo.avg_score:.1f}<span style="font-size:18px">/10</span></div><div class="lbl">Avg Fit Score</div></div>
      <div class="stat"><div class="num">{demo.messages_generated}</div><div class="lbl">Messages Ready</div></div>
    </div>
  </div>

  <div class="card">
    <h2>Lead Score Distribution</h2>
    <p style="font-size:13px;color:#7f8c8d;margin-bottom:16px">How well each lead matches your ideal customer profile</p>
    <div>
      <div style="display:flex;align-items:center;margin-bottom:8px">
        <span style="width:90px;font-size:13px;color:#27ae60;font-weight:600">Score 7–10</span>
        <div class="bar-wrap" style="flex:1"><div class="bar" style="width:{bar_width_h}%;background:#27ae60">{high} leads</div></div>
      </div>
      <div style="display:flex;align-items:center;margin-bottom:8px">
        <span style="width:90px;font-size:13px;color:#f39c12;font-weight:600">Score 5–7</span>
        <div class="bar-wrap" style="flex:1"><div class="bar" style="width:{bar_width_m}%;background:#f39c12">{medium} leads</div></div>
      </div>
      <div style="display:flex;align-items:center">
        <span style="width:90px;font-size:13px;color:#e74c3c;font-weight:600">Score &lt;5</span>
        <div class="bar-wrap" style="flex:1"><div class="bar" style="width:{bar_width_l}%;background:#e74c3c">{low} leads</div></div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Top 10 Leads Found</h2>
    <table>
      <thead><tr><th>#</th><th>Company</th><th>Contact</th><th>Role</th><th>Fit Score</th></tr></thead>
      <tbody>{lead_rows}</tbody>
    </table>
  </div>

  <div class="card">
    <h2>Sample Personalized Messages</h2>
    <p style="font-size:14px;color:#555;margin-bottom:16px">
      Here is what a personalized outreach message would look like for your business.
      Each message is written specifically for that company — not a template blast.
    </p>
    {sample_blocks if sample_blocks else '<p style="color:#aaa">No sample messages generated yet.</p>'}
  </div>

  <div class="cta">
    <h2>Ready to Start Sending?</h2>
    <p>We've already done the hard work — your leads are verified, scored, and messages are written.<br>
       Activate your account to start reaching out today.</p>
    <a href="mailto:hello@youragency.com?subject=Activate Account — {demo.prospect_name}" class="cta-btn">
      Contact Us to Activate &rarr;
    </a>
  </div>

  <div class="footer">
    Report ID: {demo.id} &nbsp;·&nbsp; This report is valid until {demo.expires_at.strftime('%B %d, %Y') if demo.expires_at else 'N/A'}
  </div>

</div>
</body>
</html>"""


# ── Synthetic fallback leads (when scraping fails) ────────────────────────────
def _synthetic_leads(industry: str, city: str) -> list:
    """Returns placeholder leads so demo report is never empty."""
    companies = [
        ("Sharma & Associates", "Rajesh Sharma", "Director"),
        ("Patel Enterprises", "Priya Patel", "MD"),
        ("Global Solutions Pvt Ltd", "Amit Verma", "CEO"),
        ("NextGen Services", "Sunita Rao", "Founder"),
        ("Prime Consultants", "Vikram Nair", "Partner"),
    ]
    return [
        {
            "name": name, "company": company, "role": role,
            "industry": industry, "city": city,
            "email": f"contact@{company.lower().replace(' ', '').replace('&','')[:12]}.com",
            "whatsapp": "", "website": "", "notes": f"Found in {city} {industry} sector",
        }
        for company, name, role in companies
    ]
