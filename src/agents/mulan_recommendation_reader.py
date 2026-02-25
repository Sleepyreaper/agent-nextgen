"""Mulan Recommendation Reader - Parses recommendation letters into structured insights."""

import json
import re
from typing import Dict, Any, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.telemetry_helpers import agent_run
from src.utils import safe_load_json


class MulanRecommendationReader(BaseAgent):
    """
    Specialized agent (Mulan) for reading recommendation letters and extracting:
    - Strengths and growth areas
    - Evidence and specificity
    - Comparative statements
    - Endorsement strength and credibility
    """

    def __init__(self, name: str, client: AzureOpenAI, model: Optional[str] = None, db_connection=None):
        super().__init__(name, client)
        self.model = model or config.foundry_model_name or config.deployment_name
        self.db = db_connection

    async def parse_recommendation(self, recommendation_text: str, applicant_name: str = "Unknown", application_id: Optional[int] = None) -> Dict[str, Any]:
        """Parse a recommendation letter into structured data."""
        with agent_run("Mulan", "parse_recommendation", {"applicant": applicant_name, "application_id": str(application_id or "")}) as span:
            prompt = self._build_prompt(applicant_name, recommendation_text)

            try:
                # Use up to 8000 chars — Belle's section detection now routes only
                # recommendation pages here, so the input is focused.
                recommendation_input = recommendation_text[:8000]
                query_messages = [
                    {"role": "system", "content": "You are an expert extractor of recommendation letters. Extract concise evidence snippets, recommender identity clues, and endorsement signals.\n\nIMPORTANT: The text may contain page markers like '--- PAGE N of M ---'. These indicate page boundaries from a multi-page PDF. Note which page each recommendation or endorsement comes from. If multiple recommendation letters span different pages, identify each recommender separately. Focus on recommendation content and ignore any transcript or essay sections if present."},
                    {"role": "user", "content": f"Recommendation for {applicant_name}:\n\n{recommendation_input}"}
                ]

                format_template = [
                    {"role": "system", "content": "You are Mulan. Use the extracted facts to produce the final JSON with the required fields and evidence mappings. Return valid JSON only."},
                    {"role": "user", "content": "Extracted facts: {found}\n\nNow produce the structured JSON with fields: applicant_name, recommender_name, recommender_role, relationship, duration_known, key_strengths, growth_areas, comparative_statements, evidence_examples, core_competencies, endorsement_strength, specificity_score, credibility_notes, consensus_view, divergent_views, summary, eligibility_signals, confidence."}
                ]

                q_resp, response = self.two_step_query_format(
                    operation_base="mulan.parse_recommendation",
                    model=self.model,
                    query_messages=query_messages,
                    format_messages_template=format_template,
                    query_kwargs={"max_completion_tokens": 600, "temperature": 0},
                    format_kwargs={"max_completion_tokens": 1200, "temperature": 1, "refinements": 2, "refinement_instruction": "Refine the JSON output to ensure clear evidence mapping and consistent endorsement strength scoring. If multiple recommenders are present, separate them explicitly.", "response_format": {"type": "json_object"}}
                )

                payload = response.choices[0].message.content
                data = safe_load_json(payload)
                data["status"] = "success"
                data["agent"] = self.name

                if self.db and application_id:
                    self.db.save_mulan_recommendation(
                        application_id=application_id,
                        agent_name=self.name,
                        recommender_name=data.get("recommender_name"),
                        recommender_role=data.get("recommender_role"),
                        endorsement_strength=data.get("endorsement_strength"),
                        specificity_score=data.get("specificity_score"),
                        summary=data.get("summary"),
                        raw_text=recommendation_text,
                        parsed_json=json.dumps(data, ensure_ascii=True)
                    )
                if span:
                    span.set_attribute("agent.result.endorsement", str(data.get("endorsement_strength", "")))
                return data

            except Exception as e:
                return {
                    "status": "error",
                    "agent": self.name,
                    "error": str(e)
                }

    def _build_prompt(self, applicant_name: str, recommendation_text: str) -> str:
        """Build the prompt for parsing recommendation letters."""
        prompt_parts = [
            "You are parsing a recommendation letter for a competitive internship program.",
            "If multiple letters are concatenated, separate distinct recommenders and summarize consensus vs divergence.",
            "Avoid bias: do not overweight a single enthusiastic or negative letter if other evidence contradicts it.",
            "Return a JSON object with the fields below.",
            "",
            f"Applicant: {applicant_name}",
            "",
            "Recommendation letter:",
            recommendation_text,
            "",
            "Required JSON fields:",
            "{",
            "  \"applicant_name\": \"\",",
            "  \"recommender_name\": \"\",",
            "  \"recommender_role\": \"\",",
            "  \"relationship\": \"\",",
            "  \"duration_known\": \"\",",
            "  \"key_strengths\": [\"\"],",
            "  \"growth_areas\": [\"\"],",
            "  \"comparative_statements\": [\"\"],",
            "  \"evidence_examples\": [\"\"],",
            "  \"core_competencies\": {",
            "    \"stem_curiosity\": \"\",",
            "    \"initiative\": \"\",",
            "    \"community_impact\": \"\",",
            "    \"communication\": \"\",",
            "    \"resilience\": \"\"",
            "  },",
            "  \"endorsement_strength\": 0,",
            "  \"specificity_score\": 0,",
            "  \"credibility_notes\": \"\",",
            "  \"consensus_view\": \"(what most recommenders agree on)\",",
            "  \"divergent_views\": [\"(where recommenders disagree)\"],",
            "  \"summary\": \"(3-5 sentences with concrete examples)\",",
            "  \"eligibility_signals\": [\"(any mention of grade level, age, or STEM access goals)\"],",
            "  \"confidence\": \"High|Medium|Low\"",
            "}"
        ]

        return "\n".join(prompt_parts)

    async def process(self, message: str) -> str:
        """Process a general message."""
        self.add_to_history("user", message)
        messages = [
            {
                "role": "system",
                "content": "You are Mulan, part of an NIH Department of Genetics review panel evaluating Emory NextGen applicants. You extract structured insights with evidence and note any eligibility signals from recommendations."
            }
        ] + self.conversation_history

        response = self._create_chat_completion(
            operation="mulan.process",
            model=self.model,
            messages=messages,
            max_completion_tokens=1000,
            temperature=1,
            refinements=2,
            refinement_instruction="Refine your assistant response to improve extraction of recommender details and evidence snippets."
        )
        assistant_message = response.choices[0].message.content
        self.add_to_history("assistant", assistant_message)
        return assistant_message
