"""Milo Data Scientist - Learns patterns from training outcomes."""

import json
import time
from typing import Any, Dict, List, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent


class MiloDataScientist(BaseAgent):
    """
    Milo (Data Scientist) analyzes historical training data only.

    This agent:
    - Reads training examples (accepted vs not accepted)
    - Extracts patterns and signals from prior selections
    - Produces a structured summary for Merlin to use
    """

    def __init__(
        self,
        name: str,
        client: AzureOpenAI,
        model: str,
        db_connection: Optional[Any] = None,
        max_samples_per_group: int = 12,
        cache_seconds: int = 600
    ):
        super().__init__(name, client)
        self.model = model
        self.db = db_connection
        self.max_samples_per_group = max_samples_per_group
        self.cache_seconds = cache_seconds
        self._cached_insights: Optional[Dict[str, Any]] = None
        self._cached_at: float = 0
        self._cached_signature: Optional[tuple] = None

    async def analyze_training_insights(self) -> Dict[str, Any]:
        """Analyze training-only data and return selection insights."""
        if not self.db:
            return {
                "status": "error",
                "agent": self.name,
                "error": "Database connection not available"
            }

        try:
            training_examples = self.db.get_training_examples()
        except Exception as e:
            return {
                "status": "error",
                "agent": self.name,
                "error": str(e)
            }

        samples = self._build_samples(training_examples)
        signature = (
            samples["counts"]["accepted"],
            samples["counts"]["not_selected"],
            samples["counts"]["unknown"]
        )

        if self._is_cache_valid(signature):
            cached = dict(self._cached_insights)
            cached["cached"] = True
            return cached

        prompt = self._build_prompt(samples)
        try:
            response = self._create_chat_completion(
                operation="milo.analyze_training",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Milo, a careful data scientist. "
                            "Use only the provided training data. "
                            "Focus on patterns that differentiate accepted vs not selected. "
                            "If evidence is weak, say so. Return valid JSON only."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1200,
                temperature=0.4,
                response_format={"type": "json_object"}
            )
            payload = response.choices[0].message.content
            data = json.loads(payload)
            data.update({
                "status": "success",
                "agent": self.name,
                "cached": False,
                "training_counts": samples["counts"],
                "sample_sizes": samples["sample_sizes"]
            })
        except Exception as e:
            data = {
                "status": "error",
                "agent": self.name,
                "error": str(e)
            }

        self._cached_insights = data
        self._cached_signature = signature
        self._cached_at = time.time()
        return data

    async def process(self, message: str) -> str:
        """Generic message handler."""
        self.add_to_history("user", message)
        response = self._create_chat_completion(
            operation="milo.process",
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are Milo, a data scientist who summarizes training patterns."
                }
            ] + self.conversation_history,
            max_completion_tokens=600,
            temperature=0.4
        )
        assistant_message = response.choices[0].message.content
        self.add_to_history("assistant", assistant_message)
        return assistant_message

    def _build_samples(self, training_examples: List[Dict[str, Any]]) -> Dict[str, Any]:
        accepted = []
        not_selected = []
        unknown = []

        for row in training_examples:
            item = {
                "applicant_name": row.get("applicant_name") or row.get("applicantname"),
                "was_selected": row.get("was_selected"),
                "application_text": self._truncate(row.get("application_text") or row.get("applicationtext")),
                "transcript_text": self._truncate(row.get("transcript_text") or row.get("transcripttext")),
                "recommendation_text": self._truncate(row.get("recommendation_text") or row.get("recommendationtext")),
                "school_name": row.get("school_name") or row.get("schoolname"),
                "status": row.get("status")
            }

            if item["was_selected"] is True:
                accepted.append(item)
            elif item["was_selected"] is False:
                not_selected.append(item)
            else:
                unknown.append(item)

        accepted_sample = accepted[: self.max_samples_per_group]
        not_selected_sample = not_selected[: self.max_samples_per_group]
        unknown_sample = unknown[: self.max_samples_per_group]

        return {
            "counts": {
                "accepted": len(accepted),
                "not_selected": len(not_selected),
                "unknown": len(unknown)
            },
            "sample_sizes": {
                "accepted": len(accepted_sample),
                "not_selected": len(not_selected_sample),
                "unknown": len(unknown_sample)
            },
            "samples": {
                "accepted": accepted_sample,
                "not_selected": not_selected_sample,
                "unknown": unknown_sample
            }
        }

    def _build_prompt(self, samples: Dict[str, Any]) -> str:
        samples_json = json.dumps(samples, ensure_ascii=True)
        return "\n".join([
            "Analyze the training data below.",
            "Only use this data. Do not invent facts.",
            "Identify patterns that differentiate accepted vs not selected.",
            "Return JSON with the fields:",
            "{",
            '  "summary": "",',
            '  "accepted_signals": [""],',
            '  "not_selected_signals": [""],',
            '  "differentiators": [""],',
            '  "selection_risks": [""],',
            '  "data_gaps": [""],',
            '  "recommendations_for_merlin": [""],',
            '  "confidence": "High|Medium|Low"',
            "}",
            "Training data (JSON):",
            samples_json
        ])

    def _truncate(self, text: Optional[str], limit: int = 1200) -> str:
        if not text:
            return ""
        text = str(text)
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    def _is_cache_valid(self, signature: tuple) -> bool:
        if self._cached_insights is None:
            return False
        if self._cached_signature != signature:
            return False
        return (time.time() - self._cached_at) < self.cache_seconds
