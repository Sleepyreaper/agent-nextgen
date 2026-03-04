"""Agent Evaluator — quality metrics for all agents using Azure AI Evaluation SDK.

Runs groundedness, coherence, relevance, and fluency evaluators against stored
agent outputs.  Also computes custom metrics: inter-agent agreement (Merlin vs
Gaston) and outcome accuracy against the ``was_selected`` ground truth.

Usage:
    evaluator = AgentEvaluator(db)
    results = evaluator.run_batch_evaluation()    # returns summary dict
    results = evaluator.get_latest_results()      # returns stored results
"""

import json
import logging
import statistics
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from src.config import config
from src.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# SDK availability — graceful fallback
# ---------------------------------------------------------------------------
_SDK_AVAILABLE = False
try:
    from azure.ai.evaluation import (
        GroundednessEvaluator,
        CoherenceEvaluator,
        RelevanceEvaluator,
        FluencyEvaluator,
        SimilarityEvaluator,
    )
    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "azure-ai-evaluation SDK not installed — SDK-based evaluators "
        "disabled.  Install with: pip install azure-ai-evaluation"
    )


# ---------------------------------------------------------------------------
# Agent ↔ evaluator mapping
# ---------------------------------------------------------------------------
# Each entry defines which SDK evaluators to run and how to build the
# (query, response, context) tuple from database row data.

AGENT_EVAL_CONFIG: Dict[str, Dict[str, Any]] = {
    "Tiana": {
        "evaluators": ["groundedness", "relevance", "coherence"],
        "table": "tiana_applications",
        "response_fields": ["essay_summary", "parsed_json"],
        "context_source": "application_text",
        "query": "Analyse this student application and produce a structured summary with readiness score.",
    },
    "Rapunzel": {
        "evaluators": ["groundedness", "coherence"],
        "table": "rapunzel_grades",
        "response_fields": ["summary", "parsed_json"],
        "context_source": "transcript_text",
        "query": "Analyse this student transcript and extract GPA, academic strength, and course levels.",
    },
    "Mulan": {
        "evaluators": ["groundedness", "coherence"],
        "table": "mulan_recommendations",
        "response_fields": ["summary", "parsed_json"],
        "context_source": "recommendation_text",
        "query": "Analyse this recommendation letter and assess endorsement strength and specificity.",
    },
    "Merlin": {
        "evaluators": ["groundedness", "coherence", "relevance"],
        "table": "merlin_evaluations",
        "response_fields": ["rationale", "parsed_json"],
        "context_source": "application_text",
        "query": "Produce a comprehensive final evaluation of this student with an overall score and recommendation.",
    },
    "Aurora": {
        "evaluators": ["coherence", "fluency"],
        "table": "aurora_evaluations",
        "response_fields": ["formatted_evaluation"],
        "context_source": "application_text",
        "query": "Format the evaluation results into a clear, readable executive summary.",
    },
}

# Recommendation tier mapping for outcome accuracy
_REC_POSITIVE = {"strong admit", "admit", "strongly recommend", "recommend", "accept"}
_REC_NEGATIVE = {"waitlist", "reconsider", "deny", "reject", "do not recommend"}


class AgentEvaluator:
    """Orchestrates AI quality evaluations for agent outputs."""

    def __init__(self, db):
        """
        Args:
            db: Database helper instance (src.database.DatabaseHelper)
        """
        self.db = db
        self._evaluators: Dict[str, Any] = {}
        self._model_config: Optional[Dict[str, str]] = None

    # ------------------------------------------------------------------
    # SDK evaluator initialisation
    # ------------------------------------------------------------------

    def _get_model_config(self) -> Dict[str, str]:
        """Build model_config dict for the Azure AI Evaluation SDK judge model."""
        if self._model_config:
            return self._model_config

        # The SDK evaluation judge should use a capable model.
        # Prefer the workhorse tier (4.1-mini) to balance quality vs cost.
        endpoint = config.azure_openai_endpoint or config.foundry_project_endpoint
        api_key = config.azure_openai_api_key or config.foundry_api_key
        deployment = config.model_tier_workhorse or config.deployment_name

        if not endpoint or not api_key:
            raise RuntimeError(
                "Cannot initialise AI Evaluation SDK: AZURE_OPENAI_ENDPOINT and "
                "AZURE_OPENAI_API_KEY (or Foundry equivalents) must be configured."
            )

        self._model_config = {
            "azure_endpoint": endpoint,
            "azure_deployment": deployment,
            "api_key": api_key,
            "api_version": config.api_version or "2025-04-14",
        }
        return self._model_config

    def _get_evaluator(self, name: str):
        """Lazily create and cache an SDK evaluator instance."""
        if not _SDK_AVAILABLE:
            return None
        if name in self._evaluators:
            return self._evaluators[name]

        mc = self._get_model_config()
        cls_map = {
            "groundedness": GroundednessEvaluator,
            "coherence": CoherenceEvaluator,
            "relevance": RelevanceEvaluator,
            "fluency": FluencyEvaluator,
            "similarity": SimilarityEvaluator,
        }
        cls = cls_map.get(name)
        if not cls:
            logger.warning(f"Unknown evaluator: {name}")
            return None

        try:
            evaluator = cls(model_config=mc)
            self._evaluators[name] = evaluator
            return evaluator
        except Exception as exc:
            logger.error(f"Failed to create {name} evaluator: {exc}")
            return None

    # ------------------------------------------------------------------
    # Data fetching helpers
    # ------------------------------------------------------------------

    def _get_training_applications(self) -> List[Dict[str, Any]]:
        """Fetch training applications with agent outputs."""
        query = """
            SELECT a.application_id, a.applicant_name, a.application_text,
                   a.was_selected, a.agent_results
            FROM Applications a
            WHERE a.is_training_example = TRUE
            ORDER BY a.application_id
        """
        return self.db.execute_query(query) or []

    def _get_agent_output(self, table: str, application_id: int) -> Optional[Dict[str, Any]]:
        """Fetch agent output row for a specific application."""
        try:
            query = f"SELECT * FROM {table} WHERE application_id = %s ORDER BY created_at DESC LIMIT 1"
            rows = self.db.execute_query(query, (application_id,))
            return rows[0] if rows else None
        except Exception:
            return None

    def _build_response_text(self, row: Dict[str, Any], fields: List[str]) -> str:
        """Build a response string from agent output fields."""
        parts = []
        for field in fields:
            val = row.get(field)
            if val is None:
                continue
            if isinstance(val, dict):
                parts.append(json.dumps(val, indent=2, default=str))
            elif isinstance(val, str) and val.strip():
                parts.append(val.strip())
        return "\n\n".join(parts) if parts else ""

    def _get_context_text(self, application: Dict[str, Any], source: str) -> str:
        """Get context text for an evaluation (the source document the agent analysed)."""
        # Try agent_results JSON first (Belle-extracted sections)
        agent_results = application.get("agent_results")
        if agent_results:
            if isinstance(agent_results, str):
                try:
                    agent_results = json.loads(agent_results)
                except Exception:
                    agent_results = {}
            if isinstance(agent_results, dict):
                # Try Belle's agent_fields for section-specific text
                belle = agent_results.get("belle", {}) or agent_results.get("document_analysis", {})
                if isinstance(belle, dict):
                    fields = belle.get("agent_fields", belle)
                    if isinstance(fields, dict) and fields.get(source):
                        return str(fields[source])[:4000]

        # Fallback to application_text
        app_text = application.get("application_text", "") or ""
        return app_text[:4000]

    # ------------------------------------------------------------------
    # SDK evaluation
    # ------------------------------------------------------------------

    def _evaluate_single(
        self,
        agent_name: str,
        evaluator_name: str,
        query: str,
        response: str,
        context: str,
    ) -> Optional[Dict[str, Any]]:
        """Run a single SDK evaluator and return score + reason."""
        evaluator = self._get_evaluator(evaluator_name)
        if not evaluator:
            return None

        try:
            result = evaluator(
                query=query,
                response=response,
                context=context,
            )
            # SDK returns e.g. {"groundedness": 4.0, "groundedness_reason": "..."}
            score = result.get(evaluator_name) or result.get(f"gpt_{evaluator_name}")
            reason = result.get(f"{evaluator_name}_reason") or result.get(f"gpt_{evaluator_name}_reason")
            if score is not None:
                return {"score": float(score), "reason": reason}
        except Exception as exc:
            logger.warning(f"SDK evaluator {evaluator_name} failed for {agent_name}: {exc}")
        return None

    # ------------------------------------------------------------------
    # Consistency metrics (no AI calls)
    # ------------------------------------------------------------------

    def compute_consistency_metrics(self) -> Dict[str, Any]:
        """Compute inter-agent agreement and outcome accuracy metrics.

        These metrics require no AI judge calls — they are computed purely
        from stored agent outputs and the ``was_selected`` ground truth.
        """
        metrics: Dict[str, Any] = {
            "merlin_gaston_agreement": None,
            "merlin_gaston_score_correlation": None,
            "outcome_accuracy": None,
            "per_agent_outcome_correlation": {},
            "score_distributions": {},
        }

        applications = self._get_training_applications()
        if not applications:
            return metrics

        # ── Merlin vs Gaston agreement ──
        merlin_scores: List[float] = []
        gaston_scores: List[float] = []
        merlin_recs: List[str] = []
        gaston_recs: List[str] = []
        agreements = 0
        comparisons = 0

        # ── Outcome accuracy ──
        true_positives = 0
        false_positives = 0
        true_negatives = 0
        false_negatives = 0
        outcome_pairs: List[Tuple[float, bool]] = []

        for app in applications:
            app_id = app.get("application_id")
            was_selected = app.get("was_selected")

            # Merlin
            merlin_row = self._get_agent_output("merlin_evaluations", app_id)
            merlin_score = None
            merlin_rec = None
            if merlin_row:
                merlin_score = merlin_row.get("overall_score")
                merlin_rec = (merlin_row.get("recommendation") or "").strip().lower()
                if merlin_score is not None:
                    merlin_scores.append(float(merlin_score))
                    merlin_recs.append(merlin_rec)

            # Gaston (stored in ai_evaluations with agent_name='Gaston')
            gaston_row = self._get_agent_output("ai_evaluations", app_id)
            gaston_score = None
            gaston_rec = None
            if gaston_row and (gaston_row.get("agent_name") or "").lower() == "gaston":
                gaston_score = gaston_row.get("overall_score")
                gaston_rec = (gaston_row.get("recommendation") or "").strip().lower()
                if gaston_score is not None:
                    gaston_scores.append(float(gaston_score))
                    gaston_recs.append(gaston_rec)

            # Agreement check (both must have recommendations)
            if merlin_rec and gaston_rec:
                comparisons += 1
                m_pos = merlin_rec in _REC_POSITIVE
                g_pos = gaston_rec in _REC_POSITIVE
                if m_pos == g_pos:
                    agreements += 1

            # Outcome accuracy (Merlin score vs was_selected)
            if merlin_score is not None and was_selected is not None:
                outcome_pairs.append((float(merlin_score), bool(was_selected)))
                predicted_positive = merlin_rec in _REC_POSITIVE if merlin_rec else float(merlin_score) >= 65
                actual_positive = bool(was_selected)
                if predicted_positive and actual_positive:
                    true_positives += 1
                elif predicted_positive and not actual_positive:
                    false_positives += 1
                elif not predicted_positive and actual_positive:
                    false_negatives += 1
                else:
                    true_negatives += 1

        # Compute agreement rate
        if comparisons > 0:
            metrics["merlin_gaston_agreement"] = round(agreements / comparisons * 100, 1)

        # Compute Pearson correlation between Merlin and Gaston scores
        if len(merlin_scores) >= 3 and len(gaston_scores) >= 3:
            n = min(len(merlin_scores), len(gaston_scores))
            ms = merlin_scores[:n]
            gs = gaston_scores[:n]
            try:
                metrics["merlin_gaston_score_correlation"] = round(
                    self._pearson(ms, gs), 4
                )
            except Exception:
                pass

        # Outcome accuracy metrics
        total_predictions = true_positives + false_positives + true_negatives + false_negatives
        if total_predictions > 0:
            accuracy = (true_positives + true_negatives) / total_predictions
            precision = true_positives / max(true_positives + false_positives, 1)
            recall = true_positives / max(true_positives + false_negatives, 1)
            f1 = 2 * precision * recall / max(precision + recall, 0.001)
            metrics["outcome_accuracy"] = {
                "accuracy": round(accuracy * 100, 1),
                "precision": round(precision * 100, 1),
                "recall": round(recall * 100, 1),
                "f1": round(f1 * 100, 1),
                "total": total_predictions,
                "confusion_matrix": {
                    "true_positives": true_positives,
                    "false_positives": false_positives,
                    "true_negatives": true_negatives,
                    "false_negatives": false_negatives,
                },
            }

        # Score distributions (accepted vs rejected)
        if outcome_pairs:
            accepted = [s for s, sel in outcome_pairs if sel]
            rejected = [s for s, sel in outcome_pairs if not sel]
            if accepted:
                metrics["score_distributions"]["accepted"] = {
                    "count": len(accepted),
                    "mean": round(statistics.mean(accepted), 1),
                    "median": round(statistics.median(accepted), 1),
                    "min": round(min(accepted), 1),
                    "max": round(max(accepted), 1),
                }
            if rejected:
                metrics["score_distributions"]["rejected"] = {
                    "count": len(rejected),
                    "mean": round(statistics.mean(rejected), 1),
                    "median": round(statistics.median(rejected), 1),
                    "min": round(min(rejected), 1),
                    "max": round(max(rejected), 1),
                }

        return metrics

    @staticmethod
    def _pearson(x: List[float], y: List[float]) -> float:
        """Compute Pearson correlation coefficient."""
        n = len(x)
        if n < 2:
            return 0.0
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        std_x = (sum((xi - mean_x) ** 2 for xi in x)) ** 0.5
        std_y = (sum((yi - mean_y) ** 2 for yi in y)) ** 0.5
        if std_x == 0 or std_y == 0:
            return 0.0
        return cov / (std_x * std_y)

    # ------------------------------------------------------------------
    # Full batch evaluation
    # ------------------------------------------------------------------

    def run_batch_evaluation(
        self,
        agents: Optional[List[str]] = None,
        evaluator_names: Optional[List[str]] = None,
        max_students: int = 0,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """Run a full batch evaluation on training students.

        Args:
            agents: List of agent names to evaluate (default: all configured)
            evaluator_names: List of evaluator names to use (default: per agent config)
            max_students: Max students to evaluate (0 = all)
            progress_callback: Optional callable(state_dict) for progress updates

        Returns:
            Summary dict with aggregate scores, per-agent breakdown, and consistency.
        """
        batch_id = f"eval_{uuid.uuid4().hex[:12]}_{int(time.time())}"
        started_at = time.time()

        target_agents = agents or list(AGENT_EVAL_CONFIG.keys())
        sdk_available = _SDK_AVAILABLE

        summary = {
            "batch_id": batch_id,
            "status": "running",
            "started_at": started_at,
            "sdk_available": sdk_available,
            "agents_evaluated": target_agents,
            "evaluators_used": [],
            "total_students": 0,
            "total_evaluations": 0,
            "per_agent": {},
            "consistency": {},
            "errors": [],
        }

        # Ensure eval tables exist
        self._ensure_tables()

        # Save run record
        self._save_run_record(batch_id, "running")

        try:
            if progress_callback:
                progress_callback({"state": "running", "progress": "fetching training data"})

            applications = self._get_training_applications()
            if max_students > 0:
                applications = applications[:max_students]

            summary["total_students"] = len(applications)

            if not applications:
                summary["status"] = "completed"
                summary["errors"].append("No training applications found")
                self._update_run_record(batch_id, summary)
                return summary

            # ── SDK evaluations ──
            if sdk_available:
                all_evaluators_used = set()
                for agent_name in target_agents:
                    agent_cfg = AGENT_EVAL_CONFIG.get(agent_name)
                    if not agent_cfg:
                        continue

                    evals = evaluator_names or agent_cfg["evaluators"]
                    agent_scores: Dict[str, List[float]] = {e: [] for e in evals}
                    agent_results_count = 0

                    for idx, app in enumerate(applications):
                        app_id = app.get("application_id")
                        if progress_callback:
                            progress_callback({
                                "state": "running",
                                "progress": f"Evaluating {agent_name} — student {idx + 1}/{len(applications)}",
                                "agent": agent_name,
                                "student_index": idx + 1,
                                "total_students": len(applications),
                            })

                        # Get agent output
                        row = self._get_agent_output(agent_cfg["table"], app_id)
                        if not row:
                            continue

                        response_text = self._build_response_text(row, agent_cfg["response_fields"])
                        if not response_text or len(response_text.strip()) < 20:
                            continue

                        context_text = self._get_context_text(app, agent_cfg["context_source"])
                        query_text = agent_cfg["query"]

                        for eval_name in evals:
                            result = self._evaluate_single(
                                agent_name, eval_name, query_text, response_text, context_text
                            )
                            if result:
                                agent_scores[eval_name].append(result["score"])
                                agent_results_count += 1
                                all_evaluators_used.add(eval_name)
                                self._save_result(
                                    batch_id, app_id, agent_name, eval_name,
                                    result["score"], result.get("reason"),
                                )

                    # Agent-level aggregates
                    agent_summary = {"evaluations": agent_results_count}
                    for eval_name, scores in agent_scores.items():
                        if scores:
                            agent_summary[eval_name] = {
                                "avg": round(statistics.mean(scores), 2),
                                "min": round(min(scores), 2),
                                "max": round(max(scores), 2),
                                "count": len(scores),
                            }
                    summary["per_agent"][agent_name] = agent_summary
                    summary["total_evaluations"] += agent_results_count

                summary["evaluators_used"] = sorted(all_evaluators_used)
            else:
                summary["errors"].append(
                    "azure-ai-evaluation SDK not installed — skipping SDK evaluators. "
                    "Only consistency metrics will be computed."
                )

            # ── Consistency metrics (always available) ──
            if progress_callback:
                progress_callback({"state": "running", "progress": "computing consistency metrics"})

            summary["consistency"] = self.compute_consistency_metrics()

            summary["status"] = "completed"
            summary["completed_at"] = time.time()
            summary["duration_seconds"] = round(time.time() - started_at, 1)

        except Exception as exc:
            logger.error(f"Batch evaluation failed: {exc}", exc_info=True)
            summary["status"] = "failed"
            summary["errors"].append(str(exc))

        self._update_run_record(batch_id, summary)
        return summary

    # ------------------------------------------------------------------
    # Results retrieval
    # ------------------------------------------------------------------

    def get_latest_results(self) -> Dict[str, Any]:
        """Get results from the most recent evaluation run."""
        try:
            run_query = """
                SELECT * FROM agent_evaluation_runs
                ORDER BY created_at DESC LIMIT 1
            """
            runs = self.db.execute_query(run_query)
            if not runs:
                return {"status": "no_runs", "message": "No evaluation runs found. Run an evaluation first."}

            run = runs[0]
            batch_id = run.get("batch_id")

            # Fetch per-agent aggregates
            agg_query = """
                SELECT agent_name, evaluator_name,
                       AVG(score) as avg_score,
                       MIN(score) as min_score,
                       MAX(score) as max_score,
                       COUNT(*) as eval_count
                FROM agent_evaluation_results
                WHERE batch_id = %s
                GROUP BY agent_name, evaluator_name
                ORDER BY agent_name, evaluator_name
            """
            agg_rows = self.db.execute_query(agg_query, (batch_id,)) or []

            per_agent: Dict[str, Dict] = {}
            for row in agg_rows:
                agent = row["agent_name"]
                evaluator = row["evaluator_name"]
                if agent not in per_agent:
                    per_agent[agent] = {}
                per_agent[agent][evaluator] = {
                    "avg": round(float(row["avg_score"]), 2) if row["avg_score"] else None,
                    "min": round(float(row["min_score"]), 2) if row["min_score"] else None,
                    "max": round(float(row["max_score"]), 2) if row["max_score"] else None,
                    "count": row["eval_count"],
                }

            return {
                "status": "success",
                "batch_id": batch_id,
                "run_status": run.get("status"),
                "started_at": str(run.get("started_at", "")),
                "completed_at": str(run.get("completed_at", "")),
                "total_students": run.get("total_students"),
                "total_evaluations": run.get("total_evaluations"),
                "avg_groundedness": float(run["avg_groundedness"]) if run.get("avg_groundedness") else None,
                "avg_coherence": float(run["avg_coherence"]) if run.get("avg_coherence") else None,
                "avg_relevance": float(run["avg_relevance"]) if run.get("avg_relevance") else None,
                "avg_fluency": float(run["avg_fluency"]) if run.get("avg_fluency") else None,
                "outcome_accuracy": float(run["outcome_accuracy"]) if run.get("outcome_accuracy") else None,
                "merlin_gaston_agreement": float(run["merlin_gaston_agreement"]) if run.get("merlin_gaston_agreement") else None,
                "per_agent": per_agent,
            }

        except Exception as exc:
            logger.error(f"Failed to fetch evaluation results: {exc}", exc_info=True)
            return {"status": "error", "message": str(exc)}

    def get_run_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get historical evaluation runs for trend tracking."""
        try:
            query = """
                SELECT batch_id, status, started_at, completed_at,
                       total_students, total_evaluations,
                       avg_groundedness, avg_coherence, avg_relevance, avg_fluency,
                       outcome_accuracy, merlin_gaston_agreement,
                       agents_evaluated, evaluators_used
                FROM agent_evaluation_runs
                ORDER BY created_at DESC
                LIMIT %s
            """
            rows = self.db.execute_query(query, (limit,)) or []
            results = []
            for row in rows:
                results.append({
                    "batch_id": row.get("batch_id"),
                    "status": row.get("status"),
                    "started_at": str(row.get("started_at", "")),
                    "completed_at": str(row.get("completed_at", "")),
                    "total_students": row.get("total_students"),
                    "total_evaluations": row.get("total_evaluations"),
                    "avg_groundedness": float(row["avg_groundedness"]) if row.get("avg_groundedness") else None,
                    "avg_coherence": float(row["avg_coherence"]) if row.get("avg_coherence") else None,
                    "avg_relevance": float(row["avg_relevance"]) if row.get("avg_relevance") else None,
                    "avg_fluency": float(row["avg_fluency"]) if row.get("avg_fluency") else None,
                    "outcome_accuracy": float(row["outcome_accuracy"]) if row.get("outcome_accuracy") else None,
                    "merlin_gaston_agreement": float(row["merlin_gaston_agreement"]) if row.get("merlin_gaston_agreement") else None,
                })
            return results
        except Exception as exc:
            logger.error(f"Failed to fetch run history: {exc}", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Database persistence
    # ------------------------------------------------------------------

    def _ensure_tables(self):
        """Create evaluation tables if they don't exist."""
        try:
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS agent_evaluation_results (
                    evaluation_result_id SERIAL PRIMARY KEY,
                    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
                    agent_name VARCHAR(100) NOT NULL,
                    evaluator_name VARCHAR(100) NOT NULL,
                    score NUMERIC(5,2),
                    reason TEXT,
                    batch_id VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS agent_evaluation_runs (
                    run_id SERIAL PRIMARY KEY,
                    batch_id VARCHAR(100) UNIQUE NOT NULL,
                    status VARCHAR(50) DEFAULT 'running',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    total_students INTEGER DEFAULT 0,
                    total_evaluations INTEGER DEFAULT 0,
                    avg_groundedness NUMERIC(5,2),
                    avg_coherence NUMERIC(5,2),
                    avg_relevance NUMERIC(5,2),
                    avg_fluency NUMERIC(5,2),
                    merlin_gaston_agreement NUMERIC(5,2),
                    merlin_gaston_score_corr NUMERIC(5,4),
                    outcome_accuracy NUMERIC(5,2),
                    outcome_precision NUMERIC(5,2),
                    outcome_recall NUMERIC(5,2),
                    outcome_f1 NUMERIC(5,2),
                    evaluators_used TEXT,
                    agents_evaluated TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        except Exception as exc:
            logger.warning(f"Could not ensure evaluation tables: {exc}")

    def _save_result(
        self,
        batch_id: str,
        application_id: int,
        agent_name: str,
        evaluator_name: str,
        score: float,
        reason: Optional[str],
    ):
        """Persist a single evaluation result."""
        try:
            self.db.execute_query(
                """
                INSERT INTO agent_evaluation_results
                    (application_id, agent_name, evaluator_name, score, reason, batch_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (application_id, agent_name, evaluator_name, score, reason, batch_id),
            )
        except Exception as exc:
            logger.warning(f"Failed to save eval result: {exc}")

    def _save_run_record(self, batch_id: str, status: str):
        """Create a run record."""
        try:
            self.db.execute_query(
                """
                INSERT INTO agent_evaluation_runs (batch_id, status)
                VALUES (%s, %s)
                ON CONFLICT (batch_id) DO NOTHING
                """,
                (batch_id, status),
            )
        except Exception as exc:
            logger.warning(f"Failed to save run record: {exc}")

    def _update_run_record(self, batch_id: str, summary: Dict[str, Any]):
        """Update the run record with final results."""
        try:
            consistency = summary.get("consistency", {})
            outcome = consistency.get("outcome_accuracy", {})

            self.db.execute_query(
                """
                UPDATE agent_evaluation_runs SET
                    status = %s,
                    completed_at = NOW(),
                    total_students = %s,
                    total_evaluations = %s,
                    avg_groundedness = %s,
                    avg_coherence = %s,
                    avg_relevance = %s,
                    avg_fluency = %s,
                    merlin_gaston_agreement = %s,
                    merlin_gaston_score_corr = %s,
                    outcome_accuracy = %s,
                    outcome_precision = %s,
                    outcome_recall = %s,
                    outcome_f1 = %s,
                    evaluators_used = %s,
                    agents_evaluated = %s,
                    error_message = %s
                WHERE batch_id = %s
                """,
                (
                    summary.get("status", "completed"),
                    summary.get("total_students", 0),
                    summary.get("total_evaluations", 0),
                    self._avg_from_per_agent(summary, "groundedness"),
                    self._avg_from_per_agent(summary, "coherence"),
                    self._avg_from_per_agent(summary, "relevance"),
                    self._avg_from_per_agent(summary, "fluency"),
                    consistency.get("merlin_gaston_agreement"),
                    consistency.get("merlin_gaston_score_correlation"),
                    outcome.get("accuracy") if isinstance(outcome, dict) else None,
                    outcome.get("precision") if isinstance(outcome, dict) else None,
                    outcome.get("recall") if isinstance(outcome, dict) else None,
                    outcome.get("f1") if isinstance(outcome, dict) else None,
                    ", ".join(summary.get("evaluators_used", [])),
                    ", ".join(summary.get("agents_evaluated", [])),
                    "; ".join(summary.get("errors", [])) or None,
                    batch_id,
                ),
            )
        except Exception as exc:
            logger.warning(f"Failed to update run record: {exc}")

    @staticmethod
    def _avg_from_per_agent(summary: Dict, metric: str) -> Optional[float]:
        """Compute an overall average for a metric across all agents."""
        values = []
        for agent_data in summary.get("per_agent", {}).values():
            m = agent_data.get(metric)
            if isinstance(m, dict) and m.get("avg") is not None:
                values.append(m["avg"])
        return round(statistics.mean(values), 2) if values else None
