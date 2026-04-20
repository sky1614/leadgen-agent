"""
Plan enforcement — called at key points in the agent pipeline.
All functions return (allowed: bool, reason: str)
"""
from ..config import get_plan


def get_user_plan(db, client_id: str) -> dict:
    from ..models import UserDB
    user = db.query(UserDB).filter(UserDB.client_id == client_id).first()
    tier = user.plan if user else "free"
    return get_plan(tier)


def check_leads_cap(db, client_id: str) -> tuple:
    """Check if client has hit monthly lead cap."""
    from datetime import datetime
    from ..models import LeadDB
    plan  = get_user_plan(db, client_id)
    cap   = plan["leads_per_month"]
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = db.query(LeadDB).filter(
        LeadDB.client_id == client_id,
        LeadDB.created_at >= month_start
    ).count()
    if count >= cap:
        return False, f"Monthly lead cap reached ({cap} leads on {plan['name']} plan)"
    return True, f"{cap - count} leads remaining this month"


def check_fit_score(db, client_id: str, fit_score: float) -> tuple:
    """Check if lead meets plan's minimum fit score."""
    plan    = get_user_plan(db, client_id)
    minimum = plan["fit_score_min"]
    if fit_score < minimum:
        return False, f"Fit score {fit_score} below {plan['name']} minimum ({minimum})"
    return True, "ok"


def check_channel(db, client_id: str, channel: str) -> tuple:
    """Check if plan allows this channel."""
    plan = get_user_plan(db, client_id)
    if channel not in plan["channels"]:
        return False, f"{channel} not available on {plan['name']} plan"
    return True, "ok"


def check_campaign_cap(db, client_id: str) -> tuple:
    """Check if client can create another campaign."""
    from ..models import CampaignDB
    plan  = get_user_plan(db, client_id)
    cap   = plan["max_campaigns"]
    count = db.query(CampaignDB).filter(
        CampaignDB.client_id == client_id,
        CampaignDB.status == "active"
    ).count()
    if count >= cap:
        return False, f"Campaign limit reached ({cap} on {plan['name']} plan). Upgrade to add more."
    return True, "ok"


def check_feature(db, client_id: str, feature: str) -> tuple:
    """
    Check if plan includes a feature.
    feature: 'whatsapp' | 'multi_agent' | 'ai_dashboard' | 'rag_opro_ab' | 'api_access' | 'white_label'
    """
    plan = get_user_plan(db, client_id)
    if not plan.get(feature, False):
        return False, f"{feature.replace('_',' ').title()} not available on {plan['name']} plan. Upgrade to unlock."
    return True, "ok"


def get_enrichment_depth(db, client_id: str) -> str:
    """Returns 'basic' | 'standard' | 'deep'"""
    return get_user_plan(db, client_id)["enrichment_depth"]


def get_allowed_sources(db, client_id: str) -> list:
    """Returns list of allowed lead sources for this plan."""
    return get_user_plan(db, client_id)["sources"]


def get_plan_summary(db, client_id: str) -> dict:
    """Returns full plan info — used by frontend."""
    from datetime import datetime
    from ..models import LeadDB
    plan        = get_user_plan(db, client_id)
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used        = db.query(LeadDB).filter(
        LeadDB.client_id == client_id,
        LeadDB.created_at >= month_start
    ).count()
    return {
        **plan,
        "leads_used_this_month": used,
        "leads_remaining":       max(0, plan["leads_per_month"] - used),
        "usage_pct":             round((used / plan["leads_per_month"]) * 100, 1) if plan["leads_per_month"] else 0,
    }