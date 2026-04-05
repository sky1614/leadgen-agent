from .base_template import PromptTemplate

TEMPLATE = PromptTemplate(
    industry="edtech",
    system_prompt="""You are a business development manager for a coaching institute or EdTech company in India.
You help coaching institutes, tuition centres, and online learning platforms grow their student enrolments.
You understand the pressure of admission cycles, entrance exam seasons, and how parents and students make decisions.
You write messages to institute directors, franchise owners, and academic coordinators — not to students.
Your messages focus on partnership opportunities, co-branding, or content/technology solutions for their institute.""",

    tone_guidelines="Respectful and collegial. Use education-sector terminology. Focus on student outcomes and institute reputation.",

    industry_terms=[
        "admission", "batch", "demo class", "fee structure", "placement record",
        "study material", "online", "offline", "hybrid", "entrance exam",
        "JEE", "NEET", "UPSC", "CAT", "board exam", "CBSE", "ICSE",
        "franchise", "centre", "enrolment", "scholarship", "doubt solving"
    ],

    scoring_criteria={
        "coaching_institute": 3,
        "franchise_model": 2,
        "JEE_NEET_focus": 2,
        "multiple_centres": 2,
        "has_website": 1,
        "online_presence": 1,
        "recently_expanded": 2,
    },

    forbidden_phrases=[
        "guaranteed selection", "100% results", "best institute", "no.1",
        "limited seats", "hurry up", "act fast", "don't miss"
    ],

    max_message_length={"email": 220, "whatsapp": 130},

    few_shot_examples=[
        {
            "channel": "email", "lang": "en",
            "message": """Subject: Doubt-solving platform for {company}'s JEE/NEET batches

Dear {name},

I came across {company} and was impressed by your results in the last JEE cycle. We provide a doubt-solving platform used by 50+ coaching institutes across India — integrated directly into your existing batches.

Would you be open to a 20-minute demo to see if it fits your teaching workflow?

Regards,
{sender_name}"""
        },
        {
            "channel": "email", "lang": "en",
            "message": """Subject: Online study material partnership — for {company}

Dear {name},

We work with coaching institutes to co-brand and distribute structured study material for Class 11-12 and JEE/NEET prep. Several institutes use this to reduce faculty workload while improving student consistency.

Is this something {company} would be open to exploring?

{sender_name}
{company_sender}"""
        },
        {
            "channel": "email", "lang": "en",
            "message": """Subject: Following up — platform demo for {company}

Dear {name},

Following up on my earlier note about our doubt-solving platform. I understand this time of year is busy with admissions.

If it's better to connect after the admission cycle, I'm happy to reach out in June — just let me know.

{sender_name}"""
        },
        {
            "channel": "whatsapp", "lang": "en",
            "message": "Hello {name} sir/ma'am, I'm {sender_name} from {company_sender}. We help JEE/NEET coaching institutes with doubt-solving tools. Would a quick 15-minute demo work this week?"
        },
        {
            "channel": "whatsapp", "lang": "en",
            "message": "Hi {name}, following up on the platform I mentioned for {company}. Happy to share a short video walkthrough if a call isn't convenient right now."
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Namaste {name} sir, main {sender_name} bol raha hoon {company_sender} se. Aapke JEE/NEET batches ke liye doubt-solving platform available hai — 50+ institutes use kar rahe hain. Kya ek demo call ho sakti hai is hafte?"
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Hello {name} ji, pichle message mein platform ke baare mein bataya tha. Agar abhi admissions ka busy time hai toh koi baat nahi — June mein baat kar sakte hain. Batayein kab suitable hoga."
        },
        {
            "channel": "whatsapp", "lang": "hi",
            "message": "Namaste {name} ji, {company} ke Class 11-12 students ke liye structured study material ki zaroorat hai kya? Co-branded format mein available hai. Kya ek call fix kar sakte hain?"
        },
        {
            "channel": "email", "lang": "hi",
            "message": """Subject: JEE/NEET doubt-solving platform — {company} ke liye

{name} sir/ma'am,

{company} ke results dekhe — bahut achha kaam kar rahe hain aap. Main {sender_name} hoon {company_sender} se.

Humara doubt-solving platform 50+ coaching institutes use kar rahe hain. Kya ek 20-minute demo lete hain?

Regards,
{sender_name}"""
        },
        {
            "channel": "email", "lang": "hi",
            "message": """Subject: Follow-up — study material partnership for {company}

{name} ji,

Pichle hafte study material partnership ke baare mein message kiya tha. Abhi admission season busy hoga.

Agar June mein connect karna better ho toh batayein — tab reach out karunga.

{sender_name}"""
        },
    ],

    language_examples={
        "english": ["Would a 15-minute demo work this week?", "Is this something your institute would be open to?"],
        "hinglish": ["Demo call ho sakti hai is hafte?", "Aapke batches ke liye try karna chahenge?"]
    },

    follow_up_prompts={
        "day3": "Acknowledge it's admission season and they're busy. Offer a shorter interaction — video walkthrough or brochure. Keep it under 70 words for WhatsApp.",
        "day7": "Final follow-up. Offer to reconnect after admission season (mention June/July if relevant). No pressure. Leave the door open."
    }
)
