"""Merlin Student Evaluator - Produces overall recommendation using all agent outputs."""

import json
from typing import Dict, Any
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent


class MerlinStudentEvaluator(BaseAgent):
    """
    Specialized agent (Merlin) that synthesizes all other agent outputs into
    a final student recommendation.
    """

    def __init__(self, name: str, client: AzureOpenAI, model: str, db_connection=None):
        super().__init__(name, client)
        self.model = model
        self.db = db_connection

    async def evaluate_student(
        self,
        application: Dict[str, Any],
        agent_outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate an overall recommendation based on all agent outputs."""
        applicant_name = application.get("applicant_name", application.get("ApplicantName", "Unknown"))
        application_id = application.get("application_id", application.get("ApplicationID"))
        prompt = self._build_prompt(applicant_name, application, agent_outputs)

        try:
            response = self._create_chat_completion(
                operation="merlin.evaluate_student",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are Merlin, part of an NIH Department of Genetics review panel evaluating Emory NextGen applicants. Apply the requirements: rising junior or senior in high school, must be 16 years old by June 1, 2026, and must demonstrate interest in advancing STEM education to groups from a variety of backgrounds. Produce a fair, consistent final recommendation using evidence from all agents. Explain how evidence maps to the overall score. Return valid JSON only."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1400,
                temperature=1,
                response_format={"type": "json_object"}
            )

            payload = response.choices[0].message.content
            data = json.loads(payload)
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
            "Use Milo's training insights (if present) as a prior, but do not let them override direct evidence.",
            "Confirm eligibility against requirements and note any gaps or unknowns.",
            "",
            f"Applicant: {applicant_name}",
            "",
            "Milo training insights (JSON):",
            training_json,
            "",
            "Specialist agent outputs (JSON):",
            outputs_json,
            "",
            "Return a JSON object with the fields below:",
            "{",
            '  "applicant_name": "",',
            '  "overall_score": 0,',
            '  "recommendation": "Strongly Recommend|Recommend|Consider|Do Not Recommend",',
            '  "rationale": "(2-3 short paragraphs with evidence)",',
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
            temperature=1
        )
        assistant_message = response.choices[0].message.content
        self.add_to_history("assistant", assistant_message)
        return assistant_message
