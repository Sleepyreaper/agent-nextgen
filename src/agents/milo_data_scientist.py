"""Milo Data Scientist - Deep-learning pattern analysis for student selection.

Milo is the quantitative brain of the NextGen Scholars evaluation system.
He studies every accepted and rejected student from prior cohorts, learns
what separates the best from the rest, and applies that intelligence to
score, rank, and recommend the 2026 applicant pool.

Character: Milo Thatch (Disney's "Atlantis: The Lost Empire") -
           a meticulous researcher who dives deep into data.
"""

import json
import logging
import os
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from src.agents.base_agent import BaseAgent
from src.config import config
from src.telemetry import get_tracer
from src.agents.telemetry_helpers import agent_run
from src.agents.naveen_school_data_scientist import NaveenSchoolDataScientist
from src.utils import safe_load_json

logger = logging.getLogger(__name__)

# --- Constants ---
MAX_TRAINING_SAMPLES = 60          # Max samples per group sent to AI
MAX_CANDIDATE_TEXT_LEN = 2500      # Truncation for long text fields per candidate
MAX_BATCH_SIZE = 8                 # Candidates evaluated per AI call in batch mode
RANKING_CACHE_SECONDS = 900        # 15-minute cache for the full ranking


class MiloDataScientist(BaseAgent):
    """
    Milo (Data Scientist) - builds a selection model from training outcomes
    and applies it to rank the 2026 applicant pool.

    Capabilities:
    - Analyze 100+ rejected and 20+ accepted training examples to learn patterns
    - Cross-reference historical human rubric scores (2024 cohort)
    - Evaluate every 2026 applicant with a multi-dimensional AI-driven score
    - Produce a ranked Top-50 nominee list (to be narrowed to 25)
    - Persist rankings for the UI leaderboard
    """

    def __init__(
        self,
        name: str = "Milo Data Scientist",
        client: Any = None,
        model: Optional[str] = None,
        db_connection: Optional[Any] = None,
        max_samples_per_group: int = MAX_TRAINING_SAMPLES,
        cache_seconds: int = 600
    ):
        super().__init__(name, client)
        self.model = (
            model
            or config.model_tier_premium
            or config.foundry_model_name
            or config.deployment_name
        )
        self.model_display = self.model or "unknown"
        self.db = db_connection
        self.max_samples_per_group = max_samples_per_group
        self.cache_seconds = cache_seconds
        self.emoji = "📊"
        self.description = "Analyzes historical patterns and ranks 2026 candidates"

        # Insight cache
        self._cached_insights: Optional[Dict[str, Any]] = None
        self._cached_at: float = 0
        self._cached_signature: Optional[tuple] = None

        # Ranking cache
        self._cached_ranking: Optional[Dict[str, Any]] = None
        self._cached_ranking_at: float = 0

    # -------------------------------------------------------------------
    #  STEP 1 - LEARN FROM TRAINING DATA
    # -------------------------------------------------------------------

    async def analyze_training_insights(self) -> Dict[str, Any]:
        """Analyze ALL training data to build a comprehensive selection model.

        Pulls every training example (accepted & not-selected), enriches each
        with agent outputs (Tiana, Rapunzel, Mulan, Merlin scores) and
        historical human rubric scores, then asks the AI to identify the
        deep patterns that separate selected from rejected candidates.
        """
        _otel = agent_run("Milo Data Scientist", "analyze_training_insights",
                          agent_id="milo-data-scientist")
        _otel.__enter__()

        if not self.db:
            _otel.__exit__(None, None, None)
            return self._error("Database connection not available")

        try:
            training_examples = self.db.get_training_examples()
        except Exception as e:
            _otel.__exit__(None, None, None)
            return self._error(str(e))

        # Load historical human scoring data for calibration
        historical_data = self._load_historical_data()

        # Build enriched samples with agent outputs
        samples = self._build_enriched_samples(training_examples)
        signature = (
            samples["counts"]["selected"],
            samples["counts"]["not_selected"],
            samples["counts"]["unknown"],
            historical_data.get("total_scored", 0) if historical_data else 0,
        )

        if self._is_cache_valid(signature):
            cached = dict(self._cached_insights)
            cached["cached"] = True
            _otel.__exit__(None, None, None)
            return cached

        prompt = self._build_insight_prompt(samples, historical_data)

        try:
            response = self._create_chat_completion(
                operation="milo.analyze_training",
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt_insights()},
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=3000,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            data = safe_load_json(response.choices[0].message.content)
            data.update({
                "status": "success",
                "agent": self.name,
                "model_used": self.model,
                "model_display": self.model_display,
                "cached": False,
                "training_counts": samples["counts"],
                "sample_sizes": samples["sample_sizes"],
                "historical_data_available": bool(
                    historical_data and historical_data.get("total_scored", 0) > 0
                ),
                "historical_scored_count": (
                    historical_data.get("total_scored", 0) if historical_data else 0
                ),
            })
        except Exception as e:
            data = self._error(str(e))

        self._cached_insights = data
        self._cached_signature = signature
        self._cached_at = time.time()
        _otel.__exit__(None, None, None)
        return data

    # -------------------------------------------------------------------
    #  STEP 2 - EVALUATE A SINGLE CANDIDATE
    # -------------------------------------------------------------------

    async def compute_alignment(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Deep-evaluate a single 2026 applicant against learned patterns.

        Uses training insights + historical scores + the full rubric to
        produce a multi-dimensional score with detailed rationale.

        Returns:
            nextgen_match (0-100)   - probability of being in the final 50
            match_score (0-100)     - raw profile alignment
            rubric_scores           - estimated 0-12 rubric breakdown
            tier                    - STRONG ADMIT / ADMIT / WAITLIST / DECLINE
            key_strengths           - top differentiators
            key_risks               - concerns
            explanation             - 3-5 sentence rationale
        """
        _otel = agent_run("Milo Data Scientist", "compute_alignment",
                          agent_id="milo-data-scientist")
        _otel.__enter__()

        if not application:
            _otel.__exit__(None, None, None)
            return {"status": "error", "error": "No application provided"}

        # Ensure fresh training insights
        insights = await self.analyze_training_insights()

        # Build rich candidate profile
        candidate = self._build_candidate_profile(application)

        # Look up historical human score for this student
        historical_context = self._get_historical_context_for_student(application)

        prompt = self._build_evaluation_prompt(candidate, insights, historical_context)

        try:
            response = self._create_chat_completion(
                operation="milo.compute_alignment",
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt_evaluate()},
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=1500,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            data = safe_load_json(response.choices[0].message.content)

            # Normalise keys
            if "nextgen_match" not in data and "match_score" in data:
                data["nextgen_match"] = data["match_score"]
            data.setdefault("status", "success")
            data.setdefault("agent", self.name)
            # Backward compat: populate key_differentiators from key_strengths
            if "key_differentiators" not in data and "key_strengths" in data:
                data["key_differentiators"] = data["key_strengths"]
        except Exception as e:
            data = {"status": "error", "agent": self.name, "error": str(e)}

        _otel.__exit__(None, None, None)
        return data

    # -------------------------------------------------------------------
    #  STEP 3 - RANK ALL 2026 CANDIDATES -> TOP 50
    # -------------------------------------------------------------------

    async def rank_all_candidates(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Evaluate every 2026 (non-training, non-test) application and produce
        a ranked nominee list.

        Returns the Top 50 with scores, tiers, and a recommended Top 25 shortlist.
        Results are cached and can be persisted to the database.
        """
        _otel = agent_run("Milo Data Scientist", "rank_all_candidates",
                          agent_id="milo-data-scientist")
        _otel.__enter__()

        if not self.db:
            _otel.__exit__(None, None, None)
            return self._error("Database connection not available")

        # Check ranking cache
        if (
            not force_refresh
            and self._cached_ranking
            and (time.time() - self._cached_ranking_at) < RANKING_CACHE_SECONDS
        ):
            cached = dict(self._cached_ranking)
            cached["cached"] = True
            _otel.__exit__(None, None, None)
            return cached

        # Get training insights first
        insights = await self.analyze_training_insights()

        # Fetch all 2026 applications (non-training, non-test)
        candidates = self._get_2026_candidates()
        if not candidates:
            _otel.__exit__(None, None, None)
            return {
                "status": "no_candidates",
                "agent": self.name,
                "message": "No 2026 applications found to rank.",
                "total_candidates": 0,
            }

        logger.info("Milo ranking %d candidates...", len(candidates))

        # Evaluate in batches
        scored_candidates = []
        for i in range(0, len(candidates), MAX_BATCH_SIZE):
            batch = candidates[i : i + MAX_BATCH_SIZE]
            batch_results = await self._evaluate_batch(batch, insights)
            scored_candidates.extend(batch_results)

        # Sort by composite score (nextgen_match) descending
        scored_candidates.sort(
            key=lambda c: c.get("nextgen_match", 0), reverse=True
        )

        # Assign ranks
        for rank, candidate in enumerate(scored_candidates, 1):
            candidate["rank"] = rank

        top_50 = scored_candidates[:50]
        top_25 = scored_candidates[:25]

        # Build tier distribution
        tier_counts = {}
        for c in scored_candidates:
            tier = c.get("tier", "UNKNOWN")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        result = {
            "status": "success",
            "agent": self.name,
            "model_used": self.model,
            "model_display": self.model_display,
            "cached": False,
            "total_candidates": len(candidates),
            "total_scored": len(scored_candidates),
            "top_50": top_50,
            "top_25_shortlist": top_25,
            "all_ranked": scored_candidates,
            "tier_distribution": tier_counts,
            "score_stats": self._compute_score_stats(scored_candidates),
            "generated_at": datetime.utcnow().isoformat(),
        }

        self._cached_ranking = result
        self._cached_ranking_at = time.time()

        # Persist rankings to DB
        self._persist_rankings(scored_candidates)

        _otel.__exit__(None, None, None)
        return result

    # -------------------------------------------------------------------
    #  BATCH EVALUATION
    # -------------------------------------------------------------------

    async def _evaluate_batch(
        self, batch: List[Dict[str, Any]], insights: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Evaluate a batch of candidates in a single AI call for efficiency."""
        profiles = []
        for app in batch:
            profile = self._build_candidate_profile(app)
            hist = self._get_historical_context_for_student(app)
            if hist:
                profile["historical_human_scores"] = hist
            profiles.append(profile)

        prompt = self._build_batch_evaluation_prompt(profiles, insights)

        try:
            payload = None
            for attempt in range(2):
                response = self._create_chat_completion(
                    operation="milo.evaluate_batch",
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self._system_prompt_evaluate()},
                        {"role": "user", "content": prompt},
                    ],
                    max_completion_tokens=3000,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                payload = safe_load_json(response.choices[0].message.content)

                # Guard against malformed JSON (safe_load_json returns the raw
                # string when parsing fails, and calling .get() on a str crashes).
                if isinstance(payload, dict):
                    break
                logger.warning(
                    "Milo batch response attempt %d was not valid JSON dict: %s",
                    attempt + 1,
                    str(payload)[:300],
                )

            if not isinstance(payload, dict):
                payload = {"evaluations": []}

            evaluations = payload.get("evaluations", [])

            # Merge back with application metadata
            results = []
            for i, app in enumerate(batch):
                if i < len(evaluations):
                    eval_data = evaluations[i]
                    # Guard individual entries (AI may return a string instead
                    # of a dict for a single evaluation).
                    if not isinstance(eval_data, dict):
                        logger.warning(
                            "Milo evaluation[%d] not a dict: %s", i, str(eval_data)[:200]
                        )
                        eval_data = {
                            "nextgen_match": 0,
                            "match_score": 0,
                            "tier": "DECLINE",
                            "explanation": "Malformed AI evaluation response.",
                        }
                else:
                    eval_data = {
                        "nextgen_match": 0,
                        "match_score": 0,
                        "tier": "DECLINE",
                        "explanation": "Evaluation failed - no AI response for this candidate.",
                    }
                eval_data["application_id"] = app.get("application_id")
                eval_data["applicant_name"] = (
                    app.get("applicant_name")
                    or "{} {}".format(
                        app.get("first_name", ""), app.get("last_name", "")
                    ).strip()
                )
                eval_data["high_school"] = app.get("high_school") or app.get("school_name")
                eval_data["state_code"] = app.get("state_code")
                # Ensure nextgen_match exists
                if "nextgen_match" not in eval_data and "match_score" in eval_data:
                    eval_data["nextgen_match"] = eval_data["match_score"]
                results.append(eval_data)

            return results

        except Exception as e:
            logger.error("Milo batch evaluation failed: %s", e)
            # Return zero-score fallbacks
            return [
                {
                    "application_id": app.get("application_id"),
                    "applicant_name": app.get("applicant_name", "Unknown"),
                    "nextgen_match": 0,
                    "match_score": 0,
                    "tier": "DECLINE",
                    "explanation": "Evaluation error: {}".format(e),
                }
                for app in batch
            ]

    # -------------------------------------------------------------------
    #  FOUNDRY DATASET (existing functionality preserved)
    # -------------------------------------------------------------------

    async def build_and_upload_foundry_dataset(self) -> Dict[str, Any]:
        """Build a Foundry dataset from training data and upload it."""
        if not self.db:
            return self._error("Database connection not available")

        project_endpoint = config.foundry_project_endpoint
        if not project_endpoint:
            return self._error("Foundry project endpoint not configured")

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
            return self._error("No training examples available")

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
            return self._error(str(e))
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
                    "content": (
                        "You are Milo, a data scientist who analyzes patterns "
                        "in student selection data for the Emory NextGen Scholars program."
                    ),
                }
            ]
            + self.conversation_history,
            max_completion_tokens=600,
            temperature=0.4,
        )
        assistant_message = response.choices[0].message.content
        self.add_to_history("assistant", assistant_message)
        return assistant_message

    # -------------------------------------------------------------------
    #  SYSTEM PROMPTS
    # -------------------------------------------------------------------

    def _system_prompt_insights(self) -> str:
        return (
            "You are Milo, the chief data scientist for the Emory NextGen Scholars "
            "program - a highly selective NIH-funded summer research program for "
            "high school students interested in STEM and genetics.\n\n"
            "PROGRAM FACTS:\n"
            "- Approximately 30 openings per cohort from 1,000+ applicants (~3% rate)\n"
            "- For 2026 we are expanding to select a TOP 50 nominee list, then narrow to 25\n"
            "- Students must be rising juniors/seniors, age 16+ by June 1, 2026\n"
            "- Priority for underrepresented/under-resourced backgrounds in STEM\n\n"
            "YOUR TASK:\n"
            "Study the training data below - it contains REAL students who were either "
            "SELECTED (was_selected=true) for the program or NOT SELECTED (was_selected=false). "
            "Some may have unknown selection status. Each student may include:\n"
            "  - Application essay text\n"
            "  - Transcript / academic data (GPA, courses)\n"
            "  - Recommendation letter excerpts\n"
            "  - Agent analysis outputs (Tiana application reader, Rapunzel grade reader, "
            "    Mulan recommendation reader, Merlin overall evaluator scores)\n"
            "  - Historical human rubric scores from 2024 reviewers\n\n"
            "RUBRIC (0-12 + Bonus):\n"
            "  1. Academic Record (0-3): 3=Exceptional, 2=Solid, 1=Adequate, 0=Weak\n"
            "  2. STEM Interest (0-3): 3=Deep passion with specifics, 2=Clear interest, 1=Vague, 0=None\n"
            "  3. Essay/Video (0-3): 3=Exceptional, 2=Good, 1=Minimal, 0=Missing\n"
            "  4. Recommendation (0-2): 2=Strong specific, 1=Adequate, 0=Weak\n"
            "  5. Bonus (0-1): research experience, adversity, extraordinary achievement\n\n"
            "BUILD A COMPREHENSIVE MODEL. Identify:\n"
            "  - What GPA range, coursework, and academic patterns selected students share\n"
            "  - What STEM interests and depth characterize winners\n"
            "  - What essay qualities and themes lead to selection\n"
            "  - What recommendation characteristics matter most\n"
            "  - What school backgrounds, extracurriculars, and experiences correlate with selection\n"
            "  - What clearly separates selected from not-selected students\n"
            "  - What red flags or weak signals consistently appear in not-selected students\n"
            "  - Calibration: what rubric score thresholds predict selection (e.g. total >= 9)\n\n"
            "IMPORTANT DISTINCTIONS:\n"
            "  - 'Eligible/accepted' = met basic requirements (correct files, age 16+, on time).\n"
            "    It does NOT mean chosen for the program.\n"
            "  - 'Selected' (was_selected=true) = actually chosen. THIS is the gold standard.\n\n"
            "Be precise and data-driven. Quote specific patterns from the data. "
            "If evidence is thin, say so. Return valid JSON only."
        )

    def _system_prompt_evaluate(self) -> str:
        return (
            "You are Milo, the chief data scientist for the Emory NextGen Scholars program.\n\n"
            "You have studied 100+ rejected and 20+ accepted students from prior cohorts. "
            "You know exactly what separates winners from the rest.\n\n"
            "SCORING CALIBRATION (critical - be realistic):\n"
            "- The program accepts ~3% of applicants. Most students score 20-40.\n"
            "- Only truly outstanding candidates matching the selected-student profile "
            "should score above 70.\n"
            "- A score of 50 means the student is competitive but not a lock.\n"
            "- Scores above 80 should be rare - reserved for students who closely "
            "match the best accepted students from prior cohorts.\n"
            "- Use the FULL 0-100 range. Don't cluster everyone at 60-80.\n\n"
            "RUBRIC (0-12 + Bonus) - estimate these for each candidate:\n"
            "  1. Academic Record (0-3): GPA, AP/IB/honors courseload, transcript strength\n"
            "  2. STEM Interest (0-3): depth, specificity, research/projects/clubs\n"
            "  3. Essay/Video (0-3): quality, authenticity, effort, storytelling\n"
            "  4. Recommendation (0-2): strength, specificity, endorsement level\n"
            "  5. Bonus (0-1): adversity, prior research, extraordinary achievement\n\n"
            "TIER ASSIGNMENTS:\n"
            "  STRONG ADMIT = nextgen_match >= 75 (exceptional, top ~5%)\n"
            "  ADMIT        = nextgen_match 55-74 (strong, competitive)\n"
            "  WAITLIST      = nextgen_match 35-54 (potential but gaps)\n"
            "  DECLINE       = nextgen_match < 35 (does not meet bar)\n\n"
            "When historical human rubric scores are available, weight them heavily - "
            "they are ground truth from expert reviewers.\n\n"
            "Return valid JSON only."
        )

    # -------------------------------------------------------------------
    #  DATA BUILDING HELPERS
    # -------------------------------------------------------------------

    def _build_enriched_samples(
        self, training_examples: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build training samples enriched with agent outputs & historical scores."""
        selected = []
        not_selected = []
        unknown = []

        for row in training_examples:
            application_id = row.get("application_id") or row.get("ApplicationID")
            item = {
                "applicant_name": row.get("applicant_name") or row.get("applicantname"),
                "was_selected": row.get("was_selected"),
                "status": row.get("status"),
                "high_school": (
                    row.get("high_school") or row.get("school_name")
                    or row.get("schoolname")
                ),
                "state_code": row.get("state_code"),
                "gpa": row.get("gpa"),
                "activities": row.get("activities"),
                "application_text": self._truncate(
                    row.get("application_text") or row.get("applicationtext"),
                    limit=1500,
                ),
                "transcript_text": self._truncate(
                    row.get("transcript_text") or row.get("transcripttext"),
                    limit=1500,
                ),
                "recommendation_text": self._truncate(
                    row.get("recommendation_text") or row.get("recommendationtext"),
                    limit=1500,
                ),
            }

            # Enrich with agent outputs (Tiana, Rapunzel, Mulan, Merlin scores)
            if application_id:
                agent_outputs = self._load_agent_outputs(application_id)
                if agent_outputs:
                    item["agent_scores"] = self._extract_agent_scores(agent_outputs)

                # Also pull from agent_results JSON stored on the application row
                agent_results = row.get("agent_results")
                if agent_results:
                    if isinstance(agent_results, str):
                        agent_results = safe_load_json(agent_results)
                    if isinstance(agent_results, dict):
                        stored_scores = self._extract_agent_scores(agent_results)
                        if stored_scores:
                            item.setdefault("agent_scores", {})
                            for k, v in stored_scores.items():
                                if v is not None and k not in item["agent_scores"]:
                                    item["agent_scores"][k] = v

            # Enrich with historical human rubric scores
            student_name = item.get("applicant_name", "")
            if student_name and self.db:
                try:
                    historical = self.db.get_historical_score_by_name(student_name)
                    if historical:
                        item["human_scores"] = {
                            "eligible": (historical.get("status") or "").lower() == "accepted",
                            "was_selected_2024": historical.get("was_selected"),
                            "academic_record": self._safe_float(historical.get("academic_record")),
                            "stem_interest": self._safe_float(historical.get("stem_interest")),
                            "essay_video": self._safe_float(historical.get("essay_video")),
                            "recommendation": self._safe_float(historical.get("recommendation")),
                            "bonus": self._safe_float(historical.get("bonus")),
                            "total_rating": self._safe_float(historical.get("total_rating")),
                            "overall_rating": historical.get("overall_rating"),
                            "preliminary_score": historical.get("preliminary_score"),
                        }
                except Exception:
                    pass

            # Enrich with structured school features from Naveen
            school_name = item.get("high_school")
            state_code = item.get("state_code")
            if school_name and self.db:
                try:
                    school_data = self.db.get_school_enriched_data(
                        school_name=school_name, state_code=state_code
                    )
                    if not school_data and state_code:
                        school_data = self.db.get_school_enriched_data_fuzzy(
                            school_name, state_code=state_code, threshold=0.6
                        )
                    if school_data:
                        item["school_features"] = NaveenSchoolDataScientist.generate_school_features(school_data)
                except Exception:
                    pass

            if item["was_selected"] is True:
                selected.append(item)
            elif item["was_selected"] is False:
                not_selected.append(item)
            else:
                unknown.append(item)

        # Send up to max_samples_per_group, but ALL selected (they are precious)
        selected_sample = selected[: self.max_samples_per_group]
        not_selected_sample = not_selected[: self.max_samples_per_group]
        unknown_sample = unknown[: min(self.max_samples_per_group, 20)]

        return {
            "counts": {
                "selected": len(selected),
                "not_selected": len(not_selected),
                "unknown": len(unknown),
                "accepted": len(selected),
            },
            "sample_sizes": {
                "selected": len(selected_sample),
                "not_selected": len(not_selected_sample),
                "unknown": len(unknown_sample),
                "accepted": len(selected_sample),
            },
            "samples": {
                "selected": selected_sample,
                "not_selected": not_selected_sample,
                "unknown": unknown_sample,
                "accepted": selected_sample,
            },
        }

    def _extract_agent_scores(self, agent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Pull numeric scores from agent output data."""
        scores: Dict[str, Any] = {}

        # Merlin
        merlin = agent_data.get("merlin") or {}
        if isinstance(merlin, dict):
            scores["merlin_overall"] = self._safe_float(
                merlin.get("overall_score") or merlin.get("overallscore")
            )
            scores["merlin_recommendation"] = merlin.get("recommendation")
            parsed = merlin.get("parsed_json") or merlin.get("parsedjson")
            if parsed:
                if isinstance(parsed, str):
                    parsed = safe_load_json(parsed)
                if isinstance(parsed, dict):
                    for key in ("academic_record_score", "stem_interest_score",
                                "essay_score", "recommendation_score", "bonus_score",
                                "total_rubric_score"):
                        if parsed.get(key) is not None:
                            scores[key] = self._safe_float(parsed[key])

        # Tiana
        tiana = agent_data.get("tiana") or {}
        if isinstance(tiana, dict):
            scores["readiness_score"] = self._safe_float(
                tiana.get("readiness_score") or tiana.get("readinessscore")
            )

        # Rapunzel
        rapunzel = agent_data.get("rapunzel") or {}
        if isinstance(rapunzel, dict):
            parsed = rapunzel.get("parsed_json") or rapunzel.get("parsedjson")
            if parsed:
                if isinstance(parsed, str):
                    parsed = safe_load_json(parsed)
                if isinstance(parsed, dict):
                    scores["gpa"] = self._safe_float(parsed.get("gpa"))
                    scores["academic_rigor"] = (
                        parsed.get("academic_rigor") or parsed.get("course_rigor")
                    )

        # Mulan
        mulan = agent_data.get("mulan") or {}
        if isinstance(mulan, dict):
            scores["endorsement_strength"] = self._safe_float(
                mulan.get("endorsement_strength") or mulan.get("endorsementstrength")
            )
            scores["specificity_score"] = self._safe_float(
                mulan.get("specificity_score") or mulan.get("specificityscore")
            )

        # Moana (school context)
        moana = (
            agent_data.get("moana")
            or agent_data.get("student_school_context")
            or {}
        )
        if isinstance(moana, dict):
            scores["opportunity_score"] = self._safe_float(
                moana.get("program_access_score") or moana.get("opportunity_score")
            )

        # Remove None values
        return {k: v for k, v in scores.items() if v is not None}

    def _build_candidate_profile(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Build a rich profile for a single candidate."""
        profile: Dict[str, Any] = {}
        identity_keys = (
            "application_id", "applicant_name", "first_name", "last_name",
            "high_school", "state_code", "gpa", "activities", "interest",
        )
        for key in identity_keys:
            if application.get(key):
                profile[key] = application[key]

        # Text fields (truncated)
        for key in ("application_text", "transcript_text", "recommendation_text"):
            val = application.get(key) or application.get(key.replace("_", ""))
            if val:
                profile[key] = self._truncate(str(val), MAX_CANDIDATE_TEXT_LEN)

        # Agent results
        agent_results = application.get("agent_results")
        if agent_results:
            if isinstance(agent_results, str):
                agent_results = safe_load_json(agent_results)
            if isinstance(agent_results, dict):
                scores = self._extract_agent_scores(agent_results)
                if scores:
                    profile["agent_scores"] = scores

        # Student summary
        summary = application.get("student_summary")
        if summary:
            if isinstance(summary, str):
                summary = safe_load_json(summary)
            if isinstance(summary, dict):
                for k in ("overall_assessment", "key_strengths", "areas_of_concern",
                           "recommendation", "stem_interest"):
                    if summary.get(k):
                        profile["summary_{}".format(k)] = summary[k]

        return profile

    def _get_historical_context_for_student(
        self, application: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Look up historical human scores for a specific student."""
        if not self.db:
            return None
        name = application.get("applicant_name", "")
        if not name:
            first = application.get("first_name", "")
            last = application.get("last_name", "")
            name = "{} {}".format(first, last).strip()
        if not name:
            return None
        try:
            score = self.db.get_historical_score_by_name(name)
            if not score:
                return None
            return {
                "eligible": (score.get("status") or "").lower() == "accepted",
                "was_selected": score.get("was_selected"),
                "academic_record": self._safe_float(score.get("academic_record")),
                "stem_interest": self._safe_float(score.get("stem_interest")),
                "essay_video": self._safe_float(score.get("essay_video")),
                "recommendation": self._safe_float(score.get("recommendation")),
                "bonus": self._safe_float(score.get("bonus")),
                "total_rating": self._safe_float(score.get("total_rating")),
                "overall_rating": score.get("overall_rating"),
                "preliminary_score": score.get("preliminary_score"),
                "reviewer_name": score.get("reviewer_name"),
            }
        except Exception:
            return None

    def _get_2026_candidates(self) -> List[Dict[str, Any]]:
        """Fetch all 2026 applications that are not training data and not test data."""
        if not self.db:
            return []
        try:
            # Use the existing DB method that returns non-training apps
            apps = self.db.get_applications_with_evaluations()
            # Filter out test data
            candidates = []
            for app in apps:
                is_test = app.get("is_test_data")
                if is_test is True:
                    continue
                # Parse JSON columns
                for key in ("student_summary", "agent_results"):
                    if key in app and isinstance(app[key], str):
                        try:
                            app[key] = safe_load_json(app[key])
                        except Exception:
                            pass
                candidates.append(app)
            return candidates
        except Exception as e:
            logger.error("Error fetching 2026 candidates: %s", e)
            return []

    def _load_historical_data(self) -> Optional[Dict[str, Any]]:
        """Load historical human scoring data."""
        try:
            if self.db:
                return self.db.get_historical_scores_for_milo(2024)
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------
    #  PROMPT BUILDERS
    # -------------------------------------------------------------------

    def _build_insight_prompt(
        self, samples: Dict[str, Any], historical_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build the comprehensive training analysis prompt."""
        lines = [
            "=== TRAINING DATA ANALYSIS REQUEST ===",
            "",
            "Total training examples: {} SELECTED, {} NOT SELECTED, {} unknown status.".format(
                samples["counts"]["selected"],
                samples["counts"]["not_selected"],
                samples["counts"]["unknown"],
            ),
            "",
        ]

        # Historical rubric data section
        if historical_data and historical_data.get("total_scored", 0) > 0:
            has_selection = historical_data.get("has_selection_data", False)
            selected_scores = historical_data.get("selected_scores", [])
            not_selected_scores = historical_data.get("not_selected_scores", [])
            unknown_scores = historical_data.get("selection_unknown_scores", [])

            lines.extend([
                "=== HISTORICAL HUMAN RUBRIC SCORES (2024 Cohort) ===",
                "Total scored by human reviewers: {}".format(historical_data["total_scored"]),
            ])

            if has_selection:
                lines.extend([
                    "SELECTED students with scores: {}".format(len(selected_scores)),
                    "NOT SELECTED students with scores: {}".format(len(not_selected_scores)),
                    "Selection unknown: {}".format(len(unknown_scores)),
                ])
            else:
                lines.append(
                    "NOTE: Selection outcomes not yet linked to scores. "
                    "Use rubric scores as reference."
                )

            lines.extend([
                "",
                "Rubric: Academic Record (0-3), STEM Interest (0-3), Essay/Video (0-3), "
                "Recommendation (0-2), Bonus (0-1) = Total (0-12)",
                "",
            ])

            stats = historical_data.get("stats", {})
            if stats.get("avg_selected_total"):
                lines.append(
                    "Avg total for SELECTED: {:.1f}/12".format(stats["avg_selected_total"])
                )
            if stats.get("avg_not_selected_total"):
                lines.append(
                    "Avg total for NOT SELECTED: {:.1f}/12".format(stats["avg_not_selected_total"])
                )
            if stats.get("avg_eligible_total"):
                lines.append(
                    "Avg total for eligible: {:.1f}/12".format(stats["avg_eligible_total"])
                )

            if selected_scores:
                lines.append("\nSELECTED students' human rubric scores (model students):")
                lines.append(json.dumps(selected_scores[:25], ensure_ascii=True))
            if not_selected_scores:
                lines.append("\nNOT SELECTED students' human rubric scores:")
                lines.append(json.dumps(not_selected_scores[:25], ensure_ascii=True))
            if not has_selection and unknown_scores:
                lines.append("\nAll scored (selection unknown - reference only):")
                lines.append(json.dumps(unknown_scores[:25], ensure_ascii=True))

            lines.append("=== END HISTORICAL SCORES ===\n")

        # Selected students (the gold standard)
        if samples["samples"]["selected"]:
            lines.append(
                "\n=== SELECTED STUDENTS ({} shown) ===".format(
                    samples["sample_sizes"]["selected"]
                )
            )
            lines.append("These students were CHOSEN for the program. Study them carefully.")
            lines.append(json.dumps(samples["samples"]["selected"], ensure_ascii=True))

        # Not selected students
        if samples["samples"]["not_selected"]:
            lines.append(
                "\n=== NOT SELECTED STUDENTS ({} shown) ===".format(
                    samples["sample_sizes"]["not_selected"]
                )
            )
            lines.append("These students applied but were NOT chosen. Learn what they lacked.")
            lines.append(json.dumps(samples["samples"]["not_selected"], ensure_ascii=True))

        # Unknown
        if samples["samples"]["unknown"]:
            lines.append(
                "\n=== UNKNOWN STATUS ({} shown) ===".format(
                    samples["sample_sizes"]["unknown"]
                )
            )
            lines.append(json.dumps(samples["samples"]["unknown"], ensure_ascii=True))

        lines.extend([
            "",
            "=== OUTPUT FORMAT ===",
            "Return a JSON object with these fields:",
            "{",
            '  "model_student_profile": "Detailed 3-5 sentence description of the ideal candidate '
            'based on SELECTED students - what GPA, coursework, STEM interests, essay qualities, '
            'recommendation strength, and background characterize the students who get chosen",',
            '  "selection_threshold": "What rubric total score and characteristics reliably predict selection",',
            '  "selected_signals": ["List 5-8 specific patterns from selected students"],',
            '  "not_selected_signals": ["List 5-8 specific patterns from not-selected students"],',
            '  "differentiators": ["3-5 factors that most strongly separate selected from not-selected"],',
            '  "academic_patterns": {"min_gpa": 0, "avg_gpa": 0, "typical_courseload": "", '
            '"ap_ib_importance": ""},',
            '  "essay_patterns": {"winning_themes": [], "weak_signals": [], "quality_bar": ""},',
            '  "recommendation_patterns": {"strong_indicators": [], "weak_indicators": []},',
            '  "rubric_thresholds": {"min_total_for_selection": 0, "avg_selected_total": 0, '
            '"avg_not_selected_total": 0, "score_gap": 0},',
            '  "selection_risks": ["Red flags that predict rejection"],',
            '  "data_gaps": ["What data is missing or weak"],',
            '  "recommendations_for_merlin": ["Suggestions for the final evaluator"],',
            '  "confidence": "High|Medium|Low",',
            '  "summary": "2-3 sentence executive summary"',
            "}",
        ])

        return "\n".join(lines)

    def _build_evaluation_prompt(
        self,
        candidate: Dict[str, Any],
        insights: Dict[str, Any],
        historical_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the deep evaluation prompt for a single candidate."""
        # Filter out metadata keys from insights
        insight_subset = {
            k: v for k, v in insights.items()
            if k not in ("status", "agent", "model_used", "model_display",
                          "cached", "training_counts", "sample_sizes",
                          "historical_data_available", "historical_scored_count")
        }

        lines = [
            "=== CANDIDATE EVALUATION REQUEST ===",
            "",
            "Your training insights (what you learned from 100+ students):",
            json.dumps(insight_subset, ensure_ascii=True),
        ]

        if historical_context:
            lines.extend([
                "",
                "HISTORICAL HUMAN SCORES for this student (ground truth - weight heavily):",
                json.dumps(historical_context, ensure_ascii=True),
            ])

        lines.extend([
            "",
            "CANDIDATE TO EVALUATE:",
            json.dumps(candidate, ensure_ascii=True),
            "",
            "INSTRUCTIONS:",
            "Compare this candidate against your model of selected vs not-selected students.",
            "Score conservatively - remember only ~3% of applicants are chosen.",
            "Look at EVERY dimension: academics, STEM passion, essay quality, recommendation",
            "strength, school context, extracurriculars, and intangibles.",
            "",
            "Return JSON:",
            "{",
            '  "nextgen_match": <int 0-100>,',
            '  "match_score": <int 0-100>,',
            '  "tier": "STRONG ADMIT|ADMIT|WAITLIST|DECLINE",',
            '  "rubric_scores": {',
            '    "academic_record": <0-3>,',
            '    "stem_interest": <0-3>,',
            '    "essay_video": <0-3>,',
            '    "recommendation": <0-2>,',
            '    "bonus": <0-1>,',
            '    "total": <0-12>',
            '  },',
            '  "key_strengths": ["top 2-4 differentiators"],',
            '  "key_risks": ["top 1-3 concerns"],',
            '  "key_differentiators": ["same as key_strengths for backward compat"],',
            '  "confidence": "High|Medium|Low",',
            '  "explanation": "3-5 sentence rationale comparing to accepted/rejected patterns"',
            "}",
        ])
        return "\n".join(lines)

    def _build_batch_evaluation_prompt(
        self,
        profiles: List[Dict[str, Any]],
        insights: Dict[str, Any],
    ) -> str:
        """Build evaluation prompt for a batch of candidates."""
        insight_subset = {
            k: v for k, v in insights.items()
            if k not in ("status", "agent", "model_used", "model_display",
                          "cached", "training_counts", "sample_sizes",
                          "historical_data_available", "historical_scored_count")
        }

        lines = [
            "=== BATCH CANDIDATE EVALUATION ===",
            "",
            "Your training insights:",
            json.dumps(insight_subset, ensure_ascii=True),
            "",
            "Evaluate these {} candidates. For EACH candidate, produce a score.".format(
                len(profiles)
            ),
            "Be consistent across candidates - rank them relative to each other and to your",
            "model of what a selected student looks like.",
            "",
            "CANDIDATES:",
            json.dumps(profiles, ensure_ascii=True),
            "",
            "Return JSON with an 'evaluations' array - one entry per candidate in the same order:",
            "{",
            '  "evaluations": [',
            '    {',
            '      "nextgen_match": <int 0-100>,',
            '      "match_score": <int 0-100>,',
            '      "tier": "STRONG ADMIT|ADMIT|WAITLIST|DECLINE",',
            '      "rubric_scores": {"academic_record": <0-3>, "stem_interest": <0-3>, '
            '"essay_video": <0-3>, "recommendation": <0-2>, "bonus": <0-1>, "total": <0-12>},',
            '      "key_strengths": ["top 2-3"],',
            '      "key_risks": ["top 1-2"],',
            '      "confidence": "High|Medium|Low",',
            '      "explanation": "2-3 sentence rationale"',
            '    },',
            '    ...',
            '  ]',
            "}",
        ]
        return "\n".join(lines)

    # -------------------------------------------------------------------
    #  PERSISTENCE
    # -------------------------------------------------------------------

    def _persist_rankings(self, scored_candidates: List[Dict[str, Any]]) -> None:
        """Persist ranking results into each application's agent_results."""
        if not self.db:
            return
        for candidate in scored_candidates:
            app_id = candidate.get("application_id")
            if not app_id:
                continue
            try:
                rec = self.db.get_application(app_id) or {}
                existing = rec.get("agent_results") or {}
                if isinstance(existing, str):
                    existing = safe_load_json(existing)
                if not isinstance(existing, dict):
                    existing = {}

                existing["milo_ranking"] = {
                    "rank": candidate.get("rank"),
                    "nextgen_match": candidate.get("nextgen_match"),
                    "match_score": candidate.get("match_score"),
                    "tier": candidate.get("tier"),
                    "rubric_scores": candidate.get("rubric_scores"),
                    "key_strengths": candidate.get("key_strengths"),
                    "key_risks": candidate.get("key_risks"),
                    "explanation": candidate.get("explanation"),
                    "confidence": candidate.get("confidence"),
                    "ranked_at": datetime.utcnow().isoformat(),
                }
                # Also update milo_alignment for the student_detail view
                existing["milo_alignment"] = {
                    "nextgen_match": candidate.get("nextgen_match"),
                    "match_score": candidate.get("match_score"),
                    "tier": candidate.get("tier"),
                    "explanation": candidate.get("explanation"),
                    "key_differentiators": candidate.get("key_strengths"),
                    "confidence": candidate.get("confidence"),
                }

                self.db.update_application(
                    application_id=app_id,
                    agent_results=json.dumps(existing),
                )
            except Exception as e:
                logger.debug(
                    "Could not persist ranking for app %s: %s", app_id, e
                )

    def _compute_score_stats(
        self, candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compute summary statistics for scored candidates."""
        scores = [c.get("nextgen_match", 0) for c in candidates]
        if not scores:
            return {}
        scores_sorted = sorted(scores, reverse=True)
        return {
            "mean": round(sum(scores) / len(scores), 1),
            "median": scores_sorted[len(scores_sorted) // 2],
            "max": scores_sorted[0],
            "min": scores_sorted[-1],
            "p90": scores_sorted[max(0, len(scores_sorted) // 10)],
            "p75": scores_sorted[max(0, len(scores_sorted) // 4)],
            "above_70": sum(1 for s in scores if s >= 70),
            "above_50": sum(1 for s in scores if s >= 50),
            "below_30": sum(1 for s in scores if s < 30),
        }

    # -------------------------------------------------------------------
    #  GENERAL HELPERS
    # -------------------------------------------------------------------

    def _load_agent_outputs(self, application_id: Optional[int]) -> Dict[str, Any]:
        """Load agent outputs from dedicated agent tables."""
        if not application_id or not self.db:
            return {}

        outputs: Dict[str, Any] = {}
        table_map = {
            "tiana": "tiana_applications",
            "rapunzel": "rapunzel_grades",
            "moana": "student_school_context",
            "mulan": "mulan_recommendations",
            "merlin": "merlin_evaluations",
        }

        for key, table in table_map.items():
            try:
                table_name = self.db.get_table_name(table)
                rows = self.db.execute_query(
                    "SELECT * FROM {} "
                    "WHERE application_id = %s ORDER BY created_at DESC LIMIT 1".format(
                        table_name
                    ),
                    (application_id,),
                )
                if rows:
                    outputs[key] = self._merge_parsed_json(rows[0])
            except Exception:
                continue

        return outputs

    def _merge_parsed_json(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Merge parsed_json sub-fields into row."""
        parsed = dict(row)
        parsed_json = row.get("parsed_json") or row.get("parsedjson")
        if not parsed_json:
            return parsed

        try:
            payload = safe_load_json(parsed_json)
            if isinstance(payload, dict):
                for key, value in payload.items():
                    parsed.setdefault(key, value)
        except Exception:
            pass

        return parsed

    def _build_dataset_rows(self) -> List[Dict[str, Any]]:
        """Build dataset rows for Foundry upload."""
        training_examples = self.db.get_training_examples()
        rows: List[Dict[str, Any]] = []

        for row in training_examples:
            application_id = row.get("application_id") or row.get("ApplicationID")
            agent_outputs = self._load_agent_outputs(application_id)
            school_name = row.get("school_name") or row.get("schoolname") or row.get("high_school")
            state_code = row.get("state_code")

            # Look up structured school features
            school_features = None
            if school_name and self.db:
                try:
                    school_data = self.db.get_school_enriched_data(
                        school_name=school_name, state_code=state_code
                    )
                    if not school_data and state_code:
                        school_data = self.db.get_school_enriched_data_fuzzy(
                            school_name, state_code=state_code, threshold=0.6
                        )
                    if school_data:
                        school_features = NaveenSchoolDataScientist.generate_school_features(school_data)
                except Exception:
                    pass

            entry = {
                "application_id": application_id,
                "applicant_name": row.get("applicant_name") or row.get("applicantname"),
                "was_selected": row.get("was_selected"),
                "status": row.get("status"),
                "application_text": row.get("application_text") or row.get("applicationtext"),
                "transcript_text": row.get("transcript_text") or row.get("transcripttext"),
                "recommendation_text": row.get("recommendation_text") or row.get("recommendationtext"),
                "school_name": school_name,
                "agent_outputs": agent_outputs,
            }
            if school_features:
                entry["school_features"] = school_features
            rows.append(entry)

        return rows

    def _write_jsonl(self, rows: List[Dict[str, Any]]) -> str:
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
        handle.close()
        with open(handle.name, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=True) + "\n")
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

        for conn in connections:
            name = (conn.name or "").lower()
            if "storage" in name or "blob" in name:
                return conn.name

        raise RuntimeError(
            "Foundry dataset connection not found. Set FOUNDRY_DATASET_CONNECTION_NAME."
        )

    def _truncate(self, text: Optional[str], limit: int = 1200) -> str:
        if not text:
            return ""
        text = str(text)
        return text[:limit] + "..." if len(text) > limit else text

    def _safe_float(self, val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _is_cache_valid(self, signature: tuple) -> bool:
        if self._cached_insights is None:
            return False
        if self._cached_signature != signature:
            return False
        return (time.time() - self._cached_at) < self.cache_seconds

    def _error(self, message: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "agent": self.name,
            "model_used": self.model,
            "model_display": self.model_display,
            "error": message,
        }
