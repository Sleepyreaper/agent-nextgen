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
from src.agents.telemetry_helpers import agent_run
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
        """Analyze training-only data and return selection insights.

        When historical human scores are available (imported from the 2024
        spreadsheet), they are included alongside the training examples so
        Milo can calibrate against the actual rubric dimensions.
        """
        # Register agent invocation with OpenTelemetry (GenAI Semantic Convention: invoke_agent)
        _otel_ctx = agent_run("Milo Data Scientist", "analyze_training_insights", agent_id="milo-data-scientist")
        _otel_ctx.__enter__()
        if not self.db:
            _otel_ctx.__exit__(None, None, None)
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

        # Load historical human scoring data for calibration
        historical_data = None
        try:
            historical_data = self.db.get_historical_scores_for_milo(2024)
        except Exception:
            pass  # gracefully degrade if table doesn't exist yet

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
            samples["counts"]["unknown"],
            historical_data.get("total_scored", 0) if historical_data else 0
        )

        if self._is_cache_valid(signature):
            cached = dict(self._cached_insights)
            cached["cached"] = True
            return cached

        prompt = self._build_prompt(samples, historical_data=historical_data)
        try:
            response = self._create_chat_completion(
                operation="milo.analyze_training",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Milo, a careful data scientist for the Emory NextGen Scholars program. "
                            "For the 2026 cohort we are looking for the TOP 50 candidates from 1,000+ applicants. "
                            "Use only the provided training data. "
                            "When historical human rubric scores are provided, treat them as ground truth "
                            "and use them to calibrate scoring thresholds. "
                            "Focus on patterns that differentiate accepted vs not selected. "
                            "If evidence is weak, say so. Return valid JSON only."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1800,
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
                "average_merlin_score": avg_score,
                "historical_data_available": bool(historical_data and historical_data.get("total_scored", 0) > 0),
                "historical_scored_count": historical_data.get("total_scored", 0) if historical_data else 0
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
        _otel_ctx.__exit__(None, None, None)
        return data

    async def compute_alignment(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Given a single applicant and existing training insights, ask Milo to
        compute a Next Gen Match probability.

        Context: The Emory NextGen program has ~30 openings and receives 1,000+
        applicants each year.  Milo uses historical accepted vs not-selected
        patterns to estimate how likely this student is to be selected.

        Returns JSON with:
          - nextgen_match (0-100): probability percentage the student would be
            selected given the competitive landscape.
          - match_score (0-100): raw alignment to accepted-student profile.
          - explanation: brief rationale.
        """
        # Register agent invocation (GenAI Semantic Convention: invoke_agent)
        _otel_ctx2 = agent_run("Milo Data Scientist", "compute_alignment", agent_id="milo-data-scientist")
        _otel_ctx2.__enter__()
        if not application:
            _otel_ctx2.__exit__(None, None, None)
            return {"status": "error", "error": "No application provided"}

        # ensure we have fresh insights first
        insights = await self.analyze_training_insights()

        # Build a focused subset of the application to avoid token bloat
        app_subset = {}
        for key in ('applicant_name', 'first_name', 'last_name', 'high_school',
                     'state_code', 'application_text', 'transcript_text',
                     'recommendation_text', 'gpa', 'activities', 'interest',
                     'school_name', 'agent_results'):
            if application.get(key):
                val = application[key]
                # truncate long text fields
                if isinstance(val, str) and len(val) > 1500:
                    val = val[:1500] + '...'
                app_subset[key] = val

        # Look up this student's historical human scores if available
        historical_score = None
        try:
            if self.db:
                student_name = application.get('applicant_name', '')
                historical_score = self.db.get_historical_score_by_name(student_name)
        except Exception:
            pass

        historical_context = ""
        if historical_score:
            historical_context = (
                "\n\nHISTORICAL HUMAN SCORING for this student (from 2024 cohort):\n"
                + json.dumps({
                    "status": historical_score.get("status"),
                    "academic_record": float(historical_score["academic_record"]) if historical_score.get("academic_record") is not None else None,
                    "stem_interest": float(historical_score["stem_interest"]) if historical_score.get("stem_interest") is not None else None,
                    "essay_video": float(historical_score["essay_video"]) if historical_score.get("essay_video") is not None else None,
                    "recommendation": float(historical_score["recommendation"]) if historical_score.get("recommendation") is not None else None,
                    "bonus": float(historical_score["bonus"]) if historical_score.get("bonus") is not None else None,
                    "total_rating": float(historical_score["total_rating"]) if historical_score.get("total_rating") is not None else None,
                    "overall_rating": historical_score.get("overall_rating"),
                    "reviewer_name": historical_score.get("reviewer_name"),
                    "preliminary_score": historical_score.get("preliminary_score"),
                }, ensure_ascii=True)
                + "\nUse this human scoring data to calibrate your prediction. "
                "The human reviewers' scores are the ground truth."
            )

        prompt = (
            "You are Milo, the data scientist for the Emory NextGen Scholars program.\n"
            "PROGRAM CONTEXT: For the 2026 cohort, we are looking for the TOP 50 "
            "candidates from 1,000+ applicants. Selection is extremely competitive.\n\n"
            "Your training insights from historical accepted vs not-selected students:\n"
            + json.dumps(insights, ensure_ascii=True)
            + historical_context
            + "\n\nNow evaluate this NEW applicant:\n"
            + json.dumps(app_subset, ensure_ascii=True)
            + "\n\nCompare this applicant against the historical patterns of who was "
            "selected and who was not.  Produce a 'Next Gen Match' probability that "
            "reflects how likely this student would be among the top 50 selected from "
            "1,000+ applicants.\n\n"
            "Return valid JSON with these fields:\n"
            "{\n"
            '  "nextgen_match": <int 0-100>,  // probability percentage of being selected\n'
            '  "match_score": <int 0-100>,    // raw profile alignment to accepted students\n'
            '  "confidence": "High|Medium|Low",\n'
            '  "key_differentiators": ["(2-4 factors most influencing this score)"],\n'
            '  "explanation": "(2-3 sentence rationale)"\n'
            "}"
        )
        try:
            response = self._create_chat_completion(
                operation="milo.compute_alignment",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Milo, a data scientist who analyzes historical "
                            "selection patterns for the Emory NextGen Scholars program. "
                            "For 2026, the program is expanding to select the top 50 "
                            "students from 1,000+ applicants (~5% acceptance rate). "
                            "Be realistic and calibrated — a score of 50 means a coin flip, "
                            "not a sure thing. Most applicants should score below 30. "
                            "Only truly outstanding candidates should score above 60. "
                            "When historical human rubric scores are available for a student, "
                            "weight them heavily — they represent ground truth from expert reviewers."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=900,
                temperature=0.4,
                response_format={"type": "json_object"}
            )
            payload = response.choices[0].message.content
            data = safe_load_json(payload)
            # Ensure nextgen_match is present; fall back to match_score if model omitted it
            if 'nextgen_match' not in data and 'match_score' in data:
                data['nextgen_match'] = data['match_score']
            data.setdefault("status", "success")
            data.setdefault("agent", self.name)
        except Exception as e:
            data = {
                "status": "error",
                "agent": self.name,
                "error": str(e)
            }
        _otel_ctx2.__exit__(None, None, None)
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

            # Enrich with historical rubric scores if available
            student_name = item.get("applicant_name", "")
            if student_name and self.db:
                try:
                    historical = self.db.get_historical_score_by_name(student_name)
                    if historical:
                        item["human_scores"] = {
                            "academic_record": float(historical["academic_record"]) if historical.get("academic_record") is not None else None,
                            "stem_interest": float(historical["stem_interest"]) if historical.get("stem_interest") is not None else None,
                            "essay_video": float(historical["essay_video"]) if historical.get("essay_video") is not None else None,
                            "recommendation": float(historical["recommendation"]) if historical.get("recommendation") is not None else None,
                            "bonus": float(historical["bonus"]) if historical.get("bonus") is not None else None,
                            "total_rating": float(historical["total_rating"]) if historical.get("total_rating") is not None else None,
                            "overall_rating": historical.get("overall_rating"),
                            "preliminary_score": historical.get("preliminary_score"),
                        }
                except Exception:
                    pass

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

    def _build_prompt(self, samples: Dict[str, Any], historical_data: Optional[Dict[str, Any]] = None) -> str:
        samples_json = json.dumps(samples, ensure_ascii=True)
        lines = [
            "Analyze the training data below.",
            "Only use this data. Do not invent facts.",
            "Identify patterns that differentiate accepted vs not selected.",
        ]

        # Include historical rubric data if available
        if historical_data and historical_data.get("total_scored", 0) > 0:
            lines.extend([
                "",
                "=== HISTORICAL HUMAN RUBRIC SCORES (2024 Cohort) ===",
                "These are REAL scores assigned by expert human reviewers.",
                f"Total scored applicants: {historical_data['total_scored']}",
                f"Accepted with scores: {len(historical_data.get('accepted_scores', []))}",
                f"Not accepted with scores: {len(historical_data.get('not_accepted_scores', []))}",
                "",
                "Rubric: Academic Record (0-3), STEM Interest (0-3), Essay/Video (0-3), "
                "Recommendation (0-2), Bonus (0-1) = Total (0-12)",
                "",
            ])
            stats = historical_data.get("stats", {})
            if stats.get("avg_accepted_total"):
                lines.append(f"Avg total rating for ACCEPTED students: {stats['avg_accepted_total']:.1f}")
            if stats.get("avg_rejected_total"):
                lines.append(f"Avg total rating for NOT ACCEPTED students: {stats['avg_rejected_total']:.1f}")

            # Include a sample of accepted scores
            accepted_sample = historical_data.get("accepted_scores", [])[:15]
            if accepted_sample:
                lines.append("")
                lines.append("Accepted students' rubric scores:")
                lines.append(json.dumps(accepted_sample, ensure_ascii=True))

            # Include a sample of not-accepted scores
            not_accepted_sample = historical_data.get("not_accepted_scores", [])[:15]
            if not_accepted_sample:
                lines.append("")
                lines.append("Not-accepted students' rubric scores:")
                lines.append(json.dumps(not_accepted_sample, ensure_ascii=True))

            lines.append("")
            lines.append("Use these rubric scores to understand the TRUE scoring thresholds.")
            lines.append("=== END HISTORICAL SCORES ===")
            lines.append("")

        lines.extend([
            "Return JSON with the fields:",
            "{",
            '  "summary": "",',
            '  "accepted_signals": [""],',
            '  "not_selected_signals": [""],',
            '  "differentiators": [""],',
            '  "selection_risks": [""],',
            '  "data_gaps": [""],',
            '  "recommendations_for_merlin": [""],',
            '  "rubric_thresholds": {"min_total_for_acceptance": 0, "avg_accepted_total": 0, "avg_rejected_total": 0},',
            '  "confidence": "High|Medium|Low"',
            "}",
            "Training data (JSON):",
            samples_json
        ])
        return "\n".join(lines)

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
