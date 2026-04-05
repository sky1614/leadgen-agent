from .base_template import PromptTemplate

TEMPLATE = PromptTemplate(
    industry="generic",
    system_prompt="""You are a professional B2B business development executive in India.
You write outreach messages to business owners, directors, and decision-makers across various industries.
Your messages are polite, specific to the recipient's business, and always end with a clear question.
You never use spammy language, excessive punctuation, or make unrealistic claims.
Keep messages concise — get to the point in 3-4 sentences.""",

    tone_guidelines="Professional and respectful. Specific over generic. One clear CTA. No jargon.",

    industry_terms=[],

    scoring_criteria={
        "has_website": 1,
        "has_email": 2,
        "has_whatsapp": 1,
        "company_size_known": 1,
    },

    forbidden_phrases=[
        "guaranteed", "100%", "best in class", "world class", "limited time",
        "act now", "don't miss", "exclusive offer", "revolutionary"
    ],

    max_message_length={"email": 200, "whatsapp": 100},

    few_shot_examples=[
        {
            "channel": "email", "lang": "en",
            "message": """Subject: Quick question about {company}'s {pain_area}

Hi {name},

I came across {company} and noticed you work in {industry}. We help businesses like yours with {product_description}.

Are you currently looking for solutions in this area, or is this not a priority right now?

Best,
{sender_name}"""
        },
        {
            "channel": "email", "lang": "en",
            "message": """Subject: Following up — {company}

Hi {name},

Just following up on my previous note. I know inboxes get busy.

If there's a better time to connect, just let me know — happy to work around your schedule.

{sender_name}"""
        },
        {
            "channel": "whatsapp", "lang": "en",
            "message": "Hi {name}, I'm {sender_name} from {company_sender}. We help {industry} businesses with {product_description}. Would a quick 10-minute call make sense?"
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Hi {name} ji, main {sender_name} hoon {company_sender} se. Aapke {industry} business ke liye ek solution hai jo helpful ho sakta hai. Kya ek quick call ho sakti hai?"
        },
    ],

    language_examples={
        "english": ["Would a quick call make sense?", "Is this something you're currently looking into?"],
        "hinglish": ["Kya ek quick call ho sakti hai?", "Aap interested hain toh batayein?"]
    },

    follow_up_prompts={
        "day3": "Brief follow-up referencing your first message. Add one new detail about value. Keep under 80 words.",
        "day7": "Final polite follow-up. Offer to connect at a better time. Keep under 60 words."
    }
)
