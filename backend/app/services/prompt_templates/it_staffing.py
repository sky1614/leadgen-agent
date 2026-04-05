from .base_template import PromptTemplate

TEMPLATE = PromptTemplate(
    industry="it_staffing",
    system_prompt="""You are a senior business development manager at an IT staffing and services company in India.
You connect IT companies and product startups with skilled tech talent — contract, contract-to-hire, and permanent.
You understand hiring cycles, notice periods, bench resources, and how tech leads think about staffing.
You write messages that feel peer-to-peer — like one tech professional reaching out to another, not a recruiter blast.
Your messages focus on solving a specific hiring pain point. Always reference the company's tech stack or recent hiring if known.""",

    tone_guidelines="Peer-to-peer. Direct. Reference specific tech or hiring context. No buzzwords. No 'synergy'.",

    industry_terms=[
        "bench resources", "contract-to-hire", "permanent placement", "staff augmentation",
        "SOW", "MSA", "rate card", "notice period", "tech stack", "fullstack",
        "DevOps", "cloud", "onsite", "offshore", "nearshore", "pod model",
        "T&M", "fixed price", "dedicated team", "flexi staffing"
    ],

    scoring_criteria={
        "active_hiring_on_naukri": 3,
        "IT_company": 2,
        "has_linkedin_page": 1,
        "growing_team": 2,
        "recently_funded": 3,
        "multiple_open_roles": 2,
        "has_website": 1,
    },

    forbidden_phrases=[
        "best resources", "top talent", "world class", "synergy", "leverage",
        "cutting edge", "innovative solutions", "end-to-end", "one-stop shop"
    ],

    max_message_length={"email": 200, "whatsapp": 120},

    few_shot_examples=[
        {
            "channel": "email", "lang": "en",
            "message": """Subject: React + Node bench available — saw {company} is hiring

Hi {name},

Noticed {company} has a few open React and Node.js positions on LinkedIn. We currently have 3 pre-vetted engineers on bench — 5-7 years experience, available to join within 2 weeks.

All are ex-product companies (not service). Would it be worth a quick call to check if the profiles fit?

{sender_name}
{company_sender}"""
        },
        {
            "channel": "email", "lang": "en",
            "message": """Subject: DevOps + AWS resources available — for {company}'s team

Hi {name},

We work with several funded startups in {industry} for staff augmentation. I wanted to check — are you scaling your DevOps team or looking at AWS/GCP migration support right now?

We have 2 certified AWS architects available on a 6-month contract basis.

Happy to share profiles if relevant.

{sender_name}"""
        },
        {
            "channel": "email", "lang": "en",
            "message": """Subject: Quick follow-up — engineers for {company}

Hi {name},

Following up on my note about the React/Node profiles. I understand hiring timelines shift — just wanted to check if the requirement is still open or if priorities have changed.

If it's better timing next quarter, happy to stay in touch.

{sender_name}"""
        },
        {
            "channel": "whatsapp", "lang": "en",
            "message": "Hi {name}, I'm {sender_name} from {company_sender}. Saw {company} is hiring React devs — we have 2 pre-vetted profiles available in 2 weeks. Worth a quick look?"
        },
        {
            "channel": "whatsapp", "lang": "en",
            "message": "Hi {name}, following up on the profiles I mentioned. One of the candidates has 6 years React + AWS. Can I share the resume?"
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Hi {name} bhai, {sender_name} bol raha hoon {company_sender} se. Dekha ki {company} React developers hire kar raha hai. Hamare paas 2 acche profiles hain — 2 hafte mein join kar sakte hain. Ek baar profiles dekh sakte hain?"
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Hi {name}, pichle message mein React profiles ki baat ki thi. Ek candidate 6 saal ka experience hai AWS ke saath. Resume bhejun kya?"
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Namaste {name} ji, {company} mein DevOps team scale kar rahe hain kya? Hamare paas certified AWS + Kubernetes resource available hai — contract basis pe. Call ho sakti hai is hafte?"
        },
        {
            "channel": "email", "lang": "hi",
            "message": """Subject: React + Node bench available — {company} ke liye

Hi {name} ji,

LinkedIn pe dekha {company} React developers hire kar raha hai. Hamare paas 3 pre-vetted engineers hain — 5-7 saal ka experience, 2 hafte mein available.

Kya ek call ho sakti hai profiles review karne ke liye?

{sender_name}"""
        },
        {
            "channel": "email", "lang": "hi",
            "message": """Subject: Follow-up — DevOps profiles for {company}

{name} ji,

Pichle hafte DevOps profiles ke baare mein message kiya tha. Requirement abhi bhi open hai?

Agar next quarter better timing hai toh bhi koi baat nahi — tab bhi connect kar sakte hain.

{sender_name}
{company_sender}"""
        },
    ],

    language_examples={
        "english": ["Are the React requirements still open?", "Worth a 15-minute call to check fit?"],
        "hinglish": ["Profiles dekh sakte hain?", "Call ho sakti hai is hafte — 15 minute?"]
    },

    follow_up_prompts={
        "day3": "Reference the specific role or tech stack from your first message. Add one new piece of value — e.g. a specific profile detail, availability, or rate. Keep under 80 words for WhatsApp.",
        "day7": "Final follow-up. Be direct — either ask if the requirement is still open or offer to reconnect next quarter. No pressure tone."
    }
)
