"""Milo Data Scientist - Learns patterns from training outcomes."""

import json
import os
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
# Avoid top-level dependency on `openai` to prevent import-time failures in environments
# where the package is not installed. The client is accepted as a runtime object.
from src.agents.base_agent import BaseAgent
from src.config import config
from src.telemetry import get_tracer
from src.utils import safe_load_json


class MiloDataScientist(BaseAgent):
    """
    Milo (Data Scientist) analyzes historical training data only.
    Character: Milo (Disney character from "Atlantis: The Lost Empire")
    Model: gpt-4.1 (deployed as o4miniagent in Azure AI Foundry). Actual model/deployment is resolved from configuration if not specified.

    This agent:
    - Reads training examples (accepted vs not accepted)
    - Extracts patterns and signals from prior selections
    - Produces a structured summary for Merlin to use
    """

    def __init__(
        self,
        name: str,
        client: Any,
        model: Optional[str] = None,
        db_connection: Optional[Any] = None,
        max_samples_per_group: int = 12,
        cache_seconds: int = 600
    ):
        super().__init__(name, client)
        # default to configured Foundry model or deployment name
        self.model = model or config.foundry_model_name or config.deployment_name
        self.model_display = self.model or "unknown"
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
                "model_used": self.model,
                "model_display": self.model_display,
                "error": "Database connection not available"
            }

        try:
            training_examples = self.db.get_training_examples()
        except Exception as e:
            return {
                "status": "error",
                "agent": self.name,
                "model_used": self.model,
                "model_display": self.model_display,
                "error": str(e)
            }

        # compute average merlin score across the historical training set if available
        avg_score = None
        try:
            scores = []
            for row in training_examples:
                # try common column names that may contain merlin score
                for key in ("merlin_score", "overall_score", "overallscore"):
                    if row.get(key) is not None:
                        try:
                            scores.append(float(row.get(key)))
                        except Exception:
                            pass
                        break
            if scores:
                avg_score = sum(scores) / len(scores)
        except Exception:
            avg_score = None

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
            data = safe_load_json(payload)
            data.update({
                "status": "success",
                "agent": self.name,
                "model_used": self.model,
                "model_display": self.model_display,
                "cached": False,
                "training_counts": samples["counts"],
                "sample_sizes": samples["sample_sizes"],
                "average_merlin_score": avg_score
            })
        except Exception as e:
            data = {
                "status": "error",
                "agent": self.name,
                "model_used": self.model,
                "model_display": self.model_display,
                "error": str(e)
            }

        self._cached_insights = data
        self._cached_signature = signature
        self._cached_at = time.time()
        return data

    async def compute_alignment(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Given a single applicant and existing training insights, ask Milo to
        compute a match score and NextGen alignment narrative using the AI model.
        This uses the same model as other Milo calls and may hit the cache of
        analyze_training_insights to avoid redundant work.
        """
        if not application:
            return {"status": "error", "error": "No application provided"}

        # ensure we have fresh insights first
        insights = await self.analyze_training_insights()
        prompt = (
            "You are Milo, a data scientist. You have the following training insights:\n"
            + json.dumps(insights, ensure_ascii=True)
            + "\n\nEvaluate the new applicant below in light of these patterns.\n"
            + json.dumps(application, ensure_ascii=True)
            + "\nReturn valid JSON with fields: 'match_score' (0-100), 'nextgen_align_score' (0-100), and 'explanation' (a brief rationale)."
        )
        try:
            response = self._create_chat_completion(
                operation="milo.compute_alignment",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Milo, a data scientist who summarizes training patterns."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=800,
                temperature=0.4,
                response_format={"type": "json_object"}
            )
            payload = response.choices[0].message.content
            data = safe_load_json(payload)
            data.setdefault("status", "success")
            data.setdefault("agent", self.name)
        except Exception as e:
            data = {
                "status": "error",
                "agent": self.name,
                "error": str(e)
            }
        return data

    async def build_and_upload_foundry_dataset(self) -> Dict[str, Any]:
        """Build a Foundry dataset from training data and upload it."""
        if not self.db:
            return {
                "status": "error",
                "agent": self.name,
                "error": "Database connection not available"
            }

        project_endpoint = config.foundry_project_endpoint
        if not project_endpoint:
            return {
                "status": "error",
                "agent": self.name,
                "error": "Foundry project endpoint not configured"
            }

        dataset_name = config.foundry_dataset_name or "nextgen-training-dataset"
        version = datetime.utcnow().strftime("v%Y%m%d%H%M%S")
        tracer = get_tracer()

        if tracer:
            with tracer.start_as_current_span("milo.foundry_dataset.build") as span:
                rows = self._build_dataset_rows()
                span.set_attribute("dataset.name", dataset_name)
                span.set_attribute("dataset.version", version)
                span.set_attribute("dataset.row_count", len(rows))
                file_path = self._write_jsonl(rows) if rows else None
        else:
            rows = self._build_dataset_rows()
            file_path = self._write_jsonl(rows) if rows else None

        if not rows:
            return {
                "status": "error",
                "agent": self.name,
                "error": "No training examples available"
            }

        try:
            project_client = AIProjectClient(
                credential=DefaultAzureCredential(),
                endpoint=project_endpoint
            )
            connection_name = self._resolve_dataset_connection(project_client)
            if tracer:
                with tracer.start_as_current_span("milo.foundry_dataset.upload") as span:
                    span.set_attribute("dataset.name", dataset_name)
                    span.set_attribute("dataset.version", version)
                    span.set_attribute("dataset.row_count", len(rows))
                    span.set_attribute("dataset.connection", connection_name)
                    dataset = project_client.datasets.upload_file(
                        name=dataset_name,
                        version=version,
                        file_path=file_path,
                        connection_name=connection_name
                    )
            else:
                dataset = project_client.datasets.upload_file(
                    name=dataset_name,
                    version=version,
                    file_path=file_path,
                    connection_name=connection_name
                )
            return {
                "status": "success",
                "agent": self.name,
                "dataset_name": dataset_name,
                "dataset_version": version,
                "dataset_id": getattr(dataset, "id", None),
                "row_count": len(rows)
            }
        except Exception as e:
            return {
                "status": "error",
                "agent": self.name,
                "error": str(e)
            }
        finally:
            if file_path:
                try:
                    os.remove(file_path)
                except OSError:
                    pass

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

    def _build_dataset_rows(self) -> List[Dict[str, Any]]:
        training_examples = self.db.get_training_examples()
        rows: List[Dict[str, Any]] = []

        for row in training_examples:
            application_id = row.get("application_id") or row.get("ApplicationID")
            agent_outputs = self._load_agent_outputs(application_id)
            rows.append({
                "application_id": application_id,
                "applicant_name": row.get("applicant_name") or row.get("applicantname"),
                "was_selected": row.get("was_selected"),
                "status": row.get("status"),
                "application_text": row.get("application_text") or row.get("applicationtext"),
                "transcript_text": row.get("transcript_text") or row.get("transcripttext"),
                "recommendation_text": row.get("recommendation_text") or row.get("recommendationtext"),
                "school_name": row.get("school_name") or row.get("schoolname"),
                "agent_outputs": agent_outputs
            })

        return rows

    def _load_agent_outputs(self, application_id: Optional[int]) -> Dict[str, Any]:
        if not application_id:
            return {}

        outputs: Dict[str, Any] = {}
        table_map = {
            "tiana": "tiana_applications",
            "rapunzel": "rapunzel_grades",
            "moana": "student_school_context",
            "mulan": "mulan_recommendations",
            "merlin": "merlin_evaluations"
        }

        for key, table in table_map.items():
            try:
                table_name = self.db.get_table_name(table)
                rows = self.db.execute_query(
                    f"SELECT * FROM {table_name} WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                    (application_id,)
                )
                if rows:
                    outputs[key] = self._merge_parsed_json(rows[0])
            except Exception:
                continue

        return outputs

    def _merge_parsed_json(self, row: Dict[str, Any]) -> Dict[str, Any]:
        parsed = dict(row)
        parsed_json = row.get("parsed_json") or row.get("parsedjson")
        if not parsed_json:
            return parsed

        try:
            parsed_payload = safe_load_json(parsed_json)
            if isinstance(parsed_payload, dict):
                for key, value in parsed_payload.items():
                    parsed.setdefault(key, value)
        except Exception:
            return parsed

        return parsed

    def _write_jsonl(self, rows: List[Dict[str, Any]]) -> str:
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
        handle.close()
        with open(handle.name, "w", encoding="utf-8") as file_handle:
            for row in rows:
                file_handle.write(json.dumps(row, ensure_ascii=True))
                file_handle.write("\n")
        return handle.name

    def _resolve_dataset_connection(self, project_client: AIProjectClient) -> str:
        configured = config.foundry_dataset_connection_name
        if configured:
            return configured

        try:
            connections = list(project_client.connections.list())
        except Exception as exc:
            raise RuntimeError("Unable to list Foundry connections") from exc

        if len(connections) == 1:
            return connections[0].name

        for connection in connections:
            name = (connection.name or "").lower()
            if "storage" in name or "blob" in name:
                return connection.name

        raise RuntimeError("Foundry dataset connection not found. Set FOUNDRY_DATASET_CONNECTION_NAME.")

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
