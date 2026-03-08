"""Pocahontas Cohort Analyst Agent — Cross-school comparison and equity analysis
across the entire applicant pool.

Character: Pocahontas (Disney's "Pocahontas")
Role: After Naveen has scored individual schools, Pocahontas steps back and
      looks at the WHOLE applicant pool to produce:
      - School tier groupings (high-resource, moderate, under-resourced)
      - Percentile rankings within the applicant pool
      - Equity distribution analysis
      - Cohort-level insights for the scholarship committee

Unlike Naveen (per-school) and Moana (per-student), Pocahontas operates at the
cohort level — she needs ALL school data at once to do comparative analysis.

Data flow:
    school_enriched_data (Naveen-scored) → Pocahontas cohort analysis →
    stored as cohort report → referenced by Moana and Merlin
"""

import json
import logging
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.config import config
from src.database import db

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

# Tier boundaries (opportunity_score)
TIER_THRESHOLDS = {
    'high_resource': 70,     # ≥70: well-funded, many APs, good outcomes
    'moderate': 45,          # 45-69: average resources
    # <45: under-resourced
}


class PocahontasCohortAnalyst(BaseAgent):
    """Pocahontas — Cohort Analyst Agent

    Compares schools across the applicant pool to surface patterns,
    equity insights, and relative standings that individual school
    analysis cannot reveal.

    Key outputs:
    - School tiers (high-resource / moderate / under-resourced)
    - Percentile ranks for each school within the applicant pool
    - Equity distribution (how many applicants come from each tier)
    - AI-generated cohort narrative for the scholarship committee
    - Per-school "context multiplier" that Merlin can use in scoring
    """

    def __init__(
        self,
        name: str = "Pocahontas Cohort Analyst",
        client: Any = None,
        model: Optional[str] = None,
    ):
        super().__init__(name=name, client=client)
        self.model = (
            model
            or config.model_tier_workhorse
            or config.foundry_model_name
            or config.deployment_name
        )

    # ── Main entry point ─────────────────────────────────────────────

    def analyze_cohort(
        self,
        schools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Analyze the full school cohort for comparative insights.

        Args:
            schools: List of school_enriched_data dicts. If None, fetches
                     all active schools from DB.

        Returns:
            Cohort analysis with tiers, percentiles, equity stats, and narrative.
        """
        with agent_run("Pocahontas", "analyze_cohort") as span:
            try:
                if schools is None:
                    schools = db.get_all_schools_enriched(
                        filters={'is_active': True},
                        limit=2000
                    ) or []

                if not schools:
                    return {
                        'status': 'empty',
                        'message': 'No school data available for cohort analysis',
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                    }

                scored = [s for s in schools if s.get('opportunity_score') is not None]
                unscored = [s for s in schools if s.get('opportunity_score') is None]

                if not scored:
                    return {
                        'status': 'pending',
                        'message': f'{len(unscored)} schools have no Naveen scores yet. Run batch analysis first.',
                        'total_schools': len(schools),
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                    }

                # Build tiers
                tiers = self._assign_tiers(scored)

                # Compute percentiles
                percentiles = self._compute_percentiles(scored)

                # Equity distribution
                equity = self._analyze_equity(scored, tiers)

                # Context multipliers for Merlin
                multipliers = self._compute_context_multipliers(scored, percentiles)

                # AI cohort narrative
                narrative = self._generate_cohort_narrative(
                    scored, tiers, equity, percentiles
                )

                result = {
                    'status': 'success',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'total_schools': len(schools),
                    'scored_schools': len(scored),
                    'unscored_schools': len(unscored),
                    'tiers': tiers,
                    'percentiles': percentiles,
                    'equity_analysis': equity,
                    'context_multipliers': multipliers,
                    'cohort_narrative': narrative,
                    'model_used': self.model,
                }

                # Persist to DB
                self._save_cohort_report(result)

                return result

            except Exception as e:
                logger.error(f"Pocahontas cohort analysis failed: {e}", exc_info=True)
                return {
                    'status': 'error',
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }

    # ── Tier assignment ──────────────────────────────────────────────

    def _assign_tiers(
        self, schools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Group schools into resource tiers based on opportunity score."""
        high, moderate, under = [], [], []

        for s in schools:
            score = float(s.get('opportunity_score', 0))
            name = s.get('school_name', 'Unknown')
            sid = s.get('school_enrichment_id')
            entry = {
                'school_enrichment_id': sid,
                'school_name': name,
                'opportunity_score': score,
                'frpl_pct': s.get('free_lunch_percentage'),
                'ap_count': s.get('ap_course_count'),
                'graduation_rate': s.get('graduation_rate'),
            }
            if score >= TIER_THRESHOLDS['high_resource']:
                high.append(entry)
            elif score >= TIER_THRESHOLDS['moderate']:
                moderate.append(entry)
            else:
                under.append(entry)

        return {
            'high_resource': {
                'count': len(high),
                'schools': sorted(high, key=lambda x: x['opportunity_score'], reverse=True),
                'label': 'High Resource (≥70)',
                'description': 'Well-funded schools with extensive AP/honors programs and strong outcomes',
            },
            'moderate': {
                'count': len(moderate),
                'schools': sorted(moderate, key=lambda x: x['opportunity_score'], reverse=True),
                'label': 'Moderate (45-69)',
                'description': 'Average resources — some advanced courses, moderate funding',
            },
            'under_resourced': {
                'count': len(under),
                'schools': sorted(under, key=lambda x: x['opportunity_score'], reverse=True),
                'label': 'Under-Resourced (<45)',
                'description': 'Limited AP/honors access, higher FRPL rates, lower per-pupil spending',
            },
        }

    # ── Percentile computation ───────────────────────────────────────

    @staticmethod
    def _compute_percentiles(
        schools: List[Dict[str, Any]]
    ) -> Dict[int, float]:
        """Compute percentile rank for each school within the pool.

        Returns: {school_enrichment_id: percentile_rank (0-100)}
        """
        scores = sorted(
            [(s.get('school_enrichment_id'), float(s.get('opportunity_score', 0)))
             for s in schools],
            key=lambda x: x[1]
        )
        n = len(scores)
        if n == 0:
            return {}
        result = {}
        for rank, (sid, _score) in enumerate(scores):
            result[sid] = round(rank / max(n - 1, 1) * 100, 1)
        return result

    # ── Equity analysis ──────────────────────────────────────────────

    @staticmethod
    def _analyze_equity(
        schools: List[Dict[str, Any]],
        tiers: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyze equity distribution across the applicant pool."""
        total = len(schools)
        if total == 0:
            return {}

        scores = [float(s.get('opportunity_score', 0)) for s in schools]
        frpl_vals = [float(s['free_lunch_percentage']) for s in schools
                     if s.get('free_lunch_percentage') is not None]
        title_i_count = sum(1 for s in schools if s.get('is_title_i'))

        high_need = sum(1 for f in frpl_vals if f > 50)

        return {
            'opportunity_score_stats': {
                'mean': round(statistics.mean(scores), 1),
                'median': round(statistics.median(scores), 1),
                'stdev': round(statistics.stdev(scores), 1) if len(scores) > 1 else 0,
                'min': round(min(scores), 1),
                'max': round(max(scores), 1),
            },
            'frpl_stats': {
                'mean': round(statistics.mean(frpl_vals), 1) if frpl_vals else None,
                'median': round(statistics.median(frpl_vals), 1) if frpl_vals else None,
                'above_national_avg': sum(1 for f in frpl_vals if f > 52),
                'high_need_count': high_need,
                'high_need_pct': round(high_need / total * 100, 1) if total else 0,
            },
            'title_i': {
                'count': title_i_count,
                'pct': round(title_i_count / total * 100, 1) if total else 0,
            },
            'tier_distribution': {
                'high_resource_pct': round(tiers['high_resource']['count'] / total * 100, 1),
                'moderate_pct': round(tiers['moderate']['count'] / total * 100, 1),
                'under_resourced_pct': round(tiers['under_resourced']['count'] / total * 100, 1),
            },
        }

    # ── Context multipliers ──────────────────────────────────────────

    @staticmethod
    def _compute_context_multipliers(
        schools: List[Dict[str, Any]],
        percentiles: Dict[int, float],
    ) -> Dict[int, Dict[str, Any]]:
        """Compute a context multiplier for each school that Merlin can
        use to weight student achievements.

        Schools in harder environments get a multiplier > 1.0 (boost).
        Schools in resource-rich environments get 1.0 (no adjustment).

        Formula:
            base = 1.0
            + 0.15 if FRPL > 60%
            + 0.10 if FRPL > 40%
            + 0.10 if opportunity_score percentile < 25th
            + 0.05 if Title I
            cap at 1.30 (max 30% boost)
        """
        result = {}
        for s in schools:
            sid = s.get('school_enrichment_id')
            frpl = float(s['free_lunch_percentage']) if s.get('free_lunch_percentage') is not None else None
            title_i = s.get('is_title_i', False)
            pctile = percentiles.get(sid, 50)

            multiplier = 1.0
            reasons = []

            if frpl is not None and frpl > 60:
                multiplier += 0.15
                reasons.append(f'High FRPL ({frpl:.0f}%)')
            elif frpl is not None and frpl > 40:
                multiplier += 0.10
                reasons.append(f'Elevated FRPL ({frpl:.0f}%)')

            if pctile < 25:
                multiplier += 0.10
                reasons.append(f'Bottom quartile opportunity (P{pctile:.0f})')

            if title_i:
                multiplier += 0.05
                reasons.append('Title I school')

            multiplier = min(multiplier, 1.30)

            result[sid] = {
                'multiplier': round(multiplier, 2),
                'reasons': reasons,
                'school_name': s.get('school_name'),
                'percentile': pctile,
            }
        return result

    # ── AI narrative ─────────────────────────────────────────────────

    def _generate_cohort_narrative(
        self,
        schools: List[Dict[str, Any]],
        tiers: Dict[str, Any],
        equity: Dict[str, Any],
        percentiles: Dict[int, float],
    ) -> str:
        """Generate an AI summary of the cohort's school landscape."""
        tier_dist = equity.get('tier_distribution', {})
        score_stats = equity.get('opportunity_score_stats', {})
        frpl_stats = equity.get('frpl_stats', {})

        # Build top/bottom school lists for context
        sorted_schools = sorted(schools, key=lambda s: float(s.get('opportunity_score', 0)), reverse=True)
        top_3 = sorted_schools[:3]
        bottom_3 = sorted_schools[-3:] if len(sorted_schools) > 3 else []

        prompt = f"""You are Pocahontas, a cohort-level education equity analyst for a STEM scholarship program.

APPLICANT POOL SCHOOL DATA:
- Total schools: {len(schools)}
- Opportunity Score: mean={score_stats.get('mean')}, median={score_stats.get('median')}, range={score_stats.get('min')}-{score_stats.get('max')}
- Tier distribution: {tier_dist.get('high_resource_pct', 0):.0f}% high-resource, {tier_dist.get('moderate_pct', 0):.0f}% moderate, {tier_dist.get('under_resourced_pct', 0):.0f}% under-resourced
- FRPL: mean={frpl_stats.get('mean')}%, {frpl_stats.get('high_need_count', 0)} schools above 50% ({frpl_stats.get('high_need_pct', 0):.0f}%)
- Title I schools: {equity.get('title_i', {}).get('count', 0)} ({equity.get('title_i', {}).get('pct', 0):.0f}%)

TOP OPPORTUNITY SCHOOLS:
{chr(10).join(f"  {s.get('school_name')}: score={s.get('opportunity_score')}, AP={s.get('ap_course_count')}, FRPL={s.get('free_lunch_percentage')}%" for s in top_3)}

MOST UNDER-RESOURCED SCHOOLS:
{chr(10).join(f"  {s.get('school_name')}: score={s.get('opportunity_score')}, AP={s.get('ap_course_count')}, FRPL={s.get('free_lunch_percentage')}%" for s in bottom_3)}

Write a 6-8 sentence cohort summary for the scholarship committee addressing:
1. What does the school landscape look like across the applicant pool? Is it diverse or homogeneous?
2. What equity patterns emerge? How many students come from under-resourced schools?
3. What specific attention should the committee pay to applicants from under-resourced schools?
4. Are there any red flags or notable patterns (eg most applicants from a few high-resource schools)?
5. One concrete recommendation for how the committee should use school context in evaluation.

Be direct and actionable. This informs committee-level scholarship decisions."""

        try:
            response = self._create_chat_completion(
                operation="pocahontas.cohort_narrative",
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "You are Pocahontas, an education equity analyst who examines "
                        "school data across entire applicant cohorts. You produce data-driven "
                        "summaries that help scholarship committees understand the landscape "
                        "of opportunity their applicants come from. Be specific, cite numbers, "
                        "and give actionable recommendations."
                    )},
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=1000,
                temperature=0.4,
            )

            if (response and hasattr(response, 'choices')
                    and response.choices
                    and getattr(response.choices[0].message, 'content', None)):
                return response.choices[0].message.content.strip()

        except Exception as e:
            logger.warning(f"Pocahontas AI narrative failed: {e}")

        # Fallback
        return (
            f"The applicant pool spans {len(schools)} schools. "
            f"{tier_dist.get('under_resourced_pct', 0):.0f}% of applicants come from "
            f"under-resourced schools (opportunity score <45). "
            f"Mean FRPL is {frpl_stats.get('mean', 'N/A')}%. "
            f"The committee should give extra weight to achievements from "
            f"schools in the bottom quartile of the opportunity distribution."
        )

    # ── Persistence ──────────────────────────────────────────────────

    def _save_cohort_report(self, result: Dict[str, Any]) -> None:
        """Save the cohort report to the database for later reference."""
        try:
            # Store as a JSON document in a dedicated table or analysis_history
            report_json = json.dumps(result, default=str)
            db.execute_query(
                """INSERT INTO school_analysis_history
                   (school_enrichment_id, analysis_type, analysis_data, created_at)
                   VALUES (0, 'cohort_analysis', %s, %s)""",
                (report_json, datetime.now(timezone.utc)),
                fetch=False,
            )
            logger.info("Pocahontas cohort report saved to school_analysis_history")
        except Exception as e:
            logger.warning(f"Could not save cohort report: {e}")

    # ── Lookup helpers ───────────────────────────────────────────────

    @staticmethod
    def get_latest_cohort_report() -> Optional[Dict[str, Any]]:
        """Retrieve the most recent cohort analysis from the database."""
        try:
            rows = db.execute_query(
                """SELECT analysis_data FROM school_analysis_history
                   WHERE analysis_type = 'cohort_analysis'
                   ORDER BY created_at DESC LIMIT 1"""
            )
            if rows:
                data = rows[0].get('analysis_data')
                if isinstance(data, str):
                    return json.loads(data)
                return data
        except Exception as e:
            logger.warning(f"Could not load cohort report: {e}")
        return None

    @staticmethod
    def get_school_context_multiplier(school_enrichment_id: int) -> Optional[Dict[str, Any]]:
        """Get the context multiplier for a specific school from the latest cohort report."""
        report = PocahontasCohortAnalyst.get_latest_cohort_report()
        if not report:
            return None
        multipliers = report.get('context_multipliers', {})
        return multipliers.get(school_enrichment_id) or multipliers.get(str(school_enrichment_id))

    async def process(self, message: str) -> str:
        """Process a message — not used for cohort-level analysis."""
        return "Pocahontas analyzes school cohorts via analyze_cohort() method"
