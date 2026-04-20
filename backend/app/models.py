import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Float, Text, DateTime, Boolean, ForeignKey, JSON

from .database import Base


class ClientDB(Base):
    __tablename__ = "clients"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    industry = Column(String, default="other")
    icp_config = Column(JSON, default=dict)
    tone_config = Column(JSON, default=dict)
    wa_number = Column(String, default="")
    email_domain = Column(String, default="")
    plan_tier = Column(String, default="starter")
    monthly_lead_cap = Column(Integer, default=500)
    monthly_email_cap = Column(Integer, default=1000)
    monthly_wa_cap = Column(Integer, default=1000)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    festival_blackout_dates = Column(JSON, default=list)
    onboarding_complete = Column(Boolean, default=False)
    website           = Column(String, nullable=True)
    target_industry   = Column(String, nullable=True)
    target_city       = Column(String, nullable=True)
    target_size       = Column(String, nullable=True)
    target_titles     = Column(String, nullable=True)
    product_desc      = Column(Text, nullable=True)
    preferred_channel = Column(String, default="email")
    city              = Column(String, nullable=True)
        # White-label / branding
    brand_name = Column(String, nullable=True)
    brand_logo_url = Column(String, nullable=True)
    brand_color = Column(String, default="#7c5cfc")
    brand_email_footer = Column(Text, nullable=True)
    white_label_enabled = Column(Boolean, default=False)
    # API access
    api_key_hash = Column(String, nullable=True, unique=True)
    api_key_prefix = Column(String, nullable=True)   # lga_live_XXXX (shown to user)



class UserDB(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    email = Column(String, unique=True, index=True)
    name = Column(String)
    hashed_password = Column(String)
    plan = Column(String, default="free")
    leads_used = Column(Integer, default=0)
    leads_limit = Column(Integer, default=500)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    role = Column(String, default="admin")
    trial_started_at  = Column(DateTime, default=datetime.utcnow)
    trial_ends_at     = Column(DateTime, nullable=True)
    kyc_id_type       = Column(String, nullable=True)
    kyc_id_value      = Column(String, nullable=True)
    kyc_country       = Column(String, default="IN")
    kyc_locked        = Column(Boolean, default=False)
    onboarding_done   = Column(Boolean, default=False)
    sender_name       = Column(String, nullable=True)
    sender_title      = Column(String, nullable=True)
    sender_email      = Column(String, nullable=True)
    sender_phone      = Column(String, nullable=True)


class LeadDB(Base):
    __tablename__ = "leads"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String, ForeignKey("users.id"))
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    name = Column(String)
    company = Column(String)
    email = Column(String)
    whatsapp = Column(String)
    industry = Column(String)
    role = Column(String)
    website = Column(String)
    notes = Column(String)
    source = Column(String, default="manual")
    status = Column(String, default="new")
    fit_score = Column(Float, default=0)
    enrichment_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_contacted = Column(DateTime, nullable=True)
    follow_up_day = Column(Integer, default=0)
    fingerprint = Column(String)
    email_verified = Column(Boolean, default=True)
    do_not_contact = Column(Boolean, default=False)
    wa_verified = Column(Boolean, nullable=True)
    verification_date = Column(DateTime, nullable=True)
    contact_channels = Column(JSON, default=list)
    wa_consent = Column(Boolean, default=False)
    wa_consent_date = Column(DateTime, nullable=True)
    wa_consent_source = Column(String, nullable=True)

class CampaignDB(Base):
    __tablename__ = "campaigns"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String, ForeignKey("users.id"))
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    name = Column(String)
    product_description = Column(Text)
    target_industry = Column(String)
    tone = Column(String, default="professional")
    channel = Column(String, default="both")
    status = Column(String, default="active")
    sent_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class MessageLogDB(Base):
    __tablename__ = "message_log"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String, ForeignKey("users.id"))
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    lead_id = Column(String)
    campaign_id = Column(String)
    channel = Column(String)
    message = Column(Text)
    status = Column(String, default="simulated")
    follow_up_number = Column(Integer, default=0)
    sendgrid_message_id = Column(String, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    opened_at = Column(DateTime, nullable=True)
    clicked_at = Column(DateTime, nullable=True)
    bounced = Column(Boolean, default=False)
    bounce_type = Column(String, nullable=True)
    spam_reported = Column(Boolean, default=False)
    unsubscribed = Column(Boolean, default=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    approval_status = Column(String, default="pending_approval")
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    ab_test_id = Column(String, nullable=True)
    ab_test_variant = Column(String, nullable=True)
    rejection_reason = Column(String, nullable=True)
    quality_gate_score = Column(Float, nullable=True)
    quality_gate_issues = Column(JSON, nullable=True)


class ConversationDB(Base):
    __tablename__ = "conversations"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    lead_id = Column(String)
    role = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ScrapedSourceDB(Base):
    __tablename__ = "scraped_sources"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String)
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    url = Column(String)
    industry = Column(String)
    schedule = Column(String, default="daily")
    last_run = Column(DateTime, nullable=True)
    leads_found = Column(Integer, default=0)


class AgentJobDB(Base):
    __tablename__ = "agent_jobs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    user_id = Column(String, ForeignKey("users.id"))
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    campaign_id = Column(String)
    industry = Column(String)
    source_url = Column(String, default="")
    status = Column(String, default="running")
    total_leads = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    prospector_status = Column(String, nullable=True)
    scorer_status = Column(String, nullable=True)
    writer_status = Column(String, nullable=True)
    delivery_status = Column(String, nullable=True)
    leads_found = Column(Integer, default=0)
    leads_scored = Column(Integer, default=0)
    leads_written = Column(Integer, default=0)
    auto_approved_count = Column(Integer, default=0)
    pending_approval_count = Column(Integer, default=0)

class AgentJobItemDB(Base):
    __tablename__ = "agent_job_items"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    job_id = Column(String, ForeignKey("agent_jobs.id"))
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    lead_id = Column(String)
    lead_name = Column(String)
    lead_company = Column(String)
    lead_email = Column(String)
    lead_whatsapp = Column(String)
    fit_score = Column(Float, default=0)
    email_message = Column(Text)
    whatsapp_message = Column(Text)
    status = Column(String, default="pending")

class AIUsageDB(Base):
    __tablename__ = "ai_usage"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    client_id = Column(String, nullable=True)
    model_used = Column(String)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)
    units_used = Column(Integer, default=0)       # tokens, emails, msgs, or searches
    cost_inr = Column(Float, default=0.0)
    task_type = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class QualityLogDB(Base):
    __tablename__ = "quality_logs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    client_id = Column(String, nullable=True)
    lead_id = Column(String, nullable=True)
    job_id = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    passed = Column(Boolean, default=False)
    passed_after_regen = Column(Boolean, default=False)
    failed_permanently = Column(Boolean, default=False)
    quality_score = Column(Float, default=0.0)
    issues_json = Column(Text, default="[]")   # JSON list of issues
    created_at = Column(DateTime, default=datetime.utcnow)

class WeeklyReportDB(Base):
    __tablename__ = "weekly_reports"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    client_id = Column(String, nullable=True)
    week_start = Column(DateTime, nullable=True)
    week_end = Column(DateTime, nullable=True)
    stats_json = Column(Text, default="{}")
    sent_to = Column(String, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    status = Column(String, default="pending")   # pending, sent, failed
    created_at = Column(DateTime, default=datetime.utcnow)


class DemoDB(Base):
    __tablename__ = "demos"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    prospect_name = Column(String)
    industry = Column(String)
    city = Column(String)
    target_description = Column(Text)
    requester_email = Column(String, nullable=True)
    requester_phone = Column(String, nullable=True)
    status = Column(String, default="created")   # created, running, complete, expired
    leads_found = Column(Integer, default=0)
    leads_verified = Column(Integer, default=0)
    messages_generated = Column(Integer, default=0)
    avg_score = Column(Float, default=0.0)
    report_viewed = Column(Boolean, default=False)
    report_viewed_at = Column(DateTime, nullable=True)
    converted_to_paid = Column(Boolean, default=False)
    demo_client_id = Column(String, nullable=True)   # temp ClientDB id
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)


class SubscriptionDB(Base):
    __tablename__ = "subscriptions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    razorpay_subscription_id = Column(String, nullable=True, unique=True)
    razorpay_customer_id = Column(String, nullable=True)
    plan_tier = Column(String, default="starter")
    billing_cycle = Column(String, default="monthly")   # monthly / quarterly
    status = Column(String, default="created")          # created, authenticated, active, cancelled, completed, paused
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    trial_end = Column(DateTime, nullable=True)
    grace_period_end = Column(DateTime, nullable=True)  # for failed payments
    cancelled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PaymentDB(Base):
    __tablename__ = "payments"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    subscription_id = Column(String, nullable=True)
    razorpay_payment_id = Column(String, nullable=True)
    razorpay_invoice_id = Column(String, nullable=True)
    amount_paise = Column(Integer, default=0)           # stored in paise (INR * 100)
    currency = Column(String, default="INR")
    status = Column(String, default="pending")          # pending, captured, failed, refunded
    failure_reason = Column(String, nullable=True)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    invoice_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class ClientWebhookDB(Base):
    __tablename__ = "client_webhooks"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    url = Column(String, nullable=False)
    secret = Column(String, nullable=False)          # HMAC secret for signing
    events = Column(JSON, default=list)              # ["lead_found","message_sent",...]
    is_active = Column(Boolean, default=True)
    failure_count = Column(Integer, default=0)
    last_triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class AgentReflectionDB(Base):
    __tablename__ = "agent_reflections"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    job_id = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    lessons_json = Column(Text, default="[]")
    avoid_patterns_json = Column(Text, default="[]")
    confidence_score = Column(Float, default=0.0)
    was_applied = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class PromptVersionDB(Base):
    __tablename__ = "prompt_versions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    template_name = Column(String, nullable=False)
    prompt_text = Column(Text, nullable=False)
    reply_rate_at_creation = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class EpisodicMemoryDB(Base):
    __tablename__ = "episodic_memory"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    lead_id = Column(String, nullable=True)
    outcome = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    message_length = Column(Integer, default=0)
    had_name = Column(Boolean, default=False)
    had_company = Column(Boolean, default=False)
    had_pain_point = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class SemanticMemoryDB(Base):
    __tablename__ = "semantic_memory"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    pattern_type = Column(String, nullable=True)
    pattern_value = Column(String, nullable=True)
    success_rate = Column(Float, default=0.0)
    sample_count = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)

class AutonomousLoopDB(Base):
    __tablename__ = "autonomous_loop"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    campaign_id = Column(String, nullable=True)
    replan_count = Column(Integer, default=0)
    last_replan_at = Column(DateTime, nullable=True)
    last_performance_json = Column(Text, default="{}")
    last_strategy_json = Column(Text, default="{}")
    total_improvements = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class ReactTraceDB(Base):
    __tablename__ = "react_traces"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    job_id = Column(String, nullable=True)
    lead_id = Column(String, nullable=True)
    trace_type = Column(String, nullable=True)
    decision = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    thought_trace_json = Column(Text, nullable=True)
    recommended_action = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class JudgeEvaluationDB(Base):
    __tablename__ = "judge_evaluations"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, nullable=True)
    lead_id = Column(String, nullable=True)
    job_id = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    personalization_score = Column(Float, default=0.0)
    cultural_fit_score = Column(Float, default=0.0)
    cta_strength_score = Column(Float, default=0.0)
    tone_match_score = Column(Float, default=0.0)
    clarity_score = Column(Float, default=0.0)
    weighted_score = Column(Float, default=0.0)
    verdict = Column(String, nullable=True)
    primary_weakness = Column(String, nullable=True)
    was_rewritten = Column(Boolean, default=False)
    final_passed = Column(Boolean, default=False)
    red_flags_json = Column(Text, default="[]")
    improvement_suggestion = Column(Text, nullable=True)
    judge_model = Column(String, nullable=True)
    evaluation_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ABTestDB(Base):
    __tablename__ = "ab_tests"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())[:12])
    client_id = Column(String, ForeignKey("clients.id"), nullable=True)
    campaign_id = Column(String, nullable=True)
    template_name = Column(String, nullable=True)
    control_prompt = Column(Text, nullable=True)
    treatment_prompt = Column(Text, nullable=True)
    control_messages_sent = Column(Integer, default=0)
    control_replies = Column(Integer, default=0)
    control_opens = Column(Integer, default=0)
    control_bounces = Column(Integer, default=0)
    treatment_messages_sent = Column(Integer, default=0)
    treatment_replies = Column(Integer, default=0)
    treatment_opens = Column(Integer, default=0)
    treatment_bounces = Column(Integer, default=0)
    status = Column(String, default="running")
    winner = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
