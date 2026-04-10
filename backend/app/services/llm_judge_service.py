import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

logger = logging.getLogger("llm_judge")

JUDGE_DIMENSIONS = {
    'personalization': 0.30,
    'cultural_fit':    0.20,
    'cta_strength':    0.20,
    'tone_match':      0.15,
    'clarity':         0.15,
}
MIN_JUDGE_SCORE = 6.5
MIN_DIMENSION_SCORE = 5.0
JUDGE_TIMEOUT_SECONDS = 8

_judge_executor = ThreadPoolExecutor(max_workers=4)


def build_judge_prompt(message_text, lead_data, campaign_data, channel, language, client_config):
    region = client_config.get('region', 'India') if client_config else 'India'
    tone = getattr(campaign_data, 'tone', 'professional')
    lead_name = getattr(lead_data, 'name', '')
    lead_role = getattr(lead_data, 'role', '')
    lead_company = getattr(lead_data, 'company', '')
    lead_industry = getattr(lead_data, 'industry', '')

    return f"""You are an expert B2B outreach evaluator.
Score this {channel} message on 5 dimensions.
Be strict — most messages score 5-7, not 9-10.

Message to evaluate:
{message_text}

Context:
- Lead: {lead_name}, {lead_role} at {lead_company}
- Industry: {lead_industry}
- Channel: {channel}
- Language style: {language}
- Campaign tone: {tone}
- Client region: {region}

Score each dimension 1-10:

1. PERSONALIZATION (30% weight):
   Does it reference specific details about this
   company or person? Generic = 1, Highly specific = 10

2. CULTURAL_FIT (20% weight):
   Is the tone, language, and approach appropriate
   for Indian B2B context and this region?
   Inappropriate = 1, Perfect fit = 10

3. CTA_STRENGTH (20% weight):
   Is the call-to-action clear, specific, and
   low-friction? No CTA = 1, Perfect CTA = 10

4. TONE_MATCH (15% weight):
   Does the tone match the requested campaign tone
   and the lead's seniority level?
   Completely off = 1, Perfect match = 10

5. CLARITY (15% weight):
   Is the message clear, concise, and easy to act on?
   Confusing = 1, Crystal clear = 10

Return ONLY this JSON:
{{
  "scores": {{
    "personalization": float,
    "cultural_fit": float,
    "cta_strength": float,
    "tone_match": float,
    "clarity": float
  }},
  "weighted_score": float,
  "verdict": "pass" or "fail" or "borderline",
  "primary_weakness": str,
  "improvement_suggestion": str,
  "red_flags": [str],
  "standout_elements": [str]
}}"""


def evaluate_message(message_text, lead_data, campaign_data, channel, language,
                     client_config, client_id):
    try:
        from .groq_service import generate_ai, FALLBACK_MODEL
        prompt = build_judge_prompt(message_text, lead_data, campaign_data,
                                    channel, language, client_config)
        t0 = time.time()

        future = _judge_executor.submit(
            generate_ai, prompt, 'judge', client_id, FALLBACK_MODEL
        )
        result = future.result(timeout=JUDGE_TIMEOUT_SECONDS)

        elapsed_ms = int((time.time() - t0) * 1000)
        raw = result.get('text', '')

        # Strip markdown fences if present
        if '```' in raw:
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        scores = data.get('scores', {})

        # Calculate weighted score if not provided or wrong
        weighted = sum(
            scores.get(dim, 0) * w for dim, w in JUDGE_DIMENSIONS.items()
        )
        weighted = round(data.get('weighted_score', weighted), 2)

        return {
            'scores': scores,
            'weighted_score': weighted,
            'verdict': data.get('verdict', 'borderline'),
            'primary_weakness': data.get('primary_weakness', ''),
            'improvement_suggestion': data.get('improvement_suggestion', ''),
            'red_flags': data.get('red_flags', [])[:3],
            'standout_elements': data.get('standout_elements', [])[:2],
            'judge_model': result.get('model_used', ''),
            'evaluation_time_ms': elapsed_ms,
        }
    except Exception as e:
        logger.warning(f"judge evaluate_message failed (non-blocking): {e}")
        return None


def check_dimension_failures(scores):
    failures = []
    for dim in JUDGE_DIMENSIONS:
        score = scores.get(dim, 0)
        if score < MIN_DIMENSION_SCORE:
            failures.append({
                'dimension': dim,
                'score': score,
                'threshold': MIN_DIMENSION_SCORE,
            })
    return failures


def build_judge_fix_prompt(original_message, judge_result):
    scores = judge_result.get('scores', {})
    primary = judge_result.get('primary_weakness', '')
    primary_score = scores.get(primary, 0)
    suggestion = judge_result.get('improvement_suggestion', '')
    red_flags = judge_result.get('red_flags', [])
    standout = judge_result.get('standout_elements', [])
    failed_dims = check_dimension_failures(scores)

    failed_lines = '\n'.join(
        f"  - {f['dimension']}: {f['score']}/10 (needs >{f['threshold']})"
        for f in failed_dims
    ) or '  None'

    red_flag_lines = '\n'.join(f'  - {r}' for r in red_flags) or '  None'
    standout_lines = ', '.join(standout) if standout else 'None'

    return f"""Rewrite this message fixing these specific issues:

Primary weakness: {primary} (scored {primary_score}/10)

Specific improvement needed:
  {suggestion}

Red flags to eliminate:
{red_flag_lines}

Failed dimensions:
{failed_lines}

Original message:
{original_message}

Requirements for rewrite:
- Fix the primary weakness first
- Eliminate all red flags
- Keep these strong elements: {standout_lines}
- Keep same length and channel format

Return ONLY the rewritten message."""


def judge_and_maybe_fix(message_text, lead_data, campaign_data, channel, language,
                        client_config, client_id, allow_rewrite=True):
    judge_result = evaluate_message(
        message_text, lead_data, campaign_data, channel, language,
        client_config, client_id
    )

    if judge_result is None:
        return {'message': message_text, 'judge_skipped': True, 'final_score': None}

    weighted = judge_result['weighted_score']
    verdict = judge_result['verdict']

    if verdict == 'pass' and weighted >= MIN_JUDGE_SCORE:
        return {'message': message_text, 'passed': True, 'judge_result': judge_result}

    if verdict == 'borderline':
        logger.warning({
            'event': 'judge_borderline',
            'weighted_score': weighted,
            'primary_weakness': judge_result.get('primary_weakness'),
        })
        return {'message': message_text, 'passed': True, 'judge_result': judge_result}

    # verdict == 'fail' or weighted < MIN_JUDGE_SCORE
    if not allow_rewrite:
        return {'message': message_text, 'passed': False, 'judge_result': judge_result}

    original_score = weighted
    try:
        from .groq_service import generate_ai
        fix_prompt = build_judge_fix_prompt(message_text, judge_result)
        regen = generate_ai(fix_prompt, task_type='message_regen', client_id=client_id)
        rewrite_text = regen.get('text', message_text)

        rewrite_judge = evaluate_message(
            rewrite_text, lead_data, campaign_data, channel, language,
            client_config, client_id
        )

        if rewrite_judge and rewrite_judge['weighted_score'] >= MIN_JUDGE_SCORE:
            return {
                'message': rewrite_text,
                'passed': True,
                'was_rewritten': True,
                'original_score': original_score,
                'final_score': rewrite_judge['weighted_score'],
                'judge_result': rewrite_judge,
            }
        else:
            return {
                'message': message_text,
                'passed': False,
                'rewrite_attempted': True,
                'judge_result': judge_result,
            }
    except Exception as e:
        logger.error(f"judge rewrite failed: {e}")
        return {'message': message_text, 'passed': False, 'rewrite_attempted': True,
                'judge_result': judge_result}


def save_judge_result(client_id, lead_id, job_id, channel, judge_result,
                      was_rewritten, final_passed, db):
    def _save():
        try:
            from ..database import SessionLocal
            from ..models import JudgeEvaluationDB
            _db = SessionLocal()
            try:
                scores = judge_result.get('scores', {})
                record = JudgeEvaluationDB(
                    id=str(uuid.uuid4())[:12],
                    client_id=client_id,
                    lead_id=lead_id,
                    job_id=job_id,
                    channel=channel,
                    personalization_score=scores.get('personalization', 0.0),
                    cultural_fit_score=scores.get('cultural_fit', 0.0),
                    cta_strength_score=scores.get('cta_strength', 0.0),
                    tone_match_score=scores.get('tone_match', 0.0),
                    clarity_score=scores.get('clarity', 0.0),
                    weighted_score=judge_result.get('weighted_score', 0.0),
                    verdict=judge_result.get('verdict', ''),
                    primary_weakness=judge_result.get('primary_weakness', ''),
                    was_rewritten=was_rewritten,
                    final_passed=final_passed,
                    red_flags_json=json.dumps(judge_result.get('red_flags', [])),
                    improvement_suggestion=judge_result.get('improvement_suggestion', ''),
                    judge_model=judge_result.get('judge_model', ''),
                    evaluation_time_ms=judge_result.get('evaluation_time_ms', 0),
                    created_at=datetime.utcnow(),
                )
                _db.add(record)
                _db.commit()
            finally:
                _db.close()
        except Exception as e:
            logger.error(f"save_judge_result failed: {e}")

    _judge_executor.submit(_save)


def get_judge_analytics(client_id, days=30, db=None):
    try:
        from datetime import timedelta
        from sqlalchemy import func
        from ..models import JudgeEvaluationDB

        close_db = False
        if db is None:
            from ..database import SessionLocal
            db = SessionLocal()
            close_db = True

        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            records = db.query(JudgeEvaluationDB).filter(
                JudgeEvaluationDB.client_id == client_id,
                JudgeEvaluationDB.created_at >= cutoff,
            ).all()

            total = len(records)
            if total == 0:
                return {
                    'total_evaluated': 0, 'pass_rate': 0.0, 'rewrite_rate': 0.0,
                    'avg_weighted_score': 0.0, 'avg_scores_by_dimension': {},
                    'most_common_weakness': '', 'most_common_red_flags': [],
                    'improvement_over_time': [],
                }

            passed = sum(1 for r in records if r.final_passed)
            rewritten = sum(1 for r in records if r.was_rewritten)

            avg_scores = {
                'personalization': round(sum(r.personalization_score or 0 for r in records) / total, 2),
                'cultural_fit':    round(sum(r.cultural_fit_score or 0 for r in records) / total, 2),
                'cta_strength':    round(sum(r.cta_strength_score or 0 for r in records) / total, 2),
                'tone_match':      round(sum(r.tone_match_score or 0 for r in records) / total, 2),
                'clarity':         round(sum(r.clarity_score or 0 for r in records) / total, 2),
            }

            weakness_counts = {}
            all_red_flags = []
            for r in records:
                if r.primary_weakness:
                    weakness_counts[r.primary_weakness] = weakness_counts.get(r.primary_weakness, 0) + 1
                try:
                    flags = json.loads(r.red_flags_json or '[]')
                    all_red_flags.extend(flags)
                except Exception:
                    pass

            most_common_weakness = max(weakness_counts, key=weakness_counts.get) if weakness_counts else ''
            flag_counts = {}
            for f in all_red_flags:
                flag_counts[f] = flag_counts.get(f, 0) + 1
            top_flags = sorted(flag_counts, key=flag_counts.get, reverse=True)[:5]

            # Weekly trend
            from collections import defaultdict
            weekly = defaultdict(list)
            for r in records:
                if r.created_at:
                    week = r.created_at.isocalendar()[1]
                    weekly[week].append(r.weighted_score or 0)
            improvement = [
                {'week': w, 'avg_score': round(sum(s) / len(s), 2)}
                for w, s in sorted(weekly.items())
            ]

            return {
                'total_evaluated': total,
                'pass_rate': round(passed / total, 3),
                'rewrite_rate': round(rewritten / total, 3),
                'avg_weighted_score': round(sum(r.weighted_score or 0 for r in records) / total, 2),
                'avg_scores_by_dimension': avg_scores,
                'most_common_weakness': most_common_weakness,
                'most_common_red_flags': top_flags,
                'improvement_over_time': improvement,
            }
        finally:
            if close_db:
                db.close()
    except Exception as e:
        logger.error(f"get_judge_analytics failed: {e}")
        return {}
