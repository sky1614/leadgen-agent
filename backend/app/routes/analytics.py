import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import LeadDB, MessageLogDB, UserDB, QualityLogDB, AIUsageDB

logger = logging.getLogger("analytics")
router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
def analytics(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    leads = db.query(LeadDB).filter(LeadDB.user_id == cu.id).all()
    scores = [l.fit_score for l in leads if l.fit_score > 0]
    by_ind, by_src = {}, {}
    for l in leads:
        by_ind[l.industry or "Unknown"] = by_ind.get(l.industry or "Unknown", 0) + 1
        by_src[l.source or "manual"] = by_src.get(l.source or "manual", 0) + 1
    return {
        "total_leads": len(leads),
        "enriched": sum(1 for l in leads if l.status == "enriched"),
        "contacted": sum(1 for l in leads if l.status in ["contacted", "sequence_complete"]),
        "skipped_low_fit": sum(1 for l in leads if l.status == "skipped"),
        "avg_fit_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "total_messages": db.query(MessageLogDB).filter(MessageLogDB.user_id == cu.id).count(),
        "follow_ups_sent": db.query(MessageLogDB).filter(MessageLogDB.user_id == cu.id, MessageLogDB.follow_up_number > 0).count(),
        "leads_by_industry": by_ind,
        "leads_by_source": by_src,
        "plan": cu.plan,
        "leads_used": cu.leads_used,
        "leads_limit": cu.leads_limit
    }


@router.get("/quality")
def quality_analytics(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    import json as _json
    logs = db.query(QualityLogDB).filter(QualityLogDB.client_id == cu.client_id).all()
    total = len(logs)
    passed_first = sum(1 for l in logs if l.passed and not l.passed_after_regen)
    passed_regen = sum(1 for l in logs if l.passed_after_regen)
    failed_permanently = sum(1 for l in logs if l.failed_permanently)
    issue_counts = {}
    for log in logs:
        try:
            for issue in _json.loads(log.issues_json or "[]"):
                check = issue.get("check", "unknown")
                issue_counts[check] = issue_counts.get(check, 0) + 1
        except Exception:
            pass
    common_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)
    return {
        "total_generated": total,
        "passed_first_time": passed_first,
        "passed_after_regen": passed_regen,
        "failed_permanently": failed_permanently,
        "first_pass_rate": f"{(passed_first / total * 100):.1f}%" if total else "0%",
        "common_issues": [{"issue": k, "count": v} for k, v in common_issues[:10]]
    }


@router.get("/costs/{client_id}")
def client_costs(
    client_id: str,
    period: str = "month",
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user)
):
    """Cost breakdown for a specific client. Client can only see their own."""
    try:
        if cu.client_id and cu.client_id != client_id and cu.role != "superadmin":
            raise HTTPException(403, "Access denied")
        from ..services.cost_tracker import get_client_costs
        result = get_client_costs(client_id, period=period)
        if "error" in result:
            raise HTTPException(500, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "client_costs_error", "client_id": client_id, "error": str(e)})
        raise HTTPException(500, str(e))


@router.get("/costs/summary")
def costs_summary(
    period: str = "month",
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user)
):
    """All clients cost summary. Admin only."""
    try:
        if cu.role not in ("admin", "superadmin"):
            raise HTTPException(403, "Admin access required")
        from ..services.cost_tracker import get_all_clients_costs
        result = get_all_clients_costs(period=period)
        if "error" in result:
            raise HTTPException(500, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "costs_summary_error", "error": str(e)})
        raise HTTPException(500, str(e))


@router.post("/costs/check-alerts")
def trigger_cost_alerts(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    """Manually trigger cost alert check. Admin only."""
    try:
        if cu.role not in ("admin", "superadmin"):
            raise HTTPException(403, "Admin access required")
        from ..services.cost_tracker import check_and_alert
        result = check_and_alert()
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Plan tier → MRR mapping (INR) ─────────────────────────────────────────────
_PLAN_MRR = {"starter": 2999, "growth": 7999, "pro": 14999, "enterprise": 29999, "demo": 0, "free": 0}


@router.get("/admin-overview")
def admin_overview(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    """Admin-only: MRR, active clients, infra cost, health summary."""
    import json as _json
    from datetime import timedelta
    try:
        if cu.role not in ("admin", "superadmin"):
            raise HTTPException(403, "Admin access required")

        from ..models import ClientDB, CampaignDB
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
        total_clients = len(clients)
        mrr = sum(_PLAN_MRR.get(c.plan_tier or "starter", 2999) for c in clients)

        leads_this_month = db.query(LeadDB).filter(LeadDB.created_at >= month_start).count()

        msgs = db.query(MessageLogDB).filter(MessageLogDB.sent_at >= month_start).all()
        emails_sent = sum(1 for m in msgs if m.channel == "email")
        wa_sent     = sum(1 for m in msgs if m.channel == "whatsapp")
        meetings    = db.query(LeadDB).filter(
            LeadDB.status == "meeting_booked", LeadDB.last_contacted >= month_start
        ).count()

        # Infra cost from ai_usage
        usage = db.query(AIUsageDB).filter(AIUsageDB.created_at >= month_start).all()
        infra_cost_inr = round(sum(u.cost_inr or 0 for u in usage), 2)
        gross_margin = round(((mrr - infra_cost_inr) / mrr * 100), 1) if mrr else 0

        # Health summary
        from ..services.health_monitor import calculate_client_health
        health_counts = {"healthy": 0, "warning": 0, "critical": 0}
        for c in clients[:20]:  # cap at 20 to stay fast
            try:
                h = calculate_client_health(c.id)
                health_counts[h.get("status", "warning")] = health_counts.get(h.get("status", "warning"), 0) + 1
            except Exception:
                pass

        return {
            "total_active_clients": total_clients,
            "mrr_inr": mrr,
            "leads_this_month": leads_this_month,
            "emails_sent_this_month": emails_sent,
            "wa_sent_this_month": wa_sent,
            "meetings_this_month": meetings,
            "infra_cost_inr": infra_cost_inr,
            "gross_margin_pct": gross_margin,
            "health_summary": health_counts,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error({"event": "admin_overview_error", "error": str(e)})
        raise HTTPException(500, str(e))


@router.get("/client-detail")
def client_detail(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    """Detailed funnel + email/WA metrics for the current user's client."""
    try:
        from datetime import timedelta
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        leads = db.query(LeadDB).filter(LeadDB.client_id == cu.client_id).all() if cu.client_id else \
                db.query(LeadDB).filter(LeadDB.user_id == cu.id).all()

        funnel = {
            "new":           sum(1 for l in leads if l.status == "new"),
            "enriched":      sum(1 for l in leads if l.status == "enriched"),
            "contacted":     sum(1 for l in leads if l.status == "contacted"),
            "replied":       sum(1 for l in leads if l.status == "replied"),
            "meeting_booked":sum(1 for l in leads if l.status == "meeting_booked"),
            "closed":        sum(1 for l in leads if l.status == "closed"),
            "total":         len(leads),
        }

        msgs_filter = (MessageLogDB.client_id == cu.client_id) if cu.client_id else (MessageLogDB.user_id == cu.id)
        all_msgs = db.query(MessageLogDB).filter(msgs_filter).all()
        emails   = [m for m in all_msgs if m.channel == "email"]
        wa_msgs  = [m for m in all_msgs if m.channel == "whatsapp"]

        def pct(n, d): return f"{round(n/d*100, 1)}%" if d else "0%"

        email_metrics = {
            "sent":      len(emails),
            "delivered": sum(1 for m in emails if m.delivered_at),
            "opened":    sum(1 for m in emails if m.opened_at),
            "clicked":   sum(1 for m in emails if m.clicked_at),
            "bounced":   sum(1 for m in emails if m.bounced),
            "open_rate":    pct(sum(1 for m in emails if m.opened_at), len(emails)),
            "bounce_rate":  pct(sum(1 for m in emails if m.bounced), len(emails)),
            "click_rate":   pct(sum(1 for m in emails if m.clicked_at), len(emails)),
        }

        wa_metrics = {
            "sent":      len(wa_msgs),
            "delivered": sum(1 for m in wa_msgs if m.delivered_at),
            "read":      sum(1 for m in wa_msgs if m.opened_at),
            "replied":   sum(1 for m in wa_msgs if m.status == "replied"),
            "read_rate": pct(sum(1 for m in wa_msgs if m.opened_at), len(wa_msgs)),
        }

        # Last 10 messages
        recent = sorted(all_msgs, key=lambda m: m.sent_at or now, reverse=True)[:10]
        last_messages = [
            {
                "id": m.id, "channel": m.channel, "lead_id": m.lead_id,
                "status": m.status, "approval_status": m.approval_status,
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                "opened": bool(m.opened_at), "bounced": m.bounced,
            }
            for m in recent
        ]

        # Cost this month
        cost_filter = (AIUsageDB.client_id == cu.client_id) if cu.client_id else None
        cost_inr = 0
        if cost_filter is not None:
            usage = db.query(AIUsageDB).filter(cost_filter, AIUsageDB.created_at >= month_start).all()
            cost_inr = round(sum(u.cost_inr or 0 for u in usage), 2)

                # Autonomous loop status (read-only, no evaluation triggered)
        autonomous_status = {"replan_count": 0, "last_replan_at": None, "is_underperforming": False}
        try:
            from ..models import AutonomousLoopDB
            loop_records = db.query(AutonomousLoopDB).filter(
                AutonomousLoopDB.client_id == cu.client_id
            ).order_by(AutonomousLoopDB.updated_at.desc()).all() if cu.client_id else []
            if loop_records:
                total_replans = sum(r.replan_count for r in loop_records)
                last_replan = max((r.last_replan_at for r in loop_records if r.last_replan_at), default=None)
                autonomous_status = {
                    "replan_count": total_replans,
                    "last_replan_at": last_replan.isoformat() if last_replan else None,
                    "is_underperforming": any(r.replan_count > 0 for r in loop_records),
                }
        except Exception:
            pass

        return {
            "funnel": funnel,
            "email_metrics": email_metrics,
            "wa_metrics": wa_metrics,
            "cost_inr_this_month": cost_inr,
            "last_messages": last_messages,
            "autonomous_loop_status": autonomous_status,
        }

    except Exception as e:
        logger.error({"event": "client_detail_error", "error": str(e)})
        raise HTTPException(500, str(e))


@router.get("/pipeline")
def pipeline_stages(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    """Lead counts per pipeline stage for kanban view."""
    try:
        leads = db.query(LeadDB).filter(LeadDB.client_id == cu.client_id).all() if cu.client_id else \
                db.query(LeadDB).filter(LeadDB.user_id == cu.id).all()

        stages = ["new", "enriched", "contacted", "replied", "meeting_booked", "closed", "skipped"]
        return {
            "stages": [
                {"stage": s, "count": sum(1 for l in leads if l.status == s),
                 "leads": [{"id": l.id, "name": l.name, "company": l.company,
                            "fit_score": l.fit_score} for l in leads if l.status == s][:10]}
                for s in stages
            ]
        }
    except Exception as e:
        logger.error({"event": "pipeline_error", "error": str(e)})
        raise HTTPException(500, str(e))


@router.get("/campaigns-performance")
def campaigns_performance(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    """Per-campaign open rate, reply rate, meetings booked."""
    try:
        from ..models import CampaignDB

        camps = db.query(CampaignDB).filter(
            (CampaignDB.client_id == cu.client_id) if cu.client_id else (CampaignDB.user_id == cu.id)
        ).all()

        results = []
        for c in camps:
            msgs = db.query(MessageLogDB).filter(MessageLogDB.campaign_id == c.id).all()
            total = len(msgs)
            opened  = sum(1 for m in msgs if m.opened_at)
            clicked = sum(1 for m in msgs if m.clicked_at)
            bounced = sum(1 for m in msgs if m.bounced)

            def pct(n, d): return f"{round(n/d*100,1)}%" if d else "0%"

            results.append({
                "id": c.id, "name": c.name,
                "channel": c.channel, "tone": c.tone,
                "status": c.status,
                "messages_sent": total,
                "open_rate": pct(opened, total),
                "click_rate": pct(clicked, total),
                "bounce_rate": pct(bounced, total),
            })

        return {"campaigns": results}
    except Exception as e:
        logger.error({"event": "campaigns_performance_error", "error": str(e)})
        raise HTTPException(500, str(e))

@router.get("/judge-performance/{client_id}")
def judge_performance(
    client_id: str,
    days: int = 30,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user)
):
    try:
        from ..services.llm_judge_service import get_judge_analytics
        return get_judge_analytics(client_id, days=days, db=db)
    except Exception as e:
        logger.error({"event": "judge_performance_error", "client_id": client_id, "error": str(e)})
        raise HTTPException(500, str(e))


@router.get("/judge-scores/{job_id}")
def judge_scores_for_job(
    job_id: str,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user)
):
    try:
        import json as _json
        from ..models import JudgeEvaluationDB
        records = db.query(JudgeEvaluationDB).filter(
            JudgeEvaluationDB.job_id == job_id
        ).all()
        result = []
        for r in records:
            result.append({
                "lead_id": r.lead_id,
                "channel": r.channel,
                "verdict": r.verdict,
                "weighted_score": r.weighted_score,
                "primary_weakness": r.primary_weakness,
                "was_rewritten": r.was_rewritten,
                "scores_by_dimension": {
                    "personalization": r.personalization_score,
                    "cultural_fit": r.cultural_fit_score,
                    "cta_strength": r.cta_strength_score,
                    "tone_match": r.tone_match_score,
                    "clarity": r.clarity_score,
                },
                "red_flags": _json.loads(r.red_flags_json or "[]"),
                "improvement_suggestion": r.improvement_suggestion,
            })
        return result
    except Exception as e:
        logger.error({"event": "judge_scores_error", "job_id": job_id, "error": str(e)})
        raise HTTPException(500, str(e))

@router.get("/ai-performance-timeline/{client_id}")
def ai_performance_timeline(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    import json as _json
    from datetime import timedelta
    try:
        from ..models import PromptVersionDB, AutonomousLoopDB
        now = datetime.utcnow()
        weeks = []
        for i in range(11, -1, -1):
            week_start = (now - timedelta(weeks=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            week_start -= timedelta(days=week_start.weekday())
            week_end = week_start + timedelta(days=6)
            msgs = db.query(MessageLogDB).filter(
                MessageLogDB.client_id == client_id,
                MessageLogDB.sent_at >= week_start,
                MessageLogDB.sent_at <= week_end,
            ).all()
            total = len(msgs)
            opened = sum(1 for m in msgs if m.opened_at)
            replied_leads = 0
            if msgs:
                lead_ids = list({m.lead_id for m in msgs if m.lead_id})
                from ..models import LeadDB
                replied_leads = db.query(LeadDB).filter(
                    LeadDB.id.in_(lead_ids),
                    LeadDB.status.in_(["replied", "meeting_booked"]),
                ).count()
            quality_logs = db.query(QualityLogDB).filter(
                QualityLogDB.client_id == client_id,
                QualityLogDB.created_at >= week_start,
                QualityLogDB.created_at <= week_end,
            ).all()
            q_total = len(quality_logs)
            q_passed = sum(1 for q in quality_logs if q.passed or q.passed_after_regen)
            active_version = db.query(PromptVersionDB).filter(
                PromptVersionDB.client_id == client_id,
                PromptVersionDB.created_at <= week_end,
            ).order_by(PromptVersionDB.created_at.desc()).first()
            had_replan = db.query(AutonomousLoopDB).filter(
                AutonomousLoopDB.client_id == client_id,
                AutonomousLoopDB.last_replan_at >= week_start,
                AutonomousLoopDB.last_replan_at <= week_end,
            ).count() > 0
            weeks.append({
                "week": f"{week_start.strftime('%b %-d')} - {week_end.strftime('%b %-d')}",
                "reply_rate": round(replied_leads / total * 100, 1) if total else 0.0,
                "open_rate": round(opened / total * 100, 1) if total else 0.0,
                "quality_pass_rate": round(q_passed / q_total * 100, 1) if q_total else 0.0,
                "messages_sent": total,
                "prompt_version": db.query(PromptVersionDB).filter(
                    PromptVersionDB.client_id == client_id,
                    PromptVersionDB.created_at <= week_end,
                ).count(),
                "had_replan": had_replan,
            })
        return weeks
    except Exception as e:
        logger.error({"event": "ai_performance_timeline_error", "error": str(e)})
        return []
