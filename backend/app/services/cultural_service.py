import json
import logging
import os
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger("cultural_service")

_CALENDAR_PATH = os.path.join(os.path.dirname(__file__), "festival_calendar.json")

# ── Regional tone config ───────────────────────────────────────────────────────
REGIONAL_TONE = {
    "north_india": {
        "language": "hinglish",
        "formality": "casual",
        "notes": "Use 'ji' suffix. Hinglish natural. Warm and friendly.",
        "greeting": "Namaste",
        "avoid": ["Dear Sir/Madam", "To Whom It May Concern"],
    },
    "south_india": {
        "language": "en",
        "formality": "formal",
        "notes": "Professional English preferred. Avoid Hindi. Use formal salutations.",
        "greeting": "Dear",
        "avoid": ["yaar", "bhai", "ji suffix"],
    },
    "west_india": {
        "language": "en",
        "formality": "professional",
        "notes": "Business-focused. Gujarati greetings acceptable. Straight to the point.",
        "greeting": "Hello",
        "avoid": ["overly casual language"],
    },
    "east_india": {
        "language": "en",
        "formality": "formal",
        "notes": "Formal English. Reference local Bengal/Odisha/NE context where relevant.",
        "greeting": "Dear",
        "avoid": ["Hindi terms", "casual tone"],
    },
    "pan_india": {
        "language": "en",
        "formality": "professional",
        "notes": "Safe professional English with light Hinglish acceptable.",
        "greeting": "Hi",
        "avoid": ["strong regional references"],
    },
}

# ── Festive greeting templates ────────────────────────────────────────────────
FESTIVE_GREETINGS = {
    "Diwali": {
        "en": [
            "Wishing you and your team a very Happy Diwali! May this festival of lights bring prosperity and joy to {company}. 🪔",
            "Happy Diwali from all of us at {sender_company}! Wishing {company} a bright and prosperous year ahead.",
            "This Diwali, we're grateful for the connection with {company}. Wishing you joy, success, and all the best for the year ahead. Happy Diwali! 🪔✨",
            "Warm Diwali wishes to you and the entire team at {company}. May the new year bring new opportunities and growth!",
            "Happy Diwali! Wishing {name} and the {company} team a festive and joyful celebration. 🎆",
        ],
        "hi": [
            "Aapko aur {company} ki poori team ko Diwali ki hardik shubhkamnayein! 🪔 Yeh tyohar aapke liye khushiyon aur safalta lekar aaye.",
            "Happy Diwali {name} ji! {company} ke liye bahut saari roshan aur khushiyan laaye yeh diya ka tyohar. 🪔✨",
            "Diwali mubarak ho {name} ji! {sender_company} ki taraf se aapko aur aapki family ko bahut saari shubhkamnayein.",
            "Yeh Diwali {company} ke liye special ho — naye avsar, nai safaltaayein. Diwali ki hardik badhaai! 🎆",
            "Happy Diwali! {name} ji, aapka aur {company} ka yeh saal bahut accha jaaye — {sender_company} ki taraf se dher saari shubhkamnayein.",
        ]
    },
    "Holi": {
        "en": [
            "Happy Holi from {sender_company}! Wishing {company} a colourful and joyful celebration. 🎨",
            "Colours, sweets, and good vibes — Happy Holi to you and the team at {company}! 🌈",
            "Wishing {name} and everyone at {company} a very Happy Holi! May this festival bring new energy and fresh beginnings.",
            "Happy Holi! May the colours of this festival bring joy and positivity to {company}. 🎨✨",
            "From {sender_company} to {company} — wishing you a safe and colourful Holi celebration!",
        ],
        "hi": [
            "Holi ki bahut bahut badhaai {name} ji! {company} ki poori team ko rang birangi shubhkamnayein. 🎨",
            "Happy Holi! {sender_company} ki taraf se {company} ke liye rang, khushi aur meethaai ki shubhkamnayein. 🌈",
            "Yeh Holi {company} ke liye bahut khushi lekar aaye — {name} ji, Holi mubarak ho! 🎨✨",
            "Rang de Basanti! {name} ji, Holi ki hardik shubhkamnayein — naya rang, naya josh. 🌈",
            "Holi mubarak {name} ji! {sender_company} ki taraf se aapko aur {company} ko yeh rangon ka tyohar mubarak ho.",
        ]
    },
    "Eid": {
        "en": [
            "Eid Mubarak to you and your family! Wishing peace, joy, and blessings for {company}. 🌙⭐",
            "Eid Mubarak from {sender_company}! May this Eid bring happiness and prosperity to {name} and the team at {company}.",
            "Wishing you a blessed Eid! May the spirit of togetherness and gratitude fill your celebrations. 🌙",
            "Eid Mubarak {name}! {sender_company} wishes you and {company} a joyful and blessed celebration.",
            "Happy Eid! Wishing peace, happiness, and success to {company} this festive season. 🌙✨",
        ],
        "hi": [
            "Eid Mubarak {name} ji! {sender_company} ki taraf se aapko aur {company} ko eid ki bahut saari badhaai. 🌙⭐",
            "Eid Mubarak! Is tyohar ki khushi {company} ke liye bahut saari barkat aur khushiyan laaye. 🌙",
            "Eid ki hardik shubhkamnayein {name} ji — {sender_company} ki taraf se aapki poori team ko Eid Mubarak!",
        ]
    },
    "Christmas": {
        "en": [
            "Wishing you a Merry Christmas and a Happy New Year! May the holiday season bring joy to {company}. 🎄",
            "Season's greetings from {sender_company}! Wishing {name} and the {company} team a wonderful Christmas. 🎄✨",
            "Merry Christmas! May the festive season bring warmth, joy, and well-deserved rest for {company}.",
            "Happy Christmas from {sender_company}! Wishing you a peaceful and joyful celebration with your loved ones.",
            "Wishing {company} a Merry Christmas and an amazing 2027 ahead! 🎄🎆",
        ],
        "hi": [
            "Merry Christmas {name} ji! {company} ki poori team ko Christmas ki hardik shubhkamnayein. 🎄✨",
            "Happy Christmas! {sender_company} ki taraf se {name} ji aur {company} ko festive season ki badhaai. 🎄",
        ]
    },
    "New Year": {
        "en": [
            "Happy New Year from {sender_company}! Wishing {company} an incredible 2027 — full of growth and success. 🎆",
            "Here's to a great new year! {sender_company} wishes {name} and the {company} team all the best for 2027. 🎉",
            "Happy New Year! May 2027 bring new opportunities and growth for {company}. 🎆✨",
            "Wishing you a wonderful year ahead! Happy New Year from {sender_company} to {company}. 🥂",
            "New year, new goals! Wishing {name} and {company} a successful and fulfilling 2027. 🎆",
        ],
        "hi": [
            "Naye saal ki hardik shubhkamnayein {name} ji! 2027 {company} ke liye bahut accha saal ho. 🎆",
            "Happy New Year! {sender_company} ki taraf se {company} ko naye saal ki bahut saari badhaai aur shubhkamnayein. 🎉✨",
        ]
    }
}


# ── Calendar loader ───────────────────────────────────────────────────────────
def _load_calendar() -> dict:
    try:
        with open(_CALENDAR_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error({"event": "calendar_load_error", "error": str(e)})
        return {}


# ── Main blackout check ───────────────────────────────────────────────────────
def is_blackout_date(check_date: date = None, client_id: str = None) -> dict:
    """
    Returns {is_blackout: bool, festival_name: str, type: str}
    type: 'full_blackout' | 'soft_blackout' | None
    """
    if check_date is None:
        check_date = date.today()

    date_str = check_date.isoformat()
    year_str = str(check_date.year)

    calendar = _load_calendar()
    year_data = calendar.get(year_str, {})

    # Check global festival calendar
    for festival, info in year_data.items():
        if date_str in info.get("dates", []):
            result = {
                "is_blackout": True,
                "festival_name": festival,
                "type": info.get("type", "full_blackout")
            }
            logger.info({"event": "blackout_hit", "date": date_str, "festival": festival, "type": result["type"]})
            return result

    # Check client-specific custom blackout dates
    if client_id:
        try:
            from ..database import SessionLocal
            from ..models import ClientDB
            db = SessionLocal()
            client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
            db.close()
            if client and date_str in (client.festival_blackout_dates or []):
                return {"is_blackout": True, "festival_name": "custom_blackout", "type": "full_blackout"}
        except Exception as e:
            logger.warning({"event": "client_blackout_check_error", "error": str(e)})

    return {"is_blackout": False, "festival_name": None, "type": None}


# ── Regional tone getter ───────────────────────────────────────────────────────
def get_regional_tone(client_id: str) -> dict:
    """Returns regional tone config for a client."""
    try:
        from ..database import SessionLocal
        from ..models import ClientDB
        db = SessionLocal()
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        db.close()
        if client and isinstance(client.tone_config, dict):
            region = client.tone_config.get("region", "pan_india")
            return REGIONAL_TONE.get(region, REGIONAL_TONE["pan_india"])
    except Exception as e:
        logger.warning({"event": "regional_tone_error", "error": str(e)})
    return REGIONAL_TONE["pan_india"]


# ── Festive greeting picker ───────────────────────────────────────────────────
def get_festive_greeting(festival_name: str, lead, client, lang: str = "en") -> str:
    """
    Returns a festive greeting for an existing lead.
    Only call during soft_blackout periods.
    """
    # Map festival to greeting key
    festival_map = {
        "Diwali": "Diwali", "Holi": "Holi",
        "Eid ul-Fitr": "Eid", "Eid ul-Adha": "Eid",
        "Christmas": "Christmas",
        "New Year Eve": "New Year",
    }
    key = festival_map.get(festival_name)
    if not key:
        return ""

    templates = FESTIVE_GREETINGS.get(key, {})
    lang_key = "hi" if lang in ("hi", "hinglish") else "en"
    options = templates.get(lang_key) or templates.get("en", [])
    if not options:
        return ""

    import random
    template = random.choice(options)

    return template.format(
        name=(lead.name or "").split()[0] if lead.name else "there",
        company=lead.company or "your company",
        sender_company=client.name or "our team"
    )


# ── Calendar update helper ────────────────────────────────────────────────────
def add_custom_blackout(client_id: str, dates: list, festival_name: str = "custom"):
    """Add client-specific blackout dates to their config."""
    try:
        from ..database import SessionLocal
        from ..models import ClientDB
        db = SessionLocal()
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if client:
            existing = list(client.festival_blackout_dates or [])
            for d in dates:
                if d not in existing:
                    existing.append(d)
            client.festival_blackout_dates = existing
            db.commit()
        db.close()
        return {"success": True, "added": dates}
    except Exception as e:
        logger.error({"event": "add_blackout_error", "error": str(e)})
        return {"error": str(e)}
