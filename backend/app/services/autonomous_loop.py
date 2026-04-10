import json
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger("autonomous_loop")

MIN_REPLY_RATE = 0.05
MIN_OPEN_RATE = 0.15
MAX_BOUNCE_RATE = 0.10
MAX_REPLAN_ATTEMPTS = 3
REPLAN_COOLDOWN_HOURS = 24
MIN_MESSAGES_BEFORE_EVAL = 15


def evaluate_campaign_performance(client_id: str, campaign_id: str, db) -> dict:
    try:
        from ..models import MessageLogDB, QualityLogDB, LeadDB

        cutoff = datetime.utcnow() - timedelta(days=14)
        logs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.campaign_id == campaign_id,
            MessageLogDB.sent_at >= cutoff,
        ).all()

        if len(logs) < MIN_MESSAGES_BEFORE_EVAL:
            return None

        total = len(logs)
        emails = [l for l in logs if l.channel == "email"]
        total_emails = len(emails)

        lead_ids = list(set(l.lead_id for l in logs if l.lead_id))
        replied_leads = db.query(LeadDB).filter(
            LeadDB.id.in_(lead_ids), LeadDB.status == "replied"
        ).count() if lead_ids else 0

        reply_rate = round(replied_leads / total, 4) if total else 0.0
        open_rate = round(sum(1 for l in emails if l.opened_at) / total_emails, 4) if total_emails else 0.0
        bounce_rate = round(sum(1 for l in emails if l.bounced) / total_emails, 4) if total_emails else 0.0

        ql = db.query(QualityLogDB).filter(
            QualityLogDB.client_id == client_id,
            QualityLogDB.created_at >= cutoff,
        ).all()
        qpass = sum(1 for q in ql if q.passed or q.passed_after_regen)
        quality_pass_rate = round(qpass / len(ql), 4) if ql else 1.0

        failed = []
        if reply_rate < MIN_REPLY_RATE:
            failed.append("reply_rate")
        if open_rate < MIN_OPEN_RATE:
            failed.append("open_rate")
        if bounce_rate > MAX_BOUNCE_RATE:
            failed.append("bounce_rate")

        return {
            "reply_rate": reply_rate,
            "open_rate": open_rate,
            "bounce_rate": bounce_rate,
            "quality_pass_rate": quality_pass_rate,
            "total_messages": total,
            "is_underperforming": len(failed) > 0,
            "failed_thresholds": failed,
        }
    except Exception as e:
        logger.error(f"evaluate_campaign_performance error: {e}")
        return None


def check_replan_eligibility(client_id: str, campaign_id: str, db) -> bool:
    try:
        from ..models import AutonomousLoopDB

        record = db.query(AutonomousLoopDB).filter(
            AutonomousLoopDB.client_id == client_id,
            AutonomousLoopDB.campaign_id == campaign_id,
        ).first()

        if not record:
            return True
        if record.replan_count >= MAX_REPLAN_ATTEMPTS:
            logger.warning(f"LOOP: max replan attempts reached client={client_id} campaign={campaign_id}")
            return False
        if record.last_replan_at:
            hours_since = (datetime.utcnow() - record.last_replan_at).total_seconds() / 3600
            if hours_since < REPLAN_COOLDOWN_HOURS:
                logger.info(f"LOOP: cooldown active, {hours_since:.1f}h since last replan")
                return False
        return True
    except Exception as e:
        logger.error(f"check_replan_eligibility error: {e}")
        return False


def generate_new_strategy(client_id: str, campaign_id: str, performance_data: dict,
                           failed_thresholds: list, current_strategy: str, db) -> dict:
    try:
        from .groq_service import generate_ai
        from ..models import AgentReflectionDB, ReactTraceDB, PromptVersionDB

        reflections = db.query(AgentReflectionDB).filter(
            AgentReflectionDB.client_id == client_id
        ).order_by(AgentReflectionDB.created_at.desc()).limit(3).all()

        reflection_lessons = []
        for r in reflections:
            try:
                lessons = json.loads(r.lessons_json or "[]")
                reflection_lessons.extend([l.get("fix", "") for l in lessons if l.get("fix")])
            except Exception:
                pass

        react_traces = db.query(ReactTraceDB).filter(
            ReactTraceDB.client_id == client_id,
            ReactTraceDB.trace_type == "lead_evaluation",
        ).order_by(ReactTraceDB.created_at.desc()).limit(3).all()

        react_red_flags = []
        for t in react_traces:
            try:
                thoughts = json.loads(t.thought_trace_json or "[]")
                react_red_flags.extend(thoughts[-1:])
            except Exception:
                pass

        active_prompt = db.query(PromptVersionDB).filter(
            PromptVersionDB.client_id == client_id,
            PromptVersionDB.is_active == True,
        ).order_by(PromptVersionDB.created_at.desc()).first()

        prompt = f"""You are an autonomous campaign strategist.
This B2B outreach campaign is underperforming.
Generate a new strategy to fix it.

Current performance:
- Reply rate: {round(performance_data.get('reply_rate', 0) * 100, 1)}% (target: 5%+)
- Open rate: {round(performance_data.get('open_rate', 0) * 100, 1)}% (target: 15%+)
- Bounce rate: {round(performance_data.get('bounce_rate', 0) * 100, 1)}% (target: <10%)

Failed thresholds: {failed_thresholds}

Past reflections: {reflection_lessons}
Recent ReAct red flags: {react_red_flags}
Current approach: {current_strategy}

Generate a new strategy. Be specific and actionable.

Return ONLY this JSON:
{{
  "strategy_changes": [
    {{"what": "str", "why": "str", "how": "str"}}
  ],
  "new_tone": "professional",
  "new_channel_priority": "email",
  "message_length_adjustment": "shorter",
  "new_targeting_criteria": "str",
  "expected_improvement": "str",
  "confidence": 0.8
}}"""

        result = generate_ai(prompt, task_type="autonomous_strategy", client_id=client_id)
        text = result["text"]
        if "```" in text:
            text = text.split("```")[1]
            text = text[4:] if text.startswith("json") else text
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"generate_new_strategy error: {e}")
        return None


def apply_new_strategy(client_id: str, campaign_id: str, new_strategy: dict, db) -> bool:
    try:
        from ..models import CampaignDB, ClientDB, AutonomousLoopDB
        from .opro_service import save_optimized_prompt

        campaign = db.query(CampaignDB).filter(CampaignDB.id == campaign_id).first()
        if campaign and new_strategy.get("new_tone"):
            campaign.tone = new_strategy["new_tone"]

        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if client and new_strategy.get("new_channel_priority"):
            tone_cfg = dict(client.tone_config or {})
            tone_cfg["preferred_channel"] = new_strategy["new_channel_priority"]
            client.tone_config = tone_cfg

        if new_strategy.get("new_targeting_criteria"):
            strategy_note = f"\nAutonomous strategy update: {new_strategy['new_targeting_criteria']}"
            save_optimized_prompt(
                client_id=client_id,
                template_name="autonomous_override",
                new_prompt=strategy_note,
                old_reply_rate=0.0,
                db=db,
            )

        record = db.query(AutonomousLoopDB).filter(
            AutonomousLoopDB.client_id == client_id,
            AutonomousLoopDB.campaign_id == campaign_id,
        ).first()
        if record:
            record.last_strategy_json = json.dumps(new_strategy)
            record.updated_at = datetime.utcnow()

        db.commit()
        logger.info(f"LOOP: strategy applied client={client_id} campaign={campaign_id}")
        return True
    except Exception as e:
        logger.error(f"apply_new_strategy error: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return False


def trigger_replan(client_id: str, campaign_id: str, performance_data: dict, db) -> dict:
    try:
        if not check_replan_eligibility(client_id, campaign_id, db):
            from ..models import AutonomousLoopDB
            record = db.query(AutonomousLoopDB).filter(
                AutonomousLoopDB.client_id == client_id,
                AutonomousLoopDB.campaign_id == campaign_id,
            ).first()
            reason = "max attempts reached" if (record and record.replan_count >= MAX_REPLAN_ATTEMPTS) else "cooldown active"
            return {"replanned": False, "reason": reason}

        current_strategy = f"reply_rate={performance_data.get('reply_rate')}, open_rate={performance_data.get('open_rate')}"
        failed = performance_data.get("failed_thresholds", [])

        new_strategy = generate_new_strategy(client_id, campaign_id, performance_data, failed, current_strategy, db)

        if new_strategy is None:
            return {"replanned": False, "reason": "strategy generation failed"}

        if new_strategy.get("confidence", 0) < 0.6:
            return {"replanned": False, "reason": f"low confidence strategy: {new_strategy.get('confidence')}"}

        applied = apply_new_strategy(client_id, campaign_id, new_strategy, db)
        if not applied:
            return {"replanned": False, "reason": "strategy application failed"}

        from ..models import AutonomousLoopDB
        record = db.query(AutonomousLoopDB).filter(
            AutonomousLoopDB.client_id == client_id,
            AutonomousLoopDB.campaign_id == campaign_id,
        ).first()

        if not record:
            record = AutonomousLoopDB(
                client_id=client_id,
                campaign_id=campaign_id,
                replan_count=0,
            )
            db.add(record)

        record.replan_count += 1
        record.last_replan_at = datetime.utcnow()
        record.last_performance_json = json.dumps(performance_data)
        record.last_strategy_json = json.dumps(new_strategy)
        record.updated_at = datetime.utcnow()
        db.commit()

        logger.info({
            "event": "autonomous_replan",
            "client_id": client_id,
            "campaign_id": campaign_id,
            "replan_count": record.replan_count,
            "failed_thresholds": failed,
            "expected_improvement": new_strategy.get("expected_improvement"),
        })

        return {
            "replanned": True,
            "replan_count": record.replan_count,
            "changes_made": [c.get("what") for c in new_strategy.get("strategy_changes", [])],
            "expected_improvement": new_strategy.get("expected_improvement", ""),
        }
    except Exception as e:
        logger.error(f"trigger_replan error: {e}")
        return {"replanned": False, "reason": str(e)}


def run_autonomous_evaluation(client_id: str, db) -> list:
    results = []
    try:
        from ..models import CampaignDB

        campaigns = db.query(CampaignDB).filter(
            CampaignDB.client_id == client_id,
            CampaignDB.status == "active",
        ).all()

        for camp in campaigns:
            try:
                perf = evaluate_campaign_performance(client_id, camp.id, db)
                if perf is None:
                    results.append({"campaign_id": camp.id, "status": "insufficient_data"})
                    continue

                entry = {"campaign_id": camp.id, "performance": perf, "replan_result": None}

                if perf.get("is_underperforming"):
                    replan = trigger_replan(client_id, camp.id, perf, db)
                    entry["replan_result"] = replan
                    logger.info(f"LOOP: campaign={camp.id} underperforming, replan={replan}")
                else:
                    logger.info(f"LOOP: campaign={camp.id} performing OK")

                results.append(entry)
            except Exception as e:
                logger.error(f"LOOP: evaluation error campaign={camp.id}: {e}")
                results.append({"campaign_id": camp.id, "status": "error", "error": str(e)})

    except Exception as e:
        logger.error(f"run_autonomous_evaluation error: {e}")

    return results
