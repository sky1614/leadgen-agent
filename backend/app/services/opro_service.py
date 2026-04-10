import logging
from datetime import datetime, timedelta

logger = logging.getLogger("opro_service")


def get_reply_rate_by_template(client_id: str, db):
    try:
        from ..models import MessageLogDB, LeadDB, CampaignDB
        cutoff = datetime.utcnow() - timedelta(days=30)

        logs = (
            db.query(MessageLogDB)
            .filter(
                MessageLogDB.client_id == client_id,
                MessageLogDB.sent_at >= cutoff,
            )
            .all()
        )

        campaign_map = {}
        for log in logs:
            cid = log.campaign_id
            if cid not in campaign_map:
                campaign_map[cid] = {"total": 0, "replied": 0, "template_used": "generic"}
            campaign_map[cid]["total"] += 1

        lead_ids = list({log.lead_id for log in logs})
        replied_leads = (
            db.query(LeadDB.id)
            .filter(LeadDB.id.in_(lead_ids), LeadDB.status == "replied")
            .all()
        )
        replied_set = {r.id for r in replied_leads}

        for log in logs:
            if log.lead_id in replied_set:
                campaign_map[log.campaign_id]["replied"] += 1

        campaigns = (
            db.query(CampaignDB)
            .filter(CampaignDB.id.in_(list(campaign_map.keys())))
            .all()
        )
        camp_industry = {c.id: c.target_industry or "generic" for c in campaigns}

        results = []
        for cid, data in campaign_map.items():
            if data["total"] < 10:
                continue
            reply_rate = round(data["replied"] / data["total"], 4)
            results.append({
                "campaign_id": cid,
                "template_used": camp_industry.get(cid, "generic"),
                "reply_rate": reply_rate,
                "message_count": data["total"],
            })

        return results
    except Exception as e:
        logger.error(f"get_reply_rate_by_template error: {e}")
        return []


def optimize_prompt(template_name: str, current_prompt: str, performance_data: dict, client_id: str) -> str:
    try:
        from .groq_service import generate_ai
        from ..models import MessageLogDB
        from ..database import SessionLocal

        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(days=30)
            logs = (
                db.query(MessageLogDB)
                .filter(
                    MessageLogDB.client_id == client_id,
                    MessageLogDB.sent_at >= cutoff,
                )
                .order_by(MessageLogDB.sent_at.desc())
                .all()
            )
        finally:
            db.close()

        replied_ids = {l.lead_id for l in logs if l.status == "sent"}
        top_msgs = [l.message for l in logs if l.lead_id in replied_ids][:3]
        bottom_msgs = [l.message for l in logs if l.lead_id not in replied_ids][:3]

        reply_rate_pct = round(performance_data.get("reply_rate", 0) * 100, 1)

        meta_prompt = f"""You are an expert prompt engineer. Below are outreach message prompts and their reply rates. Rewrite the system_prompt to improve reply rate. Keep industry terms, forbidden phrases list, and max_message_length unchanged. Only improve the instruction quality, tone guidance, and persuasion strategy.

Current prompt: {current_prompt}
Current reply rate: {reply_rate_pct}%
Top performing message examples: {top_msgs}
Worst performing message examples: {bottom_msgs}

Return ONLY the improved system_prompt text, nothing else."""

        result = generate_ai(meta_prompt, task_type="opro", client_id=client_id)
        return result["text"]
    except Exception as e:
        logger.error(f"optimize_prompt error: {e}")
        return current_prompt


def save_optimized_prompt(client_id: str, template_name: str, new_prompt: str, old_reply_rate: float, db):
    try:
        from ..models import PromptVersionDB

        db.query(PromptVersionDB).filter(
            PromptVersionDB.client_id == client_id,
            PromptVersionDB.template_name == template_name,
            PromptVersionDB.is_active == True,
        ).update({"is_active": False})

        new_version = PromptVersionDB(
            client_id=client_id,
            template_name=template_name,
            prompt_text=new_prompt,
            reply_rate_at_creation=old_reply_rate,
            is_active=True,
        )
        db.add(new_version)
        db.commit()
        logger.info(f"OPRO: saved optimized prompt for client={client_id} template={template_name}")
        return new_version
    except Exception as e:
        db.rollback()
        logger.error(f"save_optimized_prompt error: {e}")
        return None


def run_opro_cycle(client_id: str, db) -> dict:
    optimized = []
    skipped = []
    try:
        rates = get_reply_rate_by_template(client_id, db)

        for entry in rates:
            template_name = entry["template_used"]
            reply_rate = entry["reply_rate"]

            if reply_rate >= 0.10:
                skipped.append({"campaign_id": entry["campaign_id"], "reply_rate": reply_rate, "reason": "above threshold"})
                continue

            try:
                from .groq_service import _get_template
                template = _get_template(template_name)
                current_prompt = template.system_prompt

                new_prompt = optimize_prompt(template_name, current_prompt, entry, client_id)
                saved = save_optimized_prompt(client_id, template_name, new_prompt, reply_rate, db)

                logger.info(f"OPRO: optimized template={template_name} old_rate={reply_rate} client={client_id}")
                optimized.append({
                    "campaign_id": entry["campaign_id"],
                    "template_name": template_name,
                    "old_reply_rate": reply_rate,
                    "version_id": saved.id if saved else None,
                })
            except Exception as e:
                logger.error(f"OPRO cycle inner error template={template_name}: {e}")
                skipped.append({"campaign_id": entry["campaign_id"], "reason": str(e)})

    except Exception as e:
        logger.error(f"run_opro_cycle error: {e}")

    return {
        "optimized_count": len(optimized),
        "skipped_count": len(skipped),
        "details": {"optimized": optimized, "skipped": skipped},
    }
