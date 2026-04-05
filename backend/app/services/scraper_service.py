import re
import os
import json
import logging
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

from ..config import APOLLO_API_KEY, GOOGLE_PLACES_API_KEY

logger = logging.getLogger("scraper_service")

# ── Simple file-based cache (7-day TTL) ───────────────────────────────────────
_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".places_cache.json")
_CACHE_TTL_DAYS = 7

def _load_cache() -> dict:
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_cache(cache: dict):
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        logger.warning({"event": "cache_save_error", "error": str(e)})

def _cache_key(query: str, location: str) -> str:
    return hashlib.md5(f"{query}|{location}".encode()).hexdigest()

def _cache_get(key: str) -> Optional[list]:
    cache = _load_cache()
    entry = cache.get(key)
    if not entry:
        return None
    cached_at = datetime.fromisoformat(entry["cached_at"])
    if datetime.utcnow() - cached_at > timedelta(days=_CACHE_TTL_DAYS):
        return None
    return entry["data"]

def _cache_set(key: str, data: list):
    cache = _load_cache()
    cache[key] = {"cached_at": datetime.utcnow().isoformat(), "data": data}
    _save_cache(cache)


# ── Google Places cost constants (USD per 1000 requests) ─────────────────────
_GP_COST_TEXT_SEARCH = 0.032   # $32/1000
_GP_COST_PLACE_DETAILS = 0.017  # $17/1000


def _log_places_cost(client_id: str, task_type: str, count: int, cost_usd: float):
    try:
        from ..database import SessionLocal
        from ..models import AIUsageDB
        db = SessionLocal()
        db.add(AIUsageDB(
            client_id=client_id,
            model_used="google_places",
            input_tokens=count,
            output_tokens=0,
            estimated_cost_usd=round(cost_usd, 6),
            task_type=task_type
        ))
        db.commit()
        db.close()
    except Exception as e:
        logger.warning({"event": "places_cost_log_error", "error": str(e)})


def _check_budget(client_id: str, needed_usd: float) -> bool:
    """Returns True if client has enough remaining monthly Places budget."""
    try:
        from ..database import SessionLocal
        from ..models import AIUsageDB, ClientDB
        db = SessionLocal()
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spent = db.query(AIUsageDB).filter(
            AIUsageDB.client_id == client_id,
            AIUsageDB.model_used == "google_places",
            AIUsageDB.created_at >= month_start
        ).all()
        total_spent = sum(s.estimated_cost_usd or 0 for s in spent)
        db.close()
        # Google gives $200/month free credit — use 80% as safety limit
        return (total_spent + needed_usd) < 160.0
    except Exception:
        return True


# ── Industry-specific search queries ─────────────────────────────────────────
INDUSTRY_SEARCH_QUERIES = {
    "real_estate": [
        "real estate agents in {city}",
        "property dealers in {city}",
        "builders and developers in {city}",
        "property brokers {city}",
        "real estate consultants {city}",
    ],
    "it_staffing": [
        "IT companies in {city}",
        "software companies in {city}",
        "staffing agencies in {city}",
        "IT recruitment firms {city}",
        "technology companies {city}",
    ],
    "edtech": [
        "coaching institutes in {city}",
        "tuition classes in {city}",
        "JEE NEET coaching {city}",
        "test preparation center {city}",
        "educational institute {city}",
    ],
    "fmcg": [
        "FMCG distributors in {city}",
        "wholesale grocery {city}",
        "consumer goods company {city}",
    ],
    "manufacturing": [
        "manufacturing companies in {city}",
        "industrial companies {city}",
        "factory {city}",
    ],
    "retail": [
        "retail stores in {city}",
        "supermarket {city}",
        "shopping centre {city}",
    ],
    "logistics": [
        "logistics companies in {city}",
        "freight forwarding {city}",
        "courier service {city}",
    ],
    "healthcare": [
        "hospitals in {city}",
        "clinics in {city}",
        "medical centre {city}",
    ],
    "finance": [
        "financial services {city}",
        "accounting firms {city}",
        "CA firms {city}",
    ],
    "construction": [
        "construction companies in {city}",
        "builders {city}",
        "civil contractors {city}",
    ],
}

def _get_queries_for_industry(industry: str, city: str) -> list:
    key = industry.lower().replace(" ", "_").replace("-", "_")
    queries = INDUSTRY_SEARCH_QUERIES.get(key, [f"{industry} companies in {city}"])
    return [q.format(city=city) for q in queries]


# ── Email scraper (from website homepage) ────────────────────────────────────
def _scrape_email_from_website(url: str) -> str:
    if not url or not url.startswith("http"):
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ")
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', text)
        emails = [e for e in emails if not any(e.endswith(x) for x in ['.png', '.jpg', '.gif', '.svg', '.css'])]
        return emails[0] if emails else ""
    except Exception:
        return ""


# ── Google Places Text Search ─────────────────────────────────────────────────
def search_google_places(query: str, location: str = "", radius_km: int = 20,
                          client_id: str = None) -> list:
    """
    Search Google Places Text Search API.
    location: 'lat,lng' string or city name (resolved via geocode).
    Returns list of business dicts.
    """
    if not GOOGLE_PLACES_API_KEY:
        logger.info({"event": "google_places_skipped", "reason": "no API key"})
        return []

    cache_key = _cache_key(query, location)
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info({"event": "google_places_cache_hit", "query": query})
        return cached

    if not _check_budget(client_id, _GP_COST_TEXT_SEARCH * 3):
        logger.warning({"event": "google_places_budget_exceeded", "client_id": client_id})
        return []

    base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": query,
        "key": GOOGLE_PLACES_API_KEY,
        "region": "in",
        "language": "en",
    }
    if radius_km and location:
        params["radius"] = radius_km * 1000
        params["location"] = location

    all_results = []
    page = 0
    next_page_token = None
    request_count = 0

    try:
        while page < 3:  # max 3 pages = 60 results
            if next_page_token:
                time.sleep(2)  # Google requires delay before using next_page_token
                params = {"pagetoken": next_page_token, "key": GOOGLE_PLACES_API_KEY}

            resp = requests.get(base_url, params=params, timeout=15)
            request_count += 1
            data = resp.json()

            status = data.get("status", "")
            if status not in ("OK", "ZERO_RESULTS"):
                logger.warning({"event": "places_api_error", "status": status, "query": query, "ts": datetime.utcnow().isoformat()})
                break

            for place in data.get("results", []):
                if place.get("business_status") == "PERMANENTLY_CLOSED":
                    continue

                name = place.get("name", "")
                address = place.get("formatted_address", "")
                rating = place.get("rating", 0)
                review_count = place.get("user_ratings_total", 0)
                place_id = place.get("place_id", "")
                types = place.get("types", [])

                # Build lead score hint from rating/reviews
                score_hint = ""
                if rating >= 4.0 and review_count >= 50:
                    score_hint = "high_rating_active"
                elif review_count == 0:
                    score_hint = "no_reviews"

                all_results.append({
                    "name": name,
                    "company": name,
                    "address": address,
                    "rating": rating,
                    "review_count": review_count,
                    "place_id": place_id,
                    "types": types,
                    "score_hint": score_hint,
                    "source": "google_places",
                })

            next_page_token = data.get("next_page_token")
            if not next_page_token:
                break
            page += 1

    except Exception as e:
        logger.error({"event": "google_places_request_error", "query": query, "error": str(e), "ts": datetime.utcnow().isoformat()})

    if request_count > 0:
        cost = request_count * _GP_COST_TEXT_SEARCH
        _log_places_cost(client_id, "google_places_text_search", request_count, cost)

    _cache_set(cache_key, all_results)
    logger.info({"event": "google_places_results", "query": query, "count": len(all_results)})
    return all_results


# ── Google Place Details ───────────────────────────────────────────────────────
def get_place_details(place_id: str, client_id: str = None) -> dict:
    """
    Fetch rich details for a place. Only call for leads that pass initial scoring.
    """
    if not GOOGLE_PLACES_API_KEY or not place_id:
        return {}

    if not _check_budget(client_id, _GP_COST_PLACE_DETAILS):
        logger.warning({"event": "places_details_budget_exceeded", "client_id": client_id})
        return {}

    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields": "formatted_phone_number,international_phone_number,website,opening_hours,reviews,price_level",
                "key": GOOGLE_PLACES_API_KEY,
                "language": "en",
            },
            timeout=15
        )
        _log_places_cost(client_id, "google_places_details", 1, _GP_COST_PLACE_DETAILS)

        result = resp.json().get("result", {})
        reviews = result.get("reviews", [])[:5]

        return {
            "phone": result.get("international_phone_number") or result.get("formatted_phone_number", ""),
            "website": result.get("website", ""),
            "price_level": result.get("price_level"),
            "opening_hours": result.get("opening_hours", {}).get("weekday_text", []),
            "recent_reviews": [
                {"text": r.get("text", ""), "rating": r.get("rating"), "time": r.get("relative_time_description")}
                for r in reviews
            ],
        }
    except Exception as e:
        logger.error({"event": "place_details_error", "place_id": place_id, "error": str(e), "ts": datetime.utcnow().isoformat()})
        return {}


# ── Deduplication ─────────────────────────────────────────────────────────────
def _dedup_leads(leads: list) -> list:
    seen_phones = set()
    seen_names = set()
    result = []
    for lead in leads:
        phone = (lead.get("whatsapp") or "").replace(" ", "").replace("-", "")
        name_key = f"{(lead.get('name') or '').lower().strip()}|{(lead.get('address') or lead.get('notes') or '')[:30].lower()}"
        if phone and phone in seen_phones:
            continue
        if name_key in seen_names:
            continue
        if phone:
            seen_phones.add(phone)
        seen_names.add(name_key)
        result.append(lead)
    return result


def _dedup_against_db(leads: list, client_id: str) -> list:
    """Remove leads already in the database for this client."""
    try:
        from ..database import SessionLocal
        from ..models import LeadDB
        db = SessionLocal()
        existing_emails = set(
            r[0] for r in db.query(LeadDB.email).filter(
                LeadDB.client_id == client_id, LeadDB.email != None
            ).all()
        )
        existing_phones = set(
            r[0] for r in db.query(LeadDB.whatsapp).filter(
                LeadDB.client_id == client_id, LeadDB.whatsapp != None
            ).all()
        )
        db.close()
        filtered = []
        for lead in leads:
            if lead.get("email") and lead["email"] in existing_emails:
                continue
            if lead.get("whatsapp") and lead["whatsapp"] in existing_phones:
                continue
            filtered.append(lead)
        return filtered
    except Exception as e:
        logger.warning({"event": "db_dedup_error", "error": str(e)})
        return leads


# ── Unified search ────────────────────────────────────────────────────────────
def search_leads(client_id: str, industry: str = "", city: str = "Mumbai",
                  count: int = 20) -> list:
    """
    Primary: Google Places → enrich with Place Details → scrape email
    Fallback: OSM if Google returns <10 results
    """
    all_leads = []

    # Step 1: Google Places
    queries = _get_queries_for_industry(industry, city)
    for query in queries[:2]:   # max 2 queries per search to control cost
        gp_results = search_google_places(query, location="", client_id=client_id)
        all_leads.extend(gp_results)
        if len(all_leads) >= count:
            break

    # Enrich top results with Place Details + email scrape
    enriched = []
    for place in all_leads[:count]:
        lead = dict(place)
        place_id = lead.pop("place_id", "")
        lead.pop("types", None)
        lead.pop("score_hint", None)
        lead.pop("address", None)

        # Get phone + website from Place Details (only for promising leads)
        if place_id and (lead.get("rating", 0) >= 3.5 or place.get("score_hint") == "high_rating_active"):
            details = get_place_details(place_id, client_id=client_id)
            lead["whatsapp"] = details.get("phone", "")
            lead["website"] = details.get("website", "")
            lead["notes"] = f"Rating: {place.get('rating', 'N/A')}, Reviews: {place.get('review_count', 0)}, Source: Google Places"

            # Scrape email from website
            if lead.get("website"):
                lead["email"] = _scrape_email_from_website(lead["website"])
            if not lead.get("email") and lead.get("website"):
                domain = lead["website"].replace("https://", "").replace("http://", "").split("/")[0]
                lead["email"] = f"info@{domain}"
        else:
            lead["whatsapp"] = ""
            lead["website"] = ""
            if place_id:
                slug = (lead.get("company") or "").lower().replace(" ", "").replace("&", "and")[:20]
                lead["email"] = f"info@{slug}.com" if slug else ""
            lead["notes"] = f"Rating: {place.get('rating', 'N/A')}, Reviews: {place.get('review_count', 0)}, Source: Google Places"

        lead["industry"] = industry
        lead["role"] = ""
        lead["source"] = "google_places"
        enriched.append(lead)

    # Step 2: OSM fallback if Google returned < 10 results
    if len(enriched) < 10:
        logger.info({"event": "osm_fallback", "google_results": len(enriched), "industry": industry, "city": city})
        osm_leads = search_osm_businesses(industry, city, count=count - len(enriched))
        for lead in osm_leads:
            lead["source"] = "osm"
        enriched.extend(osm_leads)

    # Dedup within results and against DB
    enriched = _dedup_leads(enriched)
    if client_id:
        enriched = _dedup_against_db(enriched, client_id)

    logger.info({"event": "search_leads_complete", "industry": industry, "city": city, "total": len(enriched)})
    return enriched[:count]


# ── Existing OSM functions (unchanged, kept as fallback) ──────────────────────
OSM_TAG_MAP = {
    "fmcg":         [("shop", "supermarket"), ("shop", "convenience"), ("shop", "wholesale"), ("shop", "grocery")],
    "manufacturing": [("industrial", "factory"), ("craft", "manufacturer"), ("office", "manufacturer")],
    "retail":       [("shop", "clothes"), ("shop", "electronics"), ("shop", "furniture"), ("shop", "hardware")],
    "logistics":    [("amenity", "post_office"), ("office", "logistics"), ("shop", "courier")],
    "education":    [("amenity", "school"), ("amenity", "college"), ("amenity", "university"), ("amenity", "training")],
    "construction": [("craft", "construction"), ("office", "construction"), ("craft", "builder")],
    "healthcare":   [("amenity", "hospital"), ("amenity", "clinic"), ("amenity", "pharmacy"), ("healthcare", "centre")],
    "finance":      [("amenity", "bank"), ("office", "financial_services"), ("office", "accountant")],
    "saas":         [("office", "it"), ("office", "software"), ("office", "technology")],
    "marketing":    [("office", "advertising"), ("office", "marketing"), ("office", "media")],
    "real estate":  [("office", "estate_agent"), ("shop", "real_estate_agent")],
    "e-commerce":   [("office", "it"), ("shop", "online")],
    "real_estate":  [("office", "estate_agent"), ("shop", "real_estate_agent")],
    "it_staffing":  [("office", "it"), ("office", "software")],
    "edtech":       [("amenity", "school"), ("amenity", "college"), ("amenity", "training")],
}

SAMPLE_LEADS = {
    "SaaS": [
        {"name": "Alex Johnson", "company": "CloudFlow Inc", "email": "alex@cloudflow.io", "whatsapp": "", "industry": "SaaS", "role": "CTO", "website": "cloudflow.io", "notes": "Series A startup, 50 employees"},
        {"name": "Sara Kim", "company": "DataPulse", "email": "sara.kim@datapulse.com", "whatsapp": "", "industry": "SaaS", "role": "Head of Engineering", "website": "datapulse.com", "notes": "B2B analytics platform"},
        {"name": "Raj Patel", "company": "Nexus Labs", "email": "raj@nexuslabs.io", "whatsapp": "", "industry": "SaaS", "role": "Founder", "website": "nexuslabs.io", "notes": "Developer tools startup"},
    ],
    "Real Estate": [
        {"name": "John Smith", "company": "PropTech Solutions", "email": "john@proptech.io", "whatsapp": "", "industry": "Real Estate", "role": "CEO", "website": "proptech.io", "notes": "Real estate tech startup"},
        {"name": "Maria Garcia", "company": "HomeFind", "email": "maria@homefind.com", "whatsapp": "", "industry": "Real Estate", "role": "Head of Sales", "website": "homefind.com", "notes": "Property listing platform"},
    ],
    "FMCG": [
        {"name": "Amit Sharma", "company": "NatureFresh Foods", "email": "amit@naturefresh.in", "whatsapp": "+919876543210", "industry": "FMCG", "role": "National Sales Head", "website": "naturefresh.in", "notes": "Packaged foods brand"},
        {"name": "Pooja Mehta", "company": "PureLife Consumer", "email": "pooja@purelife.co.in", "whatsapp": "+919765432109", "industry": "FMCG", "role": "VP Marketing", "website": "purelife.co.in", "notes": "FMCG distributor"},
    ],
    "Education": [
        {"name": "Dr. Pradeep Sharma", "company": "BrightFuture Academy", "email": "pradeep@brightfuture.in", "whatsapp": "+917776543210", "industry": "Education", "role": "Director", "website": "brightfuture.in", "notes": "Coaching institute, 2000 students"},
        {"name": "Anjali Gupta", "company": "LearnSmart EdTech", "email": "anjali@learnsmart.co.in", "whatsapp": "+917665432109", "industry": "Education", "role": "CEO", "website": "learnsmart.co.in", "notes": "Online learning platform"},
    ],
    "Manufacturing": [
        {"name": "Suresh Patel", "company": "Patel Engineering Works", "email": "suresh@pateleng.com", "whatsapp": "+919321098765", "industry": "Manufacturing", "role": "Managing Director", "website": "pateleng.com", "notes": "Auto parts manufacturer"},
        {"name": "Ramesh Verma", "company": "Verma Steel Industries", "email": "ramesh@vermasteel.in", "whatsapp": "+919210987654", "industry": "Manufacturing", "role": "CEO", "website": "vermasteel.in", "notes": "Steel fabrication"},
    ],
}

MESSAGE_TEMPLATES = {
    "email": "Subject: Quick question for {company}\n\nHi {name},\n\nI came across {company} and was impressed by your work in the {industry} space.\n\nWe help {industry} companies streamline their outreach and grow faster. I'd love to share how we could help {company} as well.\n\nWould you be open to a quick 15-minute call this week?\n\nBest regards",
    "whatsapp": "Hi {name}! I noticed {company} is doing great work in {industry}. We help similar companies grow faster. Would love to connect — open to a quick chat this week?",
}


def message_template(lead, camp, channel: str) -> str:
    t = MESSAGE_TEMPLATES.get(channel, MESSAGE_TEMPLATES["email"])
    return t.format(
        name=lead.name.split()[0] if lead.name else "there",
        company=lead.company or "your company",
        industry=lead.industry or camp.target_industry or "your industry",
    )


def scrape_url_no_ai(url: str, industry: str = "") -> list:
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        emails = list(set(re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', text)))
        emails = [e for e in emails if not any(e.endswith(x) for x in ['.png', '.jpg', '.gif', '.svg'])][:5]
        phones = re.findall(r'\+?[\d\s\-\(\)]{10,15}', text)
        og_site = soup.find('meta', property='og:site_name')
        title = soup.find('title')
        company = (og_site.get('content', '') if og_site
                   else (title.text.split('|')[0].split('-')[0].strip() if title
                         else url.split('/')[2].replace('www.', '').split('.')[0].title()))
        leads = []
        for email in emails:
            name = email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
            leads.append({
                "name": name, "company": company, "email": email,
                "whatsapp": phones[0].strip() if phones else "",
                "industry": industry, "role": "", "website": url,
                "notes": f"Scraped from {url}"
            })
        return leads
    except Exception:
        return []


def scrape_url(url: str, industry: str = "") -> list:
    from .groq_service import gemini
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ", strip=True)[:3000]
        prompt = f"""Extract leads from webpage. URL:{url} Industry:{industry}
Content:{text}
Return ONLY JSON array: [{{"name":"","company":"","email":"","whatsapp":"","industry":"{industry}","role":"","website":"{url}","notes":""}}]
Return [] if none found."""
        t = gemini(prompt)
        if "```" in t:
            t = t.split("```")[1]
            t = t[4:] if t.startswith("json") else t
        return json.loads(t.strip())
    except Exception:
        return scrape_url_no_ai(url, industry)


def get_city_bbox(city: str):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{city}, India", "format": "json", "limit": 1},
            headers={"User-Agent": "LeadGenAI/1.0"},
            timeout=10
        )
        results = r.json()
        if not results:
            return None
        bb = results[0]["boundingbox"]
        return bb[0], bb[1], bb[2], bb[3]
    except Exception:
        return None


def search_osm_businesses(industry: str, city: str, count: int = 5) -> list:
    bbox = get_city_bbox(city)
    if not bbox:
        return []
    south, north, west, east = bbox
    industry_key = industry.lower()
    tags = next((v for k, v in OSM_TAG_MAP.items() if k in industry_key), [("office", "company")])
    tag_queries = "\n".join([f'  node["{k}"="{v}"]({south},{west},{north},{east});' for k, v in tags])
    query = f'[out:json][timeout:30];\n({tag_queries}\n);\nout body {count * 5};'
    try:
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            headers={"User-Agent": "LeadGenAI/1.0"},
            timeout=30
        )
        elements = r.json().get("elements", [])
    except Exception:
        return []
    leads = []
    for el in elements:
        t = el.get("tags", {})
        name = t.get("name", "")
        if not name:
            continue
        phone = t.get("phone", t.get("contact:phone", t.get("contact:mobile", "")))
        website = t.get("website", t.get("contact:website", ""))
        email = t.get("email", t.get("contact:email", ""))
        addr = " ".join(filter(None, [t.get("addr:housenumber", ""), t.get("addr:street", ""), t.get("addr:city", ""), city]))
        if not website:
            slug = name.lower().replace(" ", "").replace("&", "and")
            website = f"https://www.{slug}.com"
        if not email:
            domain = website.replace("https://", "").replace("http://", "").split("/")[0]
            email = f"info@{domain}"
        leads.append({
            "name": name, "company": name, "email": email, "whatsapp": phone,
            "industry": industry, "role": "", "website": website,
            "notes": addr or f"Found in {city} via OpenStreetMap"
        })
        if len(leads) >= count:
            break
    return leads


def search_apollo(industry: str, city: str, count: int = 5) -> list:
    api_key = APOLLO_API_KEY
    if not api_key:
        return []
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    payload = {
        "organization_locations": [f"{city}, India"],
        "q_keywords": industry,
        "page": 1,
        "per_page": count
    }
    try:
        r = requests.post("https://api.apollo.io/api/v1/accounts/search", json=payload, headers=headers, timeout=15)
        accounts = r.json().get("accounts", [])
    except Exception:
        accounts = []
    leads = []
    for acc in accounts:
        name = acc.get("name", "")
        website = acc.get("website_url", "") or acc.get("primary_domain", "")
        phone = acc.get("phone", "") or ""
        industry_val = acc.get("industry", "") or industry
        domain = acc.get("primary_domain", "")
        email = f"info@{domain}" if domain else ""
        if not name:
            continue
        leads.append({
            "name": name, "company": name, "email": email, "whatsapp": phone,
            "industry": industry_val, "role": "", "website": website,
            "notes": f"{acc.get('city', '')}, {acc.get('state', '')}, {acc.get('country', '')}".strip(", ")
        })
    if not leads:
        try:
            cp = {"contact_locations": [f"{city}, India"], "q_keywords": industry, "page": 1, "per_page": count}
            r2 = requests.post("https://api.apollo.io/api/v1/contacts/search", json=cp, headers=headers, timeout=15)
            contacts = r2.json().get("contacts", [])
            for c in contacts:
                name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
                email = c.get("email", "") or ""
                phone = c.get("phone_numbers", [{}])[0].get("raw_number", "") if c.get("phone_numbers") else ""
                company = c.get("organization_name", "")
                leads.append({
                    "name": name, "company": company, "email": email, "whatsapp": phone,
                    "industry": industry, "role": c.get("title", ""), "website": "",
                    "notes": f"Apollo contact - {city}"
                })
        except Exception:
            pass
    return leads
