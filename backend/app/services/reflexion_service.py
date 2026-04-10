import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("reflexion_service")


def analyze_job_failures(job_id: str, client_id: str, db) -> dict:
    try:
        from ..models import AgentJobItemDB, QualityLogDB, MessageLogDB, LeadDB

        rejected = db.query(AgentJobItemDB).filter(
            AgentJobItemDB.job_id == job_id,
            AgentJobItemDB.status == "rejected"
        ).all()

        quality_failures = db.query(QualityLogDB).filter(
            QualityLogDB.job_id == job_id,
            QualityLogDB.failed_permanently == True
        ).all()

        job_lead_ids = [r.lead_id for r in db.query(AgentJobItemDB).filter(
            AgentJobItemDB.job_id == job_id
        ).all()]

        bounced_logs = db.query(MessageLogDB).filter(
            MessageLogDB.lead_id.in_(job_lead_ids),
            MessageLogDB.bounced == True
        ).all() if job_lead_ids else []

        low_score_leads = db.query(LeadDB).filter(
            LeadDB.id.in_(job_lead_ids),
            LeadDB.fit_score < 5
        ).all() if job_lead_ids else []

        summary = {
            "rejected_count": len(rejected),
            "quality_failures": [
                {"lead_id": q.lead_id, "issues_json": q.issues_json}
                for q in quality_failures
            ],
            "bounce_count": len(bounced_logs),
            "low_score_leads": [l.id for l in low_score_leads],
        }

        if (summary["rejected_count"] == 0 and not summary["quality_failures"]
                and summary["bounce_count"] == 0 and not summary["low_score_leads"]):
            return {}

        return summary
    except Exception as e:
        logger.error(f"analyze_job_failures error: {e}")
        return {}


def generate_reflection(failure_summary: dict, campaign_context: dict, client_id: str):
    try:
        if (failure_summary.get("rejected_count", 0) <= 2
                and len(failure_summary.get("quality_failures", [])) <= 3):
            return None

        from .groq_service import generate_ai

        industry = campaign_context.get("industry", "general")
        tone = campaign_context.get("tone", "professional")

        prompt = f"""You are an AI agent that just completed a B2B outreach job.
Analyze these failures and generate 3 specific actionable lessons to improve the next run.

Campaign industry: {industry}
Campaign tone: {tone}
Failures: {json.dumps(failure_summary)}

Return ONLY a JSON object:
{{
  "lessons": [
    {{"issue": "str", "root_cause": "str", "fix": "str"}},
    {{"issue": "str", "root_cause": "str", "fix": "str"}},
    {{"issue": "str", "root_cause": "str", "fix": "str"}}
  ],
  "avoid_next_run": ["str", "str", "str"],
  "confidence_score": 0.0
}}"""

        result = generate_ai(prompt, task_type="reflexion", client_id=client_id)
        text = result["text"]
        if "```" in text:
            text = text.split("```")[1]
            text = text[4:] if text.startswith("json") else text
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"generate_reflection error: {e}")
        return None


def save_reflection(client_id: str, job_id: str, reflection_data: dict, db, industry: str = "") -> str:
    try:
        from ..models import AgentReflectionDB

        record = AgentReflectionDB(
            client_id=client_id,
            job_id=job_id,
            industry=industry,
            lessons_json=json.dumps(reflection_data.get("lessons", [])),
            avoid_patterns_json=json.dumps(reflection_data.get("avoid_next_run", [])),
            confidence_score=float(reflection_data.get("confidence_score", 0.0)),
            was_applied=False,
        )
        db.add(record)
        db.commit()
        logger.info(f"REFLEXION: saved reflection id={record.id} client={client_id} job={job_id}")
        return record.id
    except Exception as e:
        db.rollback()
        logger.error(f"save_reflection error: {e}")
        return ""


def get_active_reflections(client_id: str, industry: str, db) -> list:
    try:
        from ..models import AgentReflectionDB

        cutoff = datetime.utcnow() - timedelta(days=30)
        records = (
            db.query(AgentReflectionDB)
            .filter(
                AgentReflectionDB.client_id == client_id,
                AgentReflectionDB.industry == industry,
                AgentReflectionDB.created_at >= cutoff,
                AgentReflectionDB.confidence_score >= 0.6,
            )
            .order_by(AgentReflectionDB.created_at.desc())
            .limit(3)
            .all()
        )

        patterns = []
        for r in records:
            try:
                patterns.extend(json.loads(r.avoid_patterns_json or "[]"))
            except Exception:
                pass
        return patterns
    except Exception as e:
        logger.error(f"get_active_reflections error: {e}")
        return []


def build_reflection_context(client_id: str, industry: str, db) -> str:
    try:
        patterns = get_active_reflections(client_id, industry, db)
        if not patterns:
            return ""
        lines = "\n".join(f"- {p}" for p in patterns)
        return f"AVOID these patterns from previous failed runs:\n{lines}"
    except Exception as e:
        logger.error(f"build_reflection_context error: {e}")
        return ""
