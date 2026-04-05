import difflib
import json
import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger("quality_gate")

SPAM_WORDS_EN = [
    "guaranteed", "limited time", "act now", "congratulations", "winner",
    "click here", "free gift", "no obligation", "risk free", "urgent",
    "you've been selected", "claim now", "don't miss", "exclusive offer",
    "100% free", "special promotion", "double your", "earn money"
]
SPAM_WORDS_HI = [
    "jaldi karein", "sirf aaj", "muft", "inaam", "lucky winner",
    "abhi karen", "free mein", "guaranteed results"
]
CASUAL_WORDS = ["bro", "dude", "yaar", "buddy", "mate", "chill", "lol", "haha"]
FORMAL_WORDS = ["dear sir", "dear madam", "to whom it may concern", "respected sir"]


def _word_count(text: str) -> int:
    return len(text.split())


def _extract_phones(text: str) -> list:
    return re.findall(r'[\+]?[\d][\d\s\-\(\)]{8,}[\d]', text)


def _extract_emails(text: str) -> list:
    return re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)


def _extract_urls(text: str) -> list:
    return re.findall(r'https?://\S+|www\.\S+', text)


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def check_message_quality(
    message_text: str,
    lead_data,          # LeadDB object or dict
    client_config: dict,
    channel: str = "email",
    recent_messages: list = None   # list of recent message strings for duplicate check
) -> dict:
    """
    Run all quality checks on a generated message.
    Returns: {passed: bool, issues: list, score: float, warnings: list}
    """
    issues = []
    warnings = []
    ts = datetime.utcnow().isoformat()

    # Normalize lead_data to dict
    if hasattr(lead_data, "__dict__"):
        lead = {
            "name": getattr(lead_data, "name", "") or "",
            "company": getattr(lead_data, "company", "") or "",
            "email": getattr(lead_data, "email", "") or "",
            "whatsapp": getattr(lead_data, "whatsapp", "") or "",
            "website": getattr(lead_data, "website", "") or "",
            "enrichment_json": getattr(lead_data, "enrichment_json", "{}") or "{}",
        }
    else:
        lead = lead_data

    text_lower = message_text.lower()
    tone = (client_config.get("tone") or "professional").lower()
    language = (client_config.get("language") or "en").lower()

    # ── a. Company name match ────────────────────────────────────────────────
    try:
        lead_company = (lead.get("company") or "").strip().lower()
        lead_name = (lead.get("name") or "").strip().lower()
        # Extract capitalized proper nouns (rough heuristic)
        capitalized = re.findall(r'\b[A-Z][a-zA-Z]{2,}\b', message_text)
        suspicious = [
            w for w in capitalized
            if w.lower() not in text_lower[:20]   # allow sender intro
            and lead_company and w.lower() not in lead_company
            and lead_name and w.lower() not in lead_name
            and w.lower() not in ("hi", "hello", "dear", "regards", "best", "thanks", "subject")
        ]
        # Only flag if a clearly different company name appears
        hallucinated = [w for w in suspicious if len(w) > 4 and w.lower() not in message_text[:50].lower()]
        if len(hallucinated) > 3:
            issues.append({
                "check": "company_name_match",
                "detail": f"Possible hallucinated names: {hallucinated[:5]}. Lead company: '{lead.get('company')}'"
            })
    except Exception as e:
        logger.warning({"check": "company_name_match", "error": str(e), "ts": ts})

    # ── b. Contact info hallucination ────────────────────────────────────────
    try:
        found_phones = _extract_phones(message_text)
        found_emails = _extract_emails(message_text)
        found_urls = _extract_urls(message_text)

        lead_phone = lead.get("whatsapp", "").replace(" ", "").replace("-", "")
        lead_email = lead.get("email", "").lower()
        lead_website = (lead.get("website", "") or "").lower().replace("https://", "").replace("http://", "").rstrip("/")

        for phone in found_phones:
            clean = phone.replace(" ", "").replace("-", "")
            if lead_phone and clean not in lead_phone and lead_phone not in clean:
                issues.append({"check": "contact_hallucination", "detail": f"Hallucinated phone number: {phone}"})
                break

        for email in found_emails:
            if lead_email and email.lower() != lead_email:
                # Could be sender's email — skip if it looks like a from address
                if "sender" not in text_lower[:100]:
                    issues.append({"check": "contact_hallucination", "detail": f"Unrecognized email in message: {email}"})
                    break

        for url in found_urls:
            clean_url = url.replace("https://", "").replace("http://", "").rstrip("/").lower()
            if lead_website and clean_url and clean_url not in lead_website and lead_website not in clean_url:
                issues.append({"check": "contact_hallucination", "detail": f"Unrecognized URL in message: {url}"})
                break
    except Exception as e:
        logger.warning({"check": "contact_hallucination", "error": str(e), "ts": ts})

    # ── c. Message length ─────────────────────────────────────────────────────
    try:
        wc = _word_count(message_text)
        if channel == "whatsapp":
            if wc < 20:
                issues.append({"check": "length", "detail": f"WhatsApp message too short ({wc} words, min 20)"})
            elif wc > 150:
                issues.append({"check": "length", "detail": f"WhatsApp message too long ({wc} words, max 150)"})
        else:  # email
            if wc < 40:
                issues.append({"check": "length", "detail": f"Email too short ({wc} words, min 40)"})
            elif wc > 350:
                issues.append({"check": "length", "detail": f"Email too long ({wc} words, max 350)"})
    except Exception as e:
        logger.warning({"check": "length", "error": str(e), "ts": ts})

    # ── d. Spam word filter ───────────────────────────────────────────────────
    try:
        found_spam = [w for w in SPAM_WORDS_EN if w in text_lower]
        found_spam_hi = [w for w in SPAM_WORDS_HI if w in text_lower]
        if found_spam or found_spam_hi:
            issues.append({"check": "spam_words", "detail": f"Spam phrases found: {found_spam + found_spam_hi}"})
    except Exception as e:
        logger.warning({"check": "spam_words", "error": str(e), "ts": ts})

    # ── e. Duplicate message check ────────────────────────────────────────────
    try:
        if recent_messages:
            for prev in recent_messages[-50:]:
                sim = _similarity(message_text, prev)
                if sim > 0.80:
                    issues.append({"check": "duplicate", "detail": f"Message is {sim*100:.0f}% similar to a recent message"})
                    break
    except Exception as e:
        logger.warning({"check": "duplicate", "error": str(e), "ts": ts})

    # ── f. Language consistency ───────────────────────────────────────────────
    try:
        hindi_pattern = re.compile(r'[\u0900-\u097F]')
        has_devanagari = bool(hindi_pattern.search(message_text))
        hinglish_words = ["hai", "hoon", "kya", "aap", "main", "kar", "se", "ke", "ki", "ko", "mein", "nahi", "bhi"]
        hinglish_word_count = sum(1 for w in hinglish_words if f" {w} " in text_lower)
        is_hinglish = hinglish_word_count >= 3

        if language == "en" and (has_devanagari or is_hinglish):
            warnings.append({"check": "language", "detail": "Client config is English but message contains Hindi/Hinglish"})
        elif language in ("hi", "hinglish") and not is_hinglish and not has_devanagari:
            warnings.append({"check": "language", "detail": "Client config is Hinglish but message is pure English"})

        # Fail if 3+ languages mixed
        has_english = bool(re.search(r'[a-zA-Z]{3,}', message_text))
        lang_count = sum([has_english, has_devanagari, is_hinglish and has_english])
        if lang_count >= 3 and has_devanagari:
            issues.append({"check": "language_mixing", "detail": "Message mixes 3+ languages (Devanagari + English + Hinglish)"})
    except Exception as e:
        logger.warning({"check": "language_consistency", "error": str(e), "ts": ts})

    # ── g. Tone check ─────────────────────────────────────────────────────────
    try:
        if tone in ("formal", "professional"):
            found_casual = [w for w in CASUAL_WORDS if f" {w}" in text_lower or f"{w} " in text_lower]
            if found_casual:
                issues.append({"check": "tone", "detail": f"Casual words in formal message: {found_casual}"})
        elif tone == "casual":
            found_formal = [w for w in FORMAL_WORDS if w in text_lower]
            if found_formal:
                warnings.append({"check": "tone", "detail": f"Formal phrases in casual message: {found_formal}"})
    except Exception as e:
        logger.warning({"check": "tone", "error": str(e), "ts": ts})

    # ── h. Personalization check ─────────────────────────────────────────────
    try:
        lead_name_first = (lead.get("name") or "").split()[0].lower() if lead.get("name") else ""
        lead_company_lc = (lead.get("company") or "").lower()
        enrichment = {}
        try:
            enrichment = json.loads(lead.get("enrichment_json", "{}") or "{}")
        except Exception:
            pass
        icebreaker = (enrichment.get("icebreaker") or "").lower()[:30]

        has_personalization = (
            (lead_name_first and lead_name_first in text_lower) or
            (lead_company_lc and len(lead_company_lc) > 3 and lead_company_lc in text_lower) or
            (icebreaker and len(icebreaker) > 5 and icebreaker[:15] in text_lower)
        )
        if not has_personalization:
            issues.append({"check": "personalization", "detail": "Message has no personalization (no lead name, company, or specific detail)"})
    except Exception as e:
        logger.warning({"check": "personalization", "error": str(e), "ts": ts})

    # ── Final scoring ─────────────────────────────────────────────────────────
    max_checks = 8
    passed_checks = max_checks - len(issues)
    score = round((passed_checks / max_checks) * 10, 1)
    passed = len(issues) == 0

    result = {
        "passed": passed,
        "issues": issues,
        "warnings": warnings,
        "score": score,
        "word_count": _word_count(message_text),
        "ts": ts
    }

    if not passed:
        logger.warning({
            "event": "quality_check_failed",
            "issues": issues,
            "score": score,
            "ts": ts
        })

    return result


def build_fix_prompt(original_prompt: str, issues: list) -> str:
    """Build a regeneration prompt that instructs the AI to fix specific issues."""
    issue_descriptions = "\n".join(f"- {i['check']}: {i['detail']}" for i in issues)
    return f"""{original_prompt}

IMPORTANT: Your previous response had quality issues. Fix ALL of the following:
{issue_descriptions}

Rewrite the message fixing every issue listed above. Do not introduce new ones."""
