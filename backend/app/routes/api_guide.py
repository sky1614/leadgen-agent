from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["docs"])

_GUIDE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeadGen AI — API Guide</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e8e8f0;font-size:15px;line-height:1.7}
.layout{display:flex;min-height:100vh}
.sidebar{width:260px;background:#111118;border-right:1px solid #2a2a38;padding:24px 20px;position:sticky;top:0;height:100vh;overflow-y:auto;flex-shrink:0}
.content{flex:1;max-width:820px;padding:40px 48px}
.logo{font-size:18px;font-weight:800;color:#7c5cfc;margin-bottom:32px;display:block}
.nav-section{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:#6b6b80;margin:20px 0 8px;font-weight:600}
.nav-link{display:block;padding:6px 10px;border-radius:6px;font-size:13px;color:#9ca3af;text-decoration:none;transition:all .15s;margin-bottom:2px}
.nav-link:hover,.nav-link.active{background:rgba(124,92,252,.15);color:#7c5cfc}
h1{font-size:32px;font-weight:800;letter-spacing:-.5px;margin-bottom:8px}
h2{font-size:22px;font-weight:700;margin:48px 0 12px;padding-top:48px;border-top:1px solid #2a2a38;color:#e8e8f0;letter-spacing:-.3px}
h3{font-size:16px;font-weight:700;margin:24px 0 8px;color:#7c5cfc}
p{color:#9ca3af;margin-bottom:12px}
pre{background:#18181f;border:1px solid #2a2a38;border-radius:8px;padding:16px;overflow-x:auto;font-size:13px;font-family:'Fira Code','DM Mono',monospace;line-height:1.6;margin:12px 0}
code{background:#18181f;border:1px solid #2a2a38;border-radius:4px;padding:2px 6px;font-size:12px;font-family:'DM Mono',monospace;color:#00e5a0}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;font-family:monospace}
.get{background:rgba(0,229,160,.15);color:#00e5a0}
.post{background:rgba(124,92,252,.15);color:#7c5cfc}
.put{background:rgba(245,166,35,.15);color:#f5a623}
.delete{background:rgba(255,107,107,.12);color:#ff6b6b}
.endpoint{background:#18181f;border:1px solid #2a2a38;border-radius:8px;padding:16px;margin:10px 0}
.endpoint-header{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.endpoint-path{font-family:'DM Mono',monospace;font-size:14px;font-weight:600}
.endpoint-desc{font-size:13px;color:#6b6b80}
.note{background:rgba(124,92,252,.08);border:1px solid rgba(124,92,252,.25);border-radius:8px;padding:14px 16px;margin:16px 0;font-size:14px;color:#c4b5fd}
.warn{background:rgba(245,166,35,.08);border-color:rgba(245,166,35,.25);color:#fcd34d}
table{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0}
th{text-align:left;padding:8px 12px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#6b6b80;border-bottom:1px solid #2a2a38}
td{padding:10px 12px;border-bottom:1px solid rgba(42,42,56,.5);color:#9ca3af}
td code{font-size:12px}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
  <a href="/api-guide" class="logo">LeadGen AI</a>
  <div class="nav-section">Getting Started</div>
  <a class="nav-link" href="#authentication">Authentication</a>
  <a class="nav-link" href="#api-keys">API Keys</a>
  <a class="nav-link" href="#errors">Error Codes</a>
  <div class="nav-section">Core Endpoints</div>
  <a class="nav-link" href="#leads">Leads</a>
  <a class="nav-link" href="#campaigns">Campaigns</a>
  <a class="nav-link" href="#agent">Agent / Auto-run</a>
  <a class="nav-link" href="#messages">Messages</a>
  <a class="nav-link" href="#analytics">Analytics</a>
  <div class="nav-section">Enterprise</div>
  <a class="nav-link" href="#webhooks">Webhooks</a>
  <a class="nav-link" href="#white-label">White Label</a>
  <div class="nav-section">Reference</div>
  <a class="nav-link" href="/docs" target="_blank">Interactive Docs ↗</a>
  <a class="nav-link" href="/redoc" target="_blank">ReDoc ↗</a>
</aside>

<div class="content">
  <h1>LeadGen AI API</h1>
  <p>Programmatic access to leads, campaigns, agent runs, analytics, and webhooks. Base URL: <code>https://api.yourdomain.in</code></p>

  <h2 id="authentication">Authentication</h2>
  <p>All endpoints require authentication via either a <strong>Bearer JWT token</strong> (dashboard users) or an <strong>API key</strong> (programmatic access).</p>

  <h3>Bearer JWT (Dashboard)</h3>
  <p>Obtain a token by calling <code>POST /auth/login</code>, then include it on every request:</p>
  <pre>Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...</pre>

  <h3>API Key (Enterprise / Programmatic)</h3>
  <p>Generate an API key from your dashboard under <strong>Settings → API Key</strong>. Pass it as a header:</p>
  <pre>X-Api-Key: lga_live_a1b2c3d4e5f6...</pre>
  <div class="note">API keys are rate-limited to <strong>100 requests per minute</strong>. JWT tokens have no rate limit.</div>

  <h2 id="api-keys">Getting an API Key</h2>
  <p>Generate your API key programmatically or via the dashboard:</p>
  <pre>POST /enterprise/api-key/generate
Authorization: Bearer &lt;your_jwt_token&gt;

# Response:
{
  "api_key": "lga_live_abc123...",     // Save this — shown only once
  "prefix": "lga_live_abc1...",
  "warning": "Save this key now. It will not be shown again."
}</pre>
  <div class="note warn">The full API key is shown only once at generation time. Store it securely (e.g. in your .env file). If lost, revoke and regenerate.</div>

  <h2 id="errors">Error Codes</h2>
  <table>
    <tr><th>Code</th><th>Meaning</th></tr>
    <tr><td><code>400</code></td><td>Bad request — check your request body</td></tr>
    <tr><td><code>401</code></td><td>Not authenticated — invalid or missing token/API key</td></tr>
    <tr><td><code>403</code></td><td>Forbidden — you don't have access to this resource</td></tr>
    <tr><td><code>404</code></td><td>Resource not found</td></tr>
    <tr><td><code>422</code></td><td>Validation error — missing required field</td></tr>
    <tr><td><code>429</code></td><td>Rate limit exceeded</td></tr>
    <tr><td><code>500</code></td><td>Internal server error</td></tr>
  </table>

  <h2 id="leads">Leads</h2>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/leads</span></div>
    <div class="endpoint-desc">List all leads for your account.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge post">POST</span><span class="endpoint-path">/leads</span></div>
    <div class="endpoint-desc">Add a single lead manually.</div>
  </div>
  <pre># Add a lead
POST /leads
X-Api-Key: lga_live_...
Content-Type: application/json

{
  "name": "Rajesh Kumar",
  "company": "TechSoft India",
  "email": "rajesh@techsoft.in",
  "whatsapp": "+919876543210",
  "industry": "SaaS",
  "role": "Founder"
}</pre>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge post">POST</span><span class="endpoint-path">/leads/{id}/enrich</span></div>
    <div class="endpoint-desc">Trigger AI enrichment and fit scoring for a lead.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/leads/export/csv</span></div>
    <div class="endpoint-desc">Download all leads as CSV.</div>
  </div>

  <h2 id="campaigns">Campaigns</h2>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/campaigns</span></div>
    <div class="endpoint-desc">List all campaigns.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge post">POST</span><span class="endpoint-path">/campaigns</span></div>
    <div class="endpoint-desc">Create a campaign.</div>
  </div>
  <pre># Create a campaign
POST /campaigns
X-Api-Key: lga_live_...

{
  "name": "Q2 SaaS Outreach",
  "product_description": "We build AI agents for B2B sales teams...",
  "target_industry": "SaaS",
  "tone": "professional",
  "channel": "both"
}</pre>

  <h2 id="agent">Agent / Auto-run</h2>
  <p>Trigger the full autonomous pipeline: find leads → enrich → score → generate messages → queue for approval.</p>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge post">POST</span><span class="endpoint-path">/agent/run</span></div>
    <div class="endpoint-desc">Start an agent run for a campaign + industry. Returns a job_id.</div>
  </div>
  <pre># Trigger agent
POST /agent/run
X-Api-Key: lga_live_...

{
  "campaign_id": "abc12345",
  "industry": "Real Estate",
  "count": 10,
  "source_url": ""
}

# Response
{
  "success": true,
  "job_id": "job_xyz789",
  "leads_processed": 10
}</pre>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/agent/jobs/{job_id}</span></div>
    <div class="endpoint-desc">Poll job status. Status: running → pending_approval → approved → error.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge post">POST</span><span class="endpoint-path">/agent/jobs/{job_id}/approve</span></div>
    <div class="endpoint-desc">Approve all messages in a job and trigger sending.</div>
  </div>

  <h2 id="messages">Messages</h2>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/messages/pending</span></div>
    <div class="endpoint-desc">List messages awaiting approval.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge put">PUT</span><span class="endpoint-path">/messages/{id}/approve</span></div>
    <div class="endpoint-desc">Approve a single message for sending.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge put">PUT</span><span class="endpoint-path">/messages/{id}/reject</span></div>
    <div class="endpoint-desc">Reject a message with an optional reason.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge post">POST</span><span class="endpoint-path">/messages/approve-batch</span></div>
    <div class="endpoint-desc">Approve multiple messages at once.</div>
  </div>
  <pre>POST /messages/approve-batch
{ "message_ids": ["id1", "id2", "id3"] }</pre>

  <h2 id="analytics">Analytics</h2>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/analytics</span></div>
    <div class="endpoint-desc">Basic lead and message counts.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/analytics/client-detail</span></div>
    <div class="endpoint-desc">Full funnel + email/WA metrics with per-channel breakdown.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/analytics/pipeline</span></div>
    <div class="endpoint-desc">Lead counts at each pipeline stage (new/contacted/replied/meeting/closed).</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/analytics/campaigns-performance</span></div>
    <div class="endpoint-desc">Per-campaign open rate, click rate, bounce rate.</div>
  </div>
  <div class="endpoint">
    <div class="endpoint-header"><span class="badge get">GET</span><span class="endpoint-path">/analytics/health</span></div>
    <div class="endpoint-desc">Client health score (0–100) with 7 components and auto-fix alerts.</div>
  </div>

  <h2 id="webhooks">Webhooks (Enterprise)</h2>
  <p>Register HTTPS URLs to receive real-time events when leads are found, messages are sent, or replies come in.</p>
  <h3>Supported events</h3>
  <table>
    <tr><th>Event</th><th>When triggered</th></tr>
    <tr><td><code>lead_found</code></td><td>New lead added to pipeline</td></tr>
    <tr><td><code>message_sent</code></td><td>Message approved and dispatched</td></tr>
    <tr><td><code>reply_received</code></td><td>Lead replies via WhatsApp or email</td></tr>
    <tr><td><code>meeting_booked</code></td><td>Lead status changes to meeting_booked</td></tr>
  </table>
  <h3>Register a webhook</h3>
  <pre>POST /enterprise/webhooks
X-Api-Key: lga_live_...

{
  "url": "https://your-server.com/webhook",
  "events": ["lead_found", "message_sent"]
}

# Response includes signing_secret — save it</pre>
  <h3>Verifying signatures</h3>
  <p>Every event includes a <code>X-LeadGen-Signature</code> header. Verify it in your handler:</p>
  <pre>import hmac, hashlib

def verify(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)</pre>
  <h3>Event payload structure</h3>
  <pre>{
  "event": "message_sent",
  "timestamp": "2026-03-31T09:15:00Z",
  "client_id": "client_abc123",
  "data": {
    "lead_id": "lead_xyz",
    "company": "Acme Corp",
    "channel": "whatsapp",
    "message_id": "msg_123"
  }
}</pre>

  <h2 id="white-label">White Label (Pro/Enterprise)</h2>
  <p>Customise the sender name, email footer, and brand color used in all client-facing communications.</p>
  <pre>PUT /enterprise/white-label
X-Api-Key: lga_live_...

{
  "brand_name": "Acme Sales AI",
  "brand_color": "#1d4ed8",
  "brand_email_footer": "Sent by Acme Sales AI · Unsubscribe below",
  "white_label_enabled": true
}</pre>

</div>
</div>
</body>
</html>"""


@router.get("/api-guide", response_class=HTMLResponse, include_in_schema=False)
def api_guide():
    """Developer API guide page."""
    return HTMLResponse(content=_GUIDE_HTML)
