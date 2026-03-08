"""Merlin Student Evaluator — GPT-5-mini final synthesis agent.

Produces an overall recommendation, rubric scores, and a concise
applicant summary written for Emory faculty reviewers.
"""

import json
import logging
from typing import Dict, Any, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.telemetry_helpers import agent_run
from src.utils import safe_load_json

logger = logging.getLogger(__name__)


class MerlinStudentEvaluator(BaseAgent):
    """Merlin — final-stage evaluator powered by GPT-5-mini.

    Synthesises outputs from every upstream agent (Rapunzel, Tiana, Mulan,
    Moana, Gaston, Milo) into a single authoritative recommendation and a
    5-to-8-sentence applicant summary suitable for faculty review.
    """

    EMOJI = "🧙"
    DESCRIPTION = "Final Evaluator — GPT-5-mini deep synthesis"

    def __init__(self, name: str, client: AzureOpenAI, model: Optional[str] = None, db_connection=None):
        super().__init__(name, client)
        self.model = model or config.model_tier_merlin or config.foundry_model_name or config.deployment_name
        self.db = db_connection

    async def evaluate_student(
        self,
        application: Dict[str, Any],
        agent_outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate an overall recommendation based on all agent outputs."""
        applicant_name = application.get("applicant_name", application.get("ApplicantName", "Unknown"))
        application_id = application.get("application_id", application.get("ApplicationID"))

        with agent_run("Merlin", "evaluate_student", {"applicant": applicant_name, "application_id": str(application_id or "")}) as span:
            system_prompt = self._system_prompt()
            user_prompt = self._build_prompt(applicant_name, application, agent_outputs)

            try:
                response = self._create_chat_completion(
                    operation="merlin.evaluate_student",
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_completion_tokens=2400,
                    temperature=0,
                    refinements=2,
                    refinement_instruction=(
                        "Refine the JSON recommendation: (1) ensure each decision_driver "
                        "cites a specific agent output and numeric value, (2) verify the "
                        "applicant_summary is exactly 5-8 sentences and reads naturally for "
                        "a genetics-department faculty audience, (3) confirm rubric dimension "
                        "scores sum correctly to rubric_total, and (4) double-check that "
                        "nextgen_match aligns with overall_rating tier."
                    ),
                    response_format={"type": "json_object"}
                )

                payload = response.choices[0].message.content
                data = safe_load_json(payload)
                if not isinstance(data, dict):
                    data = {"raw_response": str(data)}

                # ── Helper: detect if data needs a retry ──
                def _needs_retry(d):
                    """True if result is empty or a message-object wrapper."""
                    if not isinstance(d, dict):
                        return True
                    # Message-object wrapper with empty content
                    if 'role' in d and 'refusal' in d:
                        inner = d.get('content', '')
                        if not inner or (isinstance(inner, str) and not inner.strip()):
                            return True
                    # Completely empty / raw_response-only result
                    if set(d.keys()) <= {'raw_response', 'status'} and not d.get('raw_response'):
                        return True
                    return False

                def _unwrap_message_object(d):
                    """If d is a Foundry message-object wrapper, unwrap it."""
                    if not isinstance(d, dict) or 'role' not in d or 'refusal' not in d:
                        return d
                    inner = d.get('content', '')
                    if isinstance(inner, str) and inner.strip():
                        try:
                            unwrapped = json.loads(inner)
                            if isinstance(unwrapped, dict):
                                return unwrapped
                        except Exception:
                            return {"raw_response": inner}
                    elif isinstance(inner, dict):
                        return inner
                    return d  # Return as-is if can't unwrap

                # Detect when the Foundry adapter returns a message-object-like
                # dict (has 'role'/'refusal' keys with a nested 'content' field)
                # instead of the actual AI output.  Unwrap the inner content.
                data = _unwrap_message_object(data)

                # ── Retry loop: up to 2 retries if result is empty ──
                if _needs_retry(data):
                    for retry_num in range(1, 3):
                        logger.warning(
                            "Merlin received empty/invalid response for application %s "
                            "(attempt %d); retrying (attempt %d)...",
                            application_id, retry_num, retry_num + 1,
                        )
                        try:
                            retry_response = self._create_chat_completion(
                                operation=f"merlin.evaluate_student.retry{retry_num}",
                                model=self.model,
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt}
                                ],
                                max_completion_tokens=3000,
                                temperature=0,
                                refinements=1,
                                refinement_instruction=(
                                    "Ensure the JSON contains overall_score, recommendation, "
                                    "rationale, applicant_summary, and nextgen_match fields."
                                ),
                                response_format={"type": "json_object"}
                            )
                            retry_payload = retry_response.choices[0].message.content
                            retry_data = safe_load_json(retry_payload)
                            if isinstance(retry_data, dict):
                                retry_data = _unwrap_message_object(retry_data)
                            if (isinstance(retry_data, dict)
                                    and not _needs_retry(retry_data)
                                    and retry_data.get('overall_score') is not None):
                                data = retry_data
                                logger.info(
                                    "Merlin retry %d succeeded for application %s",
                                    retry_num, application_id,
                                )
                                break
                            else:
                                logger.warning(
                                    "Merlin retry %d also returned empty for application %s",
                                    retry_num, application_id,
                                )
                        except Exception as retry_err:
                            logger.error(
                                "Merlin retry %d failed for application %s: %s",
                                retry_num, application_id, retry_err,
                            )
                    else:
                        # All retries exhausted
                        logger.error(
                            "Merlin all retries exhausted for application %s — empty response",
                            application_id,
                        )
                        data = {"raw_response": "", "status": "empty_response"}

                normalized = self._normalize_score(
                    data.get("overall_score"),
                    data.get("recommendation")
                )
                data["overall_score"] = normalized["score"]
                if normalized["adjusted"]:
                    data["score_adjusted"] = True
                    data["score_adjustment_reason"] = normalized["reason"]

                # Ensure nextgen_match is present
                if 'nextgen_match' not in data:
                    milo_align = agent_outputs.get('milo_alignment', {})
                    if isinstance(milo_align, dict) and 'nextgen_match' in milo_align:
                        data['nextgen_match'] = milo_align['nextgen_match']

                # ── applicant_summary ↔ executive_summary backward compat ──
                # The new prompt asks for `applicant_summary` (5-8 sentences).
                # The UI reads `executive_summary` so we keep both in sync.
                if data.get('applicant_summary') and not data.get('executive_summary'):
                    # Build a short exec summary from the first 2-3 sentences
                    sentences = [s.strip() for s in data['applicant_summary'].replace('\n', ' ').split('.') if s.strip()]
                    data['executive_summary'] = '. '.join(sentences[:3]) + '.' if sentences else data['applicant_summary']
                elif data.get('executive_summary') and not data.get('applicant_summary'):
                    data['applicant_summary'] = data['executive_summary']

                # Only mark as "success" if we actually got meaningful output
                if data.get("status") != "empty_response":
                    data["status"] = "success"
                data["agent"] = self.name

                # Only persist to DB if we have meaningful content
                # (prevents empty rows that block richer data from applications.agent_results)
                merlin_has_content = (
                    data.get("overall_score") is not None
                    or data.get("recommendation")
                    or data.get("rationale")
                    or data.get("executive_summary")
                    or data.get("applicant_summary")
                )
                if self.db and application_id and merlin_has_content:
                    self.db.save_merlin_evaluation(
                        application_id=application_id,
                        agent_name=self.name,
                        overall_score=data.get("overall_score"),
                        recommendation=data.get("recommendation"),
                        rationale=data.get("rationale"),
                        confidence=data.get("confidence"),
                        parsed_json=json.dumps(data, ensure_ascii=True)
                    )
                elif self.db and application_id and not merlin_has_content:
                    logger.warning(
                        "Merlin skipping DB save for application %s — no meaningful content",
                        application_id,
                    )
                if span:
                    span.set_attribute("agent.result.score", str(data.get("overall_score", "")))
                    span.set_attribute("agent.result.recommendation", str(data.get("recommendation", "")))
                    span.set_attribute("agent.result.overall_rating", str(data.get("overall_rating", "")))
                return data

            except Exception as e:
                return {
                    "status": "error",
                    "agent": self.name,
                    "error": str(e)
                }

    def _build_prompt(
        self,
        applicant_name: str,
        application: Dict[str, Any],
        agent_outputs: Dict[str, Any]
    ) -> str:
        """Build the synthesis prompt from agent outputs."""
        # ── prepare data sections ──────────────────────────────────
        outputs_json = json.dumps(agent_outputs, ensure_ascii=True, default=str)

        training_insights = agent_outputs.get("data_scientist") or {}
        training_json = json.dumps(training_insights, ensure_ascii=True, default=str)

        milo_alignment = agent_outputs.get("milo_alignment") or {}
        alignment_json = json.dumps(milo_alignment, ensure_ascii=True, default=str)

        # ── build prompt ─────────────────────────────────────────────
        prompt_parts = [
            "══════════════════════════════════════════════════════════════=",
            "APPLICANT UNDER REVIEW",
            "══════════════════════════════════════════════════════════════=",
            f"Name: {applicant_name}",
            "",

            "══════════════════════════════════════════════════════════════=",
            "MILO — TRAINING INSIGHTS (historical acceptance model)",
            "══════════════════════════════════════════════════════════════=",
            training_json,
            "",
            "(Milo analyzed prior accepted vs. not-selected applicants. Use these "
            "patterns as a Bayesian prior — where does this applicant sit relative "
            "to the historical profile of selected students? Do NOT let the prior "
            "override strong direct evidence.)",
            "",

            "══════════════════════════════════════════════════════════════=",
            "MILO — INDIVIDUAL ALIGNMENT (this student vs. model)",
            "══════════════════════════════════════════════════════════════=",
            alignment_json,
            "",

            "══════════════════════════════════════════════════════════════=",
            "SPECIALIST AGENT OUTPUTS",
            "══════════════════════════════════════════════════════════════=",
            "The following JSON contains outputs from every upstream agent:",
            "  • Rapunzel — Academic record analysis (GPA, rigor, coursework)",
            "  • Tiana    — Essay / video evaluation + STEM interest scoring",
            "  • Mulan    — Recommendation letter analysis",
            "  • Moana    — School context & opportunity assessment",
            "  • Milo     — Data scientist training insights & alignment",
            "",
            outputs_json,
            "",
        ]

        # ── Normalized scores (common 0-100 scale) ──
        norm_scores = agent_outputs.get("_normalized_scores") or {}
        if norm_scores:
            prompt_parts.extend([
                "═══════════════════════════════════════════════════════════════",
                "NORMALIZED AGENT SCORES (all on 0-100 scale)",
                "═══════════════════════════════════════════════════════════════",
                json.dumps(norm_scores, ensure_ascii=True),
                "",
                "(These scores are mechanically normalized to 0-100 from each agent's native scale. "
                "Use them as a cross-agent calibration reference alongside the raw outputs above.)",
                "",
            ])

        # ── Pocahontas context multiplier ──
        ctx_mult = agent_outputs.get("_context_multiplier") or {}
        multiplier = ctx_mult.get("multiplier", 1.0) if isinstance(ctx_mult, dict) else 1.0
        ctx_reasons = ctx_mult.get("reasons", []) if isinstance(ctx_mult, dict) else []
        data_avail = ctx_mult.get("data_availability", "sufficient") if isinstance(ctx_mult, dict) else "sufficient"

        if data_avail == 'insufficient':
            prompt_parts.extend([
                "═══════════════════════════════════════════════════════════════",
                "SCHOOL DATA NOTICE",
                "═══════════════════════════════════════════════════════════════",
                "This student's school has INSUFFICIENT publicly available data.",
                "This is common for private, charter, and religious schools that",
                "do not report to NCES/GOSA. This does NOT indicate an under-resourced school.",
                "Do NOT adjust scores based on school context. Evaluate this student",
                "purely on their application materials, transcript, and recommendations.",
                "",
            ])
        elif multiplier > 1.0:
            prompt_parts.extend([
                "═══════════════════════════════════════════════════════════════",
                "EQUITY CONTEXT MULTIPLIER (from Pocahontas Cohort Analysis)",
                "═══════════════════════════════════════════════════════════════",
                f"Multiplier: {multiplier}x",
                f"Reasons: {', '.join(ctx_reasons) if ctx_reasons else 'N/A'}",
                "",
                f"This student's school is in the bottom tier of the applicant pool. "
                f"Pocahontas recommends weighting their academic achievements {int((multiplier - 1) * 100)}% "
                f"higher than face value. Apply this multiplier when interpreting GPA, "
                f"course rigor, and AP access relative to other applicants from better-resourced schools.",
                "",
            ])

        prompt_parts.extend([
            "═══════════════════════════════════════════════════════════════",
            "YOUR TASK",
            "═══════════════════════════════════════════════════════════════",
            "Think deeply about this student. Cross-reference every agent's output. "
            "Look for corroborating evidence AND contradictions. Consider the whole "
            "person — their context, their trajectory, their potential to contribute "
            "to a genetics research lab at Emory this summer.",
            "",
            "Then return a single JSON object with EXACTLY these fields:",
            "",
            "{",
            '  "applicant_name": "<full name>",',
            '  "overall_score": <0-100 integer>,',
            '  "nextgen_match": <0-100 probability of being among ~30 selected>,',
            '  "overall_rating": "STRONG ADMIT | ADMIT | WAITLIST | DECLINE",',
            '  "recommendation": "Strongly Recommend | Recommend | Consider | Do Not Recommend",',
            "",
            '  "applicant_summary": "<EXACTLY 5-8 SENTENCES. Written for Emory Human Genetics '
            'faculty. See system prompt for detailed guidelines. This is the most '
            'important field — faculty read this first.>",',
            "",
            '  "executive_summary": "<2-3 sentence version of the above for quick scanning>",',
            "",
            '  "rubric_scores": {',
            '    "academic_record": <0-3>,',
            '    "stem_interest": <0-3>,',
            '    "essay_video": <0-3>,',
            '    "recommendation_letter": <0-2>,',
            '    "bonus": <0-1>',
            '  },',
            '  "rubric_total": <0-12, must equal sum of rubric_scores>,',
            "",
            '  "rationale": "<2-3 paragraphs mapping evidence to your decision>",',
            '  "decision_drivers": ["<top 3-5 evidence-based drivers>"],',
            '  "top_risk": "<single biggest risk or open question>",',
            '  "key_strengths": ["<3-6 specific strengths with cited evidence>"],',
            '  "key_risks": ["<2-4 specific risks or gaps>"],',
            '  "context_factors": ["<2-4 contextual notes — school resources, SES, geography>"],',
            '  "evidence_used": ["<3-6 concrete quotes or facts from agent outputs>"],',
            '  "lab_readiness": "<1-2 sentences: would this student thrive in a wet-lab or '
            'computational genetics environment?>",',
            '  "confidence": "High | Medium | Low"',
            "}",
        ])

        return "\n".join(prompt_parts)

    # ── system prompt ─────────────────────────────────────────────────

    @staticmethod
    def _system_prompt() -> str:
        """Return the full system prompt for Merlin's GPT-5-mini evaluation."""
        return (
            "You are **Merlin**, the final-stage evaluator for the Emory University "
            "Next Generation Internship (Next Gen) — Summer 2026.\n\n"

            "═══════════════════════════════════════════════════════════════\n"
            "AUDIENCE & PURPOSE\n"
            "═══════════════════════════════════════════════════════════════\n"
            "Your output will be read by professors in the **Department of Human "
            "Genetics at Emory University School of Medicine** who are selecting "
            "the top high-school applicants for paid summer research internships "
            "in their laboratories. Write with the precision and clinical judgment "
            "these faculty expect.\n\n"

            "═══════════════════════════════════════════════════════════════\n"
            "PROGRAM FACTS\n"
            "═══════════════════════════════════════════════════════════════\n"
            "• ~30 seats out of 1,000+ applicants (~3% acceptance rate).\n"
            "• Interns work alongside Emory faculty and graduate students on "
            "  active research projects in human genetics and related STEM fields.\n"
            "• Applicants must be rising juniors or seniors in high school, at "
            "  least 16 years old by June 1 2026.\n"
            "• The program prioritizes students from under-represented and "
            "  under-resourced backgrounds who demonstrate genuine passion for "
            "  STEM and potential to thrive in a research environment.\n\n"

            "═══════════════════════════════════════════════════════════════\n"
            "SCORING RUBRIC (0-12 POINTS + BONUS)\n"
            "═══════════════════════════════════════════════════════════════\n"
            "You MUST compute and include every dimension score listed below, "
            "drawing evidence from the specialist agents indicated:\n\n"

            "1. **Academic Record** (0-3) — Rapunzel's academic_record_score\n"
            "   3 = Exceptional (top-tier GPA, AP/IB/DE rigor, STEM coursework)\n"
            "   2 = Solid (strong GPA, some advanced courses)\n"
            "   1 = Adequate (average record)\n"
            "   0 = Weak or insufficient data\n\n"

            "2. **STEM Interest & Enthusiasm** (0-3) — Tiana's stem_interest_score\n"
            "   3 = Deep, specific passion (named fields, prior projects, career vision)\n"
            "   2 = Clear interest with some specifics\n"
            "   1 = Vague or generic mention\n"
            "   0 = No discernible STEM interest\n\n"

            "3. **Personal Essay / Video** (0-3) — Tiana's essay_score\n"
            "   3 = Exceptional: compelling narrative, authentic voice, clear connection "
            "     to STEM and Next Gen mission\n"
            "   2 = Good: solid effort, reasonable quality\n"
            "   1 = Minimal effort or off-topic\n"
            "   0 = Missing or very weak\n\n"

            "4. **Letter of Recommendation** (0-2) — Mulan's recommendation_score\n"
            "   2 = Strong, specific endorsement from someone who knows the student well\n"
            "   1 = Adequate or generic\n"
            "   0 = Weak, missing, or perfunctory\n\n"

            "5. **Bonus** (0-1) — award ONLY for truly exceptional circumstances:\n"
            "   prior research experience, overcoming significant adversity, "
            "   extraordinary STEM achievement, or exceptional community impact\n\n"

            "rubric_total = sum of all five dimensions (max 12)\n\n"

            "ADDITIONAL FACTORS (from Gaston & Moana):\n"
            "• Quick-pass eligibility (age, grade level)\n"
            "• Under-represented / under-resourced background (SES context)\n"
            "• Geographic access to STEM opportunities (Moana's opportunity score)\n"
            "• Previous research or advanced coursework\n\n"

            "═══════════════════════════════════════════════════════════════\n"
            "OVERALL RATING TIERS\n"
            "═══════════════════════════════════════════════════════════════\n"
            "Based on ALL evidence, assign exactly one of:\n"
            "  STRONG ADMIT  — top-tier, clear selection (nextgen_match ≥ 75)\n"
            "  ADMIT         — strong, should be selected (nextgen_match 55-74)\n"
            "  WAITLIST      — competitive but not in top cohort (nextgen_match 35-54)\n"
            "  DECLINE       — does not meet threshold (nextgen_match < 35)\n\n"

            "═══════════════════════════════════════════════════════════════\n"
            "APPLICANT SUMMARY (CRITICAL — READ CAREFULLY)\n"
            "═══════════════════════════════════════════════════════════════\n"
            "You MUST produce a field called 'applicant_summary' containing "
            "**exactly 5 to 8 sentences**. This summary is the primary text "
            "that Emory Human Genetics faculty will read when deciding which "
            "students to interview.\n\n"

            "Writing guidelines for the summary:\n"
            "• Open with the student's name, grade, school, and geographic context.\n"
            "• Highlight academic trajectory (GPA, rigor, standout courses).\n"
            "• Describe the student's STEM passion with concrete specifics — "
            "  projects, research interests, career aspirations.\n"
            "• Note the strength and substance of the recommendation letter.\n"
            "• Call out any distinguishing factor: adversity overcome, prior "
            "  research, exceptional community impact, or unique perspective.\n"
            "• Close with your professional judgment on whether this student "
            "  would thrive in an Emory genetics research lab this summer.\n"
            "• Write in a concise, clinical tone suited for faculty on a "
            "  selection committee — no filler, every sentence must add value.\n"
            "• Do NOT exceed 8 sentences.\n\n"

            "═══════════════════════════════════════════════════════════════\n"
            "DEEP-THINKING INSTRUCTIONS\n"
            "═══════════════════════════════════════════════════════════════\n"
            "Before producing JSON, reason deeply about this student:\n"
            "1. Cross-reference ALL agent outputs — look for corroborating and "
            "   conflicting evidence across Rapunzel, Tiana, Mulan, Moana, "
            "   Gaston, and Milo.\n"
            "2. Identify information gaps: what is unknown? How does uncertainty "
            "   affect your confidence?\n"
            "3. Consider the student holistically: a mediocre GPA from a "
            "   severely under-resourced school may demonstrate more grit than "
            "   a perfect GPA from a well-funded school.\n"
            "4. Compare implicitly to the historical acceptance profile (from "
            "   Milo's training insights) — does this student's pattern match "
            "   past selectees?\n"
            "5. Think about lab readiness: would this student be safe, curious, "
            "   and productive in a wet-lab or computational genetics setting?\n"
            "6. Be decisive. Faculty want clear, defensible calls, not hedging.\n\n"

            "Return valid JSON only."
        )

    # ── general conversation ─────────────────────────────────────────

    async def process(self, message: str) -> str:
        """Process a general message."""
        self.add_to_history("user", message)
        messages = [
            {
                "role": "system",
                "content": self._system_prompt()
            }
        ] + self.conversation_history

        response = self._create_chat_completion(
            operation="merlin.process",
            model=self.model,
            messages=messages,
            max_completion_tokens=1200,
            temperature=0,
            refinements=2,
            refinement_instruction=(
                "Refine your response to be more decisive. Map evidence to "
                "recommendations explicitly and keep sentences tight."
            )
        )
        assistant_message = response.choices[0].message.content
        self.add_to_history("assistant", assistant_message)
        return assistant_message

    def _normalize_score(self, score: Any, recommendation: Any) -> Dict[str, Any]:
        """Normalize score to 0-100 and align with recommendation bands when needed."""
        adjusted = False
        reason = ""

        try:
            score_val = float(score)
        except (TypeError, ValueError):
            return {"score": None, "adjusted": False, "reason": ""}

        if 0 <= score_val <= 1:
            score_val = score_val * 100
            adjusted = True
            reason = "Scaled 0-1 score to 0-100."
        elif 0 <= score_val <= 10:
            score_val = score_val * 10
            adjusted = True
            reason = "Scaled 0-10 score to 0-100."

        score_val = max(0, min(100, score_val))

        rec = (recommendation or "").strip().lower()
        bands = {
            "strongly recommend": (85, 100),
            "recommend": (70, 84),
            "consider": (55, 69),
            "do not recommend": (0, 54)
        }
        if rec in bands:
            low, high = bands[rec]
            if score_val < low:
                score_val = float(low)
                adjusted = True
                reason = reason or "Adjusted score to match recommendation band."
            elif score_val > high:
                score_val = float(high)
                adjusted = True
                reason = reason or "Adjusted score to match recommendation band."

        return {"score": round(score_val, 1), "adjusted": adjusted, "reason": reason}
