from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import AgentJobDB, AgentJobItemDB, CampaignDB, ConversationDB, LeadDB, MessageLogDB, UserDB
from ..schemas import AgentRunReq
from ..services.agent_service import run_agent_job

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run")
def agent_run(req: AgentRunReq, background_tasks: BackgroundTasks,
              db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    job = AgentJobDB(user_id=cu.id, client_id=cu.client_id, campaign_id=req.campaign_id, industry=req.industry, source_url=req.source_url or "")
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(run_agent_job, job.id, cu.id, req)
    return {"success": True, "job_id": job.id, "message": "Agent is running. Poll /agent/jobs/{job_id} for status."}


@router.post("/run-multi")
def agent_run_multi(req: AgentRunReq, db: Session = Depends(get_db),
                    cu: UserDB = Depends(get_current_user)):
    from ..services.agent_service import run_multi_agent_job_entry
    job_id = run_multi_agent_job_entry(cu.id, req, db)
    return {"success": True, "job_id": job_id, "mode": "multi_agent",
            "message": "Multi-agent pipeline launched. Poll /agent/jobs/{job_id}/pipeline-status"}


@router.get("/jobs/{job_id}/pipeline-status")
def get_pipeline_status(job_id: str, db: Session = Depends(get_db),
                        cu: UserDB = Depends(get_current_user)):
    from ..services.redis_service import get_queue_size
    job = db.query(AgentJobDB).filter(
        AgentJobDB.id == job_id, AgentJobDB.user_id == cu.id
    ).first()
    if not job:
        raise HTTPException(404, "Job not found")

    elapsed = 0
    if job.created_at:
        elapsed = int((datetime.utcnow() - job.created_at).total_seconds())

    return {
        "job_id": job_id,
        "overall_status": job.status,
        "pipeline": {
            "prospector": {
                "status": job.prospector_status or "not_started",
                "leads_found": job.leads_found or 0,
            },
            "scorer": {
                "status": job.scorer_status or "not_started",
                "leads_scored": job.leads_scored or 0,
                "leads_skipped": (job.leads_found or 0) - (job.leads_scored or 0),
            },
            "writer": {
                "status": job.writer_status or "not_started",
                "leads_written": job.leads_written or 0,
                "judge_rewrites": 0,
            },
            "delivery": {
                "status": job.delivery_status or "not_started",
                "auto_approved": job.auto_approved_count or 0,
                "pending_approval": job.pending_approval_count or 0,
            },
        },
        "redis_queue_sizes": {
            "scorer_queue": get_queue_size(f"scorer_queue:{job_id}"),
            "writer_queue": get_queue_size(f"writer_queue:{job_id}"),
            "delivery_queue": get_queue_size(f"delivery_queue:{job_id}"),
        },
        "elapsed_seconds": elapsed,
    }

@router.get("/jobs")
def get_agent_jobs(db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    jobs = db.query(AgentJobDB).filter(AgentJobDB.user_id == cu.id).order_by(AgentJobDB.created_at.desc()).all()
    return {"jobs": [{"id": j.id, "industry": j.industry, "status": j.status,
                      "total_leads": j.total_leads, "created_at": str(j.created_at)} for j in jobs]}


@router.get("/jobs/{job_id}")
def get_agent_job(job_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id, AgentJobDB.user_id == cu.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    items = db.query(AgentJobItemDB).filter(AgentJobItemDB.job_id == job_id).all()
    return {
        "job": {"id": job.id, "industry": job.industry, "status": job.status,
                "total_leads": job.total_leads, "created_at": str(job.created_at)},
        "items": [{"id": i.id, "lead_id": i.lead_id, "lead_name": i.lead_name,
                   "lead_company": i.lead_company, "lead_email": i.lead_email,
                   "lead_whatsapp": i.lead_whatsapp, "fit_score": i.fit_score,
                   "email_message": i.email_message, "whatsapp_message": i.whatsapp_message,
                   "status": i.status} for i in items]
    }


@router.post("/jobs/{job_id}/approve")
def approve_agent_job(job_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id, AgentJobDB.user_id == cu.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    items = db.query(AgentJobItemDB).filter(AgentJobItemDB.job_id == job_id, AgentJobItemDB.status == "pending").all()
    camp = db.query(CampaignDB).filter(CampaignDB.id == job.campaign_id).first()
    for item in items:
        lead = db.query(LeadDB).filter(LeadDB.id == item.lead_id).first()
        if not lead:
            continue
        db.add(MessageLogDB(user_id=cu.id, lead_id=lead.id, campaign_id=job.campaign_id,
                            channel="email", message=item.email_message))
        db.add(ConversationDB(lead_id=lead.id, role="assistant", content=item.email_message))
        lead.status = "contacted"
        lead.last_contacted = datetime.utcnow()
        lead.follow_up_day = 0
        item.status = "approved"
        if camp:
            camp.sent_count += 1
    job.status = "approved"
    db.commit()
    return {"success": True, "approved": len(items)}


@router.delete("/jobs/{job_id}/items/{item_id}")
def reject_agent_item(job_id: str, item_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    item = db.query(AgentJobItemDB).filter(AgentJobItemDB.id == item_id, AgentJobItemDB.job_id == job_id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    item.status = "rejected"
    db.commit()
    return {"success": True}

@router.get("/loop/status/{client_id}")
def loop_status(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    try:
        from ..models import AutonomousLoopDB
        records = db.query(AutonomousLoopDB).filter(
            AutonomousLoopDB.client_id == client_id
        ).order_by(AutonomousLoopDB.updated_at.desc()).all()
        return {
            "client_id": client_id,
            "campaigns": [
                {
                    "campaign_id": r.campaign_id,
                    "replan_count": r.replan_count,
                    "last_replan_at": r.last_replan_at.isoformat() if r.last_replan_at else None,
                    "last_strategy": r.last_strategy_json,
                }
                for r in records
            ]
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/loop/evaluate/{client_id}")
def loop_evaluate(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    if cu.role != "admin":
        raise HTTPException(403, "Admin only")
    try:
        from ..services.autonomous_loop import run_autonomous_evaluation
        results = run_autonomous_evaluation(client_id, db)
        return {"client_id": client_id, "results": results}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/loop/history/{client_id}")
def loop_history(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    try:
        from ..models import AutonomousLoopDB
        import json as _json
        records = db.query(AutonomousLoopDB).filter(
            AutonomousLoopDB.client_id == client_id
        ).order_by(AutonomousLoopDB.updated_at.desc()).limit(10).all()
        return {
            "history": [
                {
                    "id": r.id,
                    "campaign_id": r.campaign_id,
                    "replan_count": r.replan_count,
                    "last_replan_at": r.last_replan_at.isoformat() if r.last_replan_at else None,
                    "last_performance": _json.loads(r.last_performance_json or "{}"),
                    "last_strategy": _json.loads(r.last_strategy_json or "{}"),
                    "total_improvements": r.total_improvements,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in records
            ]
        }
    except Exception as e:
        raise HTTPException(500, str(e))



@router.get("/intelligence/summary/{client_id}")
def intelligence_summary(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    import json as _json
    result = {
        "opro": {"total_optimizations": 0, "latest_optimization_date": None, "avg_reply_rate_before": 0.0, "avg_reply_rate_after": 0.0, "active_prompt_version": 0, "improvement_pct": 0.0},
        "rag": {"total_messages_indexed": 0, "avg_similarity_score": 0.0, "rag_used_count": 0, "rag_fallback_count": 0},
        "reflexion": {"total_reflections": 0, "lessons_learned": 0, "patterns_avoided": 0, "latest_reflection_date": None},
        "memory": {"episodic_records": 0, "semantic_patterns": 0, "best_channel": None, "best_send_day": None},
        "autonomous_loop": {"total_replans": 0, "campaigns_improved": 0, "last_replan_date": None, "current_status": "idle"},
    }
    try:
        from ..models import PromptVersionDB, AgentReflectionDB, EpisodicMemoryDB, SemanticMemoryDB, AutonomousLoopDB
        versions = db.query(PromptVersionDB).filter(PromptVersionDB.client_id == client_id).order_by(PromptVersionDB.created_at.asc()).all()
        if versions:
            active = next((v for v in reversed(versions) if v.is_active), versions[-1])
            rates = [v.reply_rate_at_creation for v in versions if v.reply_rate_at_creation]
            result["opro"] = {
                "total_optimizations": len(versions),
                "latest_optimization_date": versions[-1].created_at.isoformat() if versions[-1].created_at else None,
                "avg_reply_rate_before": round(rates[0] if rates else 0.0, 3),
                "avg_reply_rate_after": round(rates[-1] if rates else 0.0, 3),
                "active_prompt_version": len(versions),
                "improvement_pct": round(((rates[-1] - rates[0]) / rates[0] * 100) if len(rates) >= 2 and rates[0] else 0.0, 1),
            }
    except Exception:
        pass
    try:
        from ..models import AgentReflectionDB
        refs = db.query(AgentReflectionDB).filter(AgentReflectionDB.client_id == client_id).all()
        total_lessons = sum(len(_json.loads(r.lessons_json or "[]")) for r in refs)
        total_patterns = sum(len(_json.loads(r.avoid_patterns_json or "[]")) for r in refs)
        latest = max((r.created_at for r in refs if r.created_at), default=None)
        result["reflexion"] = {
            "total_reflections": len(refs),
            "lessons_learned": total_lessons,
            "patterns_avoided": total_patterns,
            "latest_reflection_date": latest.isoformat() if latest else None,
        }
    except Exception:
        pass
    try:
        from ..models import EpisodicMemoryDB, SemanticMemoryDB
        ep_count = db.query(EpisodicMemoryDB).filter(EpisodicMemoryDB.client_id == client_id).count()
        sem_records = db.query(SemanticMemoryDB).filter(SemanticMemoryDB.client_id == client_id).all()
        best_channel_rec = max(sem_records, key=lambda r: r.success_rate, default=None) if sem_records else None
        day_recs = [r for r in sem_records if r.pattern_type == "best_day"]
        best_day_rec = max(day_recs, key=lambda r: r.success_rate, default=None) if day_recs else None
        result["memory"] = {
            "episodic_records": ep_count,
            "semantic_patterns": len(sem_records),
            "best_channel": best_channel_rec.channel if best_channel_rec else None,
            "best_send_day": best_day_rec.pattern_value if best_day_rec else None,
        }
    except Exception:
        pass
    try:
        from ..models import AutonomousLoopDB
        loops = db.query(AutonomousLoopDB).filter(AutonomousLoopDB.client_id == client_id).all()
        total_replans = sum(r.replan_count for r in loops)
        improved = sum(1 for r in loops if r.total_improvements > 0)
        last_date = max((r.last_replan_at for r in loops if r.last_replan_at), default=None)
        result["autonomous_loop"] = {
            "total_replans": total_replans,
            "campaigns_improved": improved,
            "last_replan_date": last_date.isoformat() if last_date else None,
            "current_status": "active" if total_replans > 0 else "idle",
        }
    except Exception:
        pass
    return result


@router.get("/intelligence/prompt-history/{client_id}")
def intelligence_prompt_history(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    try:
        from ..models import PromptVersionDB
        versions = db.query(PromptVersionDB).filter(PromptVersionDB.client_id == client_id).order_by(PromptVersionDB.created_at.asc()).limit(10).all()
        result = []
        for i, v in enumerate(versions):
            prev_rate = versions[i - 1].reply_rate_at_creation if i > 0 else None
            improvement = None
            if prev_rate is not None and prev_rate > 0:
                improvement = round((v.reply_rate_at_creation - prev_rate) / prev_rate * 100, 1)
            result.append({
                "version": i + 1,
                "template_name": v.template_name,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "reply_rate_at_creation": v.reply_rate_at_creation,
                "is_active": v.is_active,
                "prompt_preview": (v.prompt_text or "")[:150],
                "improvement_vs_previous": improvement,
            })
        return {"versions": list(reversed(result))}
    except Exception:
        return {"versions": []}


@router.get("/intelligence/lessons/{client_id}")
def intelligence_lessons(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    import json as _json
    try:
        from ..models import AgentReflectionDB
        refs = db.query(AgentReflectionDB).filter(AgentReflectionDB.client_id == client_id).order_by(AgentReflectionDB.created_at.desc()).limit(10).all()
        result = []
        for r in refs:
            try:
                lessons_raw = _json.loads(r.lessons_json or "[]")
                lessons = []
                for item in lessons_raw:
                    if isinstance(item, dict):
                        lessons.append({"issue": item.get("issue", ""), "root_cause": item.get("root_cause", ""), "fix": item.get("fix", "")})
                    else:
                        lessons.append({"issue": str(item), "root_cause": "", "fix": ""})
                patterns = _json.loads(r.avoid_patterns_json or "[]")
            except Exception:
                lessons, patterns = [], []
            result.append({
                "date": r.created_at.isoformat() if r.created_at else None,
                "job_id": r.job_id,
                "lessons": lessons,
                "patterns_to_avoid": patterns,
                "was_applied": r.was_applied,
                "confidence": r.confidence_score,
            })
        return {"lessons": result}
    except Exception:
        return {"lessons": []}


@router.get("/intelligence/react-decisions/{client_id}")
def intelligence_react_decisions(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    import json as _json
    try:
        from ..models import ReactTraceDB
        traces = db.query(ReactTraceDB).filter(ReactTraceDB.client_id == client_id).order_by(ReactTraceDB.created_at.desc()).limit(20).all()
        result = []
        for t in traces:
            try:
                thoughts = _json.loads(t.thought_trace_json or "[]")
                first_thought = thoughts[0] if thoughts else ""
                red_flags = [th for th in thoughts if isinstance(th, str) and ("skip" in th.lower() or "flag" in th.lower() or "risk" in th.lower())]
            except Exception:
                first_thought, red_flags = "", []
            result.append({
                "date": t.created_at.isoformat() if t.created_at else None,
                "lead_id": t.lead_id,
                "decision": t.decision or "",
                "confidence": t.confidence or 0.0,
                "thought_summary": str(first_thought)[:200] if first_thought else "",
                "recommended_channel": t.recommended_action or "",
                "red_flags": red_flags,
            })
        return {"decisions": result}
    except Exception:
        return {"decisions": []}

@router.post("/rag/index/{client_id}")
def rag_index(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    if cu.role != "admin":
        raise HTTPException(403, "Admin only")
    try:
        from ..services.rag_service import index_historical_messages
        result = index_historical_messages(client_id, db)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))



@router.get("/ab-tests/{client_id}")
def get_ab_tests(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    try:
        from ..models import ABTestDB
        from ..services.ab_testing_service import calculate_significance
        tests = db.query(ABTestDB).filter(
            ABTestDB.client_id == client_id
        ).order_by(ABTestDB.created_at.desc()).limit(10).all()
        result = []
        for t in tests:
            ctrl_sent = t.control_messages_sent or 0
            trt_sent = t.treatment_messages_sent or 0
            ctrl_rate = round((t.control_replies or 0) / ctrl_sent * 100, 1) if ctrl_sent else 0.0
            trt_rate = round((t.treatment_replies or 0) / trt_sent * 100, 1) if trt_sent else 0.0
            conf = calculate_significance(
                t.control_replies or 0, ctrl_sent,
                t.treatment_replies or 0, trt_sent
            )
            days = (datetime.utcnow() - t.started_at).days if t.started_at else 0
            result.append({
                "id": t.id,
                "template_name": t.template_name,
                "status": t.status,
                "winner": t.winner,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                


@router.get("/ab-tests/{client_id}")
def get_ab_tests(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    try:
        from ..models import ABTestDB
        from ..services.ab_testing_service import calculate_significance
        tests = db.query(ABTestDB).filter(ABTestDB.client_id == client_id)\
            .order_by(ABTestDB.created_at.desc()).limit(10).all()
        result = []
        for t in tests:
            ctrl_sent = t.control_messages_sent or 0
            trt_sent = t.treatment_messages_sent or 0
            ctrl_rate = round((t.control_replies or 0) / ctrl_sent, 4) if ctrl_sent else 0.0
            trt_rate = round((t.treatment_replies or 0) / trt_sent, 4) if trt_sent else 0.0
            confidence = calculate_significance(
                t.control_replies or 0, ctrl_sent,
                t.treatment_replies or 0, trt_sent,
            )
            started = t.started_at or t.created_at or datetime.utcnow()
            days_running = (datetime.utcnow() - started).days
            result.append({
                "id": t.id,
                "template_name": t.template_name,
                "status": t.status,
                "winner": t.winner,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "control_stats": {"sent": ctrl_sent, "replies": t.control_replies or 0, "opens": t.control_opens or 0, "bounces": t.control_bounces or 0, "rate": ctrl_rate},
                "treatment_stats": {"sent": trt_sent, "replies": t.treatment_replies or 0, "opens": t.treatment_opens or 0, "bounces": t.treatment_bounces or 0, "rate": trt_rate},
                "confidence": round(confidence, 3),
                "days_running": days_running,
            })
        return {"tests": result}
    except Exception as e:
        return {"tests": []}


@router.post("/ab-tests/start/{client_id}")
def start_ab_tests(client_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    if cu.role != "admin":
        raise HTTPException(403, "Admin only")
    try:
        from ..models import CampaignDB
        from ..services.ab_testing_service import maybe_start_ab_test
        campaigns = db.query(CampaignDB).filter(
            CampaignDB.client_id == client_id,
            CampaignDB.status == "active",
        ).all()
        started = []
        for camp in campaigns:
            try:
                test_id = maybe_start_ab_test(client_id, camp.id, camp.target_industry or "generic", db)
                if test_id:
                    started.append({"campaign_id": camp.id, "test_id": test_id})
            except Exception:
                pass
        return {"tests_started": len(started), "campaign_ids": started}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.delete("/ab-tests/{test_id}/cancel")
def cancel_ab_test(test_id: str, db: Session = Depends(get_db), cu: UserDB = Depends(get_current_user)):
    try:
        from ..models import ABTestDB
        test = db.query(ABTestDB).filter(ABTestDB.id == test_id).first()
        if not test:
            raise HTTPException(404, "Test not found")
        test.status = "cancelled"
        db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))