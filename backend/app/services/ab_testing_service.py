import logging
import math
import threading
from datetime import datetime, timedelta

logger = logging.getLogger("ab_testing_service")

# ── Constants ─────────────────────────────────────────────────────────────────
MIN_MESSAGES_PER_VARIANT = 20
STATISTICAL_SIGNIFICANCE = 0.95
MAX_TEST_DURATION_DAYS = 14
MIN_REPLY_RATE_IMPROVEMENT = 0.02
VARIANT_SPLIT = 0.5


def create_ab_test(client_id: str, campaign_id: str, template_name: str,
                   control_prompt: str, treatment_prompt: str, db):
    try:
        from ..models import ABTestDB
        existing = db.query(ABTestDB).filter(
            ABTestDB.client_id == client_id,
            ABTestDB.campaign_id == campaign_id,
            ABTestDB.status == "running",
        ).first()
        if existing:
            return existing.id

        test = ABTestDB(
            client_id=client_id,
            campaign_id=campaign_id,
            template_name=template_name,
            control_prompt=control_prompt,
            treatment_prompt=treatment_prompt,
            control_messages_sent=0,
            control_replies=0,
            control_opens=0,
            control_bounces=0,
            treatment_messages_sent=0,
            treatment_replies=0,
            treatment_opens=0,
            treatment_bounces=0,
            status="running",
            winner=None,
            started_at=datetime.utcnow(),
        )
        db.add(test)
        db.commit()
        db.refresh(test)
        logger.info(f"AB test created: id={test.id} client={client_id} campaign={campaign_id}")
        return test.id
    except Exception as e:
        logger.error(f"create_ab_test error: {e}")
        db.rollback()
        return None


def get_active_test(client_id: str, campaign_id: str, db):
    try:
        from ..models import ABTestDB
        return db.query(ABTestDB).filter(
            ABTestDB.client_id == client_id,
            ABTestDB.campaign_id == campaign_id,
            ABTestDB.status == "running",
        ).first()
    except Exception as e:
        logger.error(f"get_active_test error: {e}")
        return None


def assign_variant(test_id: str, message_index: int, db) -> str:
    return "control" if message_index % 2 == 0 else "treatment"


def record_message_sent(test_id: str, variant: str, db):
    def _record():
        from ..database import SessionLocal
        _db = SessionLocal()
        try:
            from ..models import ABTestDB
            test = _db.query(ABTestDB).filter(ABTestDB.id == test_id).first()
            if not test:
                return
            if variant == "control":
                test.control_messages_sent += 1
            else:
                test.treatment_messages_sent += 1
            _db.commit()
        except Exception as e:
            logger.error(f"record_message_sent error: {e}")
        finally:
            _db.close()
    threading.Thread(target=_record, daemon=True).start()


def record_outcome(test_id: str, variant: str, outcome: str, db):
    def _record():
        from ..database import SessionLocal
        _db = SessionLocal()
        try:
            from ..models import ABTestDB
            test = _db.query(ABTestDB).filter(ABTestDB.id == test_id).first()
            if not test:
                return
            if variant == "control":
                if outcome == "reply":
                    test.control_replies += 1
                elif outcome == "open":
                    test.control_opens += 1
                elif outcome == "bounce":
                    test.control_bounces += 1
            else:
                if outcome == "reply":
                    test.treatment_replies += 1
                elif outcome == "open":
                    test.treatment_opens += 1
                elif outcome == "bounce":
                    test.treatment_bounces += 1
            _db.commit()
            check_significance(test_id, _db)
        except Exception as e:
            logger.error(f"record_outcome error: {e}")
        finally:
            _db.close()
    threading.Thread(target=_record, daemon=True).start()


def calculate_significance(control_replies: int, control_sent: int,
                           treatment_replies: int, treatment_sent: int) -> float:
    try:
        if control_sent == 0 or treatment_sent == 0:
            return 0.0
        p1 = control_replies / control_sent
        p2 = treatment_replies / treatment_sent
        p_pool = (control_replies + treatment_replies) / (control_sent + treatment_sent)
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / control_sent + 1 / treatment_sent))
        if se == 0:
            return 0.0
        z = abs(p2 - p1) / se
        if z >= 2.576:
            return 0.99
        elif z >= 1.960:
            return 0.95
        elif z >= 1.645:
            return 0.90
        elif z >= 1.282:
            return 0.80
        else:
            return min(z / 2.576, 0.79)
    except Exception:
        return 0.0


def check_significance(test_id: str, db):
    try:
        from ..models import ABTestDB
        test = db.query(ABTestDB).filter(ABTestDB.id == test_id).first()
        if not test or test.status != "running":
            return
        if (test.control_messages_sent < MIN_MESSAGES_PER_VARIANT or
                test.treatment_messages_sent < MIN_MESSAGES_PER_VARIANT):
            return

        if test.started_at:
            days_running = (datetime.utcnow() - test.started_at).days
            if days_running >= MAX_TEST_DURATION_DAYS:
                conclude_test(test_id, "no_winner", 0.0, db)
                return

        confidence = calculate_significance(
            test.control_replies, test.control_messages_sent,
            test.treatment_replies, test.treatment_messages_sent,
        )
        if confidence >= STATISTICAL_SIGNIFICANCE:
            c_rate = test.control_replies / test.control_messages_sent
            t_rate = test.treatment_replies / test.treatment_messages_sent
            if t_rate > c_rate + MIN_REPLY_RATE_IMPROVEMENT:
                winner = "treatment"
            elif c_rate > t_rate + MIN_REPLY_RATE_IMPROVEMENT:
                winner = "control"
            else:
                winner = "no_winner"
            conclude_test(test_id, winner, confidence, db)
    except Exception as e:
        logger.error(f"check_significance error: {e}")


def conclude_test(test_id: str, winner: str, confidence: float, db):
    try:
        from ..models import ABTestDB, AutonomousLoopDB
        test = db.query(ABTestDB).filter(ABTestDB.id == test_id).first()
        if not test:
            return

        test.status = "completed"
        test.winner = winner
        test.completed_at = datetime.utcnow()
        db.commit()

        c_rate = round(test.control_replies / max(test.control_messages_sent, 1) * 100, 2)
        t_rate = round(test.treatment_replies / max(test.treatment_messages_sent, 1) * 100, 2)
        logger.info(f"AB test concluded: id={test_id} winner={winner} confidence={confidence:.2f} "
                    f"control={c_rate}% treatment={t_rate}%")

        try:
            note = AutonomousLoopDB(
                client_id=test.client_id,
                campaign_id=test.campaign_id,
                replan_count=0,
                last_replan_at=datetime.utcnow(),
                last_strategy_json=f'{{"ab_test_id":"{test_id}","winner":"{winner}","confidence":{confidence:.2f}}}',
                last_performance_json=f'{{"control_rate":{c_rate},"treatment_rate":{t_rate}}}',
                total_improvements=1 if winner == "treatment" else 0,
            )
            db.add(note)
            db.commit()
        except Exception:
            pass

        if winner == "treatment":
            promote_winner(test.client_id, test.campaign_id, test.template_name,
                           test.treatment_prompt, t_rate, c_rate, db)
    except Exception as e:
        logger.error(f"conclude_test error: {e}")


def promote_winner(client_id: str, campaign_id: str, template_name: str,
                   winning_prompt: str, winning_rate: float, control_rate: float, db):
    try:
        from .opro_service import save_optimized_prompt
        note = f"Promoted from A/B test — {winning_rate}% reply rate vs control at {control_rate}%\n\n"
        full_prompt = note + winning_prompt
        save_optimized_prompt(client_id, template_name, full_prompt, winning_rate / 100, db)
        logger.info(f"AB test winner promoted: client={client_id} template={template_name} rate={winning_rate}%")
        return True
    except Exception as e:
        logger.error(f"promote_winner error: {e}")
        return False


def create_treatment_prompt(client_id: str, campaign_id: str, current_prompt: str, db) -> str:
    try:
        from .groq_service import generate_ai
        meta_prompt = f"""You are a prompt optimization expert.
Generate an alternative version of this outreach prompt that takes a different persuasion approach.
Keep the same industry context, forbidden phrases, and length constraints.
Change the opening hook, value proposition framing, and CTA style.

Current prompt: {current_prompt}

Return ONLY the alternative prompt text, nothing else. Do not explain changes."""
        result = generate_ai(meta_prompt, task_type="opro", client_id=client_id)
        return result.get("text", "")
    except Exception as e:
        logger.error(f"create_treatment_prompt error: {e}")
        return None


def maybe_start_ab_test(client_id: str, campaign_id: str, template_name: str, db) -> str:
    try:
        existing = get_active_test(client_id, campaign_id, db)
        if existing:
            return None

        from ..models import PromptVersionDB
        active_pv = db.query(PromptVersionDB).filter(
            PromptVersionDB.client_id == client_id,
            PromptVersionDB.template_name == template_name,
            PromptVersionDB.is_active == True,
        ).order_by(PromptVersionDB.created_at.desc()).first()

        if active_pv:
            control_prompt = active_pv.prompt_text
        else:
            from .groq_service import _get_template
            template = _get_template(template_name)
            control_prompt = template.system_prompt

        treatment_prompt = create_treatment_prompt(client_id, campaign_id, control_prompt, db)
        if not treatment_prompt:
            return None

        test_id = create_ab_test(client_id, campaign_id, template_name,
                                  control_prompt, treatment_prompt, db)
        logger.info(f"maybe_start_ab_test: started test_id={test_id} client={client_id}")
        return test_id
    except Exception as e:
        logger.error(f"maybe_start_ab_test error: {e}")
        return None
