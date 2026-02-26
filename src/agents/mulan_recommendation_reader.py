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
        self.model = model or config.model_tier_workhorse or config.foundry_model_name or config.deployment_name
        self.db = db_connection

    async def parse_recommendation(self, recommendation_text: str, applicant_name: str = "Unknown", application_id: Optional[int] = None) -> Dict[str, Any]:
        """Parse a recommendation letter into structured data."""
        with agent_run("Mulan", "parse_recommendation", {"applicant": applicant_name, "application_id": str(application_id or "")}) as span:
            # Guard: if no recommendation text was provided, return a clean
            # "missing" result instead of sending empty text to the LLM.
            if not recommendation_text or not recommendation_text.strip() or len(recommendation_text.strip()) < 30:
                print(f"[Mulan] WARNING: No recommendation text for {applicant_name} (len={len(recommendation_text or '')}). Returning missing-data result.")
                return {
                    "status": "success",
                    "agent": self.name,
                    "applicant_name": applicant_name,
                    "recommender_name": "N/A",
                    "recommender_role": "N/A",
                    "relationship": "N/A",
                    "duration_known": "N/A",
                    "key_strengths": [],
                    "growth_areas": [],
                    "comparative_statements": [],
                    "evidence_examples": [],
                    "core_competencies": {},
                    "endorsement_strength": 0,
                    "specificity_score": 0,
                    "recommendation_score": 0,
                    "credibility_notes": "No recommendation letter was provided or detected in the uploaded documents.",
                    "consensus_view": "No recommendation available.",
                    "divergent_views": [],
                    "summary": "No recommendation letter was provided for this student. The program expects two letters of recommendation.",
                    "eligibility_signals": [],
                    "confidence": "Low",
                    "note": "No recommendation text available — document may not contain a recommendation letter."
                }

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
                    {"role": "system", "content": "You are Mulan. Use the extracted facts to produce the final JSON with the required fields and evidence mappings. Return valid JSON only.\n\n2024 NEXTGEN SCORING RUBRIC — YOUR DIMENSION: LETTER OF RECOMMENDATION (0-2 Points)\nYou are responsible for scoring the recommendation letter dimension of the official scoring rubric.\nScoring Scale:\n  2 = Strong endorsement: recommender clearly knows the student well, provides specific examples of STEM aptitude/character, enthusiastic and detailed support, comparison to other top students.\n  1 = Adequate endorsement: positive but generic, limited specifics, or recommender does not know student deeply.\n  0 = Weak/missing: form-letter quality, no substance, concerns raised, or no recommendation provided.\n\nNOTE: The program expects TWO letters of recommendation. If only one is provided, note that. If both are present, score based on the stronger of the two but note quality of both.\n\nCRITICAL — All score fields MUST be NUMERIC values, not strings:\n  - endorsement_strength: a number from 0 to 10 (NOT a word like 'Strong')\n  - specificity_score: a number from 0 to 10 (NOT a word like 'High')\n  - recommendation_score: a number from 0 to 2\n  - confidence: a string 'High', 'Medium', or 'Low' (this is the ONLY text score field)"},
                    {"role": "user", "content": "Extracted facts: {found}\n\nNow produce the structured JSON with fields: applicant_name, recommender_name, recommender_role, relationship, duration_known, key_strengths, growth_areas, comparative_statements, evidence_examples, core_competencies, endorsement_strength (NUMBER 0-10), specificity_score (NUMBER 0-10), recommendation_score (NUMBER 0-2), credibility_notes, consensus_view, divergent_views, summary, eligibility_signals, confidence."}
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
                if not isinstance(data, dict):
                    data = {"raw_response": str(data)}
                data["status"] = "success"
                data["agent"] = self.name

                # Coerce endorsement_strength and specificity_score to
                # numeric values.  The LLM sometimes returns words like
                # "Strong" or "High" instead of numbers.
                def _to_numeric(val, max_val=10.0):
                    if val is None:
                        return None
                    if isinstance(val, (int, float)):
                        return float(val)
                    if isinstance(val, str):
                        # Try direct parse first
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            pass
                        # Map common word responses to numbers
                        word_map = {
                            'strong': 8.0, 'very strong': 9.0,
                            'high': 8.0, 'very high': 9.0,
                            'moderate': 5.0, 'medium': 5.0, 'adequate': 5.0,
                            'low': 2.0, 'weak': 1.0, 'very low': 1.0,
                            'none': 0.0, 'n/a': None, 'na': None,
                        }
                        return word_map.get(val.strip().lower(), max_val / 2)
                    return None

                endorsement_val = _to_numeric(data.get("endorsement_strength"))
                specificity_val = _to_numeric(data.get("specificity_score"))
                # Also fix recommendation_score (0-2) in case it's a string
                rec_score_raw = data.get("recommendation_score")
                if isinstance(rec_score_raw, str):
                    try:
                        data["recommendation_score"] = float(rec_score_raw)
                    except (ValueError, TypeError):
                        word_map_rec = {'strong': 2, 'adequate': 1, 'weak': 0, 'high': 2, 'medium': 1, 'low': 0}
                        data["recommendation_score"] = word_map_rec.get(rec_score_raw.strip().lower(), 1)

                if self.db and application_id:
                    self.db.save_mulan_recommendation(
                        application_id=application_id,
                        agent_name=self.name,
                        recommender_name=data.get("recommender_name"),
                        recommender_role=data.get("recommender_role"),
                        endorsement_strength=endorsement_val,
                        specificity_score=specificity_val,
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
