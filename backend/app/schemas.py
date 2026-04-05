from pydantic import BaseModel
from typing import Optional


class UserCreate(BaseModel):
    email: str
    name: str
    password: str


class LeadCreate(BaseModel):
    name: str
    company: str
    email: Optional[str] = ""
    whatsapp: Optional[str] = ""
    industry: Optional[str] = ""
    role: Optional[str] = ""
    website: Optional[str] = ""
    notes: Optional[str] = ""


class CampaignCreate(BaseModel):
    name: str
    product_description: str
    target_industry: str
    tone: str = "professional"
    channel: str = "both"


class OutreachReq(BaseModel):
    lead_id: str
    campaign_id: str
    channel: str = "email"


class ScrapeReq(BaseModel):
    url: str
    industry: Optional[str] = ""
    schedule: Optional[str] = "none"


class AutoGenReq(BaseModel):
    industry: str
    count: Optional[int] = 5


class AgentRunReq(BaseModel):
    campaign_id: str
    industry: str
    source_url: Optional[str] = ""
    count: Optional[int] = 5


class PlacesSearchReq(BaseModel):
    industry: str
    city: str
    count: Optional[int] = 5


class ApolloSearchReq(BaseModel):
    industry: str
    city: str
    count: Optional[int] = 5
