"""Merlin Student Evaluator - Produces overall recommendation using all agent outputs."""

import json
from typing import Dict, Any, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.telemetry_helpers import agent_run
from src.utils import safe_load_json


class MerlinStudentEvaluator(BaseAgent):
    """
    Specialized agent (Merlin) that synthesizes all other agent outputs into
    a final student recommendation.
    """

    def __init__(self, name: str, client: AzureOpenAI, model: Optional[str] = None, db_connection=None):
        super().__init__(name, client)
        self.model = model or config.foundry_model_name or config.deployment_name
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
            prompt = self._build_prompt(applicant_name, application, agent_outputs)

            try:
                response = self._create_chat_completion(
                    operation="merlin.evaluate_student",
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are Merlin, part of an NIH Department of Genetics review panel evaluating Emory NextGen applicants. Apply the requirements: rising junior or senior in high school, must be 16 years old by June 1, 2026, and must demonstrate interest in advancing STEM education to groups from a variety of backgrounds. PROGRAM CONTEXT: There are approximately 30 openings and over 1,000 applicants — selection is extremely competitive (roughly 3% acceptance rate). Produce a fair, consistent final recommendation using evidence from all agents. Include a 'nextgen_match' probability (0-100) reflecting the student's likelihood of being among the ~30 selected. Explicitly map evidence to the overall score and recommendation. Be decisive and avoid hedging. Return valid JSON only."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    max_completion_tokens=1400,
                    temperature=1,
                    refinements=2,
                    refinement_instruction="Refine the JSON recommendation focusing on evidence mapping: ensure each decision_driver cites specific agent outputs and numeric values are normalized.",
                    response_format={"type": "json_object"}
                )

                payload = response.choices[0].message.content
                data = safe_load_json(payload)
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
                    # Fall back to Milo's value if available in the agent_outputs
                    milo_align = agent_outputs.get('milo_alignment', {})
                    if isinstance(milo_align, dict) and 'nextgen_match' in milo_align:
                        data['nextgen_match'] = milo_align['nextgen_match']
                data["status"] = "success"
                data["agent"] = self.name

                if self.db and application_id:
                    self.db.save_merlin_evaluation(
                        application_id=application_id,
                        agent_name=self.name,
                        overall_score=data.get("overall_score"),
                        recommendation=data.get("recommendation"),
                        rationale=data.get("rationale"),
                        confidence=data.get("confidence"),
                        parsed_json=json.dumps(data, ensure_ascii=True)
                    )
                if span:
                    span.set_attribute("agent.result.score", str(data.get("overall_score", "")))
                    span.set_attribute("agent.result.recommendation", str(data.get("recommendation", "")))
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
        outputs_json = json.dumps(agent_outputs, ensure_ascii=True, default=str)
        training_insights = agent_outputs.get("data_scientist") or {}
        training_json = json.dumps(training_insights, ensure_ascii=True, default=str)
        prompt_parts = [
            "You are synthesizing multiple specialist evaluations into a final recommendation.",
            "Be explicit about how school context and recommendations affect the decision.",
            "If data conflicts, call it out and weigh reliability.",
            "Use Milo's training insights (if present) as a prior, comparing the current applicant to patterns observed in previous years' selected nominees and highlighting characteristics representative of Next Gen students. Do not let these insights override direct evidence.",
            "Confirm eligibility against requirements and note any gaps or unknowns.",

            "",
            f"Applicant: {applicant_name}",
            "",
            "Milo training insights (JSON):",
            training_json,
            "",
            "(The above JSON includes Milo's analysis of prior accepted vs not selected applicants. Compare the current student to that historical profile.)",
            "",
            "Specialist agent outputs (JSON):",
            outputs_json,
            "",
            "Return a JSON object with the fields below:",
            "{",
            '  "applicant_name": "",',
            '  "overall_score": 0,  // 0-100 integer',
            '  "nextgen_match": 0,  // 0-100 probability of being among ~30 selected from 1,000+ applicants',
            '  "recommendation": "Strongly Recommend|Recommend|Consider|Do Not Recommend",',
            '  "executive_summary": "(2-3 sentence executive summary of this student)",',
            '  "rationale": "(2-3 short paragraphs with evidence)",',
            '  "decision_drivers": ["(top 3 evidence-based drivers of the decision)"] ,',
            '  "top_risk": "(single biggest risk or open question)",',
            '  "key_strengths": ["(3-6 detailed strengths with evidence)"],',
            '  "key_risks": ["(2-4 specific risks or gaps)"],',
            '  "context_factors": ["(2-4 context notes that shaped the decision)"],',
            '  "evidence_used": ["(3-6 specific quotes or facts)"],',
            '  "confidence": "High|Medium|Low"',
            "}"
        ]

        return "\n".join(prompt_parts)

    async def process(self, message: str) -> str:
        """Process a general message."""
        self.add_to_history("user", message)
        messages = [
            {
                "role": "system",
                "content": "You are Merlin, part of an NIH Department of Genetics review panel evaluating Emory NextGen applicants. You produce final recommendations grounded in evidence and program requirements."
            }
        ] + self.conversation_history

        response = self._create_chat_completion(
            operation="merlin.process",
            model=self.model,
            messages=messages,
            max_completion_tokens=1000,
            temperature=1,
            refinements=2,
            refinement_instruction="Refine your assistant response to be more decisive and explicitly map evidence to any recommendations."
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
