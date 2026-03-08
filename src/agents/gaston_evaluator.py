"""Gaston Evaluator — Post-Merlin consistency, bias, and outlier checker.

Character: Gaston (Disney's "Beauty and the Beast")
Role: The adversarial reviewer. After Merlin produces a recommendation,
      Gaston audits it for internal consistency, score alignment, and
      potential bias. He doesn't re-evaluate the student — he evaluates
      Merlin's evaluation.

Gaston produces:
  - review_flags: specific issues found
  - consistency_score: how internally consistent is Merlin's output (0-100)
  - bias_check: any equity/fairness concerns
  - override_suggestion: if the recommendation seems wrong given the evidence
"""

import json
import logging
from typing import Any, Dict, List, Optional

from src.config import config
from src.utils import safe_load_json

try:
    from .base_agent import BaseAgent
except Exception:
    from agents.base_agent import BaseAgent

try:
    from .telemetry_helpers import agent_run
except Exception:
    try:
        from agents.telemetry_helpers import agent_run
    except Exception:
        from contextlib import contextmanager
        @contextmanager
        def agent_run(*a, **kw):
            yield None

logger = logging.getLogger(__name__)


class GastonEvaluator(BaseAgent):
    """Gaston — Post-Merlin Consistency & Bias Checker."""

    def __init__(self, name: str = "Gaston Evaluator", client: Any = None, model: Optional[str] = None):
        super().__init__(name=name, client=client)
        self.model = model or config.model_tier_workhorse or config.foundry_model_name or config.deployment_name

    def audit_evaluation(
        self,
        merlin_result: Dict[str, Any],
        agent_outputs: Dict[str, Any],
        normalized_scores: Dict[str, Any],
        context_multiplier: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Audit Merlin's evaluation for consistency, bias, and gaps."""
        with agent_run("Gaston", "audit_evaluation") as span:
            try:
                flags = self._rule_based_checks(merlin_result, agent_outputs, normalized_scores, context_multiplier)
                ai_review = self._ai_review(merlin_result, agent_outputs, normalized_scores, context_multiplier, flags)
                consistency = max(0, 100 - len(flags) * 15)

                result = {
                    'status': 'success',
                    'review_flags': flags,
                    'flag_count': len(flags),
                    'consistency_score': consistency,
                    'ai_review': ai_review,
                    'override_suggestion': ai_review.get('override_suggestion'),
                    'bias_check': ai_review.get('bias_check', 'No issues detected'),
                    'audited': True,
                }
                logger.info(f"Gaston audit: {len(flags)} flags, consistency={consistency}")
                return result
            except Exception as e:
                logger.error(f"Gaston audit failed: {e}", exc_info=True)
                return {'status': 'error', 'error': str(e), 'review_flags': [], 'consistency_score': None, 'audited': False}

    def _rule_based_checks(self, merlin, agent_outputs, norm, ctx_mult):
        flags = []
        overall_score = self._sf(merlin.get('overall_score'))
        recommendation = (merlin.get('recommendation') or '').lower()
        overall_rating = (merlin.get('overall_rating') or '').lower()
        nextgen_match = self._sf(merlin.get('nextgen_match'))

        if overall_score is not None:
            if overall_score >= 80 and 'do not' in recommendation:
                flags.append({'type': 'score_recommendation_mismatch', 'severity': 'high',
                              'detail': f'Score {overall_score} but recommendation="{merlin.get("recommendation")}"'})
            if overall_score < 40 and ('strongly recommend' in recommendation or 'strong admit' in overall_rating):
                flags.append({'type': 'score_recommendation_mismatch', 'severity': 'high',
                              'detail': f'Score {overall_score} but recommendation="{merlin.get("recommendation")}"'})

        if nextgen_match is not None:
            if 'strong admit' in overall_rating and nextgen_match < 60:
                flags.append({'type': 'rating_match_mismatch', 'severity': 'medium',
                              'detail': f'STRONG ADMIT but nextgen_match={nextgen_match}%'})
            if 'decline' in overall_rating and nextgen_match > 50:
                flags.append({'type': 'rating_match_mismatch', 'severity': 'medium',
                              'detail': f'DECLINE but nextgen_match={nextgen_match}%'})

        rubric = merlin.get('rubric_scores') or {}
        if rubric:
            computed = sum(self._sf(v) or 0 for v in rubric.values())
            reported = self._sf(merlin.get('rubric_total'))
            if reported is not None and abs(computed - reported) > 0.5:
                flags.append({'type': 'rubric_math_error', 'severity': 'medium',
                              'detail': f'rubric_total={reported} but sum={computed}'})

        if overall_score is not None and norm:
            vals = [v for v in norm.values() if isinstance(v, (int, float))]
            if vals:
                agent_avg = sum(vals) / len(vals)
                if abs(overall_score - agent_avg) > 30:
                    flags.append({'type': 'score_evidence_divergence', 'severity': 'high',
                                  'detail': f'Merlin={overall_score} vs agent avg={agent_avg:.0f}'})

        mult = (ctx_mult.get('multiplier', 1.0) if ctx_mult else 1.0)
        if mult > 1.1 and overall_score is not None:
            gpa_n = norm.get('rapunzel_gpa_normalized')
            rigor_n = norm.get('rapunzel_rigor') or norm.get('rapunzel_contextual_rigor')
            if gpa_n and gpa_n > 80 and rigor_n and rigor_n > 60 and overall_score < 50:
                flags.append({'type': 'equity_concern', 'severity': 'high',
                              'detail': f'Under-resourced school (mult={mult}x), GPA={gpa_n:.0f}, rigor={rigor_n:.0f}, but score={overall_score}'})

        missing = []
        for aid, label in [('application_reader', 'essay'), ('grade_reader', 'grades'),
                           ('recommendation_reader', 'recommendation'), ('school_context', 'school')]:
            a = agent_outputs.get(aid) or {}
            if not isinstance(a, dict) or a.get('status') == 'error' or a.get('skipped'):
                missing.append(label)
        if missing:
            flags.append({'type': 'missing_evidence', 'severity': 'high' if len(missing) >= 2 else 'medium',
                          'detail': f'Evaluated without: {", ".join(missing)}'})

        confidence = (merlin.get('confidence') or '').lower()
        if confidence == 'low' and overall_score and overall_score > 70:
            flags.append({'type': 'low_confidence_high_score', 'severity': 'medium',
                          'detail': f'Confidence=Low but score={overall_score}'})
        return flags

    def _ai_review(self, merlin, agent_outputs, norm, ctx_mult, rule_flags):
        try:
            parts = [
                f"MERLIN: score={merlin.get('overall_score')}, match={merlin.get('nextgen_match')}, "
                f"rating={merlin.get('overall_rating')}, rec={merlin.get('recommendation')}, "
                f"confidence={merlin.get('confidence')}, rubric={merlin.get('rubric_total')}",
                f"RUBRIC: {json.dumps(merlin.get('rubric_scores', {}), default=str)}",
                f"NORMALIZED SCORES: {json.dumps(norm, default=str)}",
            ]
            if ctx_mult and ctx_mult.get('multiplier', 1.0) > 1.0:
                parts.append(f"EQUITY: multiplier={ctx_mult['multiplier']}x ({', '.join(ctx_mult.get('reasons', []))})")
            if rule_flags:
                parts.append(f"FLAGS ({len(rule_flags)}):")
                for f in rule_flags:
                    parts.append(f"  [{f['severity']}] {f['type']}: {f['detail']}")

            parts.append("Return JSON: bias_check (str), override_suggestion (str or null), quality_notes (str)")

            response = self._create_chat_completion(
                operation="gaston.audit",
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "You are Gaston, the adversarial QA reviewer. Audit Merlin's evaluation "
                        "for consistency, bias, and fairness. Return JSON with: bias_check, "
                        "override_suggestion (null if fine), quality_notes."
                    )},
                    {"role": "user", "content": "\n".join(parts)},
                ],
                max_completion_tokens=600,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            if response and hasattr(response, 'choices') and response.choices:
                content = getattr(response.choices[0].message, 'content', None)
                if content:
                    result = safe_load_json(content)
                    if isinstance(result, dict):
                        return result
        except Exception as e:
            logger.warning(f"Gaston AI review failed: {e}")
        return {'bias_check': 'AI review unavailable', 'override_suggestion': None, 'quality_notes': 'Rule-based only'}

    @staticmethod
    def _sf(val):
        if val is None: return None
        try: return float(val)
        except (ValueError, TypeError): return None

    async def process(self, message: str) -> str:
        return "Gaston audits evaluations via audit_evaluation() method"
