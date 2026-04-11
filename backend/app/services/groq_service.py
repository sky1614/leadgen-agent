import json
import time
import uuid
from collections import deque
import httpx
from ..config import OPENROUTER_API_KEY, PRIMARY_MODEL, FALLBACK_MODEL
from openai import OpenAI
from ..config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, PRIMARY_MODEL, FALLBACK_MODEL

# ── Client ────────────────────────────────────────────────────────────────────
_openrouter_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=OPENROUTER_BASE_URL,
    default_headers={
        "HTTP-Referer": "https://leadgenai.in",
        "X-Title": "LeadGen AI",
    }
) if OPENROUTER_API_KEY else None

# ── Cost table (USD per 1M tokens) ───────────────────────────────────────────
_COSTS = {
    "anthropic/claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
}

# ── Rate limit tracker (kept for compatibility) ───────────────────────────────
_groq_calls = deque()
_GROQ_RPM_LIMIT = 28


# ── Helpers ───────────────────────────────────────────────────────────────────
def _estimate_cost(model: str, inp: int, out: int) -> float:
    c = _COSTS.get(model, {"input": 0, "output": 0})
    return round((inp * c["input"] + out * c["output"]) / 1_000_000, 8)


def _is_groq_rate_limited() -> bool:
    now = time.time()
    while _groq_calls and now - _groq_calls[0] > 60:
        _groq_calls.popleft()
    return len(_groq_calls) >= _GROQ_RPM_LIMIT


def _log_usage(client_id, model, inp, out, task_type):
    try:
        from .cost_tracker import log_groq, log_openai
        if "gpt" in model.lower() or "openai" in model.lower():
            log_openai(client_id, inp, out, task_type)
        else:
            log_groq(client_id, inp, out, task_type)
    except Exception as e:
        print(f"USAGE LOG ERROR: {e}")


def _call_openrouter(prompt: str, model: str) -> tuple:
    res = _openrouter_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        timeout=30
    )
    u = res.usage
    return res.choices[0].message.content.strip(), u.prompt_tokens, u.completion_tokens


# ── Unified AI call ────────────────────────────────────────────────────────────
def generate_ai(prompt: str, task_type: str = "general", client_id: str = None,
                model_override: str = None) -> dict:
    """
    Try PRIMARY_MODEL first. If fails, fall back to FALLBACK_MODEL.
    If model_override is provided and OpenRouter is configured, use it directly.
    Returns: {text, model_used, input_tokens, output_tokens, cost_estimate}
    """
    if not _openrouter_client:
        raise RuntimeError("No AI provider available — set OPENROUTER_API_KEY in .env")

    if model_override and _openrouter_client:
        try:
            text, inp, out = _call_openrouter(prompt, model_override)
            _log_usage(client_id, model_override, inp, out, task_type)
            return {"text": text, "model_used": model_override,
                    "input_tokens": inp, "output_tokens": out,
                    "cost_estimate": _estimate_cost(model_override, inp, out)}
        except Exception as e:
            print(f"MODEL OVERRIDE FAILED ({model_override}), falling through: {e}")

    try:
        text, inp, out = _call_openrouter(prompt, PRIMARY_MODEL)
        _log_usage(client_id, PRIMARY_MODEL, inp, out, task_type)
        return {"text": text, "model_used": PRIMARY_MODEL,
                "input_tokens": inp, "output_tokens": out,
                "cost_estimate": _estimate_cost(PRIMARY_MODEL, inp, out)}
    except Exception as e:
        print(f"PRIMARY MODEL FAILED ({type(e).__name__}), trying fallback: {e}")

    try:
        text, inp, out = _call_openrouter(prompt, FALLBACK_MODEL)
        _log_usage(client_id, FALLBACK_MODEL, inp, out, task_type)
        print(f"FALLBACK: {FALLBACK_MODEL} used for task={task_type}")
        return {"text": text, "model_used": FALLBACK_MODEL,
                "input_tokens": inp, "output_tokens": out,
                "cost_estimate": _estimate_cost(FALLBACK_MODEL, inp, out)}
    except Exception as e:
        print(f"FALLBACK ALSO FAILED: {e}")
        raise

    raise RuntimeError("No AI provider available")

# ── Public interfaces (called by routes + agent_service) ──────────────────────
def gemini(prompt: str, client_id: str = None) -> str:
    """Backward-compatible wrapper — returns text only."""
    return generate_ai(prompt, task_type="general", client_id=client_id)["text"]


def _get_template(industry: str):
    """Load prompt template for given industry. Falls back to generic."""
    import logging
    logger = logging.getLogger("groq_service")
    industry_map = {
        "real_estate": "real_estate",
        "realestate": "real_estate",
        "property": "real_estate",
        "it_staffing": "it_staffing",
        "it staffing": "it_staffing",
        "staffing": "it_staffing",
        "recruitment": "it_staffing",
        "edtech": "edtech",
        "education": "edtech",
        "coaching": "edtech",
    }
    key = industry_map.get((industry or "").lower().replace(" ", "_"), "generic")
    try:
        if key == "real_estate":
            from .prompt_templates.real_estate import TEMPLATE
        elif key == "it_staffing":
            from .prompt_templates.it_staffing import TEMPLATE
        elif key == "edtech":
            from .prompt_templates.edtech import TEMPLATE
        else:
            from .prompt_templates.generic import TEMPLATE
        return TEMPLATE
    except Exception as e:
        logger.warning({"event": "template_load_failed", "industry": industry, "error": str(e)})
        from .prompt_templates.generic import TEMPLATE
        return TEMPLATE


def _check_forbidden(text: str, forbidden: list) -> bool:
    text_lower = text.lower()
    return any(phrase.lower() in text_lower for phrase in forbidden)


def generate_message(lead, camp, channel: str, follow_up: int = 0,
                     client_id: str = None, language: str = "en",
                     reflection_context: str = "",
                     memory_context: str = ""),
                     rag_context: str = "",
                     ab_test_variant: str = None,
                     ab_test_id: str = None) -> dict:

    import logging
    logger = logging.getLogger("groq_service")
    from .scraper_service import message_template
    from .prompt_templates.base_template import get_few_shot_block

    try:
        # Load industry template
        industry = getattr(camp, "target_industry", "") or getattr(lead, "industry", "") or ""
        template = _get_template(industry)

        # Determine language from client tone_config
        if language == "en":
            try:
                from .cultural_service import get_regional_tone
                regional = get_regional_tone(client_id) if client_id else {}
                language = regional.get("language", "en")
            except Exception:
                try:
                    from ..database import SessionLocal
                    from ..models import ClientDB
                    _db = SessionLocal()
                    client = _db.query(ClientDB).filter(ClientDB.id == client_id).first() if client_id else None
                    if client and isinstance(client.tone_config, dict):
                        language = client.tone_config.get("language", "en")
                    _db.close()
                except Exception:
                    pass

        lang = "hi" if language in ("hi", "hinglish") else "en"
                # RAG: try to retrieve dynamic few-shots; fall back to static if empty
        rag_few_shots = ""
        try:
            enrichment_preview = json.loads(lead.enrichment_json or "{}")
            lead_profile_dict = {
                "name": getattr(lead, "name", ""),
                "company": getattr(lead, "company", ""),
                "role": getattr(lead, "role", ""),
                "industry": getattr(lead, "industry", "") or industry,
                "pain_points": enrichment_preview.get("pain_points", []),
            }
            from .rag_service import build_rag_few_shots
            rag_few_shots = build_rag_few_shots(
                client_id or "", lead_profile_dict, channel, lang, industry
            )
        except Exception:
            pass
        few_shots = rag_few_shots if rag_few_shots else get_few_shot_block(template, channel, lang)


        # Follow-up context
        max_words = template.max_message_length.get(channel, 200)
        if follow_up == 0:
            fu_instruction = template.follow_up_prompts.get("intro", "Write the first outreach message.")
        elif follow_up == 1:
            fu_instruction = template.follow_up_prompts.get("day3", "Day 3 follow-up. Reference previous message, add new value.")
        else:
            fu_instruction = template.follow_up_prompts.get("day7", "Final Day 7 follow-up. Be concise with strong CTA.")

        enrichment = json.loads(lead.enrichment_json or "{}")
        lang_instruction = "Write in natural Hinglish (Hindi+English mix as used in Indian WhatsApp/email). NOT Google Translate — sound like a real Indian professional." if lang == "hi" else "Write in English."

        regional_notes = ""
        try:
            from .cultural_service import get_regional_tone
            r = get_regional_tone(client_id) if client_id else {}
            if r.get("notes"):
                regional_notes = f"Regional tone guidance: {r['notes']}"
                if r.get("avoid"):
                    regional_notes += f" Avoid: {', '.join(r['avoid'])}."
        except Exception:
            pass
            
        # Check for OPRO-optimized prompt
        active_system_prompt = template.system_prompt
        try:
            from ..database import SessionLocal
            from ..models import PromptVersionDB
            _db = SessionLocal()
            optimized = _db.query(PromptVersionDB).filter(
                PromptVersionDB.client_id == client_id,
                PromptVersionDB.template_name == template.industry,
                PromptVersionDB.is_active == True,
            ).order_by(PromptVersionDB.created_at.desc()).first()
            _db.close()
            if optimized:
                active_system_prompt = optimized.prompt_text
                logger.info(f"OPRO: using optimized prompt version={optimized.id} for client={client_id}")
        except Exception as _e:
            logger.warning(f"OPRO prompt lookup failed, using default: {_e}")
        
        # A/B test: if treatment variant, override system prompt
        if ab_test_variant == "treatment" and ab_test_id:
            try:
                from ..models import ABTestDB
                from ..database import SessionLocal
                _adb = SessionLocal()
                try:
                    _atest = _adb.query(ABTestDB).filter(ABTestDB.id == ab_test_id).first()
                    if _atest and _atest.treatment_prompt:
                        active_system_prompt = _atest.treatment_prompt
                finally:
                    _adb.close()
            except Exception:
                pass
        #reflection_block = f"\n{reflection_context}" if reflection_context else ""

        reflection_block = f"\n{reflection_context}" if reflection_context else ""
        memory_block = f"\n{memory_context}" if memory_context else ""

        prompt = f"""{active_system_prompt}


{lang_instruction}
{regional_notes}{reflection_block}{memory_block}
Channel: {channel}. Max {max_words} words.
{fu_instruction}

Lead details:
- Name: {lead.name}
- Company: {lead.company}
- Role: {lead.role}
- Industry: {lead.industry}
- Website: {lead.website}
- Icebreaker: {enrichment.get('icebreaker', '')}
- Pain points: {enrichment.get('pain_points', [])}

Product/Service being pitched: {camp.product_description}
Campaign tone: {camp.tone}

Industry terms to use naturally if relevant: {', '.join(template.industry_terms[:10])}

FORBIDDEN phrases (never use): {', '.join(template.forbidden_phrases)}

{few_shots}

Write ONLY the message. No explanation. No notes."""

        result = generate_ai(prompt, task_type="message", client_id=client_id)
        message_text = result["text"]

        # A/B test: record message sent in background
        if ab_test_id and ab_test_variant:
            try:
                from .ab_testing_service import record_message_sent
                from ..database import SessionLocal
                _db2 = SessionLocal()
                record_message_sent(ab_test_id, ab_test_variant, _db2)
                _db2.close()
            except Exception:
                pass

        # Check forbidden phrases — regenerate once if violated
        if _check_forbidden(message_text, template.forbidden_phrases):
            logger.warning({"event": "forbidden_phrase_detected", "lead_id": getattr(lead, "id", ""), "retrying": True})
            result = generate_ai(prompt + "\n\nIMPORTANT: The previous attempt contained forbidden phrases. Rewrite avoiding all forbidden phrases.", task_type="message", client_id=client_id)
            message_text = result["text"]

        result["message"] = message_text
        result.pop("text", None)

        # Record A/B message sent in background
        if ab_test_id and ab_test_variant:
            try:
                from .ab_testing_service import record_message_sent
                record_message_sent(ab_test_id, ab_test_variant, None)
            except Exception:
                pass

        result["template_used"] = template.industry
        result["language"] = lang
        return result

    except Exception as e:
        logger.error({"event": "generate_message_error", "lead_id": getattr(lead, "id", ""), "error": str(e), "ts": __import__('datetime').datetime.utcnow().isoformat()})
        from .scraper_service import message_template
        return {"message": message_template(lead, camp, channel), "model_used": "template",
                "input_tokens": 0, "output_tokens": 0, "cost_estimate": 0,
                "template_used": "fallback", "language": "en"}


def score_lead(lead, client_id: str = None) -> dict:
    try:
        template = _get_template(getattr(lead, "industry", "") or "")
        from .prompt_templates.base_template import get_scoring_boost
        boost = get_scoring_boost(template, lead)
        prompt = f"""Score this B2B lead 1-10 and return JSON only.
Lead: name={lead.name}, company={lead.company}, industry={lead.industry}, role={lead.role}, website={lead.website}
Industry scoring boost applied: +{boost} points based on {template.industry} criteria.
Return ONLY: {{"score":<1-10>,"reason":"<one sentence>","pain_points":["..."]}}"""

        result = generate_ai(prompt, task_type="score", client_id=client_id)
        data = json.loads(_clean_json(result["text"]))
        return {"score": data.get("score", 5), "reason": data.get("reason", ""),
                "pain_points": data.get("pain_points", []),
                "model_used": result["model_used"], "tokens_used": result["input_tokens"] + result["output_tokens"]}
    except Exception as e:
        print(f"SCORE ERROR: {e}")
        score = 7 if lead.email else 5
        return {"score": score, "reason": "Auto-scored", "pain_points": [], "model_used": "fallback", "tokens_used": 0}


def enrich_lead(lead, client_id: str = None) -> dict:
    try:
        prompt = f"""Analyze this B2B lead and return JSON only.
Lead: name={lead.name}, company={lead.company}, industry={lead.industry}, role={lead.role}, website={lead.website}
Return ONLY: {{"pain_points":["..."],"fit_score":<1-10>,"fit_reason":"<one sentence>","suggested_approach":"<one sentence>","icebreaker":"<personalized opening>"}}"""
        result = generate_ai(prompt, task_type="enrich", client_id=client_id)
        data = json.loads(_clean_json(result["text"]))
        data["model_used"] = result["model_used"]
        data["tokens_used"] = result["input_tokens"] + result["output_tokens"]
        return data
    except Exception as e:
        print(f"ENRICH ERROR: {e}")
        score = min(10, (7 if lead.email else 5) + (1 if lead.role else 0) + (1 if lead.website else 0))
        return {"pain_points": ["Scaling outreach", "Lead management"],
                "fit_score": score, "fit_reason": "Auto-scored",
                "suggested_approach": "Standard outreach",
                "icebreaker": f"Hi {lead.name.split()[0] if lead.name else 'there'},",
                "model_used": "fallback", "tokens_used": 0}


# ── Backward-compatible aliases ────────────────────────────────────────────────
def ai_enrich(lead, client_id: str = None) -> dict:
    return enrich_lead(lead, client_id=client_id)


def ai_message(lead, camp, channel: str, follow_up: int = 0, client_id: str = None) -> str:
    return generate_message(lead, camp, channel, follow_up, client_id=client_id)["message"]


# ── Utility ────────────────────────────────────────────────────────────────────
def _clean_json(text: str) -> str:
    if "```" in text:
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    return text.strip()
