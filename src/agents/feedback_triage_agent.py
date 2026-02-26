"""
Scuttle Feedback Triage Agent
Character: Scuttle (Disney character from "The Little Mermaid")
Understands user feedback and prepares a concise issue summary.
"""

import json
from typing import Any, Dict, Optional
from src.utils import safe_load_json
from src.config import config

# Avoid importing `openai` at module import time; accept the client as Any so
# the application can start even when the `openai` package isn't present.
from src.agents.base_agent import BaseAgent


class ScuttleFeedbackTriageAgent(BaseAgent):
    """
    Scuttle - Feedback Triage Agent
    Understands user feedback and prepares a concise issue summary.
    """

    def __init__(self, name: str = "Scuttle Feedback Triage", client: Any = None, model: Optional[str] = None):
        super().__init__(name, client)
        # use configured model if none provided
        self.model = model or config.model_tier_lightweight or config.foundry_model_name or config.deployment_name
        self.model_display = self.model or "gpt-4"  # Default display model

    async def analyze_feedback(
        self,
        feedback_type: str,
        message: str,
        email: Optional[str] = None,
        page: Optional[str] = None,
        app_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze feedback and return structured issue fields."""
        self.add_to_history("user", f"Triage {feedback_type} feedback")

        prompt = self._build_prompt(feedback_type, message, email, page, app_version)
        response = self._create_chat_completion(
            operation="feedback.triage",
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a product triage assistant. Summarize user feedback into a concise "
                        "issue report. Return JSON only."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_completion_tokens=800,
            temperature=1
        )

        response_text = response.choices[0].message.content
        self.add_to_history("assistant", response_text)
        return self._parse_response(response_text, feedback_type, message)

    async def process(self, message: str) -> str:
        """Generic process handler (unused)."""
        self.add_to_history("user", message)
        return "Feedback triage agent is ready."

    def _build_prompt(
        self,
        feedback_type: str,
        message: str,
        email: Optional[str],
        page: Optional[str],
        app_version: Optional[str]
    ) -> str:
        safe_email = email or "Not provided"
        safe_page = page or "Unknown"
        safe_version = app_version or "Unknown"

        return (
            "Analyze the following user feedback and return JSON with these keys:\n"
            "title, summary, category, priority, suggested_labels, steps_to_reproduce, "
            "expected_behavior, actual_behavior, user_context.\n\n"
            f"Feedback type: {feedback_type}\n"
            f"Message: {message}\n"
            f"User email: {safe_email}\n"
            f"Page: {safe_page}\n"
            f"App version: {safe_version}\n\n"
            "Rules:\n"
            "- title should be short and actionable\n"
            "- summary should be 2-4 sentences\n"
            "- category should be one of: bug, feature, ux, data, performance, other\n"
            "- priority should be one of: low, medium, high\n"
            "- suggested_labels should be an array of strings\n"
            "- steps_to_reproduce can be empty if unknown\n"
            "- expected_behavior and actual_behavior can be empty if not stated\n"
            "- user_context should include email, page, and version\n"
        )

    def _parse_response(
        self,
        response_text: str,
        fallback_type: str,
        fallback_message: str
    ) -> Dict[str, Any]:
        try:
            parsed = safe_load_json(response_text)
        except json.JSONDecodeError:
            parsed = {}

        title = parsed.get("title") or f"User feedback: {fallback_type}"
        summary = parsed.get("summary") or fallback_message
        category = parsed.get("category") or "other"
        priority = parsed.get("priority") or "medium"
        suggested_labels = parsed.get("suggested_labels") or ["feedback", category]

        return {
            "title": title,
            "summary": summary,
            "category": category,
            "priority": priority,
            "suggested_labels": suggested_labels,
            "steps_to_reproduce": parsed.get("steps_to_reproduce") or "",
            "expected_behavior": parsed.get("expected_behavior") or "",
            "actual_behavior": parsed.get("actual_behavior") or "",
            "user_context": parsed.get("user_context") or {},
            "agent_name": self.name,
            "model_used": self.model,
            "model_display": getattr(self, 'model_display', 'gpt-4')
        }


# Backwards compatibility alias
FeedbackTriageAgent = ScuttleFeedbackTriageAgent