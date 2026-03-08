"""
Naveen School Data Scientist Agent
Evaluates schools using NCES database records and AI to produce comprehensive
school profiles with opportunity scores, benchmarking, and narrative summaries.

Character: Naveen (Disney's "The Princess and the Frog")
Role: Takes raw NCES/CSV school data from the database and produces a
      School Evaluation Report — analysing the school's capabilities,
      resources, and outcomes against national benchmarks.
"""

import logging
import json
import re
from decimal import Decimal
from src.utils import safe_load_json
from typing import Dict, Any, Optional, List
from datetime import datetime

try:
    from .base_agent import BaseAgent
except Exception:
    from agents.base_agent import BaseAgent

try:
    from ..observability import get_tracer
except Exception:
    try:
        from observability import get_tracer
    except Exception:
        get_tracer = None

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


def _sanitize_for_json(obj):
    """Recursively convert Decimal/datetime values so json.dumps works."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return obj


class NaveenSchoolDataScientist(BaseAgent):
    """
    Naveen — School Data Scientist Agent

    Evaluates schools using imported NCES data from the database.  Produces a
    School Evaluation Report with:

    * Component scores (Academic Rigor, Resource Investment, Student Outcomes,
      Equity & Access) each 0-100
    * An overall Opportunity Score (0-100)
    * A narrative School Profile Summary explaining the school's strengths,
      gaps, and how student achievements should be interpreted in context
    * Confidence score reflecting data completeness

    Data flow:
        CSV import -> school_enriched_data table -> Naveen evaluation ->
        Moana (student context) -> Merlin (final evaluation)
    """

    def __init__(self, name: str = "Naveen School Data Scientist", client: Any = None, model: Optional[str] = None):
        """Initialize Naveen with AI client."""
        super().__init__(name=name, client=client)
        self.model = model or config.model_tier_workhorse or config.foundry_model_name or config.deployment_name
        self.model_display = self.model or "unknown"

    # ── Main entry point ─────────────────────────────────────────────

    def analyze_school(
        self,
        school_name: str,
        school_district: Optional[str] = None,
        state_code: Optional[str] = None,
        existing_data: Optional[Dict[str, Any]] = None,
        enrichment_focus: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Evaluate a school using its NCES database record and AI analysis.

        Reads the imported school data (enrollment, FRPL%, graduation rate,
        Title I status, etc.) and uses AI to produce a comprehensive School
        Evaluation Report benchmarked against national NCES standards.

        Args:
            school_name: Name of the school
            school_district: District name
            state_code: Two-letter state code (e.g. 'GA')
            existing_data: School record from school_enriched_data table
            enrichment_focus: Optional focus area for analysis

        Returns:
            Dict with enriched_data, opportunity_score, confidence_score,
            analysis_summary, school_profile, component scores, etc.
        """
        _otel_ctx = agent_run(
            "Naveen School Data Scientist", "analyze_school",
            context_data={"school_name": school_name, "state_code": state_code or ""},
            agent_id="naveen-school-data-scientist",
        )
        _otel_span = _otel_ctx.__enter__()

        result = {
            "school_name": school_name,
            "school_district": school_district,
            "state_code": state_code,
            "analysis_status": "analyzing",
            "timestamp": datetime.now().isoformat(),
            "school_profile": {},
            "enriched_data": {},
            "opportunity_score": 0,
            "confidence_score": 0,
            "analysis_summary": "",
            "data_quality_notes": "",
        }

        try:
            inferred_state = self._infer_state_code(state_code, existing_data)
            result["state_code"] = inferred_state

            # Determine data quality tier from existing record
            data_tier = self._assess_data_quality(existing_data)
            result["data_quality_notes"] = data_tier["label"]

            # Build the evaluation prompt presenting real DB data
            evaluation_prompt = self._build_evaluation_prompt(
                school_name, school_district, inferred_state,
                existing_data, enrichment_focus, data_tier,
            )

            # AI evaluation call
            logger.info(f"Naveen evaluating {school_name} ({data_tier['label']}) with AI model")
            try:
                from .telemetry_helpers import lm_call
            except Exception:
                from agents.telemetry_helpers import lm_call

            with lm_call(self.model, "school_evaluation", system_prompt="school_data_scientist"):
                ai_response = self._create_chat_completion(
                    operation="school_evaluation",
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self._system_prompt()},
                        {"role": "user", "content": evaluation_prompt},
                    ],
                    temperature=0.4,
                    max_completion_tokens=2500,
                )

            # Parse AI response
            if (ai_response and hasattr(ai_response, 'choices')
                    and ai_response.choices
                    and getattr(ai_response.choices[0].message, 'content', None)):
                response_text = ai_response.choices[0].message.content
                ai_data = self._extract_json(response_text)

                if ai_data:
                    result["enriched_data"] = ai_data
                    result["opportunity_score"] = ai_data.get("opportunity_score", 50)
                    result["confidence_score"] = ai_data.get("confidence_score", 70)
                    result["school_profile"] = {
                        "school_summary": ai_data.get("school_profile_summary", ""),
                        "academic_rigor_score": ai_data.get("academic_rigor_score", 0),
                        "resource_investment_score": ai_data.get("resource_investment_score", 0),
                        "student_outcomes_score": ai_data.get("student_outcomes_score", 0),
                        "equity_access_score": ai_data.get("equity_access_score", 0),
                        "key_insights": ai_data.get("key_insights", []),
                        "context_for_student": ai_data.get("context_for_student", ""),
                    }
                else:
                    result["enriched_data"]["raw_analysis"] = response_text
                    result["confidence_score"] = 50
                    logger.warning(f"Could not parse JSON from Naveen for {school_name}")

            # Refine if confidence is low
            if result["confidence_score"] < 60:
                refinement = self._refine_analysis(school_name, result, existing_data)
                result.update(refinement)

            result["analysis_status"] = "complete"
            result["status"] = "success"
            result["analysis_summary"] = self._generate_analysis_summary(result)

            logger.info(
                f"Naveen evaluation complete for {school_name}: "
                f"score={result['opportunity_score']}, confidence={result['confidence_score']}"
            )

        except Exception as e:
            logger.error(f"Error evaluating school {school_name}: {e}", exc_info=True)
            result["analysis_status"] = "error"
            result["status"] = "error"
            result["error"] = str(e)

        result["agent_name"] = self.name
        result["model_used"] = self.model
        result["model_display"] = self.model_display

        _otel_ctx.__exit__(None, None, None)
        return result

    # ── System prompt ────────────────────────────────────────────────

    @staticmethod
    def _system_prompt() -> str:
        """Return the system prompt with NCES benchmarks."""
        return (
            "You are Naveen, a school data scientist. You evaluate high schools using "
            "verified NCES data and produce actionable school profiles for scholarship evaluation.\n\n"
            "NCES CONDITION OF EDUCATION BENCHMARKS (2024):\n"
            "─────────────────────────────────────────────\n"
            "Graduation (ACGR 2021-22):\n"
            "  National: 87%  |  GA: 84%  |  Econ. disadvantaged: 81%\n"
            "  Asian/PI: 94%  |  White: 90%  |  Hispanic: 83%  |  Black: 81%  |  AI/AN: 74%\n"
            "  Students w/ disabilities: 71%  |  English learners: 72%\n\n"
            "College Enrollment (immediate):\n"
            "  Overall: 62%  |  4-year: 45%  |  2-year: 17%\n"
            "  Asian: 74%  |  White: 64%  |  Black: 61%  |  Hispanic: 58%\n"
            "  Female: 66%  |  Male: 57%\n\n"
            "School Resources:\n"
            "  Per-pupil spending: ~$14,000 national avg\n"
            "  Teacher salary: ~$66,000 national avg\n"
            "  Student-teacher ratio: ~16:1 national avg\n\n"
            "Academic Programs:\n"
            "  AP participation: ~35% of students take >= 1 AP course\n"
            "  AP pass rate (3+): ~60% nationally\n"
            "  10+ AP courses = strong academic investment\n"
            "  Dual enrollment: ~1.4M students (growing rapidly)\n\n"
            "Socioeconomic:\n"
            "  Title I schools: ~56% of public schools\n"
            "  Free/reduced lunch: ~52% of students eligible nationally\n"
            "  Dropout rate: 5.3% (AI/AN 9.9%, Hispanic 7.9%, Black 5.7%, White 4.3%, Asian 1.9%)\n\n"
            "YOUR TASK:\n"
            "Evaluate the provided school data against these benchmarks. Produce:\n"
            "1. Component scores (0-100): academic_rigor_score, resource_investment_score,\n"
            "   student_outcomes_score, equity_access_score\n"
            "2. Overall opportunity_score (0-100)\n"
            "3. confidence_score (0-100) based on data completeness\n"
            "4. school_profile_summary: 3-5 sentence narrative about this school\n"
            "5. key_insights: array of 3-5 specific observations\n"
            "6. context_for_student: 2-3 sentences explaining how achievements at THIS school\n"
            "   should be interpreted (is a B+ here impressive? is AP availability limited?)\n\n"
            "A school exceeding benchmarks given its demographics should score higher than raw\n"
            "numbers suggest. A 90% grad rate at a 70% FRPL school is more impressive than 92%\n"
            "at a 15% FRPL school.\n\n"
            "Return a single JSON object."
        )

    # ── Evaluation prompt ────────────────────────────────────────────

    def _build_evaluation_prompt(
        self,
        school_name: str,
        school_district: Optional[str],
        state_code: Optional[str],
        existing_data: Optional[Dict[str, Any]],
        enrichment_focus: Optional[str],
        data_tier: Dict[str, Any],
    ) -> str:
        """Build prompt presenting the real DB data for AI evaluation."""
        ed = existing_data or {}

        data_lines = [
            f"School: {school_name}",
            f"District: {school_district or ed.get('school_district', 'Unknown')}",
            f"State: {state_code or 'Unknown'}",
            f"County: {ed.get('county_name', 'Unknown')}",
            f"Data Quality: {data_tier['label']}",
            "",
            "-- ENROLLMENT & DEMOGRAPHICS (from NCES CCD) --",
            f"Total Enrollment: {self._fmt_int(ed.get('total_students'))}",
            f"Student-Teacher Ratio: {self._fmt(ed.get('student_teacher_ratio'))}",
            "",
            "-- SOCIOECONOMIC (from NCES CCD) --",
            f"Free Lunch %: {self._fmt(ed.get('free_lunch_percentage'))}",
            f"Reduced Lunch %: {self._fmt(ed.get('reduced_lunch_percentage'))}",
            f"Direct Certification %: {self._fmt(ed.get('direct_certification_pct'))}",
            f"Title I: {self._fmt_bool(ed.get('is_title_i'))}",
            f"Charter: {self._fmt_bool(ed.get('is_charter'))}",
            f"Magnet: {self._fmt_bool(ed.get('is_magnet'))}",
            f"Virtual: {self._fmt_bool(ed.get('is_virtual'))}",
            f"Locale Code: {ed.get('locale_code') or 'Unknown'}",
            "",
            "-- DISTRICT FINANCE (from NCES CCD) --",
            f"Per-Pupil Expenditure: {self._fmt_dollars(ed.get('district_exp_per_pupil'))}",
            f"Per-Pupil Revenue: {self._fmt_dollars(ed.get('district_rev_per_pupil'))}",
            f"District Poverty %: {self._fmt(ed.get('district_poverty_pct'))}",
            "",
            "-- TRENDS --",
            f"Enrollment Trend: {self._fmt_trend(ed.get('enrollment_trend_json'))}",
            f"FRPL Trend: {self._fmt_trend(ed.get('frpl_trend_json'))}",
            f"Years of Data: {ed.get('years_of_data') or 'Unknown'}",
            f"Latest School Year: {ed.get('latest_school_year') or 'Unknown'}",
        ]

        # Academic programs — check provenance for authoritative vs missing
        ap_count = ed.get('ap_course_count')
        honors_count = ed.get('honors_course_count')
        grad_rate = ed.get('graduation_rate')
        college_rate = ed.get('college_acceptance_rate')

        # Load provenance if available
        provenance = {}
        dsn = ed.get('data_source_notes') or ''
        if isinstance(dsn, str) and dsn.startswith('{'):
            try:
                provenance = json.loads(dsn)
            except (json.JSONDecodeError, TypeError):
                pass

        def _field_status(field_name, value):
            """Return (display_value, source_label) for a field."""
            src = provenance.get(field_name)
            if src:
                return str(value), f"VERIFIED ({src})"
            if value is not None and (not isinstance(value, (int, float)) or value > 0):
                return str(value), "from previous analysis"
            return None, "NOT AVAILABLE"

        data_lines.append("")
        data_lines.append("-- ACADEMIC PROGRAMS & OUTCOMES --")

        ap_val, ap_src = _field_status('ap_course_count', ap_count)
        hon_val, hon_src = _field_status('honors_course_count', honors_count)
        grad_val, grad_src = _field_status('graduation_rate', grad_rate)
        col_val, col_src = _field_status('college_acceptance_rate', college_rate)
        stem_val, stem_src = _field_status('stem_program_available', ed.get('stem_program_available'))
        ib_val, ib_src = _field_status('ib_program_available', ed.get('ib_program_available'))
        dual_val, dual_src = _field_status('dual_enrollment_available', ed.get('dual_enrollment_available'))
        ap_pass_val, ap_pass_src = _field_status('ap_exam_pass_rate', ed.get('ap_exam_pass_rate'))

        has_authoritative_academic = any(provenance.get(f) for f in [
            'ap_course_count', 'honors_course_count', 'graduation_rate', 'college_acceptance_rate'
        ])

        if has_authoritative_academic:
            data_lines.append("NOTE: Academic data below includes VERIFIED PUBLIC DATA from authoritative sources.")
            data_lines.append("Use these numbers as-is. Only estimate fields marked NOT AVAILABLE.")
        else:
            data_lines.append("NOTE: No authoritative academic data imported for this school.")
            data_lines.append("ALL academic fields below need YOUR ESTIMATE from school knowledge.")
            data_lines.append("Mark your estimates with confidence levels in the response.")

        data_lines.append(f"AP Courses: {ap_val or 'ESTIMATE NEEDED'} [{ap_src}]")
        data_lines.append(f"AP Exam Pass Rate: {ap_pass_val or 'ESTIMATE NEEDED'} [{ap_pass_src}]")
        data_lines.append(f"Honors Courses: {hon_val or 'ESTIMATE NEEDED'} [{hon_src}]")
        data_lines.append(f"STEM Programs: {stem_val or 'ESTIMATE NEEDED'} [{stem_src}]")
        data_lines.append(f"IB Program: {ib_val or 'ESTIMATE NEEDED'} [{ib_src}]")
        data_lines.append(f"Dual Enrollment: {dual_val or 'ESTIMATE NEEDED'} [{dual_src}]")
        data_lines.append(f"Graduation Rate: {(grad_val + '%') if grad_val else 'ESTIMATE NEEDED'} [{grad_src}]")
        data_lines.append(f"College Acceptance Rate: {(col_val + '%') if col_val else 'ESTIMATE NEEDED'} [{col_src}]")

        if ed.get('opportunity_score'):
            data_lines.append(f"\nPrevious Opportunity Score: {ed['opportunity_score']}")
        if ed.get('analysis_summary'):
            data_lines.append(f"Previous Analysis: {str(ed['analysis_summary'])[:500]}")

        prompt = "\n".join(data_lines)

        if enrichment_focus:
            prompt += f"\n\nFocus Area: {enrichment_focus}"

        prompt += (
            "\n\nUsing the NCES data above PLUS your knowledge of this specific school, "
            "produce a JSON evaluation. For fields marked 'ESTIMATE NEEDED', you MUST "
            "provide your best estimate — do NOT return 0.\n\n"
            "OPPORTUNITY SCORE FORMULA (you compute this):\n"
            "  opportunity_score = 0.30 * academic_rigor_score\n"
            "                    + 0.25 * student_outcomes_score\n"
            "                    + 0.25 * equity_access_score\n"
            "                    + 0.20 * resource_investment_score\n"
            "  Show your work in the school_profile_summary.\n\n"
            "Required JSON keys:\n"
            "- academic_rigor_score (0-100): AP/IB/honors breadth, STEM programs, dual enrollment\n"
            "- resource_investment_score (0-100): per-pupil spending, student-teacher ratio, class size\n"
            "- student_outcomes_score (0-100): graduation rate, college placement, AP pass rates\n"
            "- equity_access_score (0-100): FRPL context, Title I, serving disadvantaged students,\n"
            "  schools that BEAT expectations for their demographics score HIGHER\n"
            "- opportunity_score (0-100): weighted average per formula above\n"
            "- confidence_score (0-100): how confident you are in the data (lower if estimating)\n"
            "- school_profile_summary (string): 4-6 sentence narrative including the score breakdown\n"
            "- key_insights (array): 3-5 specific, non-generic insights about this school\n"
            "- context_for_student (string): 2-3 sentences for evaluators\n"
            "- graduation_rate (number): your best estimate\n"
            "- college_acceptance_rate (number): your best estimate\n"
            "- free_lunch_percentage (number): from data or estimate\n"
            "- total_enrollment (number): from data or estimate\n"
            "- funding_level (string): low / medium / high\n"
            "- academic_courses (number): AP course COUNT — must be > 0 for any school with AP program\n"
            "- stem_programs (boolean)\n"
            "- honors_programs (number): honors course count estimate\n"
            "- diversity_indicators (string)"
        )

        return prompt

    # ── Data quality assessment ──────────────────────────────────────

    @staticmethod
    def _assess_data_quality(existing_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Assess data completeness of the school record."""
        if not existing_data:
            return {"tier": "none", "label": "No existing data — AI estimation only", "fields_present": 0}

        key_fields = [
            'total_students', 'graduation_rate', 'free_lunch_percentage',
            'student_teacher_ratio', 'ap_course_count', 'district_exp_per_pupil',
            'is_title_i', 'locale_code',
        ]
        present = sum(1 for f in key_fields if existing_data.get(f) is not None)
        status = existing_data.get('analysis_status', '')

        if status == 'csv_imported' and present >= 5:
            return {"tier": "verified", "label": f"NCES verified data ({present}/{len(key_fields)} key fields)", "fields_present": present}
        if present >= 4:
            return {"tier": "rich", "label": f"Rich data ({present}/{len(key_fields)} key fields)", "fields_present": present}
        if present >= 2:
            return {"tier": "partial", "label": f"Partial data ({present}/{len(key_fields)} key fields)", "fields_present": present}
        return {"tier": "sparse", "label": f"Sparse data ({present}/{len(key_fields)} key fields)", "fields_present": present}

    # ── Formatters ───────────────────────────────────────────────────

    @staticmethod
    def _fmt(value) -> str:
        """Format a numeric value for display, handling None."""
        if value is None:
            return "Unknown"
        try:
            return f"{float(value):.1f}"
        except (ValueError, TypeError):
            return str(value)

    @staticmethod
    def _fmt_int(value) -> str:
        """Format an integer value."""
        if value is None:
            return "Unknown"
        try:
            return f"{int(value):,}"
        except (ValueError, TypeError):
            return str(value)

    @staticmethod
    def _fmt_bool(value) -> str:
        """Format a boolean value."""
        if value is None:
            return "Unknown"
        return "Yes" if value else "No"

    @staticmethod
    def _fmt_dollars(value) -> str:
        """Format dollar amount."""
        if value is None:
            return "Unknown"
        try:
            return f"${float(value):,.0f}"
        except (ValueError, TypeError):
            return str(value)

    @staticmethod
    def _fmt_trend(value) -> str:
        """Format a trend JSON field into a readable summary."""
        if value is None:
            return "Unknown"
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return str(value)[:100]
        if isinstance(value, dict):
            years = sorted(value.keys())
            if len(years) >= 2:
                first, last = years[0], years[-1]
                try:
                    delta = float(value[last]) - float(value[first])
                    direction = "+" if delta > 0 else "" if delta < 0 else "="
                    return f"{value[first]} -> {value[last]} ({direction}{delta:.0f}, {first}-{last})"
                except (ValueError, TypeError):
                    pass
            return str(value)[:100]
        return str(value)[:100]

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON object from AI response text."""
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return safe_load_json(json_match.group())
            return safe_load_json(text)
        except (json.JSONDecodeError, Exception):
            return None

    # ── Summary generation ───────────────────────────────────────────

    def _generate_analysis_summary(self, result: Dict[str, Any]) -> str:
        """Generate formatted analysis summary."""
        school = result.get("school_name", "School")
        profile = result.get("school_profile", {})
        score = result.get("opportunity_score", 0)
        confidence = result.get("confidence_score", 0)

        lines = [
            f"School Evaluation Report: {school}",
            "=" * 50,
            "",
            f"Agent: {self.name} ({self.model_display})",
            f"Data Quality: {result.get('data_quality_notes', 'Unknown')}",
            f"Analysis: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"Overall Opportunity Score: {score}/100 (confidence: {confidence}%)",
            "",
            "Component Scores:",
            f"  Academic Rigor:      {profile.get('academic_rigor_score', 'N/A')}/100",
            f"  Resource Investment: {profile.get('resource_investment_score', 'N/A')}/100",
            f"  Student Outcomes:    {profile.get('student_outcomes_score', 'N/A')}/100",
            f"  Equity & Access:     {profile.get('equity_access_score', 'N/A')}/100",
            "",
            f"Profile: {profile.get('school_summary', 'Not available')}",
            "",
            "Key Insights:",
        ]

        for insight in profile.get("key_insights", []):
            lines.append(f"  * {insight}")

        if profile.get("context_for_student"):
            lines.append("")
            lines.append(f"Student Context: {profile['context_for_student']}")

        return "\n".join(lines)

    # ── State inference ──────────────────────────────────────────────

    @staticmethod
    def _infer_state_code(
        state_code: Optional[str],
        existing_data: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """Infer a two-letter state code from existing data if missing."""
        if state_code:
            return state_code.strip().upper()

        if not existing_data:
            return None

        candidates = [
            existing_data.get("state_code"),
            existing_data.get("state"),
            existing_data.get("school_state"),
            existing_data.get("student_state"),
            existing_data.get("address_state"),
            existing_data.get("region_state"),
        ]

        for value in candidates:
            if isinstance(value, str) and len(value.strip()) == 2:
                return value.strip().upper()

        return None

    # ── Refinement ───────────────────────────────────────────────────

    def _refine_analysis(
        self,
        school_name: str,
        initial_result: Dict[str, Any],
        existing_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Refine analysis if initial confidence is low."""
        logger.info(f"Refining Naveen analysis for {school_name} (confidence: {initial_result['confidence_score']})")

        initial_json = json.dumps(_sanitize_for_json(initial_result['enriched_data']), default=str)[:2000]
        refinement_prompt = (
            f"The initial evaluation for '{school_name}' had low confidence "
            f"({initial_result['confidence_score']}%).\n\n"
            f"Initial findings: {initial_json}\n\n"
            "Please refine by:\n"
            "1. Making educated inferences based on district/region patterns\n"
            "2. Using your knowledge of this school or similar schools in the area\n"
            "3. Providing improved confidence assessment\n\n"
            "Return refined analysis as JSON with improved confidence_score and any corrected fields."
        )

        refined_response = self._create_chat_completion(
            operation="school_evaluation_refinement",
            model=self.model,
            messages=[
                {"role": "system", "content": "You are Naveen refining a school evaluation. Use your knowledge to fill data gaps and improve confidence."},
                {"role": "user", "content": refinement_prompt},
            ],
            temperature=0.3,
            max_completion_tokens=1500,
        )

        refined_data = {}
        try:
            if (refined_response and hasattr(refined_response, 'choices')
                    and refined_response.choices
                    and getattr(refined_response.choices[0].message, 'content', None)):
                refined_data = self._extract_json(refined_response.choices[0].message.content) or {}
        except Exception as e:
            logger.warning(f"Could not parse refined analysis: {e}")

        return {
            "enriched_data": refined_data or initial_result["enriched_data"],
            "confidence_score": refined_data.get("confidence_score", initial_result["confidence_score"] + 10),
        }

    async def process(self, message: str) -> str:
        """Process a message — not used for Naveen's school evaluation pipeline."""
        return "Naveen evaluates schools via analyze_school() method"

    # ── ML Feature Generation ────────────────────────────────────────

    @staticmethod
    def generate_school_features(school_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract a flat dict of ML-ready numeric features from a school enrichment record.

        Used by Milo to join structured school context into the training
        dataset — turning narrative color into quantitative signal.

        Returns only non-None values so Milo can distinguish "unknown" from
        "zero" (e.g., 0 AP courses is different from "AP data not available").
        """
        def _num(val, default=None):
            if val is None or val == '':
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        def _bool_int(val):
            if val is None:
                return None
            return 1 if val else 0

        features: Dict[str, Any] = {}

        # Identity / lookup
        if school_data.get('school_name'):
            features['school_name'] = school_data['school_name']
        if school_data.get('state_code'):
            features['state_code'] = school_data['state_code']
        if school_data.get('nces_id'):
            features['nces_id'] = school_data['nces_id']

        # Naveen component scores (0-100)
        for key in ('opportunity_score', 'data_confidence_score'):
            v = _num(school_data.get(key))
            if v is not None:
                features[f'school_{key}'] = v

        # Demographics & size
        v = _num(school_data.get('total_students'))
        if v is not None:
            features['school_enrollment'] = v
        v = _num(school_data.get('student_teacher_ratio'))
        if v is not None:
            features['school_student_teacher_ratio'] = v
        v = _num(school_data.get('graduation_rate'))
        if v is not None:
            features['school_graduation_rate'] = v
        v = _num(school_data.get('college_acceptance_rate'))
        if v is not None:
            features['school_college_acceptance_rate'] = v

        # Socioeconomic
        v = _num(school_data.get('free_lunch_percentage'))
        if v is not None:
            features['school_frpl_pct'] = v
        features['school_is_title_i'] = _bool_int(school_data.get('is_title_i'))
        features['school_is_charter'] = _bool_int(school_data.get('is_charter'))
        features['school_is_magnet'] = _bool_int(school_data.get('is_magnet'))
        v = _num(school_data.get('district_poverty_pct'))
        if v is not None:
            features['school_district_poverty_pct'] = v
        v = _num(school_data.get('district_exp_per_pupil'))
        if v is not None:
            features['school_per_pupil_spending'] = v

        # Academic programs
        v = _num(school_data.get('ap_course_count'))
        if v is not None:
            features['school_ap_count'] = v
        v = _num(school_data.get('ap_exam_pass_rate'))
        if v is not None:
            features['school_ap_pass_rate'] = v
        v = _num(school_data.get('honors_course_count'))
        if v is not None:
            features['school_honors_count'] = v
        features['school_has_stem'] = _bool_int(school_data.get('stem_program_available'))
        features['school_has_ib'] = _bool_int(school_data.get('ib_program_available'))
        features['school_has_dual_enrollment'] = _bool_int(school_data.get('dual_enrollment_available'))

        # Derived features
        frpl = _num(school_data.get('free_lunch_percentage'))
        grad = _num(school_data.get('graduation_rate'))
        if frpl is not None and grad is not None and frpl > 0:
            # "Value-add" — grad rate relative to socioeconomic challenge
            # Higher is better: a school with 70% FRPL and 90% grad rate
            # has a higher value-add than one with 10% FRPL and 92% grad
            features['school_value_add'] = round(grad - max(0, 85 - frpl * 0.15), 2)

        ap = _num(school_data.get('ap_course_count'))
        enrollment = _num(school_data.get('total_students'))
        if ap is not None and enrollment and enrollment > 0:
            features['school_ap_density'] = round(ap / (enrollment / 100), 4)

        # Resource tier (categorical → numeric)
        invest = (school_data.get('school_investment_level') or '').lower()
        if invest == 'high':
            features['school_investment_tier'] = 3
        elif invest == 'medium':
            features['school_investment_tier'] = 2
        elif invest == 'low':
            features['school_investment_tier'] = 1

        # Remove None values
        return {k: v for k, v in features.items() if v is not None}
