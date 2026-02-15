"""Tiana Application Reader - Parses student applications into structured profiles."""

import json
from typing import Dict, Any, Optional, List
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent


class TianaApplicationReader(BaseAgent):
    """
    Specialized agent (Tiana) for reading and structuring student applications.

    Extracts:
    - Personal and academic profile
    - Activities, awards, leadership
    - Essay themes and goals
    - Evidence of readiness and fit for the program
    """

    def __init__(self, name: str, client: AzureOpenAI, model: str, db_connection=None):
        super().__init__(name, client)
        self.model = model
        self.db = db_connection

    async def parse_application(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a full application record into structured data."""
        applicant_name = application.get("applicant_name", application.get("ApplicantName", "Unknown"))
        application_text = application.get("application_text", application.get("ApplicationText", ""))
        application_id = application.get("application_id", application.get("ApplicationID"))

        prompt = self._build_prompt(applicant_name, application_text, application)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are Tiana, an expert admissions reader who extracts structured applicant profiles from messy application text. Be specific and verbose in summaries. Return valid JSON only."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1500,
                temperature=1,
                response_format={"type": "json_object"}
            )

            payload = response.choices[0].message.content
            data = json.loads(payload)
            data["status"] = "success"
            data["agent"] = self.name

            recommendation_texts = data.get("recommendation_texts")
            recommendation_payload = None
            if isinstance(recommendation_texts, list) and recommendation_texts:
                recommendation_payload = json.dumps(recommendation_texts, ensure_ascii=True)

            if self.db and application_id:
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
            "  \"recommendation_texts\": [\"\"],",
            "  \"leadership_roles\": [\"\"],",
            "  \"activities\": [\"\"],",
            "  \"awards_honors\": [\"\"],",
            "  \"community_service\": \"\",",
            "  \"research_or_lab_experience\": \"\",",
            "  \"program_fit_signals\": [\"\"],",
            "  \"potential_risks\": [\"\"],",
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
                "content": "You are Tiana, an application reader who creates structured profiles from applicant materials."
            }
        ] + self.conversation_history

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=1000,
            temperature=1
        )
        assistant_message = response.choices[0].message.content
        self.add_to_history("assistant", assistant_message)
        return assistant_message
