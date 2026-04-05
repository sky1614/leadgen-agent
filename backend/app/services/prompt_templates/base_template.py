from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class PromptTemplate:
    industry: str
    system_prompt: str
    few_shot_examples: List[Dict]        # [{"channel": "email"|"whatsapp", "lang": "en"|"hi", "message": str}]
    scoring_criteria: Dict               # {"factor_name": score_delta}
    industry_terms: List[str]
    tone_guidelines: str
    language_examples: Dict              # {"english": [...], "hinglish": [...]}
    forbidden_phrases: List[str]
    max_message_length: Dict             # {"email": 300, "whatsapp": 150}  (words)
    follow_up_prompts: Dict              # {"day3": str, "day7": str}


def get_few_shot_block(template: PromptTemplate, channel: str, lang: str = "en") -> str:
    """Build a few-shot examples string for the prompt."""
    examples = [
        e for e in template.few_shot_examples
        if e.get("channel") == channel and e.get("lang") == lang
    ][:3]
    if not examples:
        return ""
    block = "\nHere are good example messages:\n"
    for i, ex in enumerate(examples, 1):
        block += f"\nExample {i}:\n{ex['message']}\n"
    return block


def get_scoring_boost(template: PromptTemplate, lead) -> int:
    """Calculate score boost from industry-specific criteria."""
    boost = 0
    enrichment_str = (lead.enrichment_json or "{}").lower()
    for factor, delta in template.scoring_criteria.items():
        if factor.lower().replace("_", " ") in enrichment_str or factor.lower() in (lead.notes or "").lower():
            boost += delta
    return boost
