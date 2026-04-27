from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional, List
import csv, io, json, os, uuid, hashlib, re, random, time
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, String, Integer, Float, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import JWTError, jwt
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from bs4 import BeautifulSoup

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "nsai-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
#GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
#GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
#_groq_client = Groq(api_key=GROQ_API_KEY)
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./leadgen.db")
# Railway PostgreSQL URLs start with postgres:// but SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_engine_kwargs = {} if DATABASE_URL.startswith("postgresql") else {"connect_args": {"check_same_thread": False}}
engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserDB(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    email = Column(String, unique=True, index=True)
    name = Column(String)
    hashed_password = Column(String)
    plan = Column(String, default="free")
    leads_used = Column(Integer, default=0)
    leads_limit = Column(Integer, default=50)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    role = Column(String, default="client")

class RevokedTokenDB(Base):
    __tablename__ = "revoked_tokens"
    jti = Column(String, primary_key=True)
    revoked_at = Column(DateTime, default=datetime.utcnow)

class LeadDB(Base):
    __tablename__ = "leads"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String)
    company = Column(String)
    email = Column(String)
    whatsapp = Column(String)
    industry = Column(String)
    role = Column(String)
    website = Column(String)
    notes = Column(String)
    source = Column(String, default="manual")
    status = Column(String, default="new")
    fit_score = Column(Float, default=0)
    enrichment_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_contacted = Column(DateTime, nullable=True)
    follow_up_day = Column(Integer, default=0)
    fingerprint = Column(String)

class CampaignDB(Base):
    __tablename__ = "campaigns"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String)
    product_description = Column(Text)
    target_industry = Column(String)
    tone = Column(String, default="professional")
    channel = Column(String, default="both")
    status = Column(String, default="active")
    sent_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class MessageLogDB(Base):
    __tablename__ = "message_log"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String, ForeignKey("users.id"))
    lead_id = Column(String)
    campaign_id = Column(String)
    channel = Column(String)
    message = Column(Text)
    status = Column(String, default="simulated")
    follow_up_number = Column(Integer, default=0)
    sent_at = Column(DateTime, default=datetime.utcnow)

class ConversationDB(Base):
    __tablename__ = "conversations"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    lead_id = Column(String)
    role = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class ScrapedSourceDB(Base):
    __tablename__ = "scraped_sources"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String)
    url = Column(String)
    industry = Column(String)
    schedule = Column(String, default="daily")
    last_run = Column(DateTime, nullable=True)
    leads_found = Column(Integer, default=0)

class AgentJobDB(Base):
    __tablename__ = "agent_jobs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String, ForeignKey("users.id"))
    campaign_id = Column(String)
    industry = Column(String)
    source_url = Column(String, default="")
    status = Column(String, default="running")  # running, pending_approval, approved, error
    total_leads = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class AgentJobItemDB(Base):
    __tablename__ = "agent_job_items"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    job_id = Column(String, ForeignKey("agent_jobs.id"))
    lead_id = Column(String)
    lead_name = Column(String)
    lead_company = Column(String)
    lead_email = Column(String)
    lead_whatsapp = Column(String)
    fit_score = Column(Float, default=0)
    email_message = Column(Text)
    whatsapp_message = Column(Text)
    status = Column(String, default="pending")  # pending, approved, rejected

class OTPStoreDB(Base):
    __tablename__ = "otp_store"
    email = Column(String, primary_key=True)
    otp = Column(String)
    expires = Column(Float)
    user_id = Column(String)

Base.metadata.create_all(bind=engine)

with engine.connect() as _conn:
    from sqlalchemy import text
    try:
        _conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'client'"))
        _conn.commit()
    except Exception:
        pass

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def hash_password(password): return pwd_context.hash(password)
def create_token(data: dict):
    to_encode = data.copy()
    to_encode.update({
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": uuid.uuid4().hex,
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id: raise HTTPException(401, "Invalid token")
    except JWTError: raise HTTPException(401, "Invalid token")
    if jti and db.query(RevokedTokenDB).filter(RevokedTokenDB.jti == jti).first():
        raise HTTPException(401, "Token revoked")
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user: raise HTTPException(401, "User not found")
    return user

def get_admin_user(cu: UserDB = Depends(get_current_user)):
    if getattr(cu, "role", "client") != "admin":
        raise HTTPException(403, "Admin access required")
    return cu

def gemini(prompt):
    import requests, os
    res = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json"
        },
        json={
            "model": "anthropic/claude-3-5-sonnet",
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    return res.json()["choices"][0]["message"]["content"].strip()

def make_fingerprint(name, company, email="", whatsapp=""):
    raw = f"{name.lower().strip()}{company.lower().strip()}{email.lower().strip()}{whatsapp.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()

def ai_enrich(lead):
    try:
        prompt = f"""Analyze this B2B lead and return JSON only.
Lead: name={lead.name}, company={lead.company}, industry={lead.industry}, role={lead.role}, website={lead.website}
Return ONLY: {{"pain_points":["..."],"fit_score":<1-10>,"fit_reason":"<one sentence>","suggested_approach":"<one sentence>","icebreaker":"<personalized opening>"}}"""
        t = gemini(prompt)
        if "```" in t: t = t.split("```")[1]; t = t[4:] if t.startswith("json") else t
        return json.loads(t.strip())
    except:
        score = 7 if lead.email else 5
        score = min(10, score + (1 if lead.role else 0) + (1 if lead.website else 0))
        return {"pain_points":["Scaling outreach","Lead management","Automation"],"fit_score":score,"fit_reason":"Auto-scored based on profile completeness","suggested_approach":"Standard outreach","icebreaker":f"Hi {lead.name.split()[0] if lead.name else 'there'},"}

def ai_message(lead, camp, channel, follow_up=0):
    try:
        enrichment = json.loads(lead.enrichment_json or "{}")
        fu = ["","This is a Day 3 follow-up. Reference previous message, add new value.","This is the final Day 7 follow-up. Be concise with strong CTA."]
        prompt = f"""Write B2B {channel} outreach. {fu[min(follow_up,2)]}
Product: {camp.product_description} | Industry: {camp.target_industry} | Tone: {camp.tone}
Lead: {lead.name}, {lead.company}, {lead.role} | Icebreaker: {enrichment.get('icebreaker','')}
Pain points: {enrichment.get('pain_points',[])}
{"Keep under 160 words, conversational" if channel=="whatsapp" else "Include Subject: line, body under 200 words"}
Write ONLY the message."""
        return gemini(prompt)
    except Exception as e:
        print(f"AI MESSAGE ERROR: {e}")
        return message_template(lead, camp, channel)

SAMPLE_LEADS = {
    "SaaS": [
        {"name":"Alex Johnson","company":"CloudFlow Inc","email":"alex@cloudflow.io","whatsapp":"","industry":"SaaS","role":"CTO","website":"cloudflow.io","notes":"Series A startup, 50 employees"},
        {"name":"Sara Kim","company":"DataPulse","email":"sara.kim@datapulse.com","whatsapp":"","industry":"SaaS","role":"Head of Engineering","website":"datapulse.com","notes":"B2B analytics platform"},
        {"name":"Raj Patel","company":"Nexus Labs","email":"raj@nexuslabs.io","whatsapp":"","industry":"SaaS","role":"Founder","website":"nexuslabs.io","notes":"Developer tools startup"},
        {"name":"Emma Wilson","company":"TaskFlow","email":"emma@taskflow.app","whatsapp":"","industry":"SaaS","role":"VP Product","website":"taskflow.app","notes":"Project management SaaS"},
        {"name":"Michael Chen","company":"APIfy","email":"m.chen@apify.dev","whatsapp":"","industry":"SaaS","role":"CEO","website":"apify.dev","notes":"API integration platform"},
    ],
    "E-commerce": [
        {"name":"Lisa Park","company":"ShopBoost","email":"lisa@shopboost.com","whatsapp":"","industry":"E-commerce","role":"Director of Marketing","website":"shopboost.com","notes":"Shopify app developer"},
        {"name":"James Torres","company":"BuyNow","email":"james@buynow.store","whatsapp":"","industry":"E-commerce","role":"Co-founder","website":"buynow.store","notes":"D2C fashion brand"},
        {"name":"Priya Sharma","company":"CartPro","email":"priya@cartpro.io","whatsapp":"","industry":"E-commerce","role":"Head of Growth","website":"cartpro.io","notes":"E-commerce optimization"},
        {"name":"David Lee","company":"RetailAI","email":"david@retailai.co","whatsapp":"","industry":"E-commerce","role":"CTO","website":"retailai.co","notes":"AI-powered retail solutions"},
        {"name":"Sophie Martin","company":"FlashSale","email":"sophie@flashsale.com","whatsapp":"","industry":"E-commerce","role":"CMO","website":"flashsale.com","notes":"Flash deals platform"},
    ],
    "Marketing": [
        {"name":"Chris Adams","company":"GrowthHive","email":"chris@growthhive.io","whatsapp":"","industry":"Marketing","role":"Founder","website":"growthhive.io","notes":"Digital marketing agency"},
        {"name":"Nina Patel","company":"LeadMagnet","email":"nina@leadmagnet.com","whatsapp":"","industry":"Marketing","role":"Head of Strategy","website":"leadmagnet.com","notes":"Lead generation agency"},
        {"name":"Tom Baker","company":"ViralEdge","email":"tom@viraledge.co","whatsapp":"","industry":"Marketing","role":"CEO","website":"viraledge.co","notes":"Social media marketing"},
        {"name":"Anna White","company":"ContentFlow","email":"anna@contentflow.io","whatsapp":"","industry":"Marketing","role":"Content Director","website":"contentflow.io","notes":"Content marketing platform"},
        {"name":"Mark Davis","company":"AdScale","email":"mark@adscale.com","whatsapp":"","industry":"Marketing","role":"CTO","website":"adscale.com","notes":"Ad automation platform"},
    ],
    "Finance": [
        {"name":"Robert Chang","company":"FinEdge","email":"robert@finedge.io","whatsapp":"","industry":"Finance","role":"CFO","website":"finedge.io","notes":"Fintech startup"},
        {"name":"Jennifer Wu","company":"PayStream","email":"jennifer@paystream.com","whatsapp":"","industry":"Finance","role":"CEO","website":"paystream.com","notes":"Payment processing"},
        {"name":"Kevin Brown","company":"WealthAI","email":"kevin@wealthai.co","whatsapp":"","industry":"Finance","role":"CTO","website":"wealthai.co","notes":"AI wealth management"},
        {"name":"Michelle Lee","company":"LoanDesk","email":"michelle@loandesk.io","whatsapp":"","industry":"Finance","role":"Head of Product","website":"loandesk.io","notes":"Digital lending platform"},
        {"name":"Steven Park","company":"TaxBot","email":"steven@taxbot.app","whatsapp":"","industry":"Finance","role":"Founder","website":"taxbot.app","notes":"Tax automation startup"},
    ],
    "Healthcare": [
        {"name":"Dr. Sarah Foster","company":"MedTech Pro","email":"sarah@medtechpro.com","whatsapp":"","industry":"Healthcare","role":"CEO","website":"medtechpro.com","notes":"Medical device company"},
        {"name":"Dr. James Liu","company":"HealthAI","email":"james@healthai.io","whatsapp":"","industry":"Healthcare","role":"CTO","website":"healthai.io","notes":"AI diagnostics platform"},
        {"name":"Emily Clark","company":"CareConnect","email":"emily@careconnect.com","whatsapp":"","industry":"Healthcare","role":"Head of Operations","website":"careconnect.com","notes":"Telemedicine platform"},
        {"name":"Dr. Arun Singh","company":"PharmaTech","email":"arun@pharmatech.io","whatsapp":"","industry":"Healthcare","role":"Director","website":"pharmatech.io","notes":"Pharma tech startup"},
        {"name":"Laura Martinez","company":"WellnessApp","email":"laura@wellnessapp.co","whatsapp":"","industry":"Healthcare","role":"Founder","website":"wellnessapp.co","notes":"Health & wellness platform"},
    ],
    "Real Estate": [
        {"name":"John Smith","company":"PropTech Solutions","email":"john@proptech.io","whatsapp":"","industry":"Real Estate","role":"CEO","website":"proptech.io","notes":"Real estate tech startup"},
        {"name":"Maria Garcia","company":"HomeFind","email":"maria@homefind.com","whatsapp":"","industry":"Real Estate","role":"Head of Sales","website":"homefind.com","notes":"Property listing platform"},
        {"name":"Brian Johnson","company":"RentFlow","email":"brian@rentflow.io","whatsapp":"","industry":"Real Estate","role":"CTO","website":"rentflow.io","notes":"Rental management platform"},
        {"name":"Susan Taylor","company":"LandValue","email":"susan@landvalue.com","whatsapp":"","industry":"Real Estate","role":"Founder","website":"landvalue.com","notes":"Land valuation startup"},
        {"name":"William Brown","company":"BuildSmart","email":"william@buildsmart.io","whatsapp":"","industry":"Real Estate","role":"Director","website":"buildsmart.io","notes":"Construction tech company"},
    ],
    "FMCG": [
        {"name":"Amit Sharma","company":"NatureFresh Foods","email":"amit@naturefresh.in","whatsapp":"+919876543210","industry":"FMCG","role":"National Sales Head","website":"naturefresh.in","notes":"Packaged foods brand, 200+ distributors"},
        {"name":"Pooja Mehta","company":"PureLife Consumer","email":"pooja@purelife.co.in","whatsapp":"+919765432109","industry":"FMCG","role":"VP Marketing","website":"purelife.co.in","notes":"FMCG distributor, pan-India presence"},
        {"name":"Rakesh Gupta","company":"Bharat Brands","email":"rakesh@bharatbrands.com","whatsapp":"+919654321098","industry":"FMCG","role":"CEO","website":"bharatbrands.com","notes":"Regional FMCG brand, 15 SKUs"},
        {"name":"Sunita Joshi","company":"GreenLeaf Products","email":"sunita@greenleaf.in","whatsapp":"+919543210987","industry":"FMCG","role":"Director Sales","website":"greenleaf.in","notes":"Organic FMCG startup"},
        {"name":"Vijay Nair","company":"QuickMart Distributors","email":"vijay@quickmart.in","whatsapp":"+919432109876","industry":"FMCG","role":"Founder","website":"quickmart.in","notes":"FMCG distribution network, Tier 2 cities"},
    ],
    "Manufacturing": [
        {"name":"Suresh Patel","company":"Patel Engineering Works","email":"suresh@pateleng.com","whatsapp":"+919321098765","industry":"Manufacturing","role":"Managing Director","website":"pateleng.com","notes":"Auto parts manufacturer, 500 employees"},
        {"name":"Ramesh Verma","company":"Verma Steel Industries","email":"ramesh@vermasteel.in","whatsapp":"+919210987654","industry":"Manufacturing","role":"CEO","website":"vermasteel.in","notes":"Steel fabrication, B2B supplier"},
        {"name":"Kavita Singh","company":"Precision Parts Ltd","email":"kavita@precisionparts.co.in","whatsapp":"+919109876543","industry":"Manufacturing","role":"Operations Head","website":"precisionparts.co.in","notes":"CNC machining, exports to EU"},
        {"name":"Dinesh Kumar","company":"Kumar Plastics","email":"dinesh@kumarplastics.in","whatsapp":"+918998765432","industry":"Manufacturing","role":"Director","website":"kumarplastics.in","notes":"Plastic injection molding"},
        {"name":"Anita Rao","company":"Rao Textiles","email":"anita@raotextiles.com","whatsapp":"+918887654321","industry":"Manufacturing","role":"GM Sales","website":"raotextiles.com","notes":"Textile manufacturer, 300 workers"},
    ],
    "Retail": [
        {"name":"Manish Agarwal","company":"AgarwalMart","email":"manish@agarwalmart.in","whatsapp":"+918776543210","industry":"Retail","role":"Owner","website":"agarwalmart.in","notes":"Supermarket chain, 12 stores"},
        {"name":"Rekha Jain","company":"Jain Fashion House","email":"rekha@jainfashion.com","whatsapp":"+918665432109","industry":"Retail","role":"Director","website":"jainfashion.com","notes":"Fashion retail, 20 outlets"},
        {"name":"Arun Tiwari","company":"TechZone Retail","email":"arun@techzoneretail.in","whatsapp":"+918554321098","industry":"Retail","role":"CEO","website":"techzoneretail.in","notes":"Electronics retail chain"},
        {"name":"Meena Pandey","company":"Pandey Grocers","email":"meena@pandeygrocers.com","whatsapp":"+918443210987","industry":"Retail","role":"Founder","website":"pandeygrocers.com","notes":"Online grocery, 5000+ customers"},
        {"name":"Sanjay Chopra","company":"Chopra Home & Living","email":"sanjay@choprahome.in","whatsapp":"+918332109876","industry":"Retail","role":"MD","website":"choprahome.in","notes":"Home furnishing retail"},
    ],
    "Logistics": [
        {"name":"Prakash Reddy","company":"Reddy Cargo Solutions","email":"prakash@reddycargo.in","whatsapp":"+918221098765","industry":"Logistics","role":"CEO","website":"reddycargo.in","notes":"Last-mile delivery, 50 vehicles"},
        {"name":"Harish Bansal","company":"Bansal Freight","email":"harish@bansalfreight.com","whatsapp":"+918110987654","industry":"Logistics","role":"Director","website":"bansalfreight.com","notes":"Pan-India freight forwarding"},
        {"name":"Deepa Mishra","company":"FastShip Logistics","email":"deepa@fastship.in","whatsapp":"+918009876543","industry":"Logistics","role":"COO","website":"fastship.in","notes":"E-commerce logistics partner"},
        {"name":"Rohit Kapoor","company":"Kapoor Cold Chain","email":"rohit@kapoorcc.com","whatsapp":"+917998765432","industry":"Logistics","role":"MD","website":"kapoorcc.com","notes":"Cold chain logistics for FMCG"},
        {"name":"Nisha Saxena","company":"QuickMove Express","email":"nisha@quickmove.in","whatsapp":"+917887654321","industry":"Logistics","role":"Founder","website":"quickmove.in","notes":"Same-day delivery startup"},
    ],
    "Education": [
        {"name":"Dr. Pradeep Sharma","company":"BrightFuture Academy","email":"pradeep@brightfuture.in","whatsapp":"+917776543210","industry":"Education","role":"Director","website":"brightfuture.in","notes":"Coaching institute, 2000 students"},
        {"name":"Anjali Gupta","company":"LearnSmart EdTech","email":"anjali@learnsmart.co.in","whatsapp":"+917665432109","industry":"Education","role":"CEO","website":"learnsmart.co.in","notes":"Online learning platform"},
        {"name":"Prof. Sunil Bose","company":"Bose Institute","email":"sunil@boseinstitute.com","whatsapp":"+917554321098","industry":"Education","role":"Founder","website":"boseinstitute.com","notes":"Professional certification courses"},
        {"name":"Priya Kulkarni","company":"SkillUp India","email":"priya@skillupindia.in","whatsapp":"+917443210987","industry":"Education","role":"Head of Partnerships","website":"skillupindia.in","notes":"Skill development platform"},
        {"name":"Manoj Tiwari","company":"TalentGrove","email":"manoj@talentgrove.com","whatsapp":"+917332109876","industry":"Education","role":"Co-founder","website":"talentgrove.com","notes":"Corporate training company"},
    ],
    "Construction": [
        {"name":"Vikram Malhotra","company":"Malhotra Builders","email":"vikram@malhotrabuilders.in","whatsapp":"+917221098765","industry":"Construction","role":"MD","website":"malhotrabuilders.in","notes":"Residential construction, 10 projects"},
        {"name":"Geeta Desai","company":"Desai Infrastructure","email":"geeta@desaiinfra.com","whatsapp":"+917110987654","industry":"Construction","role":"Director","website":"desaiinfra.com","notes":"Civil engineering contractor"},
        {"name":"Ravi Pillai","company":"Pillai Constructions","email":"ravi@pillaigroup.in","whatsapp":"+917009876543","industry":"Construction","role":"CEO","website":"pillaigroup.in","notes":"Commercial construction firm"},
        {"name":"Shobha Iyer","company":"Iyer & Associates","email":"shobha@iyerassoc.com","whatsapp":"+916998765432","industry":"Construction","role":"Partner","website":"iyerassoc.com","notes":"Architecture & construction"},
        {"name":"Naresh Bhatt","company":"BhattBuild","email":"naresh@bhattbuild.in","whatsapp":"+916887654321","industry":"Construction","role":"Founder","website":"bhattbuild.in","notes":"Affordable housing developer"},
    ],
    "IT Staffing": [
        {"name":"Nikhil Mehta","company":"TalentBridge IT","email":"nikhil@talentbridgeit.com","whatsapp":"","industry":"IT Staffing","role":"CEO","website":"talentbridgeit.com","notes":"IT staffing & recruitment, 200+ placements/year"},
        {"name":"Pooja Agarwal","company":"CodeHire Solutions","email":"pooja@codehire.in","whatsapp":"","industry":"IT Staffing","role":"Director","website":"codehire.in","notes":"Tech talent acquisition firm"},
        {"name":"Rajan Nair","company":"DevForce Staffing","email":"rajan@devforce.io","whatsapp":"","industry":"IT Staffing","role":"Founder","website":"devforce.io","notes":"Contract & permanent IT staffing"},
        {"name":"Sneha Choudhary","company":"StackRecruit","email":"sneha@stackrecruit.com","whatsapp":"","industry":"IT Staffing","role":"Head of Operations","website":"stackrecruit.com","notes":"Specializes in full-stack & cloud engineers"},
        {"name":"Arjun Pillai","company":"TechHunt India","email":"arjun@techhunt.in","whatsapp":"","industry":"IT Staffing","role":"Co-founder","website":"techhunt.in","notes":"Pan-India IT recruitment, 50+ clients"},
    ],
    "Marketing Agency": [
        {"name":"Ritu Sharma","company":"GrowthCraft Agency","email":"ritu@growthcraft.in","whatsapp":"","industry":"Marketing Agency","role":"Founder","website":"growthcraft.in","notes":"Digital marketing agency, 80+ brand clients"},
        {"name":"Varun Bhatia","company":"PixelPulse Media","email":"varun@pixelpulse.io","whatsapp":"","industry":"Marketing Agency","role":"CEO","website":"pixelpulse.io","notes":"Performance marketing & paid ads"},
        {"name":"Ananya Seth","company":"BrandBurst","email":"ananya@brandburst.co","whatsapp":"","industry":"Marketing Agency","role":"Creative Director","website":"brandburst.co","notes":"Brand strategy & social media"},
        {"name":"Karan Malhotra","company":"InfluenceFlow","email":"karan@influenceflow.in","whatsapp":"","industry":"Marketing Agency","role":"Director","website":"influenceflow.in","notes":"Influencer & content marketing agency"},
        {"name":"Divya Kapoor","company":"LeadLaunch Digital","email":"divya@leadlaunch.io","whatsapp":"","industry":"Marketing Agency","role":"Head of Strategy","website":"leadlaunch.io","notes":"B2B lead generation & SEO agency"},
    ],
    "EdTech": [
        {"name":"Rahul Joshi","company":"SkillSprint","email":"rahul@skillsprint.io","whatsapp":"","industry":"EdTech","role":"CEO","website":"skillsprint.io","notes":"Online upskilling platform, 50k+ learners"},
        {"name":"Meera Patel","company":"ClassCloud India","email":"meera@classcloud.in","whatsapp":"","industry":"EdTech","role":"Co-founder","website":"classcloud.in","notes":"K-12 online tutoring platform"},
        {"name":"Amit Kumar","company":"LearnLoop","email":"amit@learnloop.co","whatsapp":"","industry":"EdTech","role":"CTO","website":"learnloop.co","notes":"AI-powered adaptive learning for engineering students"},
        {"name":"Priya Nambiar","company":"EduReach","email":"priya@edureach.in","whatsapp":"","industry":"EdTech","role":"Head of Partnerships","website":"edureach.in","notes":"Rural EdTech startup, vernacular content"},
        {"name":"Siddharth Rao","company":"ExamAce","email":"siddharth@examace.io","whatsapp":"","industry":"EdTech","role":"Founder","website":"examace.io","notes":"UPSC & competitive exam prep platform"},
    ],
    "Finance / Fintech": [
        {"name":"Aditya Shah","company":"PayEase Fintech","email":"aditya@payease.io","whatsapp":"","industry":"Finance / Fintech","role":"CEO","website":"payease.io","notes":"UPI-based payment gateway startup"},
        {"name":"Kaveri Iyer","company":"LendSmart","email":"kaveri@lendsmart.in","whatsapp":"","industry":"Finance / Fintech","role":"Founder","website":"lendsmart.in","notes":"MSME lending platform, ₹5cr+ disbursed"},
        {"name":"Rohan Chopra","company":"WealthNest","email":"rohan@wealthnest.co","whatsapp":"","industry":"Finance / Fintech","role":"CTO","website":"wealthnest.co","notes":"Robo-advisory wealth management"},
        {"name":"Sunita Mishra","company":"InsurAI","email":"sunita@insurai.in","whatsapp":"","industry":"Finance / Fintech","role":"Head of Product","website":"insurai.in","notes":"AI-driven insurance comparison platform"},
        {"name":"Nitin Garg","company":"TaxSimple","email":"nitin@taxsimple.io","whatsapp":"","industry":"Finance / Fintech","role":"Director","website":"taxsimple.io","notes":"GST & ITR filing SaaS for SMBs"},
    ],
    "SaaS / Software": [
        {"name":"Vikram Anand","company":"CloudMatrix","email":"vikram@cloudmatrix.io","whatsapp":"","industry":"SaaS / Software","role":"CEO","website":"cloudmatrix.io","notes":"B2B SaaS for supply chain management"},
        {"name":"Pooja Reddy","company":"FormFlow","email":"pooja@formflow.app","whatsapp":"","industry":"SaaS / Software","role":"Founder","website":"formflow.app","notes":"No-code form builder SaaS, 10k+ users"},
        {"name":"Aman Gupta","company":"DeskMate Pro","email":"aman@deskmateapp.com","whatsapp":"","industry":"SaaS / Software","role":"CTO","website":"deskmateapp.com","notes":"Remote work productivity suite"},
        {"name":"Divya Sharma","company":"ReportGen AI","email":"divya@reportgen.io","whatsapp":"","industry":"SaaS / Software","role":"Head of Growth","website":"reportgen.io","notes":"Automated business reporting platform"},
        {"name":"Kiran Nair","company":"InvoiceZen","email":"kiran@invoicezen.in","whatsapp":"","industry":"SaaS / Software","role":"Co-founder","website":"invoicezen.in","notes":"GST invoicing & billing software for SMBs"},
    ],
}

MESSAGE_TEMPLATES = {
    "email": "Subject: Quick question for {company}\n\nHi {name},\n\nI came across {company} and was impressed by your work in the {industry} space.\n\nWe help {industry} companies streamline their outreach and grow faster. I'd love to share how we could help {company} as well.\n\nWould you be open to a quick 15-minute call this week?\n\nBest regards",
    "whatsapp": "Hi {name}! I noticed {company} is doing great work in {industry}. We help similar companies grow faster. Would love to connect — open to a quick chat this week?",
}

def message_template(lead, camp, channel):
    t = MESSAGE_TEMPLATES.get(channel, MESSAGE_TEMPLATES["email"])
    return t.format(
        name=lead.name.split()[0] if lead.name else "there",
        company=lead.company or "your company",
        industry=lead.industry or camp.target_industry or "your industry",
    )

def scrape_url_no_ai(url, industry=""):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        emails = list(set(re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', text)))
        emails = [e for e in emails if not any(e.endswith(x) for x in ['.png','.jpg','.gif','.svg'])][:5]
        phones = re.findall(r'\+?[\d\s\-\(\)]{10,15}', text)
        og_site = soup.find('meta', property='og:site_name')
        title = soup.find('title')
        company = og_site.get('content','') if og_site else (title.text.split('|')[0].split('-')[0].strip() if title else url.split('/')[2].replace('www.','').split('.')[0].title())
        leads = []
        for email in emails:
            name = email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
            leads.append({"name": name, "company": company, "email": email,
                          "whatsapp": phones[0].strip() if phones else "",
                          "industry": industry, "role": "", "website": url,
                          "notes": f"Scraped from {url}"})
        return leads
    except: return []

def scrape_url(url, industry=""):
    try:
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        text = BeautifulSoup(r.text,"html.parser").get_text(separator=" ",strip=True)[:3000]
        prompt = f"""Extract leads from webpage. URL:{url} Industry:{industry}
Content:{text}
Return ONLY JSON array: [{{"name":"","company":"","email":"","whatsapp":"","industry":"{industry}","role":"","website":"{url}","notes":""}}]
Return [] if none found."""
        t = gemini(prompt)
        if "```" in t: t = t.split("```")[1]; t = t[4:] if t.startswith("json") else t
        return json.loads(t.strip())
    except: return scrape_url_no_ai(url, industry)

scheduler = BackgroundScheduler()

def run_follow_ups():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        for lead in db.query(LeadDB).filter(LeadDB.status=="contacted").all():
            if not lead.last_contacted: continue
            days = (now - lead.last_contacted).days
            camp = db.query(CampaignDB).filter(CampaignDB.user_id==lead.user_id).first()
            if not camp: continue
            if days >= 3 and lead.follow_up_day == 0:
                msg = ai_message(lead, camp, "email", 1)
                db.add(MessageLogDB(user_id=lead.user_id,lead_id=lead.id,campaign_id=camp.id,channel="email",message=msg,follow_up_number=1))
                lead.follow_up_day = 3; db.commit()
            elif days >= 7 and lead.follow_up_day == 3:
                msg = ai_message(lead, camp, "email", 2)
                db.add(MessageLogDB(user_id=lead.user_id,lead_id=lead.id,campaign_id=camp.id,channel="email",message=msg,follow_up_number=2))
                lead.follow_up_day = 7; lead.status = "sequence_complete"; db.commit()
    finally: db.close()

def run_morning_scrape():
    db = SessionLocal()
    try:
        for src in db.query(ScrapedSourceDB).filter(ScrapedSourceDB.schedule=="daily").all():
            for ld in scrape_url(src.url, src.industry):
                fp = make_fingerprint(ld.get("name",""),ld.get("company",""),ld.get("email",""),ld.get("whatsapp",""))
                if db.query(LeadDB).filter(LeadDB.fingerprint==fp,LeadDB.user_id==src.user_id).first(): continue
                db.add(LeadDB(user_id=src.user_id,fingerprint=fp,source="schedule",
                              **{k:v for k,v in ld.items() if k in ["name","company","email","whatsapp","industry","role","website","notes"]}))
                src.leads_found += 1
            src.last_run = datetime.utcnow(); db.commit()
    finally: db.close()

scheduler.add_job(run_follow_ups,"interval",hours=6,id="follow_ups")
scheduler.add_job(run_morning_scrape,"cron",hour=9,minute=0,id="morning_scrape")
scheduler.start()

app = FastAPI(title="LeadGen AI v2", version="2.0.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

frontend_path = str(Path(__file__).resolve().parent.parent / "frontend")
app.mount("/frontend", StaticFiles(directory=frontend_path), name="frontend")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(frontend_path, "landing.html"))

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}

@app.get("/admin")
def serve_admin():
    return FileResponse(os.path.join(frontend_path, "admin.html"), headers=NO_CACHE_HEADERS)

@app.get("/dashboard")
def serve_dashboard():
    return FileResponse(os.path.join(frontend_path, "index.html"), headers=NO_CACHE_HEADERS)

@app.get("/client")
def serve_client():
    return FileResponse(os.path.join(frontend_path, "client.html"), headers=NO_CACHE_HEADERS)

class UserCreate(BaseModel): email:str; name:str; password:str
class LeadCreate(BaseModel):
    name:str; company:str; email:Optional[str]=""; whatsapp:Optional[str]=""
    industry:Optional[str]=""; role:Optional[str]=""; website:Optional[str]=""; notes:Optional[str]=""
class CampaignCreate(BaseModel):
    name:str; product_description:str; target_industry:str; tone:str="professional"; channel:str="both"
class OutreachReq(BaseModel): lead_id:str; campaign_id:str; channel:str="email"
class ScrapeReq(BaseModel): url:str; industry:Optional[str]=""; schedule:Optional[str]="none"
class AutoGenReq(BaseModel): industry:str; count:Optional[int]=5
class AgentRunReq(BaseModel): campaign_id:str; city: str = "Mumbai"; industry:str; source_url:Optional[str]=""; count:Optional[int]=5
class PlacesSearchReq(BaseModel): industry:str; city:str; count:Optional[int]=5
class ApolloSearchReq(BaseModel): industry:str; city:str; count:Optional[int]=5

@app.post("/auth/register")
def register(user:UserCreate, db:Session=Depends(get_db)):
    if db.query(UserDB).filter(UserDB.email==user.email).first(): raise HTTPException(400,"Email already registered")
    u = UserDB(email=user.email,name=user.name,hashed_password=hash_password(user.password))
    db.add(u); db.commit(); db.refresh(u)
    return {"access_token":create_token({"sub":u.id}),"token_type":"bearer","user":_user_dict(u)}

@app.post("/auth/login")
def login(form:OAuth2PasswordRequestForm=Depends(), db:Session=Depends(get_db)):
    u = db.query(UserDB).filter(UserDB.email==form.username).first()
    if not u or not verify_password(form.password,u.hashed_password): raise HTTPException(401,"Invalid credentials")
    otp = str(random.randint(100000, 999999))
    record = db.query(OTPStoreDB).filter(OTPStoreDB.email == u.email).first()
    if record:
        record.otp = otp; record.expires = time.time() + 600; record.user_id = u.id
    else:
        db.add(OTPStoreDB(email=u.email, otp=otp, expires=time.time() + 600, user_id=u.id))
    db.commit()
    _send_otp_email(u.email, u.name or u.email, otp)
    return {"otp_required": True, "email": u.email}

def _send_otp_email(to_email: str, name: str, otp: str):
    import logging
    logger = logging.getLogger("otp")
    logger.info(f"OTP for {to_email}: {otp}")
    print(f"\n{'='*40}\nOTP for {to_email}: {otp}\n{'='*40}\n", flush=True)
    try:
        from app.services.email_service import send_email
        send_email(
            to_email=to_email,
            subject=f"Your LeadGen AI login code: {otp}",
            body_html=f"""
            <div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#f9fafb;border-radius:12px">
              <h2 style="color:#111827;margin-bottom:8px">Your login code</h2>
              <p style="color:#6B7280;margin-bottom:24px">Hi {name}, use the code below to complete your login.</p>
              <div style="background:#fff;border:2px solid #1570EF;border-radius:10px;padding:24px;text-align:center;margin-bottom:24px">
                <span style="font-size:36px;font-weight:800;letter-spacing:8px;color:#1570EF">{otp}</span>
              </div>
              <p style="color:#9CA3AF;font-size:12px">This code expires in 10 minutes. If you didn't request this, ignore this email.</p>
            </div>""",
            body_text=f"Your LeadGen AI login code is: {otp}\nExpires in 10 minutes.",
            from_email=os.getenv("SENDGRID_FROM_EMAIL", "noreply@leadgenai.in"),
            from_name="LeadGen AI",
        )
    except Exception:
        pass  # email delivery failed but OTP is printed to terminal

class OTPVerify(BaseModel):
    email: str
    otp: str

@app.post("/auth/verify-otp")
def verify_otp(body: OTPVerify, db: Session = Depends(get_db)):
    record = db.query(OTPStoreDB).filter(OTPStoreDB.email == body.email).first()
    if not record:
        raise HTTPException(401, "OTP expired or not requested. Please login again.")
    if time.time() > record.expires:
        db.delete(record); db.commit()
        raise HTTPException(401, "OTP expired. Please login again.")
    if record.otp != body.otp.strip():
        raise HTTPException(401, "Invalid OTP. Please try again.")
    user_id = record.user_id
    db.delete(record); db.commit()
    u = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not u:
        raise HTTPException(401, "User not found.")
    return {"access_token": create_token({"sub": u.id}), "token_type": "bearer", "user": _user_dict(u)}

@app.get("/auth/me")
def me(cu:UserDB=Depends(get_current_user)): return _user_dict(cu)

@app.post("/setup/make-admin")
def setup_make_admin(email: str, secret: str, db: Session = Depends(get_db)):
    setup_secret = os.getenv("SETUP_SECRET", "")
    if not setup_secret or secret != setup_secret:
        raise HTTPException(403, "Invalid setup secret.")
    u = db.query(UserDB).filter(UserDB.email == email).first()
    if not u:
        raise HTTPException(404, "User not found. Register first.")
    u.role = "admin"
    db.commit()
    return {"ok": True, "message": f"{email} is now admin."}

@app.post("/auth/logout")
def logout(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        jti = payload.get("jti")
    except JWTError:
        return {"ok": True}
    if jti and not db.query(RevokedTokenDB).filter(RevokedTokenDB.jti == jti).first():
        db.add(RevokedTokenDB(jti=jti))
        db.commit()
    return {"ok": True}

class OnboardingData(BaseModel):
    id_type:         Optional[str] = ""
    id_value:        Optional[str] = ""
    country:         Optional[str] = "IN"
    company:         Optional[str] = ""
    industry:        Optional[str] = ""
    website:         Optional[str] = ""
    city:            Optional[str] = ""
    target_industry: Optional[str] = ""
    target_city:     Optional[str] = ""
    target_size:     Optional[str] = ""
    target_titles:   Optional[str] = ""
    product:         Optional[str] = ""
    tone:            Optional[str] = "professional"
    channel:         Optional[str] = "email"
    sender_name:     Optional[str] = ""
    sender_title:    Optional[str] = ""
    sender_email:    Optional[str] = ""
    sender_phone:    Optional[str] = ""

@app.get("/admin/users")
def admin_list_users(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    if cu.role not in ("admin", "superadmin"):
        raise HTTPException(403, "Admin only")
    users = db.query(UserDB).order_by(UserDB.created_at.desc()).all()
    result = []
    for u in users:
        lead_count = db.query(LeadDB).filter(LeadDB.user_id == u.id).count()
        msg_count  = db.query(MessageLogDB).filter(MessageLogDB.user_id == u.id).count()
        result.append({
            "id":         u.id,
            "name":       u.name,
            "email":      u.email,
            "plan":       u.plan,
            "leads_used": u.leads_used,
            "leads_limit": u.leads_limit,
            "lead_count": lead_count,
            "msg_count":  msg_count,
            "created_at": str(u.created_at),
            "is_active":  u.is_active,
        })
    return {"users": result, "total": len(result)}

@app.put("/admin/users/{user_id}")
def admin_update_user(user_id: str, data: dict, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    if cu.role not in ("admin", "superadmin"):
        raise HTTPException(403, "Admin only")
    u = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not u: raise HTTPException(404, "User not found")
    if "name"         in data: u.name      = data["name"]
    if "email"        in data: u.email     = data["email"]
    if "plan"         in data: u.plan      = data["plan"]
    if "is_active"    in data: u.is_active = data["is_active"]
    if "kyc_id_type"  in data: u.kyc_id_type  = data["kyc_id_type"]
    if "kyc_id_value" in data: u.kyc_id_value = data["kyc_id_value"]
    if data.get("kyc_id_value"): u.kyc_locked = True
    if "trial_ends_at" in data and data["trial_ends_at"]:
        from datetime import datetime
        u.trial_ends_at = datetime.fromisoformat(data["trial_ends_at"].replace("Z",""))
    db.commit()
    return {"status": "ok"}

@app.get("/auth/profile")
def get_profile(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    client_id = getattr(cu, 'client_id', None)
    client = None
    try:
        if client_id:
            client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
    except Exception:
        pass
    return {
        "name":              cu.name,
        "email":             cu.email,
        "kyc_id_type":       getattr(cu, 'kyc_id_type', None),
        "kyc_id_value":      getattr(cu, 'kyc_id_value', None),
        "kyc_country":       getattr(cu, 'kyc_country', None),
        "kyc_locked":        getattr(cu, 'kyc_locked', False),
        "sender_name":       getattr(cu, 'sender_name', None),
        "sender_title":      getattr(cu, 'sender_title', None),
        "sender_email":      getattr(cu, 'sender_email', None),
        "sender_phone":      getattr(cu, 'sender_phone', None),
        "company":           getattr(client, 'name', None),
        "industry":          getattr(client, 'industry', None),
        "website":           getattr(client, 'website', None),
        "city":              getattr(client, 'city', None),
        "target_industry":   getattr(client, 'target_industry', None),
        "target_city":       getattr(client, 'target_city', None),
        "target_size":       getattr(client, 'target_size', None),
        "target_titles":     getattr(client, 'target_titles', None),
        "product":           getattr(client, 'product_desc', None),
        "tone":              (client.tone_config.get("tone") if client and getattr(client, 'tone_config', None) else None),
        "channel":           getattr(client, 'preferred_channel', None),
        "sendgrid_connected": bool(getattr(cu, 'sender_email', None)),
        "whatsapp_connected": bool(getattr(client, 'wa_number', None)),
    }

@app.put("/auth/profile")
def update_profile(data: dict, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    client_id = getattr(cu, 'client_id', None)
    client = None
    try:
        if client_id:
            client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
    except Exception:
        pass
    # User fields (only set if the column exists on this model)
    if "name"         in data and data["name"]:         cu.name         = data["name"]
    if hasattr(cu, 'sender_name')  and "sender_name"  in data and data["sender_name"]:  cu.sender_name  = data["sender_name"]
    if hasattr(cu, 'sender_title') and "sender_title" in data: cu.sender_title = data["sender_title"]
    if hasattr(cu, 'sender_email') and "sender_email" in data and data["sender_email"]: cu.sender_email = data["sender_email"]
    if hasattr(cu, 'sender_phone') and "sender_phone" in data: cu.sender_phone = data["sender_phone"]
    # Client fields
    if client:
        if "company"         in data and data["company"]:  client.name             = data["company"]
        if "industry"        in data: client.industry         = data["industry"]
        if "website"         in data: client.website          = data["website"]
        if "city"            in data: client.city             = data["city"]
        if "target_industry" in data: client.target_industry  = data["target_industry"]
        if "target_city"     in data: client.target_city      = data["target_city"]
        if "target_size"     in data: client.target_size      = data["target_size"]
        if "target_titles"   in data: client.target_titles    = data["target_titles"]
        if "product"         in data: client.product_desc     = data["product"]
        if "tone"            in data: client.tone_config      = {"tone": data["tone"]}
        if "channel"         in data: client.preferred_channel = data["channel"]
    db.commit()
    return {"status": "ok"}

@app.get("/plan/summary")
def plan_summary(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    client_id = getattr(cu, 'client_id', None) or cu.id
    try:
        from app.services.plan_gate import get_plan_summary
        return get_plan_summary(db, client_id)
    except Exception:
        return {"name": cu.plan or "free", "leads_per_month": cu.leads_limit,
                "leads_used_this_month": cu.leads_used, "leads_remaining": max(0, cu.leads_limit - cu.leads_used),
                "usage_pct": round((cu.leads_used / cu.leads_limit) * 100, 1) if cu.leads_limit else 0}

@app.post("/auth/onboarding")
def save_onboarding(data: OnboardingData, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    from datetime import timedelta
    # Save KYC — lock if provided, only if not already locked
    if data.id_value and not cu.kyc_locked:
        cu.kyc_id_type  = data.id_type
        cu.kyc_id_value = data.id_value
        cu.kyc_country  = data.country
        cu.kyc_locked   = True
    # Save sender details
    if data.sender_name:  cu.sender_name  = data.sender_name
    if data.sender_title: cu.sender_title = data.sender_title
    if data.sender_email: cu.sender_email = data.sender_email
    if data.sender_phone: cu.sender_phone = data.sender_phone
    # Set trial window
    cu.trial_started_at = datetime.utcnow()
    cu.trial_ends_at    = datetime.utcnow() + timedelta(days=7)
    cu.onboarding_done  = True
    # Save client profile
    if getattr(cu, 'client_id', None):
        client = db.query(ClientDB).filter(ClientDB.id == cu.client_id).first()
        if client:
            if data.company:         client.name             = data.company
            if data.industry:        client.industry         = data.industry
            if data.website:         client.website          = data.website
            if data.city:            client.city             = data.city
            if data.target_industry: client.target_industry  = data.target_industry
            if data.target_city:     client.target_city      = data.target_city
            if data.target_size:     client.target_size      = data.target_size
            if data.target_titles:   client.target_titles    = data.target_titles
            if data.product:         client.product_desc     = data.product
            if data.tone:            client.tone_config      = {"tone": data.tone}
            if data.channel:         client.preferred_channel = data.channel
            client.onboarding_complete = True
    db.commit()
    return {"status": "ok", "trial_ends_at": cu.trial_ends_at.isoformat() if cu.trial_ends_at else None}

def enrich_with_hunter(domain: str) -> dict:
    if not HUNTER_API_KEY or not domain:
        return {}
    try:
        domain = domain.replace("https://","").replace("http://","").split("/")[0].replace("www.","")
        r = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 1},
            timeout=10
        )
        data = r.json().get("data", {})
        emails = data.get("emails", [])
        if emails:
            e = emails[0]
            return {
                "email": e.get("value", ""),
                "name": f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                "role": e.get("position", "")
            }
    except Exception:
        pass
    return {}

@app.get("/leads")
def get_leads(db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    leads = db.query(LeadDB).filter(LeadDB.user_id==cu.id).all()
    return {"leads":[_ld(l) for l in leads],"total":len(leads)}

@app.post("/leads")
def create_lead(lead:LeadCreate,db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    _chk(cu)
    fp = make_fingerprint(lead.name,lead.company,lead.email or "",lead.whatsapp or "")
    ex = db.query(LeadDB).filter(LeadDB.fingerprint==fp,LeadDB.user_id==cu.id).first()
    if ex: return {"success":False,"duplicate":True,"existing_id":ex.id,"message":"Duplicate lead detected"}
    l = LeadDB(user_id=cu.id,fingerprint=fp,**lead.dict())
    db.add(l); cu.leads_used+=1; db.commit(); db.refresh(l)
    return {"success":True,"lead_id":l.id,"lead":_ld(l)}

@app.post("/leads/upload-csv")
async def upload_csv(file:UploadFile=File(...),db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    added,dups,skipped = [],0,0
    for row in reader:
        if cu.leads_used >= cu.leads_limit: skipped+=1; continue
        n=row.get("name",row.get("Name","")); co=row.get("company",row.get("Company",""))
        em=row.get("email",row.get("Email","")); wa=row.get("whatsapp",row.get("phone",row.get("Phone","")))
        fp = make_fingerprint(n,co,em,wa)
        if db.query(LeadDB).filter(LeadDB.fingerprint==fp,LeadDB.user_id==cu.id).first(): dups+=1; continue
        l = LeadDB(user_id=cu.id,fingerprint=fp,name=n,company=co,email=em,whatsapp=wa,
                   industry=row.get("industry",row.get("Industry","")),
                   role=row.get("role",row.get("Role",row.get("title",""))),
                   website=row.get("website",row.get("Website","")),
                   notes=row.get("notes",row.get("Notes","")),source="csv")
        db.add(l); cu.leads_used+=1; added.append(l.id)
    db.commit()
    return {"success":True,"imported":len(added),"duplicates_skipped":dups,"limit_skipped":skipped}

@app.post("/leads/scrape")
def scrape(req:ScrapeReq,db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    scraped = scrape_url(req.url,req.industry or "")
    added,dups = [],0
    for ld in scraped:
        if cu.leads_used >= cu.leads_limit: break
        fp = make_fingerprint(ld.get("name",""),ld.get("company",""),ld.get("email",""),ld.get("whatsapp",""))
        if db.query(LeadDB).filter(LeadDB.fingerprint==fp,LeadDB.user_id==cu.id).first(): dups+=1; continue
        l = LeadDB(user_id=cu.id,fingerprint=fp,source="scrape",**{k:v for k,v in ld.items() if k in ["name","company","email","whatsapp","industry","role","website","notes"]})
        db.add(l); cu.leads_used+=1; added.append(l.id)
    if req.schedule and req.schedule!="none":
        db.add(ScrapedSourceDB(user_id=cu.id,url=req.url,industry=req.industry or "",schedule=req.schedule))
    db.commit()
    return {"success":True,"scraped":len(added),"duplicates_skipped":dups,"leads":[_ld(db.query(LeadDB).get(i)) for i in added]}

@app.post("/leads/auto-generate")
def auto_generate(req:AutoGenReq,db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    pool = SAMPLE_LEADS.get(req.industry)
    if not pool:
        all_leads = [l for group in SAMPLE_LEADS.values() for l in group]
        pool = all_leads
    sample = pool[:min(req.count, len(pool))]
    added, dups = [], 0
    for ld in sample:
        if cu.leads_used >= cu.leads_limit: break
        fp = make_fingerprint(ld["name"],ld["company"],ld["email"],ld.get("whatsapp",""))
        if db.query(LeadDB).filter(LeadDB.fingerprint==fp,LeadDB.user_id==cu.id).first(): dups+=1; continue
        l = LeadDB(user_id=cu.id,fingerprint=fp,source="auto",**{k:v for k,v in ld.items()})
        db.add(l); cu.leads_used+=1; added.append(l.id)
    db.commit()
    return {"success":True,"added":len(added),"duplicates_skipped":dups,"available_industries":list(SAMPLE_LEADS.keys()),"leads":[_ld(db.query(LeadDB).get(i)) for i in added if db.query(LeadDB).get(i)]}

@app.get("/leads/industries")
def get_industries(): return {"industries":list(SAMPLE_LEADS.keys())}

OSM_TAG_MAP = {
    "fmcg":         [("shop","supermarket"),("shop","convenience"),("shop","wholesale"),("shop","grocery")],
    "manufacturing":[("industrial","factory"),("craft","manufacturer"),("office","manufacturer")],
    "retail":       [("shop","clothes"),("shop","electronics"),("shop","furniture"),("shop","hardware")],
    "logistics":    [("amenity","post_office"),("office","logistics"),("shop","courier")],
    "education":    [("amenity","school"),("amenity","college"),("amenity","university"),("amenity","training")],
    "construction": [("craft","construction"),("office","construction"),("craft","builder")],
    "healthcare":   [("amenity","hospital"),("amenity","clinic"),("amenity","pharmacy"),("healthcare","centre")],
    "finance":      [("amenity","bank"),("office","financial_services"),("office","accountant")],
    "saas":         [("office","it"),("office","software"),("office","technology")],
    "marketing":    [("office","advertising"),("office","marketing"),("office","media")],
    "real estate":  [("office","estate_agent"),("shop","real_estate_agent")],
    "e-commerce":   [("office","it"),("shop","online")],
}

def get_city_bbox(city:str):
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q":f"{city}, India","format":"json","limit":1},
                         headers={"User-Agent":"LeadGenAI/1.0"}, timeout=10)
        results = r.json()
        if not results: return None
        bb = results[0]["boundingbox"]  # [south, north, west, east]
        return bb[0], bb[1], bb[2], bb[3]
    except: return None

def search_osm_businesses(industry:str, city:str, count:int=5):
    bbox = get_city_bbox(city)
    if not bbox: return []
    south, north, west, east = bbox
    industry_key = industry.lower()
    tags = next((v for k,v in OSM_TAG_MAP.items() if k in industry_key), [("office","company")])
    tag_queries = "\n".join([f'  node["{k}"="{v}"]({south},{west},{north},{east});' for k,v in tags])
    query = f'[out:json][timeout:30];\n({tag_queries}\n);\nout body {count*5};'
    try:
        r = requests.post("https://overpass-api.de/api/interpreter", data={"data":query},
                          headers={"User-Agent":"LeadGenAI/1.0"}, timeout=30)
        elements = r.json().get("elements", [])
    except: return []
    leads = []
    for el in elements:
        t = el.get("tags", {})
        name = t.get("name","");
        if not name: continue
        phone = t.get("phone", t.get("contact:phone", t.get("contact:mobile","")))
        website = t.get("website", t.get("contact:website",""))
        email = t.get("email", t.get("contact:email",""))
        addr = " ".join(filter(None,[t.get("addr:housenumber",""),t.get("addr:street",""),t.get("addr:city",""),city]))
        if not website:
            slug = name.lower().replace(" ","").replace("&","and")
            website = f"https://www.{slug}.com"
        if not email:
            domain = website.replace("https://","").replace("http://","").split("/")[0].replace("www.","")
            email = f"info@{domain}"
        leads.append({"name":name,"company":name,"email":email,"whatsapp":phone,
                      "industry":industry,"role":"","website":website,"notes":addr or f"Found in {city} via OpenStreetMap"})
        if len(leads) >= count: break
    return leads

@app.post("/leads/search-places")
def search_places(req:PlacesSearchReq, db:Session=Depends(get_db), cu:UserDB=Depends(get_current_user)):
    from app.services.scraper_service import search_google_places
    query = f"{req.industry} companies in {req.city}"
    raw = search_google_places(query, client_id=cu.client_id)
    if not raw:
        raw = search_osm_businesses(req.industry, req.city, req.count)
    raw = raw[:req.count]
    added, dups = [], 0
    for ld in raw:
        if cu.leads_used >= cu.leads_limit: break
        fp = make_fingerprint(ld.get("name",""), ld.get("company",""), ld.get("email",""), ld.get("whatsapp",""))
        if db.query(LeadDB).filter(LeadDB.fingerprint==fp, LeadDB.user_id==cu.id).first(): dups+=1; continue
        l = LeadDB(user_id=cu.id, fingerprint=fp, source="google_places", industry=req.industry,
                   **{k:v for k,v in ld.items() if k in ["name","company","email","whatsapp","role","website","notes"]})
        db.add(l); cu.leads_used+=1; added.append(l.id)
    db.commit()
    return {"success":True,"found":len(raw),"added":len(added),"duplicates_skipped":dups,
            "leads":[_ld(db.query(LeadDB).get(i)) for i in added if db.query(LeadDB).get(i)]}

def search_apollo(industry:str, city:str, count:int=5):
    api_key = os.getenv("APOLLO_API_KEY","")
    if not api_key: return []
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    # Search accounts (companies) by location and industry
    payload = {"organization_locations":[f"{city}, India"], "q_keywords": industry,
               "page":1, "per_page":count}
    try:
        r = requests.post("https://api.apollo.io/api/v1/accounts/search", json=payload, headers=headers, timeout=15)
        accounts = r.json().get("accounts", [])
    except: accounts = []
    leads = []
    for acc in accounts:
        name = acc.get("name","")
        website = acc.get("website_url","") or acc.get("primary_domain","")
        phone = acc.get("phone","") or ""
        industry_val = acc.get("industry","") or industry
        domain = acc.get("primary_domain","")
        email = f"info@{domain}" if domain else ""
        if not name: continue
        leads.append({"name":name,"company":name,"email":email,"whatsapp":phone,
                      "industry":industry_val,"role":"","website":website,
                      "notes":f"{acc.get('city','')}, {acc.get('state','')}, {acc.get('country','')}".strip(", ")})
    # Also search contacts if accounts returned nothing
    if not leads:
        try:
            cp = {"contact_locations":[f"{city}, India"],"q_keywords":industry,"page":1,"per_page":count}
            r2 = requests.post("https://api.apollo.io/api/v1/contacts/search", json=cp, headers=headers, timeout=15)
            contacts = r2.json().get("contacts", [])
            for c in contacts:
                name = f"{c.get('first_name','')} {c.get('last_name','')}".strip()
                email = c.get("email","") or ""
                phone = c.get("phone_numbers",[{}])[0].get("raw_number","") if c.get("phone_numbers") else ""
                company = c.get("organization_name","")
                leads.append({"name":name,"company":company,"email":email,"whatsapp":phone,
                              "industry":industry,"role":c.get("title",""),"website":"","notes":f"Apollo contact - {city}"})
        except: pass
    return leads

@app.post("/leads/search-apollo")
def apollo_search(req:ApolloSearchReq, db:Session=Depends(get_db), cu:UserDB=Depends(get_current_user)):
    if not os.getenv("APOLLO_API_KEY",""): raise HTTPException(400,"Apollo API key not configured")
    raw = search_apollo(req.industry, req.city, req.count)
    added, dups = [], 0
    for ld in raw:
        if cu.leads_used >= cu.leads_limit: break
        fp = make_fingerprint(ld["name"], ld["company"], ld["email"], ld["whatsapp"])
        if db.query(LeadDB).filter(LeadDB.fingerprint==fp, LeadDB.user_id==cu.id).first(): dups+=1; continue
        l = LeadDB(user_id=cu.id, fingerprint=fp, source="apollo",
                   **{k:v for k,v in ld.items() if k in ["name","company","email","whatsapp","industry","role","website","notes"]})
        db.add(l); cu.leads_used+=1; added.append(l.id)
    db.commit()
    return {"success":True,"found":len(raw),"added":len(added),"duplicates_skipped":dups,
            "leads":[_ld(db.query(LeadDB).get(i)) for i in added]}

@app.post("/leads/{lead_id}/enrich")
def enrich(lead_id:str,db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    l = _gl(lead_id,cu.id,db)
    e = ai_enrich(l)
    l.enrichment_json=json.dumps(e); l.fit_score=e.get("fit_score",5)
    if l.fit_score < 5:
        l.status="skipped"; db.commit()
        return {"success":True,"enrichment":e,"auto_skipped":True,"message":f"Auto-skipped — score {l.fit_score}/10 below threshold"}
    l.status="enriched"; db.commit()
    return {"success":True,"enrichment":e,"auto_skipped":False}

@app.delete("/leads/{lead_id}")
def del_lead(lead_id:str,db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    l=_gl(lead_id,cu.id,db); db.delete(l); cu.leads_used=max(0,cu.leads_used-1); db.commit()
    return {"success":True}

@app.get("/leads/export/csv")
def export(db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    from fastapi.responses import StreamingResponse
    leads=db.query(LeadDB).filter(LeadDB.user_id==cu.id).all()
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["name","company","email","whatsapp","industry","role","website","status","fit_score","source","created_at"])
    for l in leads: w.writerow([l.name,l.company,l.email,l.whatsapp,l.industry,l.role,l.website,l.status,l.fit_score,l.source,l.created_at])
    out.seek(0)
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=leads.csv"})

@app.get("/leads/{lead_id}/memory")
def memory(lead_id:str,db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    l=_gl(lead_id,cu.id,db)
    convs=db.query(ConversationDB).filter(ConversationDB.lead_id==lead_id).order_by(ConversationDB.created_at).all()
    return {"lead":_ld(l),"conversation":[{"role":c.role,"content":c.content,"at":str(c.created_at)} for c in convs]}

@app.get("/campaigns")
def get_camps(db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    c=db.query(CampaignDB).filter(CampaignDB.user_id==cu.id).all()
    return {"campaigns":[_cd(x) for x in c],"total":len(c)}

@app.post("/campaigns")
def create_camp(camp:CampaignCreate,db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    c=CampaignDB(user_id=cu.id,**camp.dict()); db.add(c); db.commit(); db.refresh(c)
    return {"success":True,"campaign_id":c.id,"campaign":_cd(c)}

@app.post("/outreach/preview")
def preview(req:OutreachReq,db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    l=_gl(req.lead_id,cu.id,db); c=_gc(req.campaign_id,cu.id,db)
    return {"success":True,"message":ai_message(l,c,req.channel),"channel":req.channel}

@app.post("/outreach/send")
def send(req:OutreachReq,db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    l=_gl(req.lead_id,cu.id,db); c=_gc(req.campaign_id,cu.id,db)
    msg=ai_message(l,c,req.channel)
    db.add(MessageLogDB(user_id=cu.id,lead_id=l.id,campaign_id=c.id,channel=req.channel,message=msg))
    db.add(ConversationDB(lead_id=l.id,role="assistant",content=msg))
    l.status="contacted"; l.last_contacted=datetime.utcnow(); l.follow_up_day=0; c.sent_count+=1; db.commit()
    return {"success":True,"message":msg,"status":"simulated","note":"Follow-ups auto-scheduled at Day 3 & Day 7."}

@app.post("/outreach/bulk")
def bulk(campaign_id:str,channel:str="email",db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    c=_gc(campaign_id,cu.id,db)
    leads=db.query(LeadDB).filter(LeadDB.user_id==cu.id,LeadDB.status.in_(["new","enriched"])).all()
    results=[]
    for l in leads:
        if l.fit_score>0 and l.fit_score<5: continue
        msg=ai_message(l,c,channel)
        db.add(MessageLogDB(user_id=cu.id,lead_id=l.id,campaign_id=c.id,channel=channel,message=msg))
        db.add(ConversationDB(lead_id=l.id,role="assistant",content=msg))
        l.status="contacted"; l.last_contacted=datetime.utcnow(); l.follow_up_day=0
        results.append({"lead_id":l.id,"lead_name":l.name})
    c.sent_count+=len(results); db.commit()
    return {"success":True,"processed":len(results),"results":results}

@app.get("/outreach/log")
def log(db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    logs=db.query(MessageLogDB).filter(MessageLogDB.user_id==cu.id).order_by(MessageLogDB.sent_at.desc()).limit(100).all()
    result = []
    for l in logs:
        d = _ld2(l)
        lead = db.query(LeadDB).filter(LeadDB.id == l.lead_id).first()
        d["lead_name"] = lead.name if lead else l.lead_id
        d["lead_company"] = lead.company if lead else ""
        result.append(d)
    return {"log": result, "total": len(result)}

@app.get("/analytics")
def analytics(db:Session=Depends(get_db),cu:UserDB=Depends(get_current_user)):
    leads=db.query(LeadDB).filter(LeadDB.user_id==cu.id).all()
    scores=[l.fit_score for l in leads if l.fit_score>0]
    by_ind,by_src={},{}
    for l in leads:
        by_ind[l.industry or "Unknown"]=by_ind.get(l.industry or "Unknown",0)+1
        by_src[l.source or "manual"]=by_src.get(l.source or "manual",0)+1
    return {"total_leads":len(leads),
            "enriched":sum(1 for l in leads if l.status=="enriched"),
            "contacted":sum(1 for l in leads if l.status in ["contacted","sequence_complete"]),
            "skipped_low_fit":sum(1 for l in leads if l.status=="skipped"),
            "avg_fit_score":round(sum(scores)/len(scores),1) if scores else 0,
            "total_messages":db.query(MessageLogDB).filter(MessageLogDB.user_id==cu.id).count(),
            "follow_ups_sent":db.query(MessageLogDB).filter(MessageLogDB.user_id==cu.id,MessageLogDB.follow_up_number>0).count(),
            "leads_by_industry":by_ind,"leads_by_source":by_src,
            "plan":cu.plan,"leads_used":cu.leads_used,"leads_limit":cu.leads_limit}

@app.get("/analytics/client-detail")
def analytics_client_detail(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    leads = db.query(LeadDB).filter(LeadDB.user_id == cu.id).all()
    statuses = {l.status for l in leads}
    funnel = {
        "new":            sum(1 for l in leads if l.status == "new"),
        "enriched":       sum(1 for l in leads if l.status == "enriched"),
        "contacted":      sum(1 for l in leads if l.status in ["contacted", "sequence_complete"]),
        "replied":        0,
        "meeting_booked": 0,
        "closed":         0,
    }
    try:
        email_logs = db.query(MessageLogDB).filter(MessageLogDB.user_id == cu.id, MessageLogDB.channel == "email").all()
        wa_logs    = db.query(MessageLogDB).filter(MessageLogDB.user_id == cu.id, MessageLogDB.channel == "whatsapp").all()
    except Exception:
        email_logs, wa_logs = [], []
    email_metrics = {
        "sent":        len(email_logs),
        "open_rate":   "0%",
        "click_rate":  "0%",
        "bounce_rate": "0%",
    }
    wa_metrics = {
        "sent":          len(wa_logs),
        "delivered":     len(wa_logs),
        "read_rate":     "0%",
        "reply_rate":    "0%",
    }
    return {"funnel": funnel, "email_metrics": email_metrics, "wa_metrics": wa_metrics}

def _search_google_places_direct(industry: str, city: str, count: int = 5):
    try:
        query = f"{industry} companies in {city} India"
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {"query": query, "key": GOOGLE_PLACES_API_KEY, "type": "establishment"}
        r = requests.get(url, params=params, timeout=10)
        results = r.json().get("results", [])
        leads = []
        for place in results[:count]:
            name = place.get("name", "")
            address = place.get("formatted_address", "")
            website = ""
            email = ""
            # Try to get details for website
            place_id = place.get("place_id", "")
            if place_id:
                try:
                    det = requests.get(
                        "https://maps.googleapis.com/maps/api/place/details/json",
                        params={"place_id": place_id, "fields": "website,formatted_phone_number", "key": GOOGLE_PLACES_API_KEY},
                        timeout=8
                    ).json().get("result", {})
                    website = det.get("website", "")
                    phone = det.get("formatted_phone_number", "")
                except:
                    phone = ""
            else:
                phone = ""
            if website:
                domain = website.replace("https://","").replace("http://","").split("/")[0]
                email = f"info@{domain}"
            leads.append({
                "name": name, "company": name, "email": email,
                "whatsapp": phone, "industry": industry,
                "role": "", "website": website,
                "notes": address
            })
        return leads
    except Exception as e:
        print(f"GOOGLE PLACES ERROR: {e}")
        return []

def _send_email_direct(to_email: str, subject: str, body: str):
    api_key = os.getenv("SENDGRID_API_KEY", "")
    sender  = os.getenv("SENDER_EMAIL", "info@nsai.in")
    if not api_key:
        print(f"SIMULATED EMAIL to {to_email}: {subject}")
        return
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": sender, "name": "LeadGen AI"},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": body},
            {"type": "text/html",  "value": body.replace("\n", "<br>")}
        ]
    }
    r = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload, timeout=15
    )
    print(f"SENDGRID RESPONSE: {r.status_code} to {to_email}")

def run_agent_job(job_id:str, user_id:str, req:AgentRunReq):
    db = SessionLocal()
    try:
        job = db.query(AgentJobDB).filter(AgentJobDB.id==job_id).first()
        user = db.query(UserDB).filter(UserDB.id==user_id).first()
        camp = db.query(CampaignDB).filter(CampaignDB.id==req.campaign_id).first()
        if not camp: job.status="error"; db.commit(); return
        # ── Plan gate checks ──────────────────────────────────────────────────────
        _client_id = getattr(user, 'client_id', None) or user.id
        try:
            from app.services.plan_gate import check_leads_cap, get_allowed_sources, get_enrichment_depth
            allowed, reason = check_leads_cap(db, _client_id)
            if not allowed:
                job.status = "error"
                db.commit()
                return
            allowed_sources = get_allowed_sources(db, _client_id)
            enrichment_depth = get_enrichment_depth(db, _client_id)
        except Exception:
            allowed_sources = ["sample"]
            enrichment_depth = "basic"

        if req.source_url:
            # Only use sources allowed by plan
            if req.source_url and "google_places" in allowed_sources:
                raw_leads = scrape_url(req.source_url, req.industry)
            else:
                raw_leads = SAMPLE_LEADS.get(req.industry, [])
            raw_leads = raw_leads[:req.count] if raw_leads else []
        else:
            city = getattr(req, 'city', 'Mumbai') or 'Mumbai'
            print(f"DEBUG: Using OSM for {req.industry} in {city}")
            clean_city = city.split(",")[0].strip()
            raw_leads = search_osm_businesses(req.industry, clean_city, req.count)
            print(f"DEBUG: OSM returned {len(raw_leads)} leads")
            if not raw_leads:
                raw_leads = SAMPLE_LEADS.get(req.industry, [])
        raw_leads = raw_leads[:req.count]

        for ld in raw_leads:
            if user.leads_used >= user.leads_limit: break
            fp = make_fingerprint(ld.get("name",""), ld.get("company",""), ld.get("email",""), ld.get("whatsapp",""))
            existing = db.query(LeadDB).filter(LeadDB.fingerprint==fp, LeadDB.user_id==user_id).first()
            if existing:
                lead = existing
            else:
                lead = LeadDB(user_id=user_id, fingerprint=fp, source="agent",
                              **{k:v for k,v in ld.items() if k in ["name","company","email","whatsapp","industry","role","website","notes"]})
                db.add(lead); user.leads_used += 1; db.commit(); db.refresh(lead)

            if lead.website and not lead.email:
                hunter = enrich_with_hunter(lead.website)
                if hunter.get("email"):
                    lead.email = hunter["email"]
                    if not lead.name or lead.name == lead.company:
                        lead.name = hunter.get("name") or lead.name
                    if not lead.role:
                        lead.role = hunter.get("role", "")
                    db.commit()

            enrichment = ai_enrich(lead)
            lead.enrichment_json = json.dumps(enrichment)
            lead.fit_score = enrichment.get("fit_score", 5)
            if lead.fit_score < 5: lead.status = "skipped"; db.commit(); continue
            lead.status = "enriched"; db.commit()

            email_msg = ai_message(lead, camp, "email")
            user_name = user.name or "Sales Team"
            email_msg = email_msg.replace("[Your Name]", user_name).replace("[your name]", user_name)
            wa_msg = ai_message(lead, camp, "whatsapp")
            item = AgentJobItemDB(job_id=job_id, lead_id=lead.id, lead_name=lead.name,
                                  lead_company=lead.company, lead_email=lead.email,
                                  lead_whatsapp=lead.whatsapp, fit_score=lead.fit_score,
                                  email_message=email_msg, whatsapp_message=wa_msg)
            db.add(item); job.total_leads += 1; db.commit()

        job.status = "pending_approval"; db.commit()
    except Exception as e:
        print(f"AGENT JOB ERROR: {e}")
        try: job.status = "error"; db.commit()
        except: pass
    finally: db.close()

@app.post("/agent/run")
def agent_run(req:AgentRunReq, background_tasks:BackgroundTasks, db:Session=Depends(get_db), cu:UserDB=Depends(get_current_user)):
    job = AgentJobDB(user_id=cu.id, campaign_id=req.campaign_id, industry=req.industry, source_url=req.source_url or "")
    db.add(job); db.commit(); db.refresh(job)
    background_tasks.add_task(run_agent_job, job.id, cu.id, req)
    return {"success":True, "job_id":job.id, "message":"Agent is running. Poll /agent/jobs/{job_id} for status."}

@app.get("/agent/jobs")
def get_agent_jobs(db:Session=Depends(get_db), cu:UserDB=Depends(get_current_user)):
    jobs = db.query(AgentJobDB).filter(AgentJobDB.user_id==cu.id).order_by(AgentJobDB.created_at.desc()).all()
    return {"jobs":[{"id":j.id,"industry":j.industry,"status":j.status,"total_leads":j.total_leads,"created_at":str(j.created_at)} for j in jobs]}

@app.get("/agent/jobs/{job_id}")
def get_agent_job(job_id:str, db:Session=Depends(get_db), cu:UserDB=Depends(get_current_user)):
    job = db.query(AgentJobDB).filter(AgentJobDB.id==job_id, AgentJobDB.user_id==cu.id).first()
    if not job: raise HTTPException(404,"Job not found")
    items = db.query(AgentJobItemDB).filter(AgentJobItemDB.job_id==job_id).all()
    return {"job":{"id":job.id,"industry":job.industry,"status":job.status,"total_leads":job.total_leads,"created_at":str(job.created_at)},
            "items":[{"id":i.id,"lead_id":i.lead_id,"lead_name":i.lead_name,"lead_company":i.lead_company,
                      "lead_email":i.lead_email,"lead_whatsapp":i.lead_whatsapp,"fit_score":i.fit_score,
                      "email_message":i.email_message,"whatsapp_message":i.whatsapp_message,"status":i.status} for i in items]}

@app.post("/agent/jobs/{job_id}/approve")
def approve_agent_job(job_id:str, db:Session=Depends(get_db), cu:UserDB=Depends(get_current_user)):
    job = db.query(AgentJobDB).filter(AgentJobDB.id==job_id, AgentJobDB.user_id==cu.id).first()
    if not job: raise HTTPException(404,"Job not found")
    items = db.query(AgentJobItemDB).filter(AgentJobItemDB.job_id==job_id, AgentJobItemDB.status=="pending").all()
    camp = db.query(CampaignDB).filter(CampaignDB.id==job.campaign_id).first()
    for item in items:
        lead = db.query(LeadDB).filter(LeadDB.id==item.lead_id).first()
        if not lead: continue
        db.add(MessageLogDB(user_id=cu.id, lead_id=lead.id, campaign_id=job.campaign_id, channel="email", message=item.email_message, status="sent"))
        db.add(ConversationDB(lead_id=lead.id, role="assistant", content=item.email_message))
        lead.status = "contacted"; lead.last_contacted = datetime.utcnow(); lead.follow_up_day = 0
        item.status = "approved"
        if camp: camp.sent_count += 1
        # Actually send the email
        if lead.email and item.email_message:
            try:
                subject = "Following up"
                body = item.email_message
                if body.startswith("Subject:"):
                    lines = body.split("\n", 2)
                    subject = lines[0].replace("Subject:", "").strip()
                    body = lines[2].strip() if len(lines) > 2 else body
                _send_email_direct(
                    to_email=lead.email,
                    subject=subject,
                    body=body,
                )
                if lead.email and item.email_message:
                    try:
                        subject = "Following up"
                        body = item.email_message
                        if body.startswith("Subject:"):
                            lines = body.split("\n", 2)
                            subject = lines[0].replace("Subject:", "").strip()
                            body = lines[2].strip() if len(lines) > 2 else body
                        _send_email_direct(to_email=lead.email, subject=subject, body=body)
                        # Update the message log status to sent
                        log = db.query(MessageLogDB).filter(
                            MessageLogDB.lead_id == lead.id,
                            MessageLogDB.channel == "email"
                        ).order_by(MessageLogDB.sent_at.desc()).first()
                        if log:
                            log.status = "sent"
                        else:
                            # Log doesn't exist yet, will be created below with sent status
                            item.status = "approved"
                    except Exception as e:
                        print(f"EMAIL SEND ERROR: {e}")
            except Exception as e:
                print(f"EMAIL SEND ERROR: {e}")
    job.status = "approved"; db.commit()
    return {"success":True, "approved":len(items)}

@app.delete("/agent/jobs/{job_id}/items/{item_id}")
def reject_agent_item(job_id:str, item_id:str, db:Session=Depends(get_db), cu:UserDB=Depends(get_current_user)):
    item = db.query(AgentJobItemDB).filter(AgentJobItemDB.id==item_id, AgentJobItemDB.job_id==job_id).first()
    if not item: raise HTTPException(404,"Item not found")
    item.status = "rejected"; db.commit()
    return {"success":True}

@app.get("/status")
def root(): return {"status":"LeadGen AI Agent v2.0","features":["auth","sqlite","duplicate_detection","auto_follow_ups","scheduled_scraping","memory","csv_export","agent_mode"]}

@app.get("/test-osm")
def test_osm(industry:str="retail", city:str="Mumbai"):
    bbox = get_city_bbox(city)
    leads = search_osm_businesses(industry, city, 5)
    return {"bbox": bbox, "leads_found": len(leads), "leads": leads}

@app.get("/admin/overview")
def admin_overview(db: Session = Depends(get_db), cu: UserDB = Depends(get_admin_user)):
    total_users = db.query(UserDB).count()
    total_leads = db.query(LeadDB).count()
    total_messages = db.query(MessageLogDB).count()
    active_users = db.query(UserDB).filter(UserDB.is_active == True).count()
    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_leads": total_leads,
        "total_messages": total_messages,
    }

@app.get("/admin/users")
def admin_users(db: Session = Depends(get_db), cu: UserDB = Depends(get_admin_user)):
    users = db.query(UserDB).order_by(UserDB.created_at.desc()).all()
    result = []
    for u in users:
        lead_count = db.query(LeadDB).filter(LeadDB.user_id == u.id).count()
        msg_count = db.query(MessageLogDB).filter(MessageLogDB.user_id == u.id).count()
        result.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "plan": u.plan,
            "leads_used": u.leads_used,
            "leads_limit": u.leads_limit,
            "lead_count": lead_count,
            "msg_count": msg_count,
            "created_at": str(u.created_at),
            "is_active": u.is_active
        })
    return {"users": result, "total": len(result)}

@app.get("/admin/agent-activity")
def admin_agent_activity(db: Session = Depends(get_db), cu: UserDB = Depends(get_admin_user)):
    jobs = db.query(AgentJobDB).order_by(AgentJobDB.created_at.desc()).limit(50).all()
    result = []
    for j in jobs:
        user = db.query(UserDB).filter(UserDB.id == j.user_id).first()
        result.append({
            "id": j.id,
            "user_email": user.email if user else "unknown",
            "industry": j.industry,
            "status": j.status,
            "total_leads": j.total_leads,
            "created_at": str(j.created_at)
        })
    return {"jobs": result, "total": len(result)}

@app.get("/admin/system-health")
def admin_system_health(db: Session = Depends(get_db), cu: UserDB = Depends(get_admin_user)):
    checks = {}
    # OpenRouter
    checks["openrouter"] = "configured" if os.getenv("OPENROUTER_API_KEY") else "missing"
    # SendGrid
    checks["sendgrid"] = "configured" if os.getenv("SENDGRID_API_KEY") else "missing"
    # Hunter
    checks["hunter"] = "configured" if os.getenv("HUNTER_API_KEY") else "missing"
    # Google Places
    checks["google_places"] = "configured" if os.getenv("GOOGLE_PLACES_API_KEY") else "missing"
    # Apollo
    checks["apollo"] = "configured" if os.getenv("APOLLO_API_KEY") else "missing"
    # DB
    try:
        db.execute(__import__('sqlalchemy').text("SELECT 1"))
        checks["database"] = "healthy"
    except:
        checks["database"] = "error"
    return {"checks": checks}

@app.get("/test-hunter")
def test_hunter(domain: str = "stripe.com"):
    result = enrich_with_hunter(domain)
    return {"domain": domain, "result": result}

@app.get("/test-apollo")
def test_apollo(industry:str="retail", city:str="Mumbai"):
    api_key = os.getenv("APOLLO_API_KEY","")
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    # Test 1: with location
    p1 = {"organization_locations":[f"{city}, India"], "q_keywords": industry, "page":1, "per_page":5}
    r1 = requests.post("https://api.apollo.io/api/v1/accounts/search", json=p1, headers=headers, timeout=15)
    # Test 2: without location
    p2 = {"q_keywords": f"{industry} India", "page":1, "per_page":5}
    r2 = requests.post("https://api.apollo.io/api/v1/accounts/search", json=p2, headers=headers, timeout=15)
    # Test 3: contacts search
    p3 = {"q_keywords": f"{industry} {city} India", "page":1, "per_page":5}
    r3 = requests.post("https://api.apollo.io/api/v1/contacts/search", json=p3, headers=headers, timeout=15)
    return {
        "with_location": {"total": r1.json().get("pagination",{}).get("total_entries",0), "sample": [a.get("name") for a in r1.json().get("accounts",[])]},
        "without_location": {"total": r2.json().get("pagination",{}).get("total_entries",0), "sample": [a.get("name") for a in r2.json().get("accounts",[])]},
        "contacts": {"total": r3.json().get("pagination",{}).get("total_entries",0), "sample": [f"{c.get('first_name')} {c.get('last_name')} @ {c.get('organization_name')}" for c in r3.json().get("contacts",[])]}
    }

@app.get("/test-places")
def test_places(industry: str = "Real Estate", city: str = "Mumbai"):
    results = _search_google_places_direct(industry, city, 5)
    return {"api_key_set": bool(GOOGLE_PLACES_API_KEY), "results_count": len(results), "results": results}

@app.get("/test-gemini")
def test_gemini():
    try:
        result = gemini("Say hello in one sentence.")
        return {"success": True, "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _gl(lid,uid,db):
    l=db.query(LeadDB).filter(LeadDB.id==lid,LeadDB.user_id==uid).first()
    if not l: raise HTTPException(404,"Lead not found")
    return l
def _gc(cid,uid,db):
    c=db.query(CampaignDB).filter(CampaignDB.id==cid,CampaignDB.user_id==uid).first()
    if not c: raise HTTPException(404,"Campaign not found")
    return c
def _chk(u):
    if u.leads_used>=u.leads_limit: raise HTTPException(403,f"Lead limit reached ({u.leads_limit}). Upgrade plan.")
def _user_dict(u): return {"id":u.id,"name":u.name,"email":u.email,"plan":u.plan,"leads_used":u.leads_used,"leads_limit":u.leads_limit,"role":getattr(u,"role","client")}
def _ld(l): return {"id":l.id,"name":l.name,"company":l.company,"email":l.email,"whatsapp":l.whatsapp,"industry":l.industry,"role":l.role,"website":l.website,"notes":l.notes,"source":l.source,"status":l.status,"fit_score":l.fit_score,"enrichment":json.loads(l.enrichment_json or "{}"),"created_at":str(l.created_at),"last_contacted":str(l.last_contacted) if l.last_contacted else None,"follow_up_day":l.follow_up_day}
def _cd(c): return {"id":c.id,"name":c.name,"product_description":c.product_description,"target_industry":c.target_industry,"tone":c.tone,"channel":c.channel,"status":c.status,"sent_count":c.sent_count,"created_at":str(c.created_at)}
def _ld2(l): return {"id":l.id,"lead_id":l.lead_id,"campaign_id":l.campaign_id,"channel":l.channel,"message":l.message,"status":l.status,"follow_up_number":l.follow_up_number,"sent_at":str(l.sent_at)}