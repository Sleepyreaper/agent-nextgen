"""Tiana Application Reader - Parses student applications into structured profiles."""

import json
from typing import Dict, Any, Optional, List
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.utils import safe_load_json
from src.agents.telemetry_helpers import agent_run, tool_call


class TianaApplicationReader(BaseAgent):
    """
    Specialized agent (Tiana) for reading and structuring student applications.

    Extracts:
    - Personal and academic profile
    - Activities, awards, leadership
    - Essay themes and goals
    - Evidence of readiness and fit for the program
    """

    def __init__(self, name: str, client: AzureOpenAI, model: Optional[str] = None, db_connection=None):
        super().__init__(name, client)
        # allow model override; otherwise use global config
        self.model = model or config.foundry_model_name or config.deployment_name
        self.db = db_connection

    async def parse_application(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a full application record into structured data."""
        applicant_name = application.get("applicant_name", application.get("ApplicantName", "Unknown"))
        application_id = application.get("application_id", application.get("ApplicationID"))
        
        with agent_run(self.name, "parse_application", {"applicant_name": applicant_name, "application_id": application_id}):
            application_text = application.get("application_text", application.get("ApplicationText", ""))
            prompt = self._build_prompt(applicant_name, application_text, application)

            try:
                # Two-step: first ask model to extract evidence and key facts,
                # then ask it to format those findings into the strict JSON schema.
                # Use up to 8000 chars — Belle's section detection now routes only
                # application/essay pages here, so the input is focused.
                application_input = application_text[:8000]
                query_messages = [
                    {"role": "system", "content": "You are a precise extractor. Read the user's application and return concise evidence bullets and facts useful for constructing a structured profile.\n\nIMPORTANT: The text may contain page markers like '--- PAGE N of M ---'. These indicate page boundaries from a multi-page PDF. Note which page each piece of evidence comes from (e.g., 'Page 3: student describes lab experience'). Focus on application/essay content and ignore any transcript or recommendation sections if present."},
                    {"role": "user", "content": f"Extract key facts and evidence from the application for: {applicant_name}.\n\nApplication text:\n{application_input}"}
                ]

                format_template = [
                    {"role": "system", "content": "You are Tiana, part of an NIH Department of Genetics review panel. Using the extracted facts provided, produce the final JSON object exactly matching the required schema. Return valid JSON only."},
                    {"role": "user", "content": "Using these extracted facts: {found}\n\nNow return the structured JSON profile with the required fields (applicant_name, school_name, intended_major, essay_summary, core_competencies, readiness_score, confidence, etc.)."}
                ]

                q_resp, response = self.two_step_query_format(
                    operation_base="tiana.parse_application",
                    model=self.model,
                    query_messages=query_messages,
                    format_messages_template=format_template,
                    query_kwargs={"max_completion_tokens": 600, "temperature": 0},
                    format_kwargs={"max_completion_tokens": 1500, "temperature": 1, "refinements": 2, "refinement_instruction": "Refine the JSON output for accuracy, completeness, and strict JSON validity. If any fields are ambiguous, favor explicit nulls and add a confidence field for uncertain values.", "response_format": {"type": "json_object"}}
                )
                # Guard against empty or malformed model responses
                payload = None
                try:
                    if not response or not getattr(response, "choices", None):
                        raise ValueError("Empty model response")
                    payload = response.choices[0].message.content
                except Exception as resp_err:
                    # Record the raw response fallback and return error structure
                    raw_resp = None
                    try:
                        raw_resp = str(response)
                    except Exception:
                        raw_resp = "<unserializable response>"
                    data = {
                        "status": "error",
                        "agent": self.name,
                        "error": f"Model response invalid: {str(resp_err)}",
                        "raw_response": raw_resp
                    }
                else:
                    data = safe_load_json(payload)
                data["status"] = "success"
                data["agent"] = self.name

                recommendation_texts = data.get("recommendation_texts")
                recommendation_payload = None
                if isinstance(recommendation_texts, list) and recommendation_texts:
                    recommendation_payload = json.dumps(recommendation_texts, ensure_ascii=True)

                if self.db and application_id:
                    with tool_call("save_tiana_application", "database", {"application_id": application_id}):
                        self.db.save_tiana_application(
                            application_id=application_id,
                            agent_name=self.name,
                            essay_summary=data.get("essay_summary"),
                            recommendation_texts=recommendation_payload,
                            readiness_score=data.get("readiness_score"),
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

    def _build_prompt(self, applicant_name: str, application_text: str, application: Dict[str, Any]) -> str:
        """Build the parsing prompt for an application."""
        prompt_parts = [
            "You are parsing a student application for a competitive internship program.",
            "Return a JSON object with the fields below.",
            "",
            f"Applicant: {applicant_name}",
            f"Email: {application.get('Email', 'N/A')}",
            "",
            "Application text:",
            application_text,
            "",
            "Required JSON fields:",
            "{",
            "  \"applicant_name\": \"\",",
            "  \"school_name\": \"\",",
            "  \"intended_major\": \"\",",
            "  \"career_interests\": [\"\"],",
            "  \"essay_summary\": \"(4-6 sentences with concrete evidence)\",",
            "  \"core_competencies\": {",
            "    \"stem_curiosity\": \"\",",
            "    \"initiative\": \"\",",
            "    \"community_impact\": \"\",",
            "    \"communication\": \"\",",
            "    \"resilience\": \"\"",
            "  },",
            "  \"recommendation_texts\": [\"\"],",
            "  \"leadership_roles\": [\"\"],",
            "  \"activities\": [\"\"],",
            "  \"awards_honors\": [\"\"],",
            "  \"community_service\": \"\",",
            "  \"research_or_lab_experience\": \"\",",
            "  \"program_fit_signals\": [\"\"],",
            "  \"potential_risks\": [\"\"],",
            "  \"eligibility_check\": [\"(note any gaps or unknowns)\"],",
            "  \"readiness_score\": 0,",
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
                "content": "You are Tiana, part of an NIH Department of Genetics review panel evaluating Emory NextGen applicants. You create structured profiles with evidence and note eligibility against program requirements."
            }
        ] + self.conversation_history

        response = self._create_chat_completion(
            operation="tiana.process",
            model=self.model,
            messages=messages,
            max_completion_tokens=1000,
            temperature=1,
            refinements=2,
            refinement_instruction="Refine your previous assistant response to improve evidence-grounding and clarity. Keep the same output format."
        )
        assistant_message = response.choices[0].message.content
        self.add_to_history("assistant", assistant_message)
        return assistant_message
