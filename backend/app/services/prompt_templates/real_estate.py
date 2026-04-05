from .base_template import PromptTemplate

TEMPLATE = PromptTemplate(
    industry="real_estate",
    system_prompt="""You are an experienced real estate business development executive in India.
You help builders, developers, and property consultants connect with potential buyers and investors.
You understand the Indian real estate market — RERA compliance, EMI structures, possession timelines, 
and how buyers think. You write messages that feel like they come from a trusted advisor, not a salesperson.
Your messages are concise, mention one specific compelling detail, and always end with a clear question.
Never promise guaranteed returns. Never use all-caps or excessive punctuation.""",

    tone_guidelines="Professional but warm. Conversational. Ask one question. Never pitch more than one project per message.",

    industry_terms=[
        "2BHK", "3BHK", "carpet area", "built-up area", "super built-up area",
        "RERA", "possession date", "ready possession", "under construction",
        "EMI", "down payment", "builder floor", "township", "gated community",
        "plot", "villa", "penthouse", "registry", "stamp duty", "OC", "CC"
    ],

    scoring_criteria={
        "RERA_registered": 2,
        "recent_listing": 3,
        "has_website": 1,
        "has_whatsapp": 2,
        "multiple_projects": 2,
        "tier1_city": 1,
        "ready_possession": 2,
    },

    forbidden_phrases=[
        "guaranteed returns", "investment opportunity", "limited time offer",
        "best deal", "don't miss out", "act now", "last few units",
        "100% safe", "assured returns"
    ],

    max_message_length={"email": 250, "whatsapp": 120},

    few_shot_examples=[
        {
            "channel": "email", "lang": "en",
            "message": """Subject: New RERA-approved 3BHK in {area} — Wanted to check if it fits your timeline

Hi {name},

I came across {company} and noticed you've been active in the {area} real estate market.

We've just launched a RERA-approved 3BHK project in {area} — ready possession, priced at ₹{price}. The carpet area is 1,150 sq ft with a covered parking.

Are you currently looking for inventory in this range, or are you focused on a different segment right now?

Best,
{sender_name}"""
        },
        {
            "channel": "email", "lang": "en",
            "message": """Subject: {area} plot project — RERA certified, 100% clear title

Hi {name},

Quick note — we have a plotted development project near {area} that might interest your buyers. RERA registered, clear title, with possession in Q3 2025.

Plot sizes range from 150 to 500 sq yards. Pricing starts at ₹{price} per sq yard.

Would it make sense to get on a 15-minute call this week to see if there's a fit?

{sender_name}
{company}"""
        },
        {
            "channel": "email", "lang": "en",
            "message": """Subject: Following up — 3BHK project details for {company}

Hi {name},

Just following up on my earlier note about our {area} project.

We've had strong interest from buyers in your segment — the EMI works out to around ₹{emi}/month with 20% down. OC is already received.

Is this something worth a quick site visit this weekend?

{sender_name}"""
        },
        {
            "channel": "whatsapp", "lang": "en",
            "message": "Hi {name}, I'm {sender_name} from {company}. We have a RERA-approved 3BHK in {area} — ready possession, ₹{price}. Are you currently looking for projects in this range?"
        },
        {
            "channel": "whatsapp", "lang": "en",
            "message": "Hi {name}, following up on my earlier message. The {area} project has 2 units left at the launch price. Happy to share the floor plan — does tomorrow work for a quick call?"
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Hi {name} ji, main {sender_name} bol raha hoon {company} se. Aapke {area} mein ek naya 3BHK project launch hua hai — RERA approved, ready possession. Starting price {price} se. Kya aap is weekend visit kar sakte hain? Reply YES karein."
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Namaste {name} ji! {company} ki taraf se — humara {area} mein ek gated community project hai, 2BHK aur 3BHK available. OC mil gayi hai, registry ready hai. Kya main aapko brochure bhej sakta hoon?"
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Hi {name} ji, pichli baar message kiya tha {area} project ke baare mein. Kuch buyers ne site visit book kar li hai is weekend. Kya aap bhi interested hain? Plot sizes 150 sq yard se shuru hote hain."
        },
        {
            "channel": "email", "lang": "hi",
            "message": """Subject: {area} mein naya 3BHK project — RERA approved

Namaste {name} ji,

{company} ki taraf se aapko connect kar raha hoon. Humara {area} mein ek nayi residential project launch hui hai — RERA registered, ready possession, aur starting price {price} se.

Kya aap is type ke projects mein interested hain ya aapka focus kisi aur segment mein hai abhi?

Regards,
{sender_name}"""
        },
        {
            "channel": "email", "lang": "hi",
            "message": """Subject: {area} plot project — clear title, RERA certified

{name} ji,

Mera pichla email aapne dekha hoga {area} project ke baare mein. EMI lagbhag {emi}/month padti hai 20% down payment ke saath. OC already mil gayi hai.

Kya is weekend ek quick site visit ho sakti hai?

{sender_name}
{company}"""
        },
    ],

    language_examples={
        "english": ["Are you currently looking for inventory in this range?", "Would a site visit this weekend work?"],
        "hinglish": ["Kya aap is weekend visit kar sakte hain?", "Main brochure bhej sakta hoon — interested hain?"]
    },

    follow_up_prompts={
        "day3": "Reference your first message briefly. Ask if they had a chance to review. Mention one new specific detail (e.g. EMI, OC status, or floor plan). Keep it under 80 words for WhatsApp.",
        "day7": "This is the final follow-up. Be brief and low-pressure. Either offer to share a brochure or suggest a site visit. If no response after this, no more follow-ups."
    }
)
