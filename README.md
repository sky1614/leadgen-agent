# LeadGen AI Agent 🚀
### Agentic Sales Lead Generation Platform — Beta v0.1

Built with Python + FastAPI + Claude AI. Finds, enriches and sends personalized outreach to leads via WhatsApp & Email.

---

## ⚡ Quick Start (5 minutes)

### 1. Install dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Set your API key
```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=your_key_here
```

### 3. Run the backend
```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 4. Open the dashboard
Open `frontend/index.html` in your browser (double-click it).

---

## 🤖 What the Agent Does

| Step | Action |
|------|--------|
| **Find** | Import leads via CSV upload OR scrape any URL with AI |
| **Enrich** | Claude scores each lead 1–10, finds pain points, writes an icebreaker |
| **Reach** | Generates personalized WhatsApp + Email messages per lead |
| **Track** | Full message log with timestamps |

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/leads` | List all leads |
| POST | `/leads` | Add single lead |
| POST | `/leads/upload-csv` | Bulk import CSV |
| POST | `/leads/scrape` | AI web scraping |
| POST | `/leads/{id}/enrich` | AI enrichment + scoring |
| GET | `/campaigns` | List campaigns |
| POST | `/campaigns` | Create campaign |
| POST | `/outreach/preview` | Preview AI message |
| POST | `/outreach/send` | Send outreach (simulated) |
| POST | `/outreach/bulk` | Bulk outreach all leads |
| GET | `/outreach/log` | Message history |
| GET | `/analytics` | Dashboard stats |

Full docs at: `http://localhost:8000/docs` (Swagger UI auto-generated)

---

## 📨 Connecting Real Outreach Channels

### Email (Gmail / SMTP)
1. Enable 2FA on Gmail → generate an App Password
2. Add to `.env`:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SENDER_EMAIL=you@gmail.com
   SENDER_PASSWORD=your_app_password
   ```

### WhatsApp (Twilio sandbox — free)
1. Sign up at twilio.com → activate WhatsApp sandbox
2. Add to `.env`:
   ```
   WHATSAPP_TOKEN=your_twilio_token
   WHATSAPP_FROM=whatsapp:+14155238886
   ```

---

## 🗂️ CSV Format

```csv
name,company,email,whatsapp,industry,role,website,notes
Rahul Gupta,TechSoft,rahul@techsoft.in,+919876543210,SaaS,Founder,techsoft.in,
```

---

## 🇮🇳 India GTM Tips

- Use **IndiaMart / TradeIndia** URLs in the scraper to pull business leads
- WhatsApp is the primary channel — prioritize it over email
- GST/compliance pain points resonate strongly with SME segment
- Pricing: ₹3,999–₹30,000/mo (enterprise customization on top)

---

## 🛣️ Roadmap (Next 30 days)

- [ ] Connect real WhatsApp Business API
- [ ] Connect SMTP for actual email delivery
- [ ] PostgreSQL database (replace in-memory store)
- [ ] Follow-up sequence automation (Day 1, Day 3, Day 7)
- [ ] Lead scoring ML model
- [ ] CRM export (CSV / HubSpot / Zoho)
- [ ] Multi-user / team accounts
- [ ] Custom business onboarding flow

---

## 📣 Launch Copy (Twitter / Discord)

> Built an AI Sales Lead Gen agent — finds leads, scores them, writes personalized WhatsApp + email outreach. Free beta access open now.
> 
> Need it customized for your business? DM me.
> 
> #buildinpublic #saas #AIagents #India

---

*Built in 12 hours. Powered by Claude AI.*
