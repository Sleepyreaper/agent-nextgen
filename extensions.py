"""Shared extensions, agent factories, and helpers used across Flask blueprints.

This module holds objects that are created once and shared by all route
modules.  ``csrf`` and ``limiter`` are initialised lazily via ``init_app()``
in ``app.py``; everything else is usable as soon as it's imported.
"""

import asyncio
import difflib
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from flask import current_app, jsonify, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

from src.config import config
from src.database import db
from src.storage import storage
from src.telemetry import telemetry
from src.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask extensions (lazy-init via init_app in app.py)
# ---------------------------------------------------------------------------
csrf = CSRFProtect()
limiter = Limiter(
    get_remote_address,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)


# ---------------------------------------------------------------------------
# Role-based access control
# ---------------------------------------------------------------------------
VALID_ROLES = {'admin', 'reviewer', 'readonly'}


def require_role(*roles):
    """Decorator: restrict a route to users whose session role is in *roles*."""
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_role = session.get('role', 'readonly')
            if user_role not in roles:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Insufficient permissions'}), 403
                return '<h1>403 — Forbidden</h1>', 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# ---------------------------------------------------------------------------
# Shared background event loop (Issue #52)
# ---------------------------------------------------------------------------
_bg_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()


def _start_bg_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


_bg_thread = threading.Thread(target=_start_bg_loop, args=(_bg_loop,), daemon=True)
_bg_thread.start()


def run_async(coro, timeout: float = 1800.0):
    """Submit a coroutine to the shared event loop and block until done."""
    future = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    return future.result(timeout=timeout)


# ---------------------------------------------------------------------------
# Agent singletons
# ---------------------------------------------------------------------------
evaluator_agent = None
orchestrator_agent = None
belle_analyzer = None
mirabel_analyzer = None
feedback_agent = None

# In-memory tracking for test sessions
test_submissions: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# Agent imports
# ---------------------------------------------------------------------------
try:
    from src.agents.ariel_adapter import ArielQAAgent
except Exception as _e:
    ArielQAAgent = None
    logger.warning("ArielQAAgent not available: %s", _e)

try:
    from src.agents.aurora_agent import AuroraAgent
except Exception as _e:
    AuroraAgent = None
    logger.warning("AuroraAgent not available: %s", _e)

from src.agents.foundry_client import FoundryClient
from src.agents.smee_orchestrator import SmeeOrchestrator
from src.agents.tiana_application_reader import TianaApplicationReader
from src.agents.rapunzel_grade_reader import RapunzelGradeReader
from src.agents.mulan_recommendation_reader import MulanRecommendationReader
from src.agents.merlin_student_evaluator import MerlinStudentEvaluator
from src.agents.gaston_evaluator import GastonEvaluator
from src.agents.bashful_agent import BashfulAgent
from src.agents.belle_document_analyzer import BelleDocumentAnalyzer
from src.agents.mirabel_video_analyzer import MirabelVideoAnalyzer
from src.agents.milo_data_scientist import MiloDataScientist
from src.agents.naveen_school_data_scientist import NaveenSchoolDataScientist
from src.agents.pocahontas_cohort_analyst import PocahontasCohortAnalyst
from src.agents.moana_school_context import MoanaSchoolContext
from src.agents.fairy_godmother_document_generator import FairyGodmotherDocumentGenerator
from src.agents.feedback_triage_agent import ScuttleFeedbackTriageAgent, FeedbackTriageAgent
from src.agents.agent_monitor import get_agent_monitor

# Aurora agent singleton
if AuroraAgent is not None:
    aurora = AuroraAgent()
else:
    aurora = None


# ---------------------------------------------------------------------------
# AI client helpers
# ---------------------------------------------------------------------------
def get_ai_client(api_version: str = None, azure_deployment: str = None):
    """Get Azure OpenAI / Foundry client."""
    if api_version is None:
        api_version = config.api_version
    if azure_deployment is None:
        azure_deployment = config.deployment_name

    if config.model_provider and config.model_provider.lower() == "foundry":
        return FoundryClient(endpoint=config.foundry_project_endpoint)

    if config.azure_openai_api_key:
        try:
            from openai import AzureOpenAI
        except ImportError as e:
            raise RuntimeError("AzureOpenAI client requested but openai package is not installed") from e
        return AzureOpenAI(
            api_key=config.azure_openai_api_key,
            api_version=api_version,
            azure_endpoint=config.azure_openai_endpoint,
            azure_deployment=azure_deployment,
        )

    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default"
    )
    try:
        from openai import AzureOpenAI
    except ImportError as e:
        raise RuntimeError("AzureOpenAI client requested but openai package is not installed") from e
    return AzureOpenAI(
        azure_ad_token_provider=token_provider,
        api_version=api_version,
        azure_endpoint=config.azure_openai_endpoint,
        azure_deployment=azure_deployment,
    )


def get_ai_client_mini():
    """Get Azure OpenAI client for o4-mini deployment."""
    return get_ai_client(api_version=config.api_version_mini, azure_deployment=config.deployment_name_mini)


# ---------------------------------------------------------------------------
# Agent factories (singletons)
# ---------------------------------------------------------------------------
def get_evaluator():
    """Get or create Gaston evaluator agent."""
    global evaluator_agent
    if not evaluator_agent:
        client_type = None
        candidate_attrs = []
        try:
            client = get_ai_client()
        except Exception as e:
            logger.exception("Failed to construct AI client: %s", e)
            return jsonify({"success": False, "error": "An internal error occurred", "configured_provider": config.model_provider}), 500

        try:
            client_type = type(client).__name__
            candidate_attrs = [a for a in dir(client) if any(k in a.lower() for k in ("chat", "generate", "completion", "complete", "completions"))]
        except Exception:
            try:
                client_type = str(type(client))
            except Exception:
                client_type = None
            candidate_attrs = []
        training_examples = db.get_training_examples()
        model_name = config.model_tier_workhorse
        evaluator_agent = GastonEvaluator(
            name="GastonEvaluator",
            client=client,
            model=model_name,
        )
    return evaluator_agent


def get_belle():
    """Get or create Belle document analyzer."""
    global belle_analyzer
    if not belle_analyzer:
        client = get_ai_client()
        model_name = config.model_tier_lightweight
        belle_analyzer = BelleDocumentAnalyzer(
            client=client,
            model=model_name
        )
    return belle_analyzer


def get_mirabel():
    """Get or create Mirabel video analyzer."""
    global mirabel_analyzer
    if not mirabel_analyzer:
        client = get_ai_client()
        vision_model = config.foundry_vision_model_name or 'gpt-4o'
        mirabel_analyzer = MirabelVideoAnalyzer(
            client=client,
            model=vision_model
        )
    return mirabel_analyzer


def get_feedback_agent():
    """Get or create feedback triage agent."""
    global feedback_agent
    if not feedback_agent:
        client = get_ai_client()
        model_name = config.model_tier_lightweight
        feedback_agent = FeedbackTriageAgent(
            name="Scuttle Feedback Triage",
            client=client,
            model=model_name
        )
    return feedback_agent


def get_orchestrator():
    """Get or create Smee orchestrator with registered agents."""
    global orchestrator_agent
    if not orchestrator_agent:
        client = get_ai_client()
        client_mini = get_ai_client_mini()
        model_premium = config.model_tier_premium
        model_merlin = config.model_tier_merlin
        model_workhorse = config.model_tier_workhorse
        model_lightweight = config.model_tier_lightweight
        orchestrator_agent = SmeeOrchestrator(
            name="Smee",
            client=client,
            model=model_workhorse,
            db_connection=db
        )

        orchestrator_agent.register_agent(
            "application_reader",
            TianaApplicationReader(name="Tiana Application Reader", client=client, model=model_workhorse, db_connection=db)
        )
        orchestrator_agent.register_agent(
            "grade_reader",
            RapunzelGradeReader(name="Rapunzel Grade Reader", client=client, model=model_premium, db_connection=db)
        )
        orchestrator_agent.register_agent(
            "school_context",
            MoanaSchoolContext(name="Moana School Context Analyzer", client=client, model=model_workhorse, db_connection=db)
        )
        orchestrator_agent.register_agent(
            "recommendation_reader",
            MulanRecommendationReader(name="Mulan Recommendation Reader", client=client, model=model_workhorse, db_connection=db)
        )
        orchestrator_agent.register_agent(
            "student_evaluator",
            MerlinStudentEvaluator(name="Merlin Student Evaluator", client=client, model=model_merlin, db_connection=db)
        )
        orchestrator_agent.register_agent(
            "data_scientist",
            MiloDataScientist(name="Milo Data Scientist", client=client, model=model_premium, db_connection=db)
        )
        orchestrator_agent.register_agent(
            "naveen",
            NaveenSchoolDataScientist(name="Naveen School Data Scientist", client=client, model=model_workhorse)
        )
        orchestrator_agent.register_agent(
            "pocahontas",
            PocahontasCohortAnalyst(name="Pocahontas Cohort Analyst", client=client, model=model_workhorse)
        )
        orchestrator_agent.register_agent("aurora", AuroraAgent() if AuroraAgent else None)
        orchestrator_agent.register_agent(
            "gaston",
            GastonEvaluator(name="Gaston Evaluator", client=client, model=model_workhorse)
        )
        orchestrator_agent.register_agent(
            "fairy_godmother",
            FairyGodmotherDocumentGenerator(db_connection=db, storage_manager=storage)
        )
        orchestrator_agent.register_agent(
            "bashful",
            BashfulAgent(name="Bashful Agent", client=client, model=model_workhorse, system_prompt="You are Bashful, a helpful assistant in the evaluation system.")
        )
        orchestrator_agent.register_agent(
            "belle",
            BelleDocumentAnalyzer(name="Belle Document Analyzer", client=client, model=model_lightweight, db_connection=db)
        )
        orchestrator_agent.register_agent(
            "scuttle",
            ScuttleFeedbackTriageAgent(name="Scuttle Feedback Triage", client=client, model=model_lightweight)
        )

        try:
            for agent_key, agent_inst in orchestrator_agent.agents.items():
                try:
                    if getattr(agent_inst, 'client', None) is None:
                        agent_inst.client = client
                        logger.info("Assigned fallback AI client to agent %s", agent_key)
                except Exception:
                    logger.debug("Could not assign client to agent %s", agent_key, exc_info=True)
        except Exception:
            logger.debug("Error while assigning clients to orchestrator agents", exc_info=True)

    return orchestrator_agent


# ---------------------------------------------------------------------------
# OCR callback
# ---------------------------------------------------------------------------
def _make_ocr_callback():
    """Create an OCR callback that uses the Azure AI vision model (GPT-4o)."""
    try:
        client = get_ai_client()
        if config.model_provider and config.model_provider.lower() == "foundry":
            vision_model = getattr(config, 'foundry_vision_model_name', None) or 'gpt-4o'
        else:
            vision_model = config.deployment_name
        logger.info("OCR callback initialized: client=%s, vision_model=%s", type(client).__name__, vision_model)
    except Exception:
        logger.warning("OCR callback: failed to create AI client")
        return None

    def _ocr(image_bytes: bytes, page_label: str) -> str:
        import base64 as _b64
        b64_image = _b64.b64encode(image_bytes).decode('utf-8')
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a precise document OCR system for student scholarship "
                    "applications. Extract ALL text from the provided image exactly "
                    "as it appears. Preserve the layout, including tables, columns, "
                    "and line breaks.\n\n"
                    "The image may be ANY of these document types:\n\n"
                    "TRANSCRIPTS / GRADE REPORTS:\n"
                    "- Every course name and its corresponding grade (letter or numeric)\n"
                    "- Credit hours / units for each course\n"
                    "- GPA values (weighted and unweighted)\n"
                    "- Semester / term / year labels\n"
                    "- Student name, school name, grade level\n"
                    "- Class rank, test scores, attendance data if present\n"
                    "- Headers like 'UNOFFICIAL TRANSCRIPT', 'ACADEMIC RECORD', etc.\n\n"
                    "RECOMMENDATION LETTERS:\n"
                    "- Full letter text including salutation, body paragraphs, and closing\n"
                    "- Author name, title, school/organization, contact info\n"
                    "- Letterhead details (school name, address, phone)\n\n"
                    "RESUMES:\n"
                    "- All sections (Education, Experience, Skills, Activities, Awards)\n"
                    "- Contact information, dates, descriptions\n\n"
                    "APPLICATION ESSAYS / FORMS:\n"
                    "- Full essay text, question prompts, student responses\n"
                    "- Form field labels and values\n\n"
                    "For tabular data, reproduce the table structure using aligned columns "
                    "or a clear delimiter (e.g., ' | ' or tabs). Each row should be on its "
                    "own line.\n\n"
                    "Do NOT summarize or interpret — reproduce the text faithfully. "
                    "If text is partially illegible, include your best reading with [?] "
                    "for uncertain characters."
                )
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Extract all text from this document image ({page_label}). "
                                "Reproduce every word, number, and table exactly as shown."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_image}",
                            "detail": "high"
                        }
                    }
                ]
            }
        ]

        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=vision_model,
                    messages=messages,
                    max_tokens=6000,
                    temperature=0.0
                )
                text = resp.choices[0].message.content or ""
                logger.info("OCR vision extracted %d chars from %s (attempt %d)", len(text), page_label, attempt)
                return text
            except Exception as e:
                logger.warning("OCR vision call failed for %s (attempt %d/%d): %s", page_label, attempt, max_retries, e)
                if attempt < max_retries:
                    time.sleep(2)
        return ""

    return _ocr


# ---------------------------------------------------------------------------
# Async processing helpers
# ---------------------------------------------------------------------------
def refresh_foundry_dataset_async(reason: str) -> None:
    def run():
        try:
            orchestrator = get_orchestrator()
            milo = orchestrator.agents.get("data_scientist") if orchestrator else None
            if not milo:
                logger.warning("Milo agent not available for dataset refresh")
                return
            result = run_async(milo.build_and_upload_foundry_dataset())
            if result.get("status") == "success":
                logger.info("Foundry dataset refreshed", extra={"dataset": result.get("dataset_name"), "version": result.get("dataset_version"), "reason": reason})
            else:
                logger.warning("Foundry dataset refresh failed", extra={"error": result.get("error"), "reason": reason})
        except Exception as exc:
            logger.warning("Foundry dataset refresh error", exc_info=True, extra={"reason": reason, "error": str(exc)})
    threading.Thread(target=run, daemon=True).start()


def start_application_processing(application_id: int) -> None:
    """Start background application processing via Smee orchestrator."""
    def run():
        try:
            application = db.get_application(application_id)
            if not application:
                logger.error(f"Processing: application {application_id} not found in DB")
                return
            orchestrator = get_orchestrator()
            logger.info(f"Processing: starting orchestrator for application {application_id}")
            result = run_async(orchestrator.coordinate_evaluation(
                application=application,
                evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'data_scientist', 'student_evaluator', 'aurora']
            ))
            result_status = result.get('status') if isinstance(result, dict) else 'unknown'
            result_keys = list(result.keys()) if isinstance(result, dict) else []
            logger.info(f"Processing: orchestrator returned for {application_id}, status={result_status}, keys={result_keys}")
            if result_status == 'paused':
                db.update_application_status(application_id, 'Needs Docs')
                logger.info(f"Processing: {application_id} paused — needs docs")
                return
            db.update_application_status(application_id, 'Completed')
            logger.info(f"Processing: {application_id} marked Completed")
        except Exception as e:
            logger.error(f"Processing FAILED for {application_id}: {str(e)}", exc_info=True)
            db.update_application_status(application_id, 'Uploaded')
    db.update_application_status(application_id, 'Processing')
    threading.Thread(target=run, daemon=True).start()


def start_training_processing(application_id: int) -> None:
    """Start background training data processing via Smee orchestrator."""
    def run():
        try:
            application = db.get_application(application_id)
            if not application:
                return
            orchestrator = get_orchestrator()
            result = run_async(orchestrator.coordinate_evaluation(
                application=application,
                evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'data_scientist', 'student_evaluator', 'aurora']
            ))
            if result.get('status') == 'paused':
                db.update_application_status(application_id, 'Needs Docs')
                return
            db.update_application_status(application_id, 'Completed')
        except Exception as e:
            logger.error(f"Training processing failed for application {application_id}: {str(e)}", exc_info=True)
            db.update_application_status(application_id, 'Uploaded')
    db.update_application_status(application_id, 'Processing')
    threading.Thread(target=run, daemon=True).start()


def start_incremental_processing(application_id: int) -> Dict[str, Any]:
    """Re-run only the agents that were previously skipped due to missing data.

    Checks the application's agent_results for agents that returned 'skipped'
    or 'error', then re-runs those plus Merlin + Aurora for fresh synthesis.
    """
    application = db.get_application(application_id)
    if not application:
        return {'status': 'error', 'error': 'Application not found'}

    agent_results = application.get('agent_results') or {}
    if isinstance(agent_results, str):
        from src.utils import safe_load_json
        agent_results = safe_load_json(agent_results)

    step_map = {
        'application_reader': 'application_reader', 'tiana': 'application_reader',
        'grade_reader': 'grade_reader', 'rapunzel': 'grade_reader',
        'recommendation_reader': 'recommendation_reader', 'mulan': 'recommendation_reader',
        'school_context': 'school_context', 'moana': 'school_context',
    }

    rerun_steps = set()
    for key, step_id in step_map.items():
        result = agent_results.get(key)
        if isinstance(result, dict) and (result.get('skipped') or result.get('status') == 'error'):
            rerun_steps.add(step_id)
        elif result is None:
            rerun_steps.add(step_id)

    rerun_steps.update(['student_evaluator', 'aurora'])
    if 'grade_reader' in rerun_steps:
        rerun_steps.add('school_context')

    steps_list = list(rerun_steps)

    def run():
        try:
            app = db.get_application(application_id)
            if not app:
                return
            orchestrator = get_orchestrator()
            result = run_async(orchestrator.coordinate_evaluation(
                application=app, evaluation_steps=steps_list,
            ))
            if isinstance(result, dict) and result.get('status') == 'paused':
                db.update_application_status(application_id, 'Needs Docs')
                return
            db.update_application_status(application_id, 'Completed')
        except Exception as e:
            logger.error(f"Incremental processing FAILED for {application_id}: {e}", exc_info=True)
            db.update_application_status(application_id, 'Uploaded')

    db.update_application_status(application_id, 'Processing')
    threading.Thread(target=run, daemon=True).start()
    return {'status': 'started', 'application_id': application_id, 'agents_to_rerun': steps_list}


# ---------------------------------------------------------------------------
# Student matching helpers (used by upload and testing blueprints)
# ---------------------------------------------------------------------------
def extract_student_name(text: str) -> Optional[str]:
    """Extract student name from application text."""
    try:
        first_match = re.search(r'First\s*Name\s*[:\-]?\s*([A-Za-z\'\-]+)', text, re.IGNORECASE)
        last_match = re.search(r'Last\s*Name\s*[:\-]?\s*([A-Za-z\'\-]+)', text, re.IGNORECASE)
        if first_match and last_match:
            return f"{first_match.group(1).strip()} {last_match.group(1).strip()}"
        match = re.search(r"(?:my name is|i am|i\'m)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        words = text.split()
        if len(words) >= 2:
            for i in range(len(words) - 1):
                if words[i][0].isupper() and words[i + 1][0].isupper():
                    name = f"{words[i]} {words[i + 1]}"
                    if len(name) < 50:
                        return name
        return None
    except Exception:
        return None


def extract_student_email(text: str) -> Optional[str]:
    """Extract email address from application text."""
    matches = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
    return matches[0] if matches else None


def _normalize_match_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9\s]", " ", value.lower()).strip()


def _token_similarity(left: Optional[str], right: Optional[str]) -> float:
    left_norm = _normalize_match_text(left)
    right_norm = _normalize_match_text(right)
    if not left_norm or not right_norm:
        return 0.0
    left_tokens = {token for token in left_norm.split() if len(token) > 1}
    right_tokens = {token for token in right_norm.split() if len(token) > 1}
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens.intersection(right_tokens)
    return len(overlap) / max(len(left_tokens), len(right_tokens))


def _string_similarity(left: Optional[str], right: Optional[str]) -> float:
    left_norm = _normalize_match_text(left)
    right_norm = _normalize_match_text(right)
    if not left_norm or not right_norm:
        return 0.0
    return difflib.SequenceMatcher(None, left_norm, right_norm).ratio()


def _extract_gpa(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"\bGPA\b\s*[:\-]?\s*([0-4]\.\d{1,2})", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _merge_uploaded_text(existing: Optional[str], incoming: str, label: str, filename: str) -> str:
    if not existing:
        return incoming
    if not incoming:
        return existing
    if incoming.strip() in existing:
        return existing
    header = f"--- New {label} Upload ({filename}) ---"
    return f"{existing}\n\n{header}\n\n{incoming}"


def _split_name_parts(full_name: Optional[str]) -> tuple:
    if not full_name:
        return None, None
    tokens = [token for token in re.split(r"\s+", full_name.strip()) if token]
    if len(tokens) < 2:
        return tokens[0], None
    return tokens[0], tokens[-1]


def _build_identity_key(
    first_name: Optional[str],
    last_name: Optional[str],
    school_name: Optional[str],
    email: Optional[str],
    full_name: Optional[str],
    filename: str
) -> str:
    def normalize(value: Optional[str]) -> Optional[str]:
        return _normalize_match_text(value) if value else None

    first_norm = normalize(first_name)
    last_norm = normalize(last_name)
    school_norm = normalize(school_name)
    email_norm = (email or "").strip().lower() or None
    name_norm = normalize(full_name)

    if first_norm and last_norm and school_norm:
        return f"name={first_norm}|{last_norm}|school={school_norm}"
    if email_norm:
        return f"email={email_norm}"
    if name_norm:
        return f"name={name_norm}"
    return f"file={filename.strip().lower()}"


def _summarize_filenames(filenames: list, max_names: int = 3) -> str:
    cleaned = [name for name in filenames if name]
    if len(cleaned) <= max_names:
        return ", ".join(cleaned)
    return f"{', '.join(cleaned[:max_names])} (+{len(cleaned) - max_names} more)"


def _aggregate_documents(documents: list) -> Dict[str, Optional[str]]:
    """Aggregate multiple document texts into application/transcript/recommendation fields."""
    fields: Dict[str, Optional[str]] = {
        "application_text": None,
        "transcript_text": None,
        "recommendation_text": None
    }
    doc_type_map = {
        'application': 'application_text',
        'personal_statement': 'application_text',
        'essay': 'application_text',
        'video_submission': 'application_text',
        'transcript': 'transcript_text',
        'grades': 'transcript_text',
        'letter_of_recommendation': 'recommendation_text'
    }
    label_map = {
        'application_text': 'Application',
        'transcript_text': 'Transcript',
        'recommendation_text': 'Recommendation'
    }
    for doc in documents:
        doc_type = doc.get('document_type') or 'unknown'
        text = doc.get('text') or ""
        filename = doc.get('filename') or "document"

        agent_fields = doc.get('agent_fields') or {}
        used_agent_fields = False
        for af_field in ('application_text', 'transcript_text', 'recommendation_text'):
            af_val = agent_fields.get(af_field)
            if af_val and isinstance(af_val, str) and len(af_val.strip()) > 20:
                fields[af_field] = _merge_uploaded_text(
                    fields.get(af_field), af_val, label_map.get(af_field, 'Document'), filename
                )
                used_agent_fields = True
        if used_agent_fields:
            continue

        target_field = doc_type_map.get(doc_type)
        if target_field:
            fields[target_field] = _merge_uploaded_text(
                fields.get(target_field), text, label_map.get(target_field, 'Document'), filename
            )
            continue

        if not fields.get('application_text'):
            fields['application_text'] = text
        elif not fields.get('recommendation_text'):
            fields['recommendation_text'] = text
        else:
            fields['transcript_text'] = fields.get('transcript_text') or text

    return fields


def _collect_documents_from_storage(student_id: str, application_type: str, belle, upload_folder: str = None) -> list:
    """Re-download and re-analyze all documents for a student from blob storage."""
    if not storage.client:
        return []
    ocr_cb = _make_ocr_callback()
    documents: list = []
    blob_names = storage.list_student_files(student_id, application_type)
    for blob_name in blob_names:
        filename = os.path.basename(blob_name)
        file_content = storage.download_file(student_id, filename, application_type)
        if not file_content:
            continue
        if upload_folder is None:
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        temp_path = os.path.join(upload_folder, f"reprocess_{student_id}_{uuid.uuid4().hex}_{filename}")
        try:
            with open(temp_path, 'wb') as handle:
                handle.write(file_content)
            file_text, _ = DocumentProcessor.process_document(temp_path, ocr_callback=ocr_cb)
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass
        try:
            analysis = belle.analyze_document(file_text, filename)
        except Exception as exc:
            logger.warning(f"Belle analysis failed during reprocess: {exc}")
            analysis = {"document_type": "unknown", "agent_fields": {}}
        documents.append({
            'filename': filename,
            'text': file_text,
            'document_type': analysis.get('document_type', 'unknown'),
            'student_info': analysis.get('student_info', {}),
            'agent_fields': analysis.get('agent_fields', {})
        })
    return documents


def find_high_probability_match(
    student_name: Optional[str],
    student_first_name: Optional[str],
    student_last_name: Optional[str],
    student_email: Optional[str],
    school_name: Optional[str],
    transcript_text: Optional[str],
    is_training: bool,
    is_test: bool
) -> Optional[Dict[str, Any]]:
    """Find an existing student record that matches the uploaded student."""
    if not student_name and not student_email:
        return None
    candidates = db.get_application_match_candidates(is_training=is_training, is_test_data=is_test)
    if not candidates:
        return None
    uploaded_gpa = _extract_gpa(transcript_text)
    best_candidate = None
    best_score = 0.0
    best_reason = ""

    for candidate in candidates:
        candidate_name = candidate.get('applicant_name') or candidate.get('full_name') or ''
        candidate_email = candidate.get('email')
        candidate_first = candidate.get('first_name') or ''
        candidate_last = candidate.get('last_name') or ''
        candidate_school = candidate.get('school_name') or candidate.get('high_school') or ''
        candidate_gpa = _extract_gpa(candidate.get('transcript_text'))

        first_similarity = _string_similarity(student_first_name, candidate_first)
        last_similarity = _string_similarity(student_last_name, candidate_last)
        email_match = bool(student_email and candidate_email and student_email.lower() == candidate_email.lower())
        name_similarity = max(_string_similarity(student_name, candidate_name), _token_similarity(student_name, candidate_name))
        school_similarity = max(_string_similarity(school_name, candidate_school), _token_similarity(school_name, candidate_school))

        gpa_similarity = 0.0
        if uploaded_gpa is not None and candidate_gpa is not None:
            gpa_diff = abs(uploaded_gpa - candidate_gpa)
            gpa_similarity = max(0.0, 1.0 - min(gpa_diff / 1.0, 1.0))

        has_school_data = bool(candidate_school and school_name)

        if student_first_name and student_last_name:
            fl_sim = 0.5 * first_similarity + 0.5 * last_similarity
            effective_name = max(name_similarity, fl_sim)
        else:
            effective_name = name_similarity

        if has_school_data:
            score = 0.55 * effective_name + 0.25 * school_similarity + 0.10 * gpa_similarity
        else:
            score = 0.80 * effective_name + 0.10 * gpa_similarity

        if name_similarity > 0.85 and school_similarity > 0.6:
            score += 0.10
        if first_similarity >= 0.95 and last_similarity >= 0.95:
            score += 0.10
        if email_match:
            score = max(score, 0.98)
        score = min(score, 1.0)

        if student_first_name and student_last_name:
            if first_similarity < 0.75 or last_similarity < 0.75:
                continue
            if has_school_data and school_similarity < 0.6:
                continue

        if score > best_score:
            best_score = score
            best_candidate = candidate
            best_reason = (
                f"first={first_similarity:.2f}, last={last_similarity:.2f}, "
                f"name={name_similarity:.2f}, school={school_similarity:.2f}, "
                f"gpa={gpa_similarity:.2f}, email={email_match}, "
                f"school_data={'yes' if has_school_data else 'no'}"
            )

    if not best_candidate:
        return None

    effective_name_sim = _string_similarity(student_name, best_candidate.get('applicant_name') or '')
    if best_score >= 0.78 and (effective_name_sim >= 0.6 or student_email):
        best_candidate['match_score'] = best_score
        best_candidate['match_reason'] = best_reason
        logger.info(
            f"Student match found: score={best_score:.2f} ({best_reason}) "
            f"→ application_id={best_candidate.get('application_id')}"
        )
        return best_candidate

    return None
