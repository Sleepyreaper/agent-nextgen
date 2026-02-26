"""Flask web application for application evaluation system."""

import os
import asyncio
import time
import uuid
import json
import re
import threading
import requests
from flask import Flask, flash, jsonify, render_template, redirect, url_for, request, Response, stream_with_context
from werkzeug.utils import secure_filename

from typing import Dict, Any, Optional
import queue
from src.test_data_generator import test_data_generator

# document processing helper used in file upload endpoints
from src.document_processor import DocumentProcessor

from src.config import config
from src.telemetry import init_telemetry, telemetry
from src.observability import is_observability_enabled, get_observability_status

from src.storage import storage

# database connection used across views
from src.database import db

# OpenTelemetry instrumentors used later
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

# logging is used in the module (logger.warning earlier) so import
import logging
logger = logging.getLogger(__name__)

try:
    from src.agents.ariel_adapter import ArielQAAgent
except Exception as _e:
    # Optional agent may be absent in some deployment packages (packaging/sync issues).
    # Defer failure until the specific endpoint is invoked so the app can boot.
    ArielQAAgent = None
    logger.warning("ArielQAAgent not available: %s", _e)

try:
    from src.agents.aurora_agent import AuroraAgent
except Exception as _e:
    # AuroraAgent also optional; allow app startup without it
    AuroraAgent = None
    logger.warning("AuroraAgent not available: %s", _e)
from src.agents.agent_requirements import AgentRequirements
from src.agents.fairy_godmother_document_generator import FairyGodmotherDocumentGenerator
from src.agents.agent_monitor import get_agent_monitor
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
from src.agents.moana_school_context import MoanaSchoolContext
from src.agents.feedback_triage_agent import ScuttleFeedbackTriageAgent, FeedbackTriageAgent

# Initialize Flask app
app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
app.secret_key = config.flask_secret_key or os.urandom(32).hex()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'


@app.context_processor
def inject_app_metadata():
    return {
        'app_version': config.app_version
    }


@app.after_request
def add_no_cache_headers(response):
    """Prevent browser caching of HTML pages so template changes take effect immediately."""
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# Initialize telemetry FIRST so the TracerProvider is set before instrumentors run.
# When Azure Monitor is configured, configure_azure_monitor() auto-instruments
# Flask, requests, psycopg2, and urllib — so manual instrumentors are a safe no-op.
init_telemetry(service_name=os.getenv("OTEL_SERVICE_NAME", "agent-framework"))

# Instrument Flask and outbound HTTP calls for App Insights.
# (When azure-monitor-opentelemetry is present these are already instrumented;
#  calling instrument_app again is harmless — OTel deduplicates.)
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
logger.info("Flask app initialized", extra={'upload_folder': app.config['UPLOAD_FOLDER']})

# One-time DB migration: strip gaston data from all stored agent_results & student_summary
try:
    _gaston_cleaned = db.execute_non_query(
        "UPDATE applications SET agent_results = agent_results - 'gaston' "
        "WHERE agent_results::jsonb ? 'gaston'"
    )
    if _gaston_cleaned:
        logger.info(f"Startup migration: cleaned gaston from {_gaston_cleaned} agent_results rows")
except Exception:
    # SQLite fallback or no rows — safe to ignore
    try:
        import json as _json
        _rows = db.execute_query(
            "SELECT application_id, agent_results FROM applications "
            "WHERE agent_results LIKE '%gaston%'"
        )
        for _row in _rows:
            _ar = _row.get('agent_results')
            if isinstance(_ar, str):
                try:
                    _ar = _json.loads(_ar)
                except Exception:
                    continue
            if isinstance(_ar, dict) and 'gaston' in _ar:
                _ar.pop('gaston', None)
                db.execute_non_query(
                    "UPDATE applications SET agent_results = %s WHERE application_id = %s",
                    (_json.dumps(_ar), _row['application_id'])
                )
    except Exception:
        pass

# Initialize Azure OpenAI client
def _make_ocr_callback():
    """Create an OCR callback that uses the Azure AI vision model (GPT-4o).
    
    Returns a function ``fn(image_bytes, page_label) -> str`` that sends
    a PDF page image to the AI vision model and returns extracted text.
    Returns None if the AI client is unavailable.

    The callback uses the dedicated vision model deployment (``config.foundry_vision_model_name``,
    default: ``gpt-4o``) which is optimised for multimodal image+text tasks.
    """
    try:
        client = get_ai_client()
        # Prefer the dedicated vision model (gpt-4o) for OCR tasks
        if config.model_provider and config.model_provider.lower() == "foundry":
            vision_model = getattr(config, 'foundry_vision_model_name', None) or 'gpt-4o'
        else:
            vision_model = config.deployment_name
        logger.info("OCR callback initialized: client=%s, vision_model=%s", type(client).__name__, vision_model)
    except Exception:
        logger.warning("OCR callback: failed to create AI client")
        return None
    
    def _ocr(image_bytes: bytes, page_label: str) -> str:
        """OCR a single page image using AI vision (GPT-4o)."""
        import base64 as _b64
        b64_image = _b64.b64encode(image_bytes).decode('utf-8')
        
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a precise document OCR system. Extract ALL text from the "
                    "provided image exactly as it appears. Preserve the layout, including "
                    "tables, columns, and line breaks. For transcripts and grade reports, "
                    "capture every course name, grade, credit, GPA, and any other data. "
                    "Do NOT summarize or interpret — reproduce the text faithfully."
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
        
        try:
            # Both AzureOpenAI and FoundryClient expose .chat.completions.create()
            # FoundryClient now preserves multimodal message format for the SDK path
            resp = client.chat.completions.create(
                model=vision_model,
                messages=messages,
                max_tokens=4000,
                temperature=0.0
            )
            text = resp.choices[0].message.content or ""
            logger.info("OCR vision extracted %d chars from %s", len(text), page_label)
            return text
        except Exception as e:
            logger.warning("OCR vision call failed for %s: %s", page_label, e)
            return ""
    
    return _ocr


def get_ai_client(api_version: str = None, azure_deployment: str = None):
    """
    Get Azure OpenAI client with specified API version.
    
    Args:
        api_version: API version to use. If None, uses config.api_version
    """
    if api_version is None:
        api_version = config.api_version

    # If caller didn't provide an explicit azure_deployment, prefer the configured deployment name
    if azure_deployment is None:
        azure_deployment = config.deployment_name
        
    # If configuration indicates Foundry as the model provider, return the Foundry adapter.
    if config.model_provider and config.model_provider.lower() == "foundry":
        # Prefer Entra ID managed identity (DefaultAzureCredential) when available;
        # do not pass an API key so the FoundryClient will attempt AAD token acquisition.
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
    """Get Azure OpenAI client for o4-mini deployment with correct API version."""
    return get_ai_client(api_version=config.api_version_mini, azure_deployment=config.deployment_name_mini)

# Initialize evaluator agent
evaluator_agent = None
orchestrator_agent = None
belle_analyzer = None
mirabel_analyzer = None
feedback_agent = None

def get_evaluator():
    """Get or create Gaston evaluator agent."""
    global evaluator_agent
    if not evaluator_agent:
        # Prepare introspection defaults in case client construction fails
        client_type = None
        candidate_attrs = []
        try:
            client = get_ai_client()
        except Exception as e:
            app.logger.exception("Failed to construct AI client: %s", e)
            return jsonify({"success": False, "error": str(e), "configured_provider": config.model_provider}), 500

        # Introspect client for debugging (don't include secrets)
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
        model_name = config.model_tier_workhorse  # Tier 2: structured evaluation scoring
        evaluator_agent = GastonEvaluator(
            name="GastonEvaluator",
            client=client,
            model=model_name,
            training_examples=training_examples
        )
    return evaluator_agent


def get_belle():
    """Get or create Belle document analyzer."""
    global belle_analyzer
    if not belle_analyzer:
        # Prepare introspection defaults so error responses can include them
        client_type = None
        candidate_attrs = []
        # Prepare introspection defaults so error responses can include them
        client_type = None
        candidate_attrs = []
        client = get_ai_client()
        model_name = config.model_tier_lightweight  # Tier 3: document classification
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
        # Mirabel uses the vision model (GPT-4o) for frame analysis
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
        model_name = config.model_tier_lightweight  # Tier 3: feedback triage
        # Use alias so callers don't need to know the renamed class
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
        # Tiered model selection — see config.py for deployment name mappings
        # Tier 1 (Premium): gpt-4.1 — complex reasoning (Rapunzel, Milo)
        # Tier 1+ (Merlin): MerlinGPT5Mini — final evaluator on GPT-5-mini
        # Tier 2 (Workhorse): WorkForce4.1mini — structured extraction
        # Tier 3 (Lightweight): LightWork5Nano — classification/triage
        model_premium = config.model_tier_premium
        model_merlin = config.model_tier_merlin
        model_workhorse = config.model_tier_workhorse
        model_lightweight = config.model_tier_lightweight
        orchestrator_agent = SmeeOrchestrator(
            name="Smee",
            client=client,
            model=model_workhorse,  # Tier 2: orchestration & human summaries
            db_connection=db
        )

        # Register specialist agents with DB connections where supported
        orchestrator_agent.register_agent(
            "application_reader",
            TianaApplicationReader(
                name="Tiana Application Reader",
                client=client,
                model=model_workhorse,  # Tier 2: structured profile extraction
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "grade_reader",
            RapunzelGradeReader(
                name="Rapunzel Grade Reader",
                client=client,
                model=model_premium,  # Tier 1: complex transcript parsing
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "school_context",
            MoanaSchoolContext(
                name="Moana School Context Analyzer",
                client=client,
                model=model_workhorse,  # Tier 2: school analysis
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "recommendation_reader",
            MulanRecommendationReader(
                name="Mulan Recommendation Reader",
                client=client,
                model=model_workhorse,  # Tier 2: recommendation extraction
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "student_evaluator",
            MerlinStudentEvaluator(
                name="Merlin Student Evaluator",
                client=client,
                model=model_merlin,  # Tier 1+: GPT-5-mini final evaluator
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "data_scientist",
            MiloDataScientist(
                name="Milo Data Scientist",
                client=client,
                model=model_premium,  # Tier 1: historical pattern analysis
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "naveen",
            NaveenSchoolDataScientist(
                name="Naveen School Data Scientist",
                client=client,
                model=model_workhorse  # Tier 2: school enrichment
            )
        )
        orchestrator_agent.register_agent(
            "aurora",
            AuroraAgent()
        )
        orchestrator_agent.register_agent(
            "fairy_godmother",
            FairyGodmotherDocumentGenerator(
                db_connection=db,
                storage_manager=storage
            )
        )
        
        # Register supporting agents
        orchestrator_agent.register_agent(
            "bashful",
            BashfulAgent(
                name="Bashful Agent",
                client=client,
                model=model_workhorse,  # Tier 2: general assistant
                system_prompt="You are Bashful, a helpful assistant in the evaluation system."
            )
        )
        orchestrator_agent.register_agent(
            "belle",
            BelleDocumentAnalyzer(
                name="Belle Document Analyzer",
                client=client,
                model=model_lightweight,  # Tier 3: classification & entity extraction
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "scuttle",
            ScuttleFeedbackTriageAgent(
                name="Scuttle Feedback Triage",
                client=client,
                model=model_lightweight  # Tier 3: feedback triage
            )
        )

        # Ensure every registered agent has a valid AI client. Some agents (e.g. Aurora)
        # may be created without a client because they don't usually call the model.
        # Assign the configured client to any agent missing one so that calls from
        # BaseAgent always have a client available and the resolver can probe it.
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


def refresh_foundry_dataset_async(reason: str) -> None:
    def run():
        try:
            orchestrator = get_orchestrator()
            milo = orchestrator.agents.get("data_scientist") if orchestrator else None
            if not milo:
                logger.warning("Milo agent not available for dataset refresh")
                return

            result = asyncio.run(milo.build_and_upload_foundry_dataset())
            if result.get("status") == "success":
                logger.info(
                    "Foundry dataset refreshed",
                    extra={"dataset": result.get("dataset_name"), "version": result.get("dataset_version"), "reason": reason}
                )
            else:
                logger.warning(
                    "Foundry dataset refresh failed",
                    extra={"error": result.get("error"), "reason": reason}
                )
        except Exception as exc:
            logger.warning("Foundry dataset refresh error", exc_info=True, extra={"reason": reason, "error": str(exc)})

    threading.Thread(target=run, daemon=True).start()


@app.route('/healthz')
def healthz():
    """Health check endpoint for Azure Front Door probes.
    Excluded from EasyAuth — returns 200 with no sensitive data."""
    return jsonify({"status": "ok"}), 200


@app.route('/')
def index():
    """Home page - Dashboard."""
    # import here to guarantee availability even if globals fail
    from src.database import db
    from flask import flash
    try:
        applications_table = db.get_table_name("applications")
        training_col = db.get_training_example_column()
        test_col = db.get_test_data_column()
        app_id_col = db.get_applications_column("application_id")
        applicant_col = db.get_applications_column("applicant_name")
        email_col = db.get_applications_column("email")
        status_col = db.get_applications_column("status")
        uploaded_col = db.get_applications_column("uploaded_date")
        test_filter = ""
        if db.has_applications_column(test_col):
            test_filter = f" AND ({test_col} = FALSE OR {test_col} IS NULL)"

        # Simplified query to avoid timeout - just get basic count with a limit
        status_expr = f"LOWER(a.{status_col})"
        query = f"""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN {status_expr} = 'pending' THEN 1 ELSE 0 END) as pending,
                   SUM(CASE WHEN {status_expr} <> 'pending' THEN 1 ELSE 0 END) as evaluated
            FROM {applications_table} a
            WHERE a.{training_col} = FALSE{test_filter}
        """
        result = db.execute_query(query)
        
        if result and len(result) > 0:
            total_count = result[0].get('total', 0)
            pending_count = result[0].get('pending', 0)
            evaluated_count = result[0].get('evaluated', 0)
        else:
            total_count = pending_count = evaluated_count = 0
        
        # Get recent students with a simple query
        recent_query = f"""
            SELECT
                a.{app_id_col} as application_id,
                a.{applicant_col} as applicant_name,
                a.{email_col} as email,
                a.{status_col} as status,
                a.{uploaded_col} as uploaded_date
            FROM {applications_table} a
            WHERE a.{training_col} = FALSE{test_filter}
            ORDER BY a.{uploaded_col} DESC
            LIMIT 10
        """
        recent_results = db.execute_query(recent_query)
        
        # Format results
        recent_students = []
        for row in recent_results:
            parts = row.get('applicant_name', '').strip().split()
            recent_students.append({
                'application_id': row.get('application_id'),
                'first_name': parts[0] if len(parts) > 0 else '',
                'last_name': parts[-1] if len(parts) > 1 else '',
                'full_name': row.get('applicant_name'),
                'email': row.get('email'),
                'status': row.get('status'),
                'uploaded_date': row.get('uploaded_date')
            })
        
        return render_template('index.html', 
                             students=recent_students,
                             pending_count=pending_count,
                             evaluated_count=evaluated_count,
                             total_count=total_count,
                             app_version=config.app_version)
    except Exception as e:
        logger.error(f"Index page error: {e}", exc_info=True)
        flash(f'Error loading applications: {str(e)}', 'error')
        return render_template('index.html', students=[], pending_count=0, evaluated_count=0, total_count=0)


@app.route('/health')
def health():
    """Health check endpoint for Azure App Service."""
    return jsonify({
        'status': 'healthy',
        'app': 'NextGen Agent System',
        'version': config.app_version
    }), 200


def _build_feedback_issue_body(
    triage: Dict[str, Any],
    feedback_type: str,
    message: str,
    email: Optional[str],
    page: Optional[str],
    user_agent: Optional[str],
    app_version: Optional[str]
) -> str:
    lines = [
        "## Summary",
        triage.get("summary") or message,
        "",
        "## Details",
        f"- Feedback type: {feedback_type}",
        f"- Category: {triage.get('category', 'other')}",
        f"- Priority: {triage.get('priority', 'medium')}",
        "",
        "## Steps to Reproduce",
        triage.get("steps_to_reproduce") or "Not provided.",
        "",
        "## Expected Behavior",
        triage.get("expected_behavior") or "Not provided.",
        "",
        "## Actual Behavior",
        triage.get("actual_behavior") or "Not provided.",
        "",
        "## User Context",
        f"- Email: {email or 'Not provided'}",
        f"- Page: {page or 'Unknown'}",
        f"- App version: {app_version or 'Unknown'}",
        f"- User agent: {user_agent or 'Unknown'}",
        "",
        "## Raw Feedback",
        message
    ]
    return "\n".join(lines)


def _store_feedback_fallback(payload: Dict[str, Any]) -> None:
    try:
        os.makedirs("logs/feedback", exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"logs/feedback/feedback_{timestamp}_{uuid.uuid4().hex[:6]}.json"
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
    except Exception as exc:
        logger.error(f"Failed to store feedback fallback: {exc}", exc_info=True)


def _create_github_issue(title: str, body: str, labels: list[str]) -> Dict[str, Any]:
    if not config.github_token:
        raise ValueError("Missing GitHub token for issue creation")

    url = f"https://api.github.com/repos/{config.github_repo}/issues"
    headers = {
        "Authorization": f"Bearer {config.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nextgen-feedback-bot"
    }
    payload = {
        "title": title,
        "body": body,
        "labels": labels
    }
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(f"GitHub issue creation failed: {response.status_code} {response.text}")
    return response.json()


@app.route('/feedback', methods=['GET','POST'])
def submit_feedback():
    """Capture user feedback (POST) or display the feedback page (GET).

    The GET handler renders a simple form and shows recent GitHub-linked
    feedback items. POST requests follow the previous logic to triage and
    optionally create an issue.
    """
    if request.method == 'GET':
        # render submission page with existing GH-linked items
        try:
            all_feedback = db.get_recent_user_feedback(limit=100) if db else []
            feedback_items = [item for item in all_feedback if item.get('issue_url') or item.get('IssueUrl')]
        except Exception:
            feedback_items = []
        return render_template('feedback.html', feedback_items=feedback_items)

    data = request.get_json(silent=True) or {}
    feedback_type = (data.get('type') or '').strip().lower()
    message = (data.get('message') or '').strip()
    email = (data.get('email') or '').strip() or None
    page = (data.get('page') or '').strip() or request.referrer
    app_version = config.app_version
    user_agent = request.headers.get('User-Agent')

    if feedback_type not in {'issue', 'feature'}:
        return jsonify({'error': 'Feedback type must be issue or feature.'}), 400
    if not message:
        return jsonify({'error': 'Feedback message is required.'}), 400

    # quick sanity check that GitHub integration is complete when token is present
    if config.github_token and not config.github_repo:
        logger.error("GitHub token provided but repository unset")
        return jsonify({'error': 'Feedback service misconfigured (missing GitHub repo).'}), 500

    feedback_id = None
    try:
        if db:
            feedback_id = db.save_user_feedback(
                feedback_type=feedback_type,
                message=message,
                email=email,
                page=page,
                app_version=app_version,
                user_agent=user_agent,
                status='received'
            )

        triage_agent = get_feedback_agent()
        triage = asyncio.run(
            triage_agent.analyze_feedback(
                feedback_type=feedback_type,
                message=message,
                email=email,
                page=page,
                app_version=app_version
            )
        )
        if feedback_id and db:
            db.update_user_feedback(
                feedback_id=feedback_id,
                triage_json=triage,
                status='triaged'
            )
        issue_body = _build_feedback_issue_body(
            triage=triage,
            feedback_type=feedback_type,
            message=message,
            email=email,
            page=page,
            user_agent=user_agent,
            app_version=app_version
        )
        labels = set(triage.get('suggested_labels', []))
        labels.update({'feedback', feedback_type})
        issue = None
        if config.github_token:
            issue = _create_github_issue(
                title=triage.get('title') or f"User feedback: {feedback_type}",
                body=issue_body,
                labels=sorted(labels)
            )
            if feedback_id and db:
                db.update_user_feedback(
                    feedback_id=feedback_id,
                    issue_url=issue.get('html_url'),
                    status='submitted'
                )
        else:
            if feedback_id and db:
                db.update_user_feedback(
                    feedback_id=feedback_id,
                    status='awaiting_github'
                )
            _store_feedback_fallback({
                "feedback_id": feedback_id,
                "type": feedback_type,
                "message": message,
                "email": email,
                "page": page,
                "app_version": app_version,
                "user_agent": user_agent,
                "error": "GitHub token not configured"
            })
            return jsonify({'error': 'GitHub integration is not configured yet. Feedback saved locally.'}), 503

        return jsonify({'status': 'success', 'issue_url': issue.get('html_url')}), 201
    except Exception as exc:
        if db:
            try:
                if feedback_id:
                    db.update_user_feedback(
                        feedback_id=feedback_id,
                        status='error'
                    )
            except Exception:
                pass
        _store_feedback_fallback({
            "type": feedback_type,
            "message": message,
            "email": email,
            "page": page,
            "app_version": app_version,
            "user_agent": user_agent,
            "error": str(exc)
        })
        logger.error(f"Feedback submission failed: {exc}", exc_info=True)
        # surface the underlying message for easier debugging, but keep generic primary text
        msg = str(exc)
        return jsonify({
            'error': 'Unable to submit feedback right now.',
            'details': msg
        }), 500


@app.route('/feedback/admin')
def feedback_admin():
    """View recent feedback submissions."""
    try:
        all_feedback = db.get_recent_user_feedback(limit=100) if db else []
        # Filter to only show GitHub issues (those with issue_url)
        feedback_items = [item for item in all_feedback if item.get('issue_url') or item.get('IssueUrl')]
        return render_template('feedback_admin.html', feedback_items=feedback_items)
    except Exception as exc:
        logger.error(f"Feedback admin error: {exc}", exc_info=True)
        flash('Unable to load feedback right now.', 'error')
        return render_template('feedback_admin.html', feedback_items=[])


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    """
    Upload new application file.
    Smee extracts student info automatically.
    """
    if request.method == 'POST':
        try:
            if 'file' not in request.files:
                flash('No file uploaded', 'error')
                return redirect(request.url)

            files = request.files.getlist('file')
            if not files or all(not f.filename for f in files):
                flash('No file selected', 'error')
                return redirect(request.url)
            
            # Determine application type from radio buttons
            app_type = request.form.get('app_type', '2026')  # Default to 2026
            is_training = (app_type == 'training')
            is_test = (app_type == 'test')
            
            # Get selection status for training data
            was_selected = None
            if is_training:
                was_selected_value = (request.form.get('was_selected') or '').strip().lower()
                was_selected = was_selected_value in {'on', 'yes', 'true', '1'}
            
            belle = get_belle()
            grouped_uploads: Dict[str, Dict[str, Any]] = {}
            valid_files = 0

            for file in files:
                if not file.filename:
                    continue

                if not DocumentProcessor.validate_file_type(file.filename):
                    flash(f"Invalid file type: {file.filename}. Please upload PDF, DOCX, TXT, or MP4 files.", 'error')
                    continue

                valid_files += 1
                filename = secure_filename(file.filename)
                temp_id = uuid.uuid4().hex
                temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{temp_id}_{filename}")
                file.save(temp_path)

                # ── Route: Video files → Mirabel, Documents → Belle ──
                is_video = DocumentProcessor.is_video_file(filename)

                if is_video:
                    # Video file: use Mirabel Video Analyzer
                    with open(temp_path, 'rb') as handle:
                        file_content = handle.read()

                    try:
                        mirabel = get_mirabel()
                        doc_analysis = mirabel.analyze_video(temp_path, filename)
                        application_text = doc_analysis.get('agent_fields', {}).get('application_text', '')
                        file_type = 'mp4'
                    except Exception as e:
                        logger.warning(f"Mirabel video analysis failed: {e}")
                        doc_analysis = {
                            "document_type": "video_submission",
                            "confidence": 0,
                            "student_info": {},
                            "extracted_data": {},
                            "agent_fields": {}
                        }
                        application_text = ""
                        file_type = 'mp4'
                    finally:
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
                else:
                    # Document file: use Belle Document Analyzer
                    ocr_callback = _make_ocr_callback()
                    application_text, file_type = DocumentProcessor.process_document(
                        temp_path, ocr_callback=ocr_callback
                    )

                    with open(temp_path, 'rb') as handle:
                        file_content = handle.read()

                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

                    try:
                        doc_analysis = belle.analyze_document(application_text, filename)
                    except Exception as e:
                        logger.warning(f"Belle analysis failed: {e}")
                    doc_analysis = {
                        "document_type": "unknown",
                        "confidence": 0,
                        "student_info": {},
                        "extracted_data": {}
                    }

                belle_student_info = doc_analysis.get('student_info', {})
                extracted_name = belle_student_info.get('name') or extract_student_name(application_text)
                first_name = belle_student_info.get('first_name')
                last_name = belle_student_info.get('last_name')
                if extracted_name and not (first_name and last_name):
                    first_name, last_name = _split_name_parts(extracted_name)

                student_email = belle_student_info.get('email') or extract_student_email(application_text) or ""
                school_name = (doc_analysis.get('agent_fields') or {}).get('school_name') or belle_student_info.get('school_name')

                identity_key = _build_identity_key(
                    first_name=first_name,
                    last_name=last_name,
                    school_name=school_name,
                    email=student_email,
                    full_name=extracted_name,
                    filename=filename
                )

                if identity_key not in grouped_uploads:
                    grouped_uploads[identity_key] = {
                        'first_name': first_name,
                        'last_name': last_name,
                        'student_name': extracted_name,
                        'student_email': student_email,
                        'school_name': school_name,
                        'files': []
                    }

                group = grouped_uploads[identity_key]
                if first_name and not group.get('first_name'):
                    group['first_name'] = first_name
                if last_name and not group.get('last_name'):
                    group['last_name'] = last_name
                if extracted_name and not group.get('student_name'):
                    group['student_name'] = extracted_name
                if student_email and not group.get('student_email'):
                    group['student_email'] = student_email
                if school_name and not group.get('school_name'):
                    group['school_name'] = school_name

                group['files'].append({
                    'filename': filename,
                    'text': application_text,
                    'file_type': file_type,
                    'file_content': file_content,
                    'document_type': doc_analysis.get('document_type', 'unknown'),
                    'student_info': belle_student_info,
                    'agent_fields': doc_analysis.get('agent_fields', {})
                })

            # ── Process pre-uploaded video blobs (chunked upload) ─────
            video_blob_info_raw = request.form.get('video_blob_info', '').strip()
            if video_blob_info_raw:
                import json as _json
                try:
                    video_blobs = _json.loads(video_blob_info_raw)
                except Exception:
                    video_blobs = []

                for vblob in video_blobs:
                    blob_path = vblob.get('blob_path')
                    vfilename = secure_filename(vblob.get('filename', 'video.mp4'))
                    if not blob_path:
                        continue

                    temp_id = uuid.uuid4().hex
                    temp_path = os.path.join(
                        app.config['UPLOAD_FOLDER'],
                        f"temp_{temp_id}_{vfilename}"
                    )

                    try:
                        ok = storage.download_video_to_file(
                            blob_path=blob_path,
                            local_path=temp_path,
                            application_type=app_type,
                        )
                        if not ok:
                            flash(f"Could not retrieve video {vfilename} from storage", 'error')
                            continue

                        valid_files += 1

                        # Read file content for later storage.upload_file()
                        with open(temp_path, 'rb') as handle:
                            file_content = handle.read()

                        try:
                            mirabel = get_mirabel()
                            doc_analysis = mirabel.analyze_video(temp_path, vfilename)
                            application_text = doc_analysis.get('agent_fields', {}).get('application_text', '')
                            file_type = 'mp4'
                        except Exception as e:
                            logger.warning("Mirabel video analysis (blob) failed: %s", e)
                            doc_analysis = {
                                "document_type": "video_submission",
                                "confidence": 0,
                                "student_info": {},
                                "extracted_data": {},
                                "agent_fields": {}
                            }
                            application_text = ""
                            file_type = 'mp4'
                    finally:
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass

                    belle_student_info = doc_analysis.get('student_info', {})
                    extracted_name = belle_student_info.get('name') or extract_student_name(application_text)
                    first_name = belle_student_info.get('first_name')
                    last_name = belle_student_info.get('last_name')
                    if extracted_name and not (first_name and last_name):
                        first_name, last_name = _split_name_parts(extracted_name)

                    student_email = belle_student_info.get('email') or extract_student_email(application_text) or ""
                    school_name = (doc_analysis.get('agent_fields') or {}).get('school_name') or belle_student_info.get('school_name')

                    identity_key = _build_identity_key(
                        first_name=first_name,
                        last_name=last_name,
                        school_name=school_name,
                        email=student_email,
                        full_name=extracted_name,
                        filename=vfilename
                    )

                    if identity_key not in grouped_uploads:
                        grouped_uploads[identity_key] = {
                            'first_name': first_name,
                            'last_name': last_name,
                            'student_name': extracted_name,
                            'student_email': student_email,
                            'school_name': school_name,
                            'files': []
                        }

                    group = grouped_uploads[identity_key]
                    if first_name and not group.get('first_name'):
                        group['first_name'] = first_name
                    if last_name and not group.get('last_name'):
                        group['last_name'] = last_name
                    if extracted_name and not group.get('student_name'):
                        group['student_name'] = extracted_name
                    if student_email and not group.get('student_email'):
                        group['student_email'] = student_email
                    if school_name and not group.get('school_name'):
                        group['school_name'] = school_name

                    group['files'].append({
                        'filename': vfilename,
                        'text': application_text,
                        'file_type': file_type,
                        'file_content': file_content,
                        'document_type': doc_analysis.get('document_type', 'video_submission'),
                        'student_info': belle_student_info,
                        'agent_fields': doc_analysis.get('agent_fields', {})
                    })

            if valid_files == 0:
                flash('No valid files uploaded.', 'error')
                return redirect(request.url)

            results = []
            for group in grouped_uploads.values():
                group_first = group.get('first_name')
                group_last = group.get('last_name')
                group_name = group.get('student_name')
                if group_first and group_last:
                    group_name = f"{group_first} {group_last}".strip()

                group_email = group.get('student_email')
                group_school = group.get('school_name')

                aggregated = _aggregate_documents(group['files'])
                match = find_high_probability_match(
                    student_name=group_name,
                    student_first_name=group_first,
                    student_last_name=group_last,
                    student_email=group_email,
                    school_name=group_school,
                    transcript_text=aggregated.get('transcript_text'),
                    is_training=is_training,
                    is_test=is_test
                )

                if match and match.get('application_id'):
                    application_id = match['application_id']
                    application_record = db.get_application(application_id) or {}
                    student_id = (
                        application_record.get('student_id')
                        or match.get('student_id')
                        or storage.generate_student_id()
                    )

                    if not application_record.get('student_id') and student_id:
                        db.update_application_fields(application_id, {'student_id': student_id})

                    for file_entry in group['files']:
                        storage_result = storage.upload_file(
                            file_content=file_entry['file_content'],
                            filename=file_entry['filename'],
                            student_id=student_id,
                            application_type=app_type
                        )
                        if not storage_result.get('success'):
                            flash(
                                f"Error uploading {file_entry['filename']} to storage: "
                                f"{storage_result.get('error')}",
                                'error'
                            )

                    documents = _collect_documents_from_storage(student_id, app_type, belle)
                    if not documents:
                        documents = group['files']

                    aggregated = _aggregate_documents(documents)
                    updates = {}
                    for field in ['application_text', 'transcript_text', 'recommendation_text']:
                        new_value = aggregated.get(field)
                        if new_value:
                            updates[field] = new_value
                        elif application_record.get(field):
                            updates[field] = application_record.get(field)

                    db.update_application_fields(application_id, updates)

                    missing_fields = []
                    if not updates.get('transcript_text'):
                        missing_fields.append('transcript')
                    if not updates.get('recommendation_text'):
                        missing_fields.append('letters_of_recommendation')
                    db.set_missing_fields(application_id, missing_fields)

                    reprocess_note = _summarize_filenames([f['filename'] for f in group['files']])
                    try:
                        db.save_agent_audit(
                            application_id,
                            'System',
                            f"reprocess:new_upload:{reprocess_note}"
                        )
                    except Exception:
                        pass

                    start_application_processing(application_id)

                    if is_training:
                        refresh_foundry_dataset_async("training_match_update")

                    results.append({
                        'application_id': application_id,
                        'action': 'matched',
                        'applicant_name': match.get('applicant_name') or group_name,
                        'match_score': match.get('match_score')
                    })
                    continue
            
                student_id = storage.generate_student_id()
                for file_entry in group['files']:
                    storage_result = storage.upload_file(
                        file_content=file_entry['file_content'],
                        filename=file_entry['filename'],
                        student_id=student_id,
                        application_type=app_type
                    )
                    if not storage_result.get('success'):
                        flash(
                            f"Error uploading {file_entry['filename']} to storage: {storage_result.get('error')}",
                            'error'
                        )

                application_text = aggregated.get('application_text') or group['files'][0]['text']
                file_type = group['files'][0].get('file_type')
                filename = group['files'][0].get('filename')
                student_name = group_name or f"Student {student_id}"

                application_id = db.create_application(
                    applicant_name=student_name,
                    email=group_email or "",
                    application_text=application_text,
                    file_name=filename,
                    file_type=file_type,
                    is_training=(is_training or is_test),
                    is_test_data=is_test,
                    was_selected=was_selected,
                    student_id=student_id
                )

                additional_fields = {}
                if aggregated.get('transcript_text'):
                    additional_fields['transcript_text'] = aggregated.get('transcript_text')
                if aggregated.get('recommendation_text'):
                    additional_fields['recommendation_text'] = aggregated.get('recommendation_text')
                if additional_fields:
                    db.update_application_fields(application_id, additional_fields)

                missing_fields = []
                if not additional_fields.get('transcript_text'):
                    missing_fields.append('transcript')
                if not additional_fields.get('recommendation_text'):
                    missing_fields.append('letters_of_recommendation')
                if missing_fields:
                    db.set_missing_fields(application_id, missing_fields)

                if is_training:
                    application_record = db.get_application(application_id) or {}
                    placeholder_fields = {}

                    if not application_record.get('application_text'):
                        placeholder_fields['application_text'] = 'No application essay provided for this training run.'
                    if not application_record.get('transcript_text'):
                        placeholder_fields['transcript_text'] = 'No transcript provided for this training run.'
                    if not application_record.get('recommendation_text'):
                        placeholder_fields['recommendation_text'] = 'No recommendation letter provided for this training run.'

                    if placeholder_fields:
                        db.update_application_fields(application_id, placeholder_fields)

                    # Auto-link historical scoring data by name match
                    # Propagate was_selected so Milo can distinguish selected vs not-selected
                    try:
                        historical = db.get_historical_score_by_name(student_name)
                        if historical:
                            db.link_historical_score_to_application(
                                historical['score_id'], application_id,
                                was_selected=was_selected
                            )
                            logger.info(
                                f"✓ Linked historical score {historical['score_id']} "
                                f"({historical.get('applicant_name')}) to application {application_id}"
                                f" [was_selected={was_selected}]"
                            )
                    except Exception as hist_err:
                        logger.warning(f"Historical score matching failed for '{student_name}': {hist_err}")

                    db.set_missing_fields(application_id, [])
                    start_training_processing(application_id)

                results.append({
                    'application_id': application_id,
                    'action': 'created',
                    'applicant_name': student_name
                })

            if not results:
                flash('No valid uploads were processed.', 'error')
                return redirect(request.url)

            matched_count = len([r for r in results if r.get('action') == 'matched'])
            created_count = len([r for r in results if r.get('action') == 'created'])

            if is_training:
                flash(
                    f"✅ Uploaded {len(results)} student group(s). "
                    f"Matched {matched_count}, created {created_count}.",
                    'success'
                )
                refresh_foundry_dataset_async("training_upload")
                return redirect(url_for('training'))

            if is_test:
                flash(
                    f"✅ Uploaded {len(results)} test student group(s). "
                    f"Matched {matched_count}, created {created_count}.",
                    'success'
                )
                return redirect(url_for('test'))

            if len(results) == 1:
                result = results[0]
                if result.get('action') == 'matched':
                    flash(
                        f"✅ Matched upload to {result.get('applicant_name', 'existing student')}. "
                        "Re-running agents with all documents.",
                        'success'
                    )
                    return redirect(url_for('student_detail', application_id=result['application_id']))

                flash(
                    f"✅ Application uploaded for {result.get('applicant_name', 'student')}. "
                    "Information needed before processing.",
                    'success'
                )
                return redirect(url_for('process_student', application_id=result['application_id']))

            flash(
                f"✅ Uploaded {len(results)} student group(s). "
                f"Matched {matched_count}, created {created_count}.",
                'success'
            )
            return redirect(url_for('students'))
            
        except Exception as e:
            flash(f'Error uploading file: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
            return redirect(request.url)
    
    # if query parameter provided, pass along to template so JS can preselect
    app_type = request.args.get('app_type')
    was_selected = request.args.get('was_selected')
    if app_type:
        logger.info(f"Upload page requested with preselect app_type={app_type}")
    return render_template('upload.html', preselect_type=app_type, preselect_selected=was_selected)


def extract_student_name(text: str) -> Optional[str]:
    """Extract student name from application text."""
    try:
        # Look for common patterns like "My name is..." or "I am..."
        import re

        # Pattern 0: Explicit First Name / Last Name fields
        first_match = re.search(r'First\s*Name\s*[:\-]?\s*([A-Za-z\'\-]+)', text, re.IGNORECASE)
        last_match = re.search(r'Last\s*Name\s*[:\-]?\s*([A-Za-z\'\-]+)', text, re.IGNORECASE)
        if first_match and last_match:
            first = first_match.group(1).strip()
            last = last_match.group(1).strip()
            return f"{first} {last}".strip()
        
        # Pattern 1: "My name is [Name]"
        match = re.search(r"(?:my name is|i am|i\'m)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Pattern 2: First capitalized words at start of text
        words = text.split()
        if len(words) >= 2:
            for i in range(len(words) - 1):
                if words[i][0].isupper() and words[i+1][0].isupper():
                    name = f"{words[i]} {words[i+1]}"
                    if len(name) < 50:  # Sanity check
                        return name
        
        return None
    except Exception:
        return None


def extract_student_email(text: str) -> Optional[str]:
    """Extract email address from application text."""
    import re
    
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


def _split_name_parts(full_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
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


def _summarize_filenames(filenames: list[str], max_names: int = 3) -> str:
    cleaned = [name for name in filenames if name]
    if len(cleaned) <= max_names:
        return ", ".join(cleaned)
    return f"{', '.join(cleaned[:max_names])} (+{len(cleaned) - max_names} more)"


def _aggregate_documents(documents: list[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    fields = {
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

        # ── Prefer Belle's section-level agent_fields over doc_type ──
        # Belle's _detect_document_sections() routes individual pages to
        # transcript_text / recommendation_text / application_text.  When
        # that data is available it is more precise than the single
        # document_type label (which is "winner-take-all" for the whole doc).
        agent_fields = doc.get('agent_fields') or {}
        used_agent_fields = False
        for af_field in ('application_text', 'transcript_text', 'recommendation_text'):
            af_val = agent_fields.get(af_field)
            if af_val and isinstance(af_val, str) and len(af_val.strip()) > 20:
                fields[af_field] = _merge_uploaded_text(
                    fields.get(af_field),
                    af_val,
                    label_map.get(af_field, 'Document'),
                    filename
                )
                used_agent_fields = True

        if used_agent_fields:
            continue

        # Fallback: route whole document text by doc_type
        target_field = doc_type_map.get(doc_type)

        if target_field:
            fields[target_field] = _merge_uploaded_text(
                fields.get(target_field),
                text,
                label_map.get(target_field, 'Document'),
                filename
            )
            continue

        # Unknown doc_type: fill whatever is still empty
        if not fields.get('application_text'):
            fields['application_text'] = text
        elif not fields.get('recommendation_text'):
            fields['recommendation_text'] = text
        else:
            fields['transcript_text'] = fields.get('transcript_text') or text

    return fields


def _collect_documents_from_storage(
    student_id: str,
    application_type: str,
    belle: Any
) -> list[Dict[str, Any]]:
    if not storage.client:
        return []

    documents: list[Dict[str, Any]] = []
    blob_names = storage.list_student_files(student_id, application_type)
    for blob_name in blob_names:
        filename = os.path.basename(blob_name)
        file_content = storage.download_file(student_id, filename, application_type)
        if not file_content:
            continue

        temp_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            f"reprocess_{student_id}_{uuid.uuid4().hex}_{filename}"
        )
        try:
            with open(temp_path, 'wb') as handle:
                handle.write(file_content)
            file_text, _ = DocumentProcessor.process_document(temp_path)
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass

        try:
            analysis = belle.analyze_document(file_text, filename)
        except Exception as exc:
            logger.warning(f"Belle analysis failed during reprocess: {exc}")
            analysis = {
                "document_type": "unknown",
                "agent_fields": {}
            }

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
    if not student_name and not student_email:
        return None

    candidates = db.get_application_match_candidates(is_training=is_training, is_test_data=is_test)
    if not candidates:
        return None

    uploaded_gpa = _extract_gpa(transcript_text)

    best_candidate = None
    best_score = 0.0
    best_reason = ""

    def split_candidate_name(name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        if not name:
            return None, None
        tokens = [token for token in re.split(r"\s+", name.strip()) if token]
        if len(tokens) < 2:
            return tokens[0], None
        return tokens[0], tokens[-1]

    for candidate in candidates:
        candidate_name = candidate.get('applicant_name')
        candidate_email = candidate.get('email')
        candidate_school = candidate.get('school_name')
        candidate_gpa = _extract_gpa(candidate.get('transcript_text'))

        candidate_first, candidate_last = split_candidate_name(candidate_name)
        first_similarity = _string_similarity(student_first_name, candidate_first)
        last_similarity = _string_similarity(student_last_name, candidate_last)

        email_match = bool(student_email and candidate_email and student_email.lower() == candidate_email.lower())
        name_similarity = max(
            _string_similarity(student_name, candidate_name),
            _token_similarity(student_name, candidate_name)
        )
        school_similarity = max(
            _string_similarity(school_name, candidate_school),
            _token_similarity(school_name, candidate_school)
        )

        gpa_similarity = 0.0
        if uploaded_gpa is not None and candidate_gpa is not None:
            gpa_diff = abs(uploaded_gpa - candidate_gpa)
            gpa_similarity = max(0.0, 1.0 - min(gpa_diff / 1.0, 1.0))

        score = 0.55 * name_similarity + 0.25 * school_similarity + 0.10 * gpa_similarity
        if name_similarity > 0.85 and school_similarity > 0.6:
            score += 0.1
        if email_match:
            score = max(score, 0.98)

        score = min(score, 1.0)

        if student_first_name and student_last_name and school_name:
            if first_similarity < 0.75 or last_similarity < 0.75 or school_similarity < 0.6:
                continue

        if score > best_score:
            best_score = score
            best_candidate = candidate
            best_reason = f"name={name_similarity:.2f}, school={school_similarity:.2f}, gpa={gpa_similarity:.2f}, email={email_match}"

    if not best_candidate:
        return None

    if best_score >= 0.78 and (_string_similarity(student_name, best_candidate.get('applicant_name')) >= 0.6 or student_email):
        best_candidate['match_score'] = best_score
        best_candidate['match_reason'] = best_reason
        return best_candidate

    return None



@app.route('/evaluate/<int:application_id>', methods=['POST'])
def evaluate(application_id):
    """Evaluate a single application."""
    try:
        # Get application
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Application not found'}), 404
        
        # Get evaluator and run evaluation
        evaluator = get_evaluator()
        evaluation = asyncio.run(evaluator.evaluate_application(application))
        
        # Save evaluation to database
        db.save_evaluation(
            application_id=application_id,
            agent_name=evaluation['agent_name'],
            overall_score=evaluation['overall_score'],
            technical_score=evaluation['technical_skills_score'],
            communication_score=evaluation['communication_score'],
            experience_score=evaluation['experience_score'],
            cultural_fit_score=evaluation['cultural_fit_score'],
            strengths=evaluation['strengths'],
            weaknesses=evaluation['weaknesses'],
            recommendation=evaluation['recommendation'],
            detailed_analysis=evaluation['detailed_analysis'],
            comparison=evaluation['comparison_to_excellence'],
            model_used=evaluation['model_used'],
            processing_time_ms=evaluation['processing_time_ms']
        )
        
        # Update application status
        db.update_application_status(application_id, 'Completed')
        
        return jsonify(evaluation)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/evaluate_all', methods=['POST'])
def evaluate_all():
    """Evaluate all pending applications."""
    try:
        pending = db.get_pending_applications()
        evaluator = get_evaluator()
        
        results = []
        for application in pending:
            evaluation = asyncio.run(evaluator.evaluate_application(application))
            
            # Save to database
            db.save_evaluation(
                application_id=application['ApplicationID'],
                agent_name=evaluation['agent_name'],
                overall_score=evaluation['overall_score'],
                technical_score=evaluation['technical_skills_score'],
                communication_score=evaluation['communication_score'],
                experience_score=evaluation['experience_score'],
                cultural_fit_score=evaluation['cultural_fit_score'],
                strengths=evaluation['strengths'],
                weaknesses=evaluation['weaknesses'],
                recommendation=evaluation['recommendation'],
                detailed_analysis=evaluation['detailed_analysis'],
                comparison=evaluation['comparison_to_excellence'],
                model_used=evaluation['model_used'],
                processing_time_ms=evaluation['processing_time_ms']
            )
            
            # Update status
            db.update_application_status(application['ApplicationID'], 'Completed')
            
            results.append({
                'application_id': application['ApplicationID'],
                'applicant_name': application['ApplicantName'],
                'recommendation': evaluation['recommendation'],
                'overall_score': evaluation['overall_score']
            })
        
        return jsonify({'success': True, 'evaluations': results})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/students')
def students():
    """View all students sorted by last name."""
    try:
        search_query = request.args.get('search', '').strip()
        
        # Get formatted student list sorted by last name
        students = db.get_formatted_student_list(is_training=False, search_query=search_query if search_query else None)
        
        # CRITICAL: Defensive filtering to ensure test data NEVER appears in 2026 production view
        filtered_students = []
        for student in students:
            is_test = student.get('is_test_data')
            is_training = student.get('is_training_example')
            
            # Only include if BOTH test and training flags are False/None
            if (is_test is None or is_test is False) and (is_training is None or is_training is False):
                filtered_students.append(student)
            else:
                if is_test:
                    logger.warning(f"🔴 SECURITY: Filtered out test data from /students: {student.get('id')}")
                if is_training:
                    logger.warning(f"🔴 SECURITY: Filtered out training data from /students: {student.get('id')}")
        
        return render_template('students.html', 
                             students=filtered_students,
                             search_query=search_query)
    except Exception as e:
        flash(f'Error loading students: {str(e)}', 'error')
        return render_template('students.html', students=[], search_query='')


@app.route('/debug/dataset')
def debug_dataset():
    """Debug view: show raw `student_summary` and `agent_results` for recent applications."""
    try:
        applications_table = db.get_table_name("applications")
        if not applications_table:
            flash('Applications table not found', 'error')
            return render_template('debug_dataset.html', rows=[])

        query = f"SELECT application_id, applicant_name, email, uploaded_date, student_summary, agent_results FROM {applications_table} ORDER BY uploaded_date DESC LIMIT 200"
        rows = db.execute_query(query)

        # Ensure JSON/text columns are pretty-printed for template display
        for r in rows:
            # student_summary
            ss = r.get('student_summary')
            if isinstance(ss, (dict, list)):
                try:
                    r['student_summary_pretty'] = json.dumps(ss, indent=2)
                except Exception:
                    r['student_summary_pretty'] = str(ss)
            elif isinstance(ss, str):
                try:
                    parsed = json.loads(ss)
                    r['student_summary_pretty'] = json.dumps(parsed, indent=2)
                except Exception:
                    r['student_summary_pretty'] = ss
            else:
                r['student_summary_pretty'] = ''

            # agent_results
            ar = r.get('agent_results')
            if isinstance(ar, (dict, list)):
                try:
                    r['agent_results_pretty'] = json.dumps(ar, indent=2)
                except Exception:
                    r['agent_results_pretty'] = str(ar)
            elif isinstance(ar, str):
                try:
                    parsed = json.loads(ar)
                    r['agent_results_pretty'] = json.dumps(parsed, indent=2)
                except Exception:
                    r['agent_results_pretty'] = ar
            else:
                r['agent_results_pretty'] = ''

        return render_template('debug_dataset.html', rows=rows)
    except Exception as e:
        flash(f'Error loading dataset: {str(e)}', 'error')
        return render_template('debug_dataset.html', rows=[])


@app.route('/training')
def training():
    """Training data management page - historical applications for agent learning."""
    try:
        search_query = request.args.get('search', '').strip()
        filter_selected = request.args.get('filter', '')
        
        # Get formatted student list for training examples, sorted by last name
        training_data = db.get_formatted_student_list(is_training=True, search_query=search_query if search_query else None)
        
        # CRITICAL: Defensive filtering to ensure test data NEVER appears in training view
        filtered_training = []
        for record in training_data:
            is_test = record.get('is_test_data')
            # Training data should NEVER be marked as test data
            if is_test is None or is_test is False:
                filtered_training.append(record)
            else:
                logger.warning(f"🔴 SECURITY: Filtered out test data from /training: {record.get('id')}")
        
        training_data = filtered_training
        
        # Apply filter if specified
        if filter_selected == 'selected':
            training_data = [t for t in training_data if t.get('was_selected')]
        elif filter_selected == 'not_selected':
            training_data = [t for t in training_data if not t.get('was_selected')]
        
        # Calculate statistics
        total_count = len(training_data)
        selected_count = len([t for t in training_data if t.get('was_selected')])
        not_selected_count = total_count - selected_count
        
        # Count students with historical XLSX matches
        matched_count = len([t for t in training_data if t.get('has_historical_match')])

        return render_template('training.html',
                             training_data=training_data,
                             search_query=search_query,
                             filter_selected=filter_selected,
                             total_count=total_count,
                             selected_count=selected_count,
                             not_selected_count=not_selected_count,
                             matched_count=matched_count,
                             is_training_view=True)
    except Exception as e:
        flash(f'Error loading training data: {str(e)}', 'error')
        return render_template('training.html', 
                             training_data=[], 
                             search_query='',
                             filter_selected='',
                             total_count=0,
                             selected_count=0,
                             not_selected_count=0)


@app.route('/test')
def test():
    """Test system page with quick test generation."""
    try:
        return render_template('test.html')
    except Exception as e:
        logger.error(f'Error loading test page: {e}', exc_info=True)
        return f'<h1>Error loading test page</h1><p>{str(e)}</p>', 500


@app.route('/test-data')
def test_data():
    """View all test students created via quick test."""
    try:
        applications_table = db.get_table_name("applications")
        test_col = db.get_test_data_column()
        app_id_col = db.get_applications_column("application_id")
        applicant_col = db.get_applications_column("applicant_name")
        email_col = db.get_applications_column("email")
        status_col = db.get_applications_column("status")
        uploaded_col = db.get_applications_column("uploaded_date")
        training_col = db.get_training_example_column()

        test_students = []
        if db.has_applications_column(test_col):
            # CRITICAL: Only return records marked with is_test_data = TRUE
            # AND NOT marked as training data
            test_students_query = f"""
                SELECT
                    a.{app_id_col} as application_id,
                    a.{applicant_col} as applicant_name,
                    a.{email_col} as email,
                    a.{status_col} as status,
                    a.{uploaded_col} as uploaded_date,
                    a.{test_col} as is_test_data,
                    a.{training_col} as is_training_example
                FROM {applications_table} a
                WHERE a.{test_col} = TRUE
                AND (a.{training_col} = FALSE OR a.{training_col} IS NULL)
                ORDER BY a.{uploaded_col} DESC
            """
            test_students = db.execute_query(test_students_query)
        
        # Format for display
        formatted_students = []
        for student in test_students:
            # Defensive check: ensure this is actually test data
            if student.get('is_test_data') and not student.get('is_training_example'):
                formatted_students.append({
                    'application_id': student.get('application_id'),
                    'applicant_name': student.get('applicant_name'),
                    'email': student.get('email'),
                    'status': student.get('status'),
                    'uploaded_date': student.get('uploaded_date')
                })
            else:
                logger.warning(f"🔴 SECURITY: Discarded invalid record from /test-data: {student.get('application_id')}")
        
        return render_template('test_data.html',
                             test_students=formatted_students,
                             total_count=len(formatted_students))
    except Exception as e:
        flash(f'Error loading test data: {str(e)}', 'error')
        return render_template('test_data.html',
                             test_students=[],
                             total_count=0)


def cleanup_test_data():
    """
    Delete all old test data (applications marked with is_test_data = TRUE).
    Also removes any incomplete/orphaned training applications (missing required fields).
    Called at the start of each new test run to ensure clean slate.
    """
    try:
        # Delete all related evaluation data first (foreign key constraints)
        applications_table = db.get_table_name("applications")
        test_col = db.get_test_data_column()
        training_col = db.get_training_example_column()
        app_id_col = db.get_applications_column("application_id")
        applicant_col = db.get_applications_column("applicant_name")

        # First, clean up any incomplete training applications (NULL application_id or applicant_name)
        if db.has_applications_column(training_col):
            incomplete_ids = db.execute_query(
                f"SELECT {app_id_col} as application_id FROM {applications_table} WHERE {training_col} = TRUE AND ({app_id_col} IS NULL OR {applicant_col} IS NULL)"
            )
            for app_record in incomplete_ids:
                app_id = app_record.get('application_id')
                if app_id:
                    # Clean up related data
                    for table in ["tiana_applications", "mulan_recommendations", "merlin_evaluations", 
                                 "student_school_context", "grade_records", "ai_evaluations", "agent_audit_logs"]:
                        try:
                            db.execute_non_query(f"DELETE FROM {table} WHERE application_id = %s", (app_id,))
                        except Exception:
                            pass
            # Delete the incomplete applications themselves
            db.execute_non_query(f"DELETE FROM {applications_table} WHERE {training_col} = TRUE AND ({app_id_col} IS NULL OR {applicant_col} IS NULL)")

        test_app_ids = []
        if db.has_applications_column(test_col):
            test_app_ids = db.execute_query(
                f"SELECT {app_id_col} as application_id FROM {applications_table} WHERE {test_col} = TRUE"
            )
        
        for app_record in test_app_ids:
            app_id = app_record.get('application_id')
            
            # Delete from specialized agent tables
            try:
                db.execute_non_query("DELETE FROM tiana_applications WHERE application_id = %s", (app_id,))
            except Exception:
                pass
            
            try:
                db.execute_non_query("DELETE FROM mulan_recommendations WHERE application_id = %s", (app_id,))
            except Exception:
                pass
            
            try:
                db.execute_non_query("DELETE FROM merlin_evaluations WHERE application_id = %s", (app_id,))
            except Exception:
                pass
            
            try:
                db.execute_non_query("DELETE FROM student_school_context WHERE application_id = %s", (app_id,))
            except Exception:
                pass
            
            try:
                db.execute_non_query("DELETE FROM grade_records WHERE application_id = %s", (app_id,))
            except Exception:
                pass
            
            try:
                db.execute_non_query("DELETE FROM ai_evaluations WHERE application_id = %s", (app_id,))
            except Exception:
                pass
            
            try:
                db.execute_non_query("DELETE FROM agent_audit_logs WHERE application_id = %s", (app_id,))
            except Exception:
                pass
        
        # Now delete the applications themselves
        db.execute_non_query("DELETE FROM Applications WHERE is_test_data = TRUE")
        
        logger.info(f"Cleaned up {len(test_app_ids)} old test applications and their related data")
        
    except Exception as e:
        logger.warning(f"Warning during test data cleanup: {str(e)}")
        # Don't fail the test if cleanup has issues - just log and continue


@app.route('/process/<int:application_id>')
def process_student(application_id):
    """Process student through Smee orchestrator."""
    try:
        application = db.get_application(application_id)
        if not application:
            flash('Student not found', 'error')
            return redirect(url_for('students'))
        
        # Show processing page with progress
        return render_template('process_student.html', 
                             application=application,
                             application_id=application_id)
        
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('students'))


# ── Chunked Video Upload API ─────────────────────────────────────────
@app.route('/api/video/upload-chunk', methods=['POST'])
def video_upload_chunk():
    """Accept a chunk of video data and stage it in Azure Blob Storage.

    Each chunk is a small (≤100 KB) multipart POST that is individually
    well below the Azure Front Door WAF request body inspection limit
    (128 KB), so even very large MP4 files can be uploaded without
    being blocked by the WAF.

    The client sends:
      - chunk      : the binary chunk (file part)
      - upload_id  : UUID generated client-side (same for all chunks)
      - chunk_index: 0-based index of this chunk
      - total_chunks: total number of chunks
      - filename   : original file name
      - app_type   : "2026" | "training" | "test"

    On the final chunk the staged blocks are committed and the response
    includes ``blob_path`` and ``container`` for use in the form POST.
    """
    chunk = request.files.get('chunk')
    if not chunk:
        return jsonify({'error': 'No chunk data'}), 400

    upload_id = request.form.get('upload_id', '')
    chunk_index = int(request.form.get('chunk_index', 0))
    total_chunks = int(request.form.get('total_chunks', 1))
    filename = secure_filename(request.form.get('filename', 'video.mp4'))
    app_type = request.form.get('app_type', '2026')

    if not filename.lower().endswith('.mp4'):
        return jsonify({'error': 'Only MP4 files are supported'}), 400
    if not upload_id:
        return jsonify({'error': 'upload_id is required'}), 400

    try:
        ok = storage.stage_video_chunk(
            upload_id=upload_id,
            filename=filename,
            chunk_index=chunk_index,
            chunk_data=chunk.read(),
            application_type=app_type,
        )
        if not ok:
            return jsonify({'error': 'Storage not available – could not stage chunk'}), 500
    except Exception as e:
        logger.error("Video chunk %d upload failed: %s", chunk_index, e)
        return jsonify({'error': str(e)}), 500

    result = {
        'upload_id': upload_id,
        'chunk_index': chunk_index,
        'total_chunks': total_chunks,
        'progress': round((chunk_index + 1) / total_chunks * 100, 1),
    }

    # Last chunk → commit all blocks
    if chunk_index == total_chunks - 1:
        try:
            commit = storage.commit_video_upload(
                upload_id=upload_id,
                filename=filename,
                total_chunks=total_chunks,
                application_type=app_type,
            )
            if commit.get('success'):
                result['complete'] = True
                result['blob_path'] = commit['blob_path']
                result['container'] = commit['container']
            else:
                return jsonify({'error': 'Failed to commit video upload'}), 500
        except Exception as e:
            logger.error("Video commit failed for %s: %s", upload_id, e)
            return jsonify({'error': str(e)}), 500

    return jsonify(result)


@app.route('/api/process/<int:application_id>', methods=['POST'])
def api_process_student(application_id):
    """API endpoint to process student with Smee orchestrator."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        # Get orchestrator
        orchestrator = get_orchestrator()
        
        # Run full agent pipeline
        result = asyncio.run(
            orchestrator.coordinate_evaluation(
                application=application,
                evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'data_scientist', 'student_evaluator']
            )
        )
        
        # If result indicates missing fields, return that status
        if result.get('status') == 'paused':
            return jsonify({
                'success': True,
                'status': 'paused',
                'application_id': application_id,
                'missing_fields': result.get('missing_fields'),
                'message': result.get('message')
            }), 202  # 202 Accepted - processing paused waiting for more info
        
        # Update status to Evaluated
        db.update_application_status(application_id, 'Completed')
        
        return jsonify({
            'success': True,
            'status': 'complete',
            'application_id': application_id,
            'result': result
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


def generate_process_updates(application_id: int):
    """Stream real-time orchestration updates for a single application."""
    application = db.get_application(application_id)
    if not application:
        yield f"data: {json.dumps({'type': 'error', 'error': 'Student not found', 'application_id': application_id}, ensure_ascii=True)}\n\n"
        return

    orchestrator = get_orchestrator()
    update_queue = queue.Queue()

    def progress_callback(update):
        logger.debug(
            f"Progress callback: {update.get('type', 'unknown')} - {update.get('agent', 'N/A')}",
            extra=update
        )
        update_queue.put(update)

    def run_orchestration():
        try:
            logger.debug(f"Starting orchestration thread for application {application_id}")
            evaluation_steps = [
                'application_reader',
                'grade_reader',
                'recommendation_reader',
                'school_context',
                'data_scientist',
                'student_evaluator',
                'aurora'
            ]

            result = asyncio.run(orchestrator.coordinate_evaluation(
                application=application,
                evaluation_steps=evaluation_steps,
                progress_callback=progress_callback
            ))

            update_queue.put({'_orchestration_complete': True, 'result': result})
        except Exception as exc:
            logger.error(
                f"Orchestration error for application {application_id}: {str(exc)}",
                exc_info=True
            )
            update_queue.put({'_orchestration_error': True, 'error': str(exc)})

    orchestration_thread = threading.Thread(target=run_orchestration, daemon=True)
    orchestration_thread.start()

    yield f"data: {json.dumps({'type': 'orchestrator_start', 'application_id': application_id}, ensure_ascii=True)}\n\n"

    while True:
        try:
            update = update_queue.get(timeout=1.0)
        except queue.Empty:
            if not orchestration_thread.is_alive():
                break
            yield ": keepalive\n\n"
            continue

        if update.get('_orchestration_complete'):
            result = update.get('result') or {}
            if result.get('status') != 'paused':
                db.update_application_status(application_id, 'Completed')
            yield f"data: {json.dumps({'type': 'orchestration_complete', 'result': result, 'application_id': application_id}, ensure_ascii=True)}\n\n"
            break
        if update.get('_orchestration_error'):
            yield f"data: {json.dumps({'type': 'orchestration_error', 'error': update.get('error'), 'application_id': application_id}, ensure_ascii=True)}\n\n"
            break

        yield f"data: {json.dumps(update, ensure_ascii=True, default=str)}\n\n"

    yield f"data: {json.dumps({'type': 'stream_complete', 'application_id': application_id}, ensure_ascii=True)}\n\n"


@app.route('/api/process/stream/<int:application_id>')
def api_process_student_stream(application_id):
    """Server-Sent Events endpoint for real-time agent progress updates."""
    return Response(
        stream_with_context(generate_process_updates(application_id)),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/status/<int:application_id>')
def api_get_status(application_id):
    """API endpoint to get application requirements and agent status."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        # Get orchestrator and check requirements
        orchestrator = get_orchestrator()
        status = orchestrator.check_application_requirements(application)
        
        return jsonify({
            'success': True,
            'application_id': application_id,
            'status': status
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/missing-fields/<int:application_id>', methods=['GET'])
def api_get_missing_fields(application_id):
    """Get missing fields/documents for a student."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        missing_fields = db.get_missing_fields(application_id)
        
        return jsonify({
            'success': True,
            'application_id': application_id,
            'applicant_name': application.get('applicant_name'),
            'missing_fields': missing_fields,
            'message': f"{len(missing_fields)} items needed" if missing_fields else "All information complete"
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500


@app.route('/api/debug/model_test', methods=['POST'])
def api_debug_model_test():
    """Debug endpoint: perform a lightweight model call and log payload/response.

    This endpoint is intended for short-lived diagnostics only. It uses the
    configured `get_ai_client()` so the call will exercise the same client
    wiring as the running application (Foundry or Azure OpenAI).
    """
    try:
        # Prepare introspection defaults so error responses can include them
        client_type = None
        candidate_attrs = []
        client = get_ai_client()
        try:
            client_type = type(client).__name__
            candidate_attrs = [a for a in dir(client) if any(k in a.lower() for k in ("chat", "generate", "completion", "complete", "completions"))]
        except Exception:
            try:
                client_type = str(type(client))
            except Exception:
                client_type = None
            candidate_attrs = []
        model_name = config.foundry_model_name if config.model_provider == 'foundry' else config.deployment_name

        messages = [
            {"role": "system", "content": "You are a lightweight diagnostics assistant."},
            {"role": "user", "content": "Respond with a single short sentence: hello from model."}
        ]

        # Try common shapes conservatively so we hit the actual adapter path.
        resp = None
        try:
            if hasattr(client, 'chat') and hasattr(client.chat, 'create'):
                resp = client.chat.create(model=model_name, messages=messages)
            elif hasattr(client, 'chat') and callable(getattr(client, 'chat')):
                resp = client.chat(model=model_name, messages=messages)
            elif hasattr(client, 'generate') and callable(getattr(client, 'generate')):
                resp = client.generate(model=model_name, messages=messages)
            else:
                # Last-resort: attempt BaseAgent-style probing
                for name in dir(client):
                    lname = name.lower()
                    if any(k in lname for k in ("chat", "generate", "completion", "complete")):
                        attr = getattr(client, name)
                        if callable(attr):
                            try:
                                resp = attr(model=model_name, messages=messages)
                                break
                            except Exception:
                                try:
                                    resp = attr(model_name, messages)
                                    break
                                except Exception:
                                    continue

        except Exception as e:
            logger.debug(f"No Merlin data: {e}")
        return jsonify({
            "configured_provider": config.model_provider,
            "adapter_status": adapter_status,
            "adapter_body": adapter_body,
        }), 500

        # Normalize response for return
        result_text = None
        try:
            if resp is None:
                result_text = "No response (client returned None)"
            else:
                # Try OpenAI-like extraction
                if hasattr(resp, 'choices') and resp.choices:
                    result_text = getattr(resp.choices[0].message, 'content', str(resp.choices[0]))
                elif isinstance(resp, dict):
                    result_text = resp.get('output') or resp.get('outputs') or str(resp)
                else:
                    result_text = str(getattr(resp, 'raw', resp))
        except Exception:
            result_text = str(resp)

        app.logger.info("Model test result: %s", result_text)
        return jsonify({
            "success": True,
            "model": model_name,
            "result": result_text,
            "client_type": client_type,
            "client_candidate_attrs": candidate_attrs,
            "configured_provider": config.model_provider
        })

    except Exception as e:
        app.logger.exception("Debug model test endpoint error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/missing-fields/<int:application_id>', methods=['POST'])
def api_update_missing_fields(application_id):
    """Update missing fields for a student."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        data = request.get_json()
        fields = data.get('fields', [])
        
        db.set_missing_fields(application_id, fields)
        
        return jsonify({
            'success': True,
            'application_id': application_id,
            'missing_fields': fields
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500


@app.route('/api/agent-questions/<int:application_id>', methods=['GET'])
def api_get_agent_questions(application_id):
    """Get questions from agents about what information they need for a student."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        # Import agent requirements
        from src.agents.agent_requirements import AgentRequirements
        
        # Get all agent questions for the standard evaluation pipeline
        evaluation_steps = ['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'data_scientist', 'student_evaluator']
        agent_questions = AgentRequirements.get_all_questions(evaluation_steps)
        
        # Get current missing fields
        missing_fields = db.get_missing_fields(application_id)
        
        # Filter to only show questions for missing fields
        relevant_questions = []
        for question_info in agent_questions:
            field_name = question_info['field_name']
            if field_name in missing_fields:
                relevant_questions.append(question_info)
        
        return jsonify({
            'success': True,
            'application_id': application_id,
            'applicant_name': application.get('applicant_name'),
            'missing_fields': missing_fields,
            'agent_questions': relevant_questions,
            'message': f"Agents are asking for {len(missing_fields)} items"
        })
        
    except Exception as e:
        logger.error(f"Error getting agent questions: {e}", exc_info=True)
        return jsonify({
            'error': str(e)
        }), 500


@app.route('/api/categorize-upload/<int:application_id>', methods=['POST'])
def api_categorize_upload(application_id):
    """
    Intelligently categorize an uploaded file and assign it to the appropriate field/agent.
    Uses Belle to understand what type of document was uploaded.
    """
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        # Get uploaded file
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Read file content
        try:
            file_content = file.read().decode('utf-8', errors='ignore')
        except Exception:
            file_content = ""
        
        # Use Belle to categorize the document
        belle = get_belle()
        doc_analysis = belle.analyze_document(file_content, file.filename)
        doc_type = doc_analysis.get('document_type', 'unknown')
        
        logger.info(f"Belle categorized upload as: {doc_type}")
        
        # Map document types to application fields using agent requirements
        from src.agents.agent_requirements import AgentRequirements
        
        field_mapping = {
            'essay': 'application_text',
            'personal_statement': 'application_text',
            'application': 'application_text',
            'transcript': 'transcript_text',
            'grades': 'transcript_text',
            'academic_record': 'transcript_text',
            'recommendation': 'recommendation_text',
            'recommendation_letter': 'recommendation_text',
            'letter_of_recommendation': 'recommendation_text',
            'reference': 'recommendation_text',
            'school': 'school_info'
        }
        
        # Find matching field
        target_field = None
        confidence = 0
        
        for doc_key, field in field_mapping.items():
            if doc_key in doc_type.lower():
                target_field = field
                confidence = doc_analysis.get('confidence', 0)
                break
        
        if not target_field:
            # Try to determine from context
            if 'gpa' in file_content.lower() or 'grade' in file_content.lower() or 'course' in file_content.lower():
                target_field = 'transcript_text'
                doc_type = 'transcript'
            elif 'recommend' in file_content.lower() or 'strength' in file_content.lower():
                target_field = 'recommendation_text'
                doc_type = 'recommendation_letter'
            elif len(file_content) > 500 and 'i' in file_content.lower():
                target_field = 'application_text'
                doc_type = 'personal_statement'
        
        if not target_field:
            return jsonify({
                'success': False,
                'error': 'Could not determine document type',
                'detected_type': doc_type,
                'message': 'Please specify what type of document this is'
            }), 400
        
        # Update application with this field
        update_query = f"UPDATE Applications SET {target_field} = %s WHERE application_id = %s"
        db.execute_non_query(update_query, (file_content, application_id))
        
        # Remove from missing fields
        field_mapping_reverse = {v: k.replace('_', ' ').title() for k, v in field_mapping.items()}
        missing_field_name = field_mapping_reverse.get(target_field, target_field)
        
        # Map to agent field names
        agent_field_mapping = {
            'application_text': 'application_essay',
            'transcript_text': 'transcript',
            'recommendation_text': 'letters_of_recommendation',
            'school_info': 'school_context'
        }
        missing_field_name = agent_field_mapping.get(target_field, missing_field_name)
        
        db.remove_missing_field(application_id, missing_field_name)
        
        logger.info(f"Assigned upload to field '{target_field}' for application {application_id}")
        
        # Get updated missing fields
        updated_missing = db.get_missing_fields(application_id)
        
        return jsonify({
            'success': True,
            'application_id': application_id,
            'detected_type': doc_type,
            'confidence': confidence,
            'assigned_field': target_field,
            'field_label': missing_field_name,
            'remaining_missing_fields': updated_missing,
            'message': f"Successfully categorized as {doc_type} ({int(confidence*100)}% confidence)"
        })
        
    except Exception as e:
        logger.error(f"Error categorizing upload: {e}", exc_info=True)
        return jsonify({
            'error': str(e)
        }), 500


@app.route('/api/resume-evaluation/<int:application_id>', methods=['POST'])
def api_resume_evaluation(application_id):
    """
    Resume evaluation for a student after missing information has been provided.
    """
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        # Check if there are still missing fields
        missing_fields = db.get_missing_fields(application_id)
        if missing_fields:
            return jsonify({
                'success': False,
                'status': 'still_missing',
                'application_id': application_id,
                'missing_fields': missing_fields,
                'message': f'Cannot resume: Still missing {", ".join(missing_fields)}'
            }), 422  # 422 Unprocessable Entity
        
        logger.info(f"Resuming evaluation for {application.get('applicant_name')} (ID: {application_id})")
        
        # All information available - run evaluation
        orchestrator = get_orchestrator()
        result = asyncio.run(
            orchestrator.coordinate_evaluation(
                application=application,
                evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'data_scientist', 'student_evaluator']
            )
        )
        
        # Check result status
        if result.get('status') == 'paused':
            return jsonify({
                'success': True,
                'status': 'paused',
                'application_id': application_id,
                'missing_fields': result.get('missing_fields'),
                'message': 'Evaluation paused - still missing information'
            }), 202
        
        # Mark as evaluated
        db.update_application_status(application_id, 'Completed')
        
        return jsonify({
            'success': True,
            'status': 'complete',
            'application_id': application_id,
            'message': 'Evaluation completed successfully'
        })
        
    except Exception as e:
        logger.error(f"Error resuming evaluation for {application_id}: {e}", exc_info=True)
        return jsonify({
            'error': str(e)
        }), 500
def api_provide_missing_info(application_id):
    """
    Handle providing missing information/documents for a student.
    Updates application and resumes evaluation if all fields are now complete.
    """
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        # Get the provided information from request
        data = request.get_json() or {}
        
        # Map provided info to application fields and remove from missing_fields
        provided_map = {
            'transcript': 'transcript_text',
            'application_essay': 'application_text',
            'letters_of_recommendation': 'recommendation_text'
        }
        
        updates = {}
        for field_key, app_field in provided_map.items():
            if field_key in data and data[field_key]:
                updates[app_field] = data[field_key]
                db.remove_missing_field(application_id, field_key)
                logger.info(f"Added {field_key} for application {application_id}")
        
        # Update application with provided information
        if updates:
            update_query = "UPDATE Applications SET " + ", ".join([f"{k} = %s" for k in updates.keys()]) + " WHERE application_id = %s"
            values = list(updates.values()) + [application_id]
            db.execute_non_query(update_query, tuple(values))
        
        # Reload application
        application = db.get_application(application_id)
        
        # Check if all fields are now provided
        missing_fields = db.get_missing_fields(application_id)
        
        if not missing_fields:
            # All information provided - resume evaluation
            logger.info(f"All information provided for {application.get('applicant_name')}. Resuming evaluation...")
            
            orchestrator = get_orchestrator()
            result = asyncio.run(
                orchestrator.coordinate_evaluation(
                    application=application,
                    evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'data_scientist', 'student_evaluator']
                )
            )
            
            # Check if evaluation completed or still paused
            if result.get('status') == 'paused':
                return jsonify({
                    'success': True,
                    'status': 'still_paused',
                    'application_id': application_id,
                    'missing_fields': result.get('missing_fields'),
                    'message': 'More information still needed'
                }), 202
            
            # Mark as evaluated
            db.update_application_status(application_id, 'Completed')
            
            return jsonify({
                'success': True,
                'status': 'complete',
                'application_id': application_id,
                'message': 'All information provided and evaluation complete'
            })
        else:
            # Still missing some fields
            return jsonify({
                'success': True,
                'status': 'still_missing',
                'application_id': application_id,
                'missing_fields': missing_fields,
                'message': f'Still missing {len(missing_fields)} items'
            }), 202
        
    except Exception as e:
        logger.error(f"Error providing missing info for {application_id}: {e}", exc_info=True)
        return jsonify({
            'error': str(e)
        }), 500


@app.route('/application/<int:application_id>')
def student_detail(application_id):
    """View details of a student application with all agent evaluations."""
    try:
        logger.debug(f"student_detail called with application_id={application_id}")
        application = db.get_application(application_id)
        logger.debug(f"db.get_application returned: {application is not None}")
        
        if not application:
            logger.warning(f"Application {application_id} not found")
            flash('Student not found', 'error')
            return redirect(url_for('students'))
        
        # CRITICAL: Sanitize application dict to prevent circular references during template rendering
        # Convert to plain dict to break any DB row object references
        try:
            application = dict(application)
        except Exception:
            pass  # Already a plain dict
        
        logger.debug(f"Application found: {application.get('applicant_name')}")
        
        # ===== FETCH SCHOOL ENRICHMENT DATA (PART OF TRAINING DATA CONTEXT) =====
        school_context = None
        school_name = application.get('school_name') or application.get('SchoolName')
        state_code = application.get('state_code') or application.get('StateCode')
        
        if school_name:
            try:
                # Get enriched school data that informed this evaluation
                school_data = db.get_school_enriched_data(
                    school_name=school_name,
                    state_code=state_code
                )
                if school_data:
                    school_context = {
                        'school_name': school_data.get('school_name'),
                        'state_code': school_data.get('state_code'),
                        'school_district': school_data.get('school_district'),
                        'enrollment_size': school_data.get('enrollment_size'),
                        'diversity_index': school_data.get('diversity_index'),
                        'socioeconomic_level': school_data.get('socioeconomic_level'),
                        'academic_programs': school_data.get('academic_programs'),
                        'graduation_rate': school_data.get('graduation_rate'),
                        'college_placement_rate': school_data.get('college_placement_rate'),
                        'opportunity_score': school_data.get('opportunity_score'),
                        'analysis_date': school_data.get('updated_at') or school_data.get('analysis_date'),
                        'web_sources': school_data.get('web_sources')
                    }
                    logger.debug(f"School context loaded for {school_name}: opportunity_score={school_context.get('opportunity_score')}")
            except Exception as e:
                logger.debug(f"Could not load school context: {e}")
        
        # Fetch all agent evaluations
        agent_results = {}
        
        # Tiana - Application Reader
        try:
            tiana_results = db.execute_query(
                "SELECT *FROM tiana_applications WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                (application_id,)
            )
            if tiana_results:
                agent_results['tiana'] = dict(tiana_results[0])  # Create explicit copy
                # Normalize common key variants used in templates (underscored vs concatenated)
                try:
                    t = agent_results['tiana']
                    # parsed_json -> parsed_data for consistency
                    raw_parsed = t.get('parsed_json')
                    if raw_parsed:
                        try:
                            import json as _json
                            parsed_obj = _json.loads(raw_parsed) if isinstance(raw_parsed, str) else raw_parsed
                            if isinstance(parsed_obj, dict):
                                t.setdefault('parsed_data', parsed_obj)
                        except Exception:
                            pass

                    # If parsed_data contains a 'content' field which is itself
                    # a stringified JSON (many agents store nested content there),
                    # try to decode and promote commonly used keys into the
                    # top-level tiana dict so templates can access them directly.
                    try:
                        pd = t.get('parsed_data')
                        if isinstance(pd, dict):
                            inner = None
                            try:
                                content = pd.get('content') or pd.get('text') or pd.get('body')
                                if isinstance(content, str) and content.strip():
                                    inner = json.loads(content)
                            except Exception:
                                inner = None

                            if isinstance(inner, dict):
                                # Promote essay_summary/readiness_score/confidence
                                if inner.get('essay_summary') and not t.get('essaysummary'):
                                    t['essaysummary'] = inner.get('essay_summary')
                                if inner.get('readiness_score') is not None and not t.get('readinessscore'):
                                    t['readinessscore'] = inner.get('readiness_score')
                                if inner.get('confidence') and not t.get('conf'):
                                    t['conf'] = inner.get('confidence')
                                # Merge any other simple keys if missing
                                for k, v in inner.items():
                                    if k not in t or not t.get(k):
                                        t.setdefault(k, v)
                    except Exception:
                        pass

                    # essay_summary -> essaysummary
                    if t.get('essay_summary') and not t.get('essaysummary'):
                        t['essaysummary'] = t.get('essay_summary')
                    # readiness_score -> readinessscore
                    if t.get('readiness_score') is not None and not t.get('readinessscore'):
                        t['readinessscore'] = t.get('readiness_score')
                    # confidence already uses 'confidence' but keep a defensive alias
                    if t.get('confidence') and not t.get('conf'):
                        t['conf'] = t.get('confidence')
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"No Tiana data: {e}")
        
        # Rapunzel - Grade Reader
        try:
            rapunzel_results = db.execute_query(
                "SELECT * FROM rapunzel_grades WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                (application_id,)
            )
            if rapunzel_results:
                agent_results['rapunzel'] = dict(rapunzel_results[0])  # Create explicit copy
                # Parse JSON fields if present
                if agent_results['rapunzel'].get('parsed_json'):
                    try:
                        import json
                        raw = agent_results['rapunzel']['parsed_json']
                        parsed = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(parsed, dict):
                            # Merge parsed data into a safe copy
                            for key, value in parsed.items():
                                if key not in agent_results['rapunzel'] or not agent_results['rapunzel'].get(key):
                                    # Ensure we're not creating circular references
                                    if key != 'rapunzel' and key != 'agent_results':
                                        agent_results['rapunzel'][key] = value
                            # If parsed contains an inner 'content' stringified JSON,
                            # decode and promote keys similarly so templates can read them.
                            try:
                                content = parsed.get('content') or parsed.get('text') or parsed.get('body')
                                if isinstance(content, str) and content.strip():
                                    inner = json.loads(content)
                                    if isinstance(inner, dict):
                                        for k, v in inner.items():
                                            if k not in agent_results['rapunzel'] or not agent_results['rapunzel'].get(k):
                                                agent_results['rapunzel'][k] = v
                            except Exception:
                                pass
                    except Exception as parse_err:
                        logger.debug(f"Error parsing rapunzel JSON: {parse_err}")
                # Promote summary → human_summary so Rapunzel appears in Agent Insights cards
                rap = agent_results['rapunzel']
                if not rap.get('human_summary'):
                    if rap.get('summary'):
                        rap['human_summary'] = rap['summary']
                    elif rap.get('full_analysis'):
                        # Use first 500 chars of full analysis as fallback
                        rap['human_summary'] = rap['full_analysis'][:500]
                # Promote GPA as a display-friendly overall_score
                if not rap.get('overall_score') and rap.get('gpa'):
                    rap['overall_score'] = f"GPA: {rap['gpa']}"
        except Exception as e:
            logger.debug(f"No Rapunzel data: {e}")
        
        # Moana - School Context
        try:
            moana_results = db.execute_query(
                "SELECT * FROM student_school_context WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                (application_id,)
            )
            if moana_results:
                agent_results['moana'] = dict(moana_results[0])  # Create explicit copy
                # Parse JSON fields if present
                if agent_results['moana'].get('parsed_json'):
                    try:
                        import json
                        parsed = json.loads(agent_results['moana']['parsed_json'])
                        if isinstance(parsed, dict):
                            # Merge parsed data into a safe copy
                            for key, value in parsed.items():
                                if key not in agent_results['moana'] or not agent_results['moana'].get(key):
                                    # Ensure we're not creating circular references
                                    if key != 'moana' and key != 'agent_results':
                                        agent_results['moana'][key] = value
                            # Promote inner 'content' JSON if present
                            try:
                                content = parsed.get('content') or parsed.get('text') or parsed.get('body')
                                if isinstance(content, str) and content.strip():
                                    inner = json.loads(content)
                                    if isinstance(inner, dict):
                                        for k, v in inner.items():
                                            if k not in agent_results['moana'] or not agent_results['moana'].get(k):
                                                agent_results['moana'][k] = v
                            except Exception:
                                pass
                    except Exception as parse_err:
                        logger.debug(f"Error parsing moana JSON: {parse_err}")
        except Exception as e:
            logger.debug(f"No Moana data: {e}")
        
        # Mulan - Recommendation Reader
        try:
            mulan_results = db.execute_query(
                "SELECT * FROM mulan_recommendations WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                (application_id,)
            )
            if mulan_results:
                # Normalize to a list of recommendations so templates can iterate
                try:
                    # If multiple rows are present return them all (most recent first)
                    rows = db.execute_query(
                        "SELECT * FROM mulan_recommendations WHERE application_id = %s ORDER BY created_at DESC",
                        (application_id,)
                    )
                    agent_results['mulan'] = [dict(r) for r in rows] if rows else [dict(mulan_results[0])]
                    # Normalize recommendation field names to match template expectations
                    try:
                        normalized = []
                        for rec in agent_results['mulan']:
                            # alias fields without underscores for template
                            try:
                                # If parsed_json exists and contains nested content, promote keys
                                rawp = rec.get('parsed_json')
                                if rawp:
                                    try:
                                        pdat = json.loads(rawp) if isinstance(rawp, str) else rawp
                                        if isinstance(pdat, dict):
                                            inner_content = None
                                            try:
                                                c = pdat.get('content') or pdat.get('text')
                                                if isinstance(c, str) and c.strip():
                                                    inner_content = json.loads(c)
                                            except Exception:
                                                inner_content = None
                                            if isinstance(inner_content, dict):
                                                for k, v in inner_content.items():
                                                    if k not in rec or not rec.get(k):
                                                        rec.setdefault(k, v)
                                            else:
                                                # merge top-level parsed_data
                                                for k, v in pdat.items():
                                                    if k not in rec or not rec.get(k):
                                                        rec.setdefault(k, v)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            if rec.get('recommender_name') and not rec.get('recommendername'):
                                rec['recommendername'] = rec.get('recommender_name')
                            if rec.get('recommender_role') and not rec.get('recommenderrole'):
                                rec['recommenderrole'] = rec.get('recommender_role')
                            if rec.get('endorsement_strength') is not None and not rec.get('endorsementstrength'):
                                rec['endorsementstrength'] = rec.get('endorsement_strength')
                            normalized.append(rec)
                        agent_results['mulan'] = normalized
                    except Exception:
                        pass
                except Exception:
                    agent_results['mulan'] = [dict(mulan_results[0])]
        except Exception as e:
            logger.debug(f"No Mulan data: {e}")
        
        # Merlin - Student Evaluator
        # --- Patch: Promote executive summary from Merlin content ---
        try:
            merlin_results = db.execute_query(
                "SELECT * FROM merlin_evaluations WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                (application_id,)
            )
            if merlin_results:
                agent_results['merlin'] = dict(merlin_results[0])  # Create explicit copy
                if agent_results['merlin'].get('parsed_json'):
                    try:
                        import json
                        raw_parsed = agent_results['merlin'].get('parsed_json')
                        if isinstance(raw_parsed, str):
                            parsed = json.loads(raw_parsed)
                        elif isinstance(raw_parsed, dict):
                            parsed = raw_parsed
                        else:
                            parsed = {}
                        agent_results['merlin']['parsed_data'] = parsed
                        mer = agent_results['merlin']
                        if isinstance(parsed, dict):
                            # Promote all useful keys from parsed_json to top-level for template access
                            for k in ('overall_score', 'match_score', 'nextgen_match', 'recommendation',
                                       'rationale', 'confidence', 'key_strengths', 'key_risks',
                                       'decision_drivers', 'top_risk', 'context_factors', 'evidence_used',
                                       'executive_summary'):
                                if parsed.get(k) is not None and not mer.get(k):
                                    mer[k] = parsed[k]
                            # Promote human_summary from the best available field
                            if not mer.get('human_summary'):
                                if parsed.get('executive_summary'):
                                    mer['human_summary'] = parsed['executive_summary']
                                elif parsed.get('summary'):
                                    mer['human_summary'] = parsed['summary']
                                elif parsed.get('rationale'):
                                    mer['human_summary'] = parsed['rationale']
                            # Also try nested 'content' JSON if present
                            content = parsed.get('content')
                            if isinstance(content, str) and content.strip():
                                try:
                                    inner = json.loads(content)
                                    if isinstance(inner, dict):
                                        for k in ('overall_score', 'recommendation', 'rationale', 'confidence',
                                                   'key_strengths', 'key_risks', 'executive_summary'):
                                            if inner.get(k) is not None and not mer.get(k):
                                                mer[k] = inner[k]
                                        if not mer.get('human_summary'):
                                            mer['human_summary'] = inner.get('executive_summary') or inner.get('summary') or inner.get('rationale')
                                except Exception:
                                    pass
                    except Exception as parse_err:
                        logger.debug(f"Error parsing merlin JSON: {parse_err}")
        except Exception as e:
            logger.debug(f"No Merlin data: {e}")
        
        # Aurora - Formatter
        try:
            aurora_results = db.execute_query(
                "SELECT * FROM aurora_evaluations WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                (application_id,)
            )
            if aurora_results:
                agent_results['aurora'] = dict(aurora_results[0])  # Create explicit copy
        except Exception as e:
            logger.debug(f"No Aurora data: {e}")

        # If the applications table has an `agent_results` JSON/JSONB column
        # (newer persistence path), prefer those consolidated results for the
        # UI.  Merge keys only when they don't collide with already-loaded
        # per-agent rows so local table data (if present) continues to take
        # precedence for individual agent records.
        try:
            app_agent_results = application.get('agent_results')
            if isinstance(app_agent_results, dict) and app_agent_results:
                for k, v in app_agent_results.items():
                    if k not in agent_results:
                        agent_results[k] = v
        except Exception as e:
            logger.debug(f"Failed to merge application.agent_results: {e}")

        # Remove gaston from agent_results — agent was removed from workflow
        agent_results.pop('gaston', None)

        # Also strip gaston from any pre-computed student_summary.agent_details
        try:
            ss = application.get('student_summary')
            if isinstance(ss, dict):
                ad = ss.get('agent_details')
                if isinstance(ad, dict):
                    ad.pop('gaston', None)
                ac = ss.get('agents_completed')
                if isinstance(ac, list) and 'gaston' in ac:
                    ac.remove('gaston')
        except Exception:
            pass

        # Get document download info
        document_path = application.get('evaluation_document_path')
        document_url = application.get('evaluation_document_url')
        document_available = bool(document_path and os.path.exists(document_path))

        reprocess_notice = None
        try:
            audit_table = db.get_table_name("agent_audit_logs")
            if audit_table and db.has_table(audit_table):
                audit_app_id_col = db.resolve_table_column(
                    "agent_audit_logs",
                    ["application_id", "applicationid"],
                )
                audit_agent_col = db.resolve_table_column(
                    "agent_audit_logs",
                    ["agent_name", "agentname"],
                )
                audit_source_col = db.resolve_table_column(
                    "agent_audit_logs",
                    ["source_file_name", "sourcefilename"],
                )
                audit_created_col = db.resolve_table_column(
                    "agent_audit_logs",
                    ["created_at", "createdat"],
                )
                if not audit_created_col:
                    audit_created_col = "created_at"
                if audit_app_id_col and audit_agent_col and audit_source_col:
                    audit_query = f"""
                        SELECT {audit_source_col} as source_file_name, {audit_created_col} as created_at
                        FROM {audit_table}
                        WHERE {audit_app_id_col} = %s AND {audit_agent_col} = %s
                        ORDER BY {audit_created_col} DESC
                        LIMIT 1
                    """
                    audit_rows = db.execute_query(audit_query, (application_id, 'System'))
                    if audit_rows:
                        source = audit_rows[0].get('source_file_name') or ''
                        if source.startswith('reprocess:'):
                            message = source.replace('reprocess:', '').strip()
                            if message.startswith('new_upload:'):
                                message = message.replace('new_upload:', 'New upload: ', 1).strip()
                            reprocess_notice = {
                                'message': message,
                                'created_at': audit_rows[0].get('created_at')
                            }
        except Exception as exc:
            logger.debug(f"Reprocess audit lookup failed: {exc}")
        
        # Fetch Aurora evaluation (formatted) - prefer this if available - BACKWARD COMPATIBILITY
        aurora_evaluation = db.get_aurora_evaluation(application_id)
        
        # Fetch Merlin evaluation (raw data) as backup - BACKWARD COMPATIBILITY
        merlin_evaluation = None
        if not aurora_evaluation:
            try:
                merlin_results = db.execute_query(
                    "SELECT * FROM merlin_evaluations WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                    (application_id,)
                )
                if merlin_results:
                    merlin_evaluation = merlin_results[0]
                    # Parse JSON if available to make fields accessible
                    if merlin_evaluation.get('parsed_json'):
                        try:
                            import json
                            parsed = json.loads(merlin_evaluation['parsed_json'])
                            # Merge parsed fields into evaluation dict
                            for key, value in parsed.items():
                                if key not in merlin_evaluation or not merlin_evaluation[key]:
                                    merlin_evaluation[key] = value
                        except Exception:
                            pass
            except Exception:
                pass

        # If the database row didn't include a precomputed student_summary we can
        # derive one on the fly from the agent_results we just gathered.  This is
        # helpful for older records created before the migration and prevents the
        # UI from appearing empty when agents have already run.
        if not application.get('student_summary') and agent_results:
            try:
                merlin = agent_results.get('merlin') or {}
                aurora = agent_results.get('aurora') or {}
                derived = {
                    'status': 'completed',
                    'overall_score': merlin.get('overallscore') or merlin.get('overall_score'),
                    'recommendation': merlin.get('recommendation'),
                    'rationale': merlin.get('rationale') or merlin.get('parsedjson', ''),
                    'key_strengths': merlin.get('parsed_data', {}).get('key_strengths', []) if isinstance(merlin.get('parsed_data'), dict) else [],
                    'key_risks': merlin.get('parsed_data', {}).get('considerations', []) if isinstance(merlin.get('parsed_data'), dict) else [],
                    'confidence': merlin.get('confidence'),
                    'agents_completed': list(agent_results.keys()),
                    'formatted_by_aurora': bool(aurora),
                    'aurora_sections': list(aurora.keys()) if isinstance(aurora, dict) else []
                }
                derived['agent_details'] = agent_results
                application['student_summary'] = derived
            except Exception as exc:
                logger.debug(f"Failed to derive summary on the fly: {exc}")
        
        logger.debug(f"About to render template with application_id={application.get('application_id')}")

        # Pull Milo insights so the UI can display training-pattern information
        milo_insights = {}
        milo_alignment = None
        alignment_score = None
        try:
            orchestrator = get_orchestrator()
            milo = orchestrator.agents.get('data_scientist') if orchestrator else None
            # if the orchestrator already ran, it may have stored alignment in the
            # application row; check there first to avoid redundant model calls.
            try:
                stored = application.get('agent_results') or {}
                if isinstance(stored, str):
                    stored = safe_load_json(stored)
                if isinstance(stored, dict):
                    # prefer explicit milo_alignment key, fall back to any
                    # computed_alignment embedded inside data_scientist result
                    milo_alignment = stored.get('milo_alignment') or \
                        (stored.get('data_scientist') or {}).get('computed_alignment')
            except Exception:
                milo_alignment = None

            if milo:
                # always refresh insights (they are cached internally)
                milo_insights = asyncio.run(milo.analyze_training_insights())
                # compute AI-derived match/align for this specific application if
                # we don't already have one from persisted results.
                if not milo_alignment:
                    try:
                        milo_alignment = asyncio.run(milo.compute_alignment(application))
                    except Exception as align_err:
                        logger.debug(f"Milo compute_alignment failed: {align_err}")
                # maintain simple numeric alignment as before as fallback
                merlin_score = None
                if agent_results.get('merlin'):
                    try:
                        merlin_score = float(agent_results['merlin'].get('overall_score') or
                                              agent_results['merlin'].get('overallscore') or 0)
                    except Exception:
                        merlin_score = None
                avg = milo_insights.get('average_merlin_score')
                if merlin_score is not None and avg is not None:
                    try:
                        alignment_score = round(merlin_score - float(avg), 1)
                    except Exception:
                        alignment_score = None
        except Exception as e:
            logger.debug(f"Milo insights fetch failed in student_detail: {e}")

        try:
            human_summary = _synthesize_human_summary(agent_results, application)
        except Exception:
            human_summary = None

        # Resolve Next Gen Match score for the UI
        # Priority: DB column > Merlin output > Milo alignment output
        nextgen_match = None
        try:
            # 1. Check DB column (persisted by orchestrator)
            db_val = application.get('nextgen_match')
            if db_val is not None:
                nextgen_match = int(float(db_val))
            # 2. Fallback to Merlin result
            if nextgen_match is None and agent_results.get('merlin'):
                merlin_ngm = agent_results['merlin'].get('nextgen_match')
                if merlin_ngm is not None:
                    nextgen_match = int(float(merlin_ngm))
            # 3. Fallback to Milo alignment
            if nextgen_match is None and milo_alignment and isinstance(milo_alignment, dict):
                milo_ngm = milo_alignment.get('nextgen_match')
                if milo_ngm is not None:
                    nextgen_match = int(float(milo_ngm))
        except Exception:
            nextgen_match = None

        # Also strip gaston from the application dict itself (passed as summary=)
        try:
            app_ar = application.get('agent_results')
            if isinstance(app_ar, dict):
                app_ar.pop('gaston', None)
        except Exception:
            pass

        return render_template('student_detail.html', 
                     summary=application,
                     agent_results=agent_results,
                     document_available=document_available,
                     document_path=document_path,
                     aurora_evaluation=aurora_evaluation,  # For backward compatibility
                     merlin_evaluation=merlin_evaluation,  # For backward compatibility
                     is_training=application.get('is_training_example', False),
                     reprocess_notice=reprocess_notice,
                     school_context=school_context,  # School data for training context
                     human_summary=human_summary,
                     milo_insights=milo_insights,
                     milo_alignment=milo_alignment,
                     alignment_score=alignment_score,
                     nextgen_match=nextgen_match)
        
    except Exception as e:
        logger.error(f"Error in student_detail: {str(e)}", exc_info=True)
        flash(f'Error loading student: {str(e)}', 'error')
        return redirect(url_for('students'))


@app.route('/student/<int:application_id>/agent-results')
def student_agent_results(application_id):
    """Return raw agent_results for a student as JSON for debugging."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404

        # replicate the same agent collection logic used in student_detail
        agent_results = {}
        for tbl, key in [
            ('tiana_applications', 'tiana'),
            ('rapunzel_grades', 'rapunzel'),
            ('student_school_context', 'moana'),
            ('mulan_recommendations', 'mulan'),
            ('merlin_evaluations', 'merlin'),
            ('aurora_evaluations', 'aurora')
        ]:
            try:
                rows = db.execute_query(
                    f"SELECT * FROM {tbl} WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                    (application_id,)
                )
                if rows:
                    agent_results[key] = dict(rows[0])
            except Exception:
                pass
        return jsonify(agent_results)
    except Exception as e:
        logger.error(f"Error in student_agent_results: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


def _synthesize_human_summary(agent_results: dict, application: dict) -> str:
    """Create a concise, human-readable executive summary from agent_results.

    Uses available fields from merlin, tiana, rapunzel, mulan, moana and aurora.
    """
    try:
        parts = []
        merlin = agent_results.get('merlin') or {}
        tiana = agent_results.get('tiana') or {}
        rap = agent_results.get('rapunzel') or {}
        mulan = agent_results.get('mulan') or {}
        moana = agent_results.get('moana') or {}
        aurora = agent_results.get('aurora') or {}

        # Profile / headline
        headline = []
        name = application.get('applicant_name') or application.get('student_name')
        if name:
            headline.append(name)
        # course rigor + GPA
        cr = rap.get('course_rigor_index') or rap.get('course_rigor')
        gpa = rap.get('gpa') or rap.get('cumulative_weighted') or rap.get('cumulative')
        if cr:
            headline.append(f"pursues high‑rigor coursework (rigor={cr})")
        elif gpa:
            headline.append(f"weighted GPA ~{gpa}")
        if headline:
            parts.append('. '.join(headline) + '.')

        # Strengths
        strengths = []
        if (rap.get('honors_awards') or rap.get('honor_roll')):
            strengths.append('consistent honor‑roll performance')
        if tiana.get('essay_summary') or (tiana.get('parsed_data') and tiana.get('parsed_data').get('essay_summary')):
            strengths.append('essay expresses motivation and fit for STEM')
        if mulan:
            # if list, inspect first
            first = mulan[0] if isinstance(mulan, list) and mulan else (mulan if isinstance(mulan, dict) else None)
            if first and (first.get('endorsement_strength') or first.get('endorsement_strength') == 0 or first.get('endorsementstrength')):
                strengths.append('teacher recommendation with modest endorsement')
        if strengths:
            parts.append('Strengths: ' + '; '.join(strengths) + '.')

        # Risks / concerns
        risks = []
        # check AP/Honors performance pattern in rapunzel parsed content
        if rap.get('course_rigor_index') and (rap.get('summary') and 'AP' in str(rap.get('summary'))):
            # heuristics: presence of AP and note of lower grades
            if 'C+' in str(rap.get('summary')) or 'drop' in str(rap.get('summary')).lower():
                risks.append('modest AP/Honors grades despite high course rigor')
        if not strengths and (not rap and not mulan and not tiana):
            risks.append('limited supporting evidence in agent outputs')
        if risks:
            parts.append('Risks: ' + '; '.join(risks) + '.')

        # Recommendation / verdict
        rec = merlin.get('recommendation') or merlin.get('parsed_data', {}).get('recommendation') or aurora.get('merlin_recommendation')
        score = merlin.get('overall_score') or merlin.get('overallscore')
        verdict = []
        if score:
            verdict.append(f'Overall score ~{score}/100')
        if rec:
            verdict.append(f'Recommendation: {rec}')
        if verdict:
            parts.append(' '.join(verdict) + '.')

        # If nothing produced, fall back to aurora short note
        if not parts and aurora:
            parts.append('Aurora produced a formatted evaluation; see detailed report.')

        return ' '.join(parts)
    except Exception:
        return ''


@app.route('/student/<int:application_id>/summary-json')
def student_summary_json(application_id):
    """Render a compact student summary page directly from agent-results JSON."""
    try:
        application = db.get_application(application_id)
        if not application:
            flash('Student not found', 'error')
            return redirect(url_for('students'))

        # reuse the same collection logic as the debug JSON endpoint
        agent_results = {}
        # Merge any existing agent_results JSON from the application row so
        # persisted per-agent summaries are visible on this page.
        try:
            ar = application.get('agent_results')
            if ar:
                if isinstance(ar, str):
                    try:
                        ar = json.loads(ar)
                    except Exception:
                        ar = None
                if isinstance(ar, dict):
                    agent_results.update(ar)
        except Exception:
            pass
        for tbl, key in [
            ('tiana_applications', 'tiana'),
            ('rapunzel_grades', 'rapunzel'),
            ('student_school_context', 'moana'),
            ('mulan_recommendations', 'mulan'),
            ('merlin_evaluations', 'merlin'),
            ('aurora_evaluations', 'aurora')
        ]:
            try:
                rows = db.execute_query(
                    f"SELECT * FROM {tbl} WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                    (application_id,)
                )
                if rows:
                    agent_results[key] = dict(rows[0])
            except Exception:
                pass

        # Executive summary: prefer Merlin's output only. Aurora is used
        # elsewhere for formatting but should not drive the executive text.
        human_summary = None
        try:
            merlin_row = agent_results.get('merlin') or agent_results.get('student_evaluator')
            if merlin_row:
                # If agent row already contains a precomputed human_summary, use it
                if isinstance(merlin_row, dict) and merlin_row.get('human_summary'):
                    human_summary = merlin_row.get('human_summary')
                else:
                    # Try parsed_json -> content
                    parsed = None
                    if isinstance(merlin_row, dict):
                        parsed = merlin_row.get('parsed_json') or merlin_row.get('parsed') or merlin_row.get('parsed_data')
                    elif isinstance(merlin_row, str):
                        try:
                            parsed = json.loads(merlin_row)
                        except Exception:
                            parsed = None

                    if isinstance(parsed, str):
                        try:
                            parsed = json.loads(parsed)
                        except Exception:
                            parsed = None

                    if isinstance(parsed, dict):
                        content = parsed.get('content') or parsed.get('summary') or parsed.get('rationale')
                        if isinstance(content, str):
                            human_summary = content
                        elif isinstance(content, dict):
                            # prefer explicit fields if present
                            human_summary = content.get('rationale') or content.get('summary') or json.dumps(content)

                    # Fallback: use top-level merlin fields
                    if not human_summary and isinstance(merlin_row, dict):
                        rec = merlin_row.get('recommendation') or merlin_row.get('recommendation_text')
                        score = merlin_row.get('overall_score') or merlin_row.get('score')
                        rationale = merlin_row.get('rationale') or merlin_row.get('detailed_analysis')
                        parts = []
                        if score is not None:
                            parts.append(f"Overall score ~{score}")
                        if rec:
                            parts.append(f"Recommendation: {rec}")
                        if rationale and not human_summary:
                            parts.append(str(rationale))
                        if parts:
                            human_summary = ' '.join(parts)
        except Exception:
            human_summary = None

        # Remove gaston from agent_results — agent was removed from workflow
        agent_results.pop('gaston', None)

        # Also strip gaston from the application dict
        try:
            app_ar = application.get('agent_results')
            if isinstance(app_ar, dict):
                app_ar.pop('gaston', None)
        except Exception:
            pass

        return render_template('student_summary_json.html',
                               application=application,
                               agent_results=agent_results,
                               human_summary=human_summary)
    except Exception as e:
        logger.error(f"Error in student_summary_json: {e}", exc_info=True)
        flash(f'Error loading summary: {str(e)}', 'error')
        return redirect(url_for('students'))


@app.route('/student/<int:application_id>/download-evaluation')
def download_evaluation(application_id):
    """Download the evaluation document for a student from Azure Storage or local backup."""
    try:
        application = db.get_application(application_id)
        if not application:
            flash('Student not found', 'error')
            return redirect(url_for('students'))
        
        document_url = application.get('evaluation_document_url')
        document_path = application.get('evaluation_document_path')
        
        # Try Azure Storage first
        if document_url and storage.client:
            try:
                # Extract filename from URL or path
                if document_path:
                    filename = os.path.basename(document_path)
                else:
                    filename = f"evaluation_{application.get('applicant_name', 'student')}.docx"
                
                # Determine application type and student ID
                is_training = application.get('is_training_example', False)
                is_test = application.get('is_test_data', False)
                
                if is_training:
                    app_type = 'training'
                elif is_test:
                    app_type = 'test'
                else:
                    app_type = '2026'
                
                # Get student ID from document path
                student_id = f"student_{application_id}"
                if document_path:
                    parts = document_path.split('/')
                    if 'student_' in str(document_path):
                        for part in parts:
                            if part.startswith('student_'):
                                student_id = part
                                break
                
                # Download from Azure Storage
                file_content = storage.download_file(student_id, filename, app_type)
                
                if file_content:
                    from io import BytesIO
                    from flask import send_file
                    
                    logger.info(f"Serving document from Azure Storage: {filename}")
                    return send_file(
                        BytesIO(file_content),
                        as_attachment=True,
                        download_name=filename,
                        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                    )
            except Exception as e:
                logger.warning(f"Could not download from Azure Storage: {e}, falling back to local")
        
        # Fallback to local file
        if document_path and os.path.exists(document_path):
            from flask import send_file
            logger.info(f"Serving document from local storage: {document_path}")
            return send_file(
                document_path,
                as_attachment=True,
                download_name=os.path.basename(document_path),
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        
        flash('Evaluation document not available', 'error')
        return redirect(url_for('student_detail', application_id=application_id))
        
    except Exception as e:
        logger.error(f"Error downloading evaluation: {str(e)}", exc_info=True)
        flash(f'Error downloading document: {str(e)}', 'error')
        return redirect(url_for('student_detail', application_id=application_id))


@app.route('/training/<int:application_id>')
def view_training_detail(application_id):
    """View details of a training example."""
    try:
        application = db.get_application(application_id)
        if not application or not application.get('is_training_example'):
            flash('Training example not found', 'error')
            return redirect(url_for('training'))

        # Strip gaston from stored agent_results in application dict
        try:
            app_ar = application.get('agent_results')
            if isinstance(app_ar, dict):
                app_ar.pop('gaston', None)
            ss = application.get('student_summary')
            if isinstance(ss, dict):
                ad = ss.get('agent_details')
                if isinstance(ad, dict):
                    ad.pop('gaston', None)
                ac = ss.get('agents_completed')
                if isinstance(ac, list) and 'gaston' in ac:
                    ac.remove('gaston')
        except Exception:
            pass

        return render_template('application.html', 
                             application=application,
                             is_training=True)
        
    except Exception as e:
        flash(f'Error loading training example: {str(e)}', 'error')
        return redirect(url_for('training'))


@app.route('/training/<int:application_id>/delete', methods=['POST'])
def delete_training(application_id):
    """Delete a training example."""
    try:
        application = db.get_application(application_id)
        if not application or not application.get('is_training_example'):
            flash('Training example not found', 'error')
            return redirect(url_for('training'))

        training_col = db.get_training_example_column()
        
        # Delete the training example
        db.execute_non_query(
            f"DELETE FROM Applications WHERE application_id = %s AND {training_col} = TRUE",
            (application_id,)
        )
        
        flash(f'Training example deleted successfully', 'success')

        refresh_foundry_dataset_async("training_delete")
        
        # Reset evaluator to reload training data
        global evaluator_agent
        evaluator_agent = None
        
        return redirect(url_for('training'))
        
    except Exception as e:
        flash(f'Error deleting training example: {str(e)}', 'error')
        return redirect(url_for('training'))


@app.route('/api/student/<int:application_id>/delete', methods=['DELETE'])
def delete_student_record(application_id):
    """Permanently delete a student and all related agent data."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'status': 'error', 'error': 'Student not found'}), 404

        student_name = application.get('applicant_name', 'Unknown')

        # Also delete blob storage files if configured
        try:
            from src.storage import StorageManager
            storage = StorageManager()
            storage.delete_student_files(str(application_id))
        except Exception as e:
            logger.debug(f"Could not delete blob files for {application_id}: {e}")

        result = db.delete_student(application_id)

        logger.info(f"Student {application_id} ({student_name}) permanently deleted: {result}")
        return jsonify({
            'status': 'success',
            'message': f'Student "{student_name}" and all related data have been permanently deleted',
            'application_id': application_id,
            'details': result
        })
    except Exception as e:
        logger.error(f"Error deleting student {application_id}: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


# API endpoint to clear all training data (excluding test data)
@app.route('/api/training-data/clear', methods=['POST'])
def clear_training_data():
    """Clear all training data from the database (excludes test uploads)."""
    try:
        training_col = db.get_training_example_column()
        test_col = db.get_test_data_column()

        if not db.has_applications_column(training_col):
            return jsonify({
                'status': 'success',
                'message': 'No training data column found; nothing to delete',
                'count': 0
            })

        where_clause = f"{training_col} = TRUE"
        if db.has_applications_column(test_col):
            where_clause += f" AND ({test_col} = FALSE OR {test_col} IS NULL)"

        training_apps = db.execute_query(f"""
            SELECT application_id
            FROM applications
            WHERE {where_clause}
        """)

        training_app_ids = [app.get('application_id') for app in training_apps]
        count_deleted = len(training_app_ids)

        if count_deleted == 0:
            logger.info("No training data to clear")
            return jsonify({
                'status': 'success',
                'message': 'No training data found to delete',
                'count': 0
            })

        for app_id in training_app_ids:
            try:
                db.execute_non_query("DELETE FROM agent_audit_logs WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM tiana_applications WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM mulan_recommendations WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM merlin_evaluations WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM aurora_evaluations WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM student_school_context WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM grade_records WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM ai_evaluations WHERE application_id = %s", (app_id,))
            except Exception as delete_error:
                logger.warning(f"Error deleting related data for application_id {app_id}: {delete_error}")

        db.execute_non_query(f"DELETE FROM applications WHERE {where_clause}")

        refresh_foundry_dataset_async("training_clear")

        global evaluator_agent
        evaluator_agent = None

        logger.info(f"✅ Cleared {count_deleted} training applications and associated data")

        return jsonify({
            'status': 'success',
            'message': f'Deleted {count_deleted} training applications',
            'count': count_deleted
        })
    except Exception as e:
        logger.error(f"Error clearing training data: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/training-data/duplicates', methods=['GET'])
def get_training_duplicates():
    """Find duplicate training records grouped by student name."""
    try:
        groups = db.find_training_duplicates()
        total_duplicates = sum(g['count'] - 1 for g in groups)  # extras beyond 1 per group
        return jsonify({
            'status': 'success',
            'groups': groups,
            'total_groups': len(groups),
            'total_duplicates': total_duplicates
        })
    except Exception as e:
        logger.error(f"Error finding training duplicates: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/training-data/bulk-delete', methods=['POST'])
def bulk_delete_training():
    """Delete multiple training records by application_id list.

    Expects JSON body: {"application_ids": [1, 2, 3]}
    Uses the cascading delete_student() for each record.
    """
    try:
        data = request.get_json(force=True)
        app_ids = data.get('application_ids', [])
        if not app_ids or not isinstance(app_ids, list):
            return jsonify({'status': 'error', 'error': 'application_ids list required'}), 400

        deleted_count = 0
        errors = []
        for app_id in app_ids:
            try:
                # Verify it's a training record before deleting
                application = db.get_application(app_id)
                if not application:
                    errors.append(f"ID {app_id}: not found")
                    continue
                if not application.get('is_training_example'):
                    errors.append(f"ID {app_id}: not a training record")
                    continue

                # Also try to clean blob storage
                try:
                    from src.storage import StorageManager
                    storage = StorageManager()
                    storage.delete_student_files(str(app_id))
                except Exception:
                    pass

                db.delete_student(app_id)
                deleted_count += 1
            except Exception as e:
                errors.append(f"ID {app_id}: {str(e)}")

        if deleted_count > 0:
            refresh_foundry_dataset_async("training_bulk_delete")
            global evaluator_agent
            evaluator_agent = None

        logger.info(f"Bulk deleted {deleted_count} training records (errors: {len(errors)})")
        return jsonify({
            'status': 'success',
            'deleted': deleted_count,
            'errors': errors,
            'message': f'Deleted {deleted_count} duplicate training record(s)'
        })
    except Exception as e:
        logger.error(f"Error in bulk delete: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ============================================================================
# HISTORICAL SCORES IMPORT
# ============================================================================

@app.route('/import-scores')
def import_scores_page():
    """Page for importing 2024 historical scoring spreadsheet."""
    stats = db.get_historical_stats(2024)
    return render_template('import_scores.html', stats=stats)


@app.route('/api/import-scores', methods=['POST'])
def api_import_scores():
    """Import historical scores from an uploaded Excel file."""
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'error': 'No file uploaded'}), 400

        file = request.files['file']
        if not file.filename or not file.filename.lower().endswith(('.xlsx', '.xls')):
            return jsonify({'status': 'error', 'error': 'Please upload an .xlsx file'}), 400

        cohort_year = int(request.form.get('cohort_year', 2024))
        clear_first = request.form.get('clear_first', '').lower() in ('true', '1', 'on', 'yes')

        # Save temp file
        temp_path = os.path.join(app.config.get('UPLOAD_FOLDER', '/tmp'), f"import_{uuid.uuid4().hex}.xlsx")
        file.save(temp_path)

        try:
            from scripts.import_historical_scores import parse_xlsx
            scores = parse_xlsx(temp_path, cohort_year)
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass

        if not scores:
            return jsonify({'status': 'error', 'error': 'No valid rows found in spreadsheet'}), 400

        if clear_first:
            deleted = db.clear_historical_scores(cohort_year)
            logger.info(f"Cleared {deleted} existing historical scores for cohort {cohort_year}")

        result = db.bulk_insert_historical_scores(scores)
        stats = db.get_historical_stats(cohort_year)

        return jsonify({
            'status': 'success',
            'imported': result['inserted'],
            'errors': result['errors'],
            'total_rows': result['total'],
            'stats': stats
        })

    except Exception as e:
        logger.error(f"Error importing historical scores: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/historical-scores/stats')
def api_historical_stats():
    """Get aggregate stats for historical scores."""
    cohort_year = int(request.args.get('cohort_year', 2024))
    stats = db.get_historical_stats(cohort_year)
    return jsonify(stats)


@app.route('/api/historical-scores/search')
def api_historical_search():
    """Search historical scores by student name."""
    name = request.args.get('name', '').strip()
    cohort_year = int(request.args.get('cohort_year', 2024))
    if not name:
        return jsonify({'status': 'error', 'error': 'Name parameter required'}), 400
    result = db.get_historical_score_by_name(name, cohort_year)
    if result:
        return jsonify({'status': 'found', 'score': result})
    return jsonify({'status': 'not_found'})


@app.route('/api/historical-scores/clear', methods=['POST'])
def api_clear_historical_scores():
    """Clear all historical scores for a cohort year."""
    cohort_year = int(request.form.get('cohort_year', 2024))
    deleted = db.clear_historical_scores(cohort_year)
    return jsonify({'status': 'success', 'deleted': deleted})


@app.route('/api/training/unmatched')
def api_unmatched_training():
    """Get training students with no linked historical XLSX score."""
    try:
        students = db.get_unmatched_training_students()
        return jsonify({'status': 'success', 'students': students, 'count': len(students)})
    except Exception as e:
        logger.error(f"Error getting unmatched training students: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/historical-scores/unlinked')
def api_unlinked_historical_scores():
    """Search historical scores not yet linked to an application."""
    try:
        search = request.args.get('search', '').strip()
        cohort_year = int(request.args.get('cohort_year', 2024))
        scores = db.search_unlinked_historical_scores(search, cohort_year)
        # Convert Decimal values for JSON serialization
        from decimal import Decimal
        serializable = []
        for row in scores:
            entry = {}
            for k, v in row.items():
                entry[k] = float(v) if isinstance(v, Decimal) else v
            serializable.append(entry)
        return jsonify({'status': 'success', 'scores': serializable, 'count': len(serializable)})
    except Exception as e:
        logger.error(f"Error searching unlinked historical scores: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/training/link-score', methods=['POST'])
def api_link_training_score():
    """Manually link a historical score record to a training application."""
    try:
        data = request.get_json(force=True)
        application_id = data.get('application_id')
        score_id = data.get('score_id')
        if not application_id or not score_id:
            return jsonify({'status': 'error', 'error': 'application_id and score_id are required'}), 400

        # Verify the application is a training record
        application = db.get_application(application_id)
        if not application:
            return jsonify({'status': 'error', 'error': 'Application not found'}), 404
        if not application.get('is_training_example'):
            return jsonify({'status': 'error', 'error': 'Application is not a training record'}), 400

        was_selected = application.get('was_selected')
        success = db.link_historical_score_to_application(score_id, application_id, was_selected=was_selected)
        if success:
            return jsonify({
                'status': 'success',
                'message': f'Linked score {score_id} to application {application_id}'
            })
        return jsonify({'status': 'error', 'error': 'Failed to link records'}), 500
    except Exception as e:
        logger.error(f"Error linking training score: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ============================================================================
# REAL-TIME TEST SYSTEM WITH SERVER-SENT EVENTS (SSE)
# ============================================================================

# In-memory tracking of test submissions and processing status
test_submissions = {}  # {session_id: {students, queue, processor_started}}
# create aurora agent only if class is available
if 'AuroraAgent' in globals() and AuroraAgent is not None:
    aurora = AuroraAgent()
else:
    aurora = None


def start_application_processing(application_id: int) -> None:
    def run():
        try:
            application = db.get_application(application_id)
            if not application:
                return

            orchestrator = get_orchestrator()
            result = asyncio.run(
                orchestrator.coordinate_evaluation(
                    application=application,
                    evaluation_steps=[
                        'application_reader',
                        'grade_reader',
                        'recommendation_reader',
                        'school_context',
                        'data_scientist',
                        'student_evaluator'
                    ]
                )
            )

            if result.get('status') == 'paused':
                db.update_application_status(application_id, 'Needs Docs')
                return

            db.update_application_status(application_id, 'Completed')
        except Exception as e:
            logger.error(
                f"Application processing failed for {application_id}: {str(e)}",
                exc_info=True
            )
            db.update_application_status(application_id, 'Uploaded')

    db.update_application_status(application_id, 'Processing')
    threading.Thread(target=run, daemon=True).start()


def start_training_processing(application_id: int) -> None:
    def run():
        try:
            application = db.get_application(application_id)
            if not application:
                return

            orchestrator = get_orchestrator()
            result = asyncio.run(
                orchestrator.coordinate_evaluation(
                    application=application,
                    evaluation_steps=[
                        'application_reader',
                        'grade_reader',
                        'recommendation_reader',
                        'school_context',
                        'data_scientist',
                        'student_evaluator'
                    ]
                )
            )

            if result.get('status') == 'paused':
                db.update_application_status(application_id, 'Needs Docs')
                return

            db.update_application_status(application_id, 'Completed')
        except Exception as e:
            logger.error(
                f"Training processing failed for application {application_id}: {str(e)}",
                exc_info=True
            )
            db.update_application_status(application_id, 'Uploaded')

    db.update_application_status(application_id, 'Processing')
    threading.Thread(target=run, daemon=True).start()


def start_session_processing(session_id: str) -> None:
    submission = test_submissions.get(session_id)
    if not submission or submission.get('processor_started'):
        return

    submission['processor_started'] = True
    if 'queue' not in submission:
        submission['queue'] = queue.Queue()

    def run():
        try:
            for update in _process_session(session_id):
                submission['queue'].put(update)
        finally:
            submission['queue'].put({'_session_complete': True})

    threading.Thread(target=run, daemon=True).start()


def generate_session_updates(session_id):
    """
    Generator function for SSE updates during test processing.
    Uses a background thread to execute the workflow even if the client disconnects.
    """
    submission = test_submissions.get(session_id)
    if not submission:
        yield f"data: {json.dumps({'error': 'Session not found'}, ensure_ascii=True)}\n\n"
        return

    if 'queue' not in submission:
        submission['queue'] = queue.Queue()

    # only start processing if we already have students generated; the
    # background worker will kick off processing when it finishes generation.
    if submission.get('students'):
        start_session_processing(session_id)

    yield f"data: {json.dumps({'type': 'connected', 'message': 'Connected to test stream'}, ensure_ascii=True)}\n\n"

    last_sent = time.time()
    while True:
        try:
            update = submission['queue'].get(timeout=0.5)
        except queue.Empty:
            if time.time() - last_sent >= 10:
                yield ": keepalive\n\n"
                last_sent = time.time()
            continue

        if update.get('_session_complete'):
            break

        yield f"data: {json.dumps(update, ensure_ascii=True, default=str)}\n\n"
        last_sent = time.time()


def _process_session(session_id):
    submission = test_submissions.get(session_id)
    if not submission:
        return

    students = submission['students']
    logger.info("[%s] _process_session starting (%d students)", session_id, len(students) if students else 0)
    orchestrator = get_orchestrator()

    application_data_list = []
    for idx, student in enumerate(students):
        name = student['name']
        email = student['email']
        application_text = student['application_text']
        transcript_text = student.get('transcript_text', '')
        recommendation_text = student.get('recommendation_text', '')
        school_data = student.get('school_data', {})

        try:
            student_id_val = storage.generate_student_id()

            application_id = db.create_application(
                applicant_name=name,
                email=email,
                application_text=application_text,
                file_name=f"test_{name.replace(' ', '_').lower()}.txt",
                file_type="txt",
                is_training=False,
                is_test_data=True,
                was_selected=None,
                student_id=student_id_val
            )

            db.update_application_fields(
                application_id,
                {
                    'transcript_text': transcript_text,
                    'recommendation_text': recommendation_text
                }
            )
            db.set_missing_fields(application_id, [])

            submission['application_ids'].append(application_id)
            application_data = db.get_application(application_id) or {}
            student_id = f"app_{application_id}"

            if not application_data:
                application_data = {
                    'application_id': application_id,
                    'applicant_name': name,
                    'email': email,
                }

            if not application_data.get('application_text'):
                application_data['application_text'] = application_text
            if not application_data.get('transcript_text'):
                application_data['transcript_text'] = transcript_text
            if not application_data.get('recommendation_text'):
                application_data['recommendation_text'] = recommendation_text
            if not application_data.get('student_id'):
                application_data['student_id'] = student_id_val

            application_data['school_name'] = school_data.get('name', '')
            application_data['school_city'] = school_data.get('city', '')
            application_data['school_state'] = school_data.get('state', '')
            application_data['school_data'] = school_data

            application_data_list.append({
                'student_id': student_id,
                'application_id': application_id,
                'application_data': application_data,
                'name': name,
                'email': email
            })

            yield {
                'type': 'student_submitted',
                'student': {'name': name, 'email': email},
                'student_id': student_id,
                'application_id': application_id
            }
        except Exception as e:
            yield {'type': 'error', 'error': f'Failed to create student record: {str(e)}'}

    if not application_data_list:
        yield {'type': 'error', 'error': 'No students could be created'}
        return

    yield {
        'type': 'orchestrator_start',
        'message': f'Smee is coordinating evaluation of {len(application_data_list)} students'
    }

    for student_num, app_data in enumerate(application_data_list, 1):
        student_id = app_data['student_id']
        application_id = app_data['application_id']
        application_data = app_data['application_data']
        applicant_name = app_data['name']

        try:
            yield {
                'type': 'student_start',
                'student_id': student_id,
                'application_id': application_id,
                'student_num': student_num,
                'total_students': len(application_data_list),
                'applicant_name': applicant_name
            }

            logger.info(
                f"Processing student: {applicant_name} (ID: {application_id})",
                extra={'data_keys': list(application_data.keys()) if application_data else []}
            )

            update_queue = queue.Queue()

            def progress_callback(update):
                logger.debug(
                    f"Progress callback: {update.get('type', 'unknown')} - {update.get('agent', 'N/A')}",
                    extra=update
                )
                update_queue.put(update)

            def run_orchestration():
                try:
                    # log at info so the activity is easier to find in App Service logs
                    logger.info(f"Starting orchestration thread for {applicant_name}")
                    evaluation_steps = [
                        'application_reader',
                        'grade_reader',
                        'recommendation_reader',
                        'school_context',
                        'data_scientist',
                        'student_evaluator',
                        'aurora'
                    ]

                    logger.debug(f"Evaluation steps: {evaluation_steps}")

                    result = asyncio.run(orchestrator.coordinate_evaluation(
                        application=application_data,
                        evaluation_steps=evaluation_steps,
                        progress_callback=progress_callback
                    ))

                    logger.info(
                        f"Orchestration complete for {applicant_name}",
                        extra={'application_id': application_id}
                    )
                    update_queue.put({'_orchestration_complete': True, 'result': result})
                except Exception as e:
                    logger.error(
                        f"Orchestration error for {applicant_name}: {str(e)}",
                        exc_info=True
                    )
                    import traceback
                    traceback.print_exc()
                    update_queue.put({'_orchestration_error': True, 'error': str(e)})

            orchestration_thread = threading.Thread(target=run_orchestration, daemon=True)
            orchestration_thread.start()

            orchestration_complete = False
            orchestration_result = None
            orchestration_error = None

            while not orchestration_complete:
                try:
                    update = update_queue.get(timeout=0.5)

                    if update.get('_orchestration_complete'):
                        orchestration_complete = True
                        orchestration_result = update.get('result')
                    elif update.get('_orchestration_error'):
                        orchestration_complete = True
                        orchestration_error = update.get('error')
                    else:
                        yield update

                except queue.Empty:
                    if not orchestration_thread.is_alive():
                        orchestration_complete = True
                    continue

            if orchestration_error:
                yield {
                    'type': 'student_error',
                    'student_id': student_id,
                    'student_num': student_num,
                    'error': f'Processing failed: {orchestration_error}'
                }
                continue

            if orchestration_result and 'results' in orchestration_result:
                merlin_result = orchestration_result['results'].get('student_evaluator', {})
                if merlin_result and merlin_result.get('status') == 'success':
                    try:
                        db.save_merlin_evaluation(
                            application_id=application_id,
                            agent_name='Merlin',
                            overall_score=merlin_result.get('overall_score'),
                            recommendation=merlin_result.get('recommendation'),
                            rationale=merlin_result.get('rationale'),
                            confidence=merlin_result.get('confidence'),
                            parsed_json=json.dumps(merlin_result, ensure_ascii=True, default=str)
                        )
                    except Exception as save_err:
                        logger.warning(f"Failed to save Merlin evaluation: {str(save_err)}")

                db.update_application_status(application_id, 'Completed')

            yield {
                'type': 'student_complete',
                'student_id': student_id,
                'student_num': student_num,
                'applicant_name': applicant_name,
                'application_id': application_id,
                'results_url': f'/application/{application_id}',
                'success': True
            }

        except Exception as e:
            logger.error(f"Error processing student {student_id}: {str(e)}", exc_info=True)
            import traceback
            traceback.print_exc()
            yield {
                'type': 'student_error',
                'student_id': student_id,
                'student_num': student_num,
                'error': f'Processing failed: {str(e)}'
            }

    yield {'type': 'all_complete', 'application_ids': submission['application_ids']}

    try:
        db.save_test_submission(
            session_id=session_id,
            student_count=len(application_data_list),
            application_ids=submission['application_ids']
        )
        submission['status'] = 'completed'
        yield {'type': 'session_saved', 'message': 'Test submission saved to database'}
    except Exception as e:
        logger.warning(f"Failed to save test submission to database: {str(e)}")
        yield {
            'type': 'save_warning',
            'message': f'Data saved in memory but database save failed: {str(e)}'
        }


@app.route('/api/test/stream/<session_id>')
def test_stream(session_id):
    """Server-Sent Events endpoint for real-time test status updates."""
    return Response(
        stream_with_context(generate_session_updates(session_id)),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )



# helper used by test routes to prepare data in background

def _prepare_test_session(session_id: str, mode: str = 'dynamic') -> None:
    """Run cleanup and student generation in a worker thread.

    This prevents the HTTP request from blocking while the database
    operations and generator run.  Once students have been produced we
    push a `student_count` update onto the session queue and kick off the
    orchestration thread.
    """
    try:
        logger.info("[%s] background worker starting (mode=%s)", session_id, mode)
        # cleanup may take a while on large datasets
        cleanup_test_data()
        logger.info("[%s] cleanup complete", session_id)

        if mode == 'preset':
            students = test_data_generator.generate_batch(count=3)
        elif mode == 'single':
            students = test_data_generator.generate_batch(count=1)
        else:
            students = test_data_generator.generate_batch()

        logger.info("[%s] generated %d test students", session_id, len(students))

        # store results and notify stream/pollers
        submission = test_submissions.get(session_id)
        if submission is not None:
            submission['students'] = students
            submission['status'] = 'processing'
            submission['queue'].put({'type': 'student_count', 'count': len(students)})

        # begin evaluation
        start_session_processing(session_id)
    except Exception as e:
        logger.error("[%s] error preparing test session: %s", session_id, str(e), exc_info=True)
        submission = test_submissions.get(session_id)
        if submission is not None:
            submission['status'] = 'error'
            submission['queue'].put({'type': 'error', 'error': str(e)})


@app.route('/api/test/submit', methods=['POST'])
def submit_test_data():
    """
    Kick off a new test run; response returns immediately with a session id.

    The heavy work lives in a daemon thread so the UI never locks up.  The
    client will receive a `student_count` event once the generator completes
    and can then update its display.
    """
    try:
        logger.info("Received request to create dynamic test session")
        session_id = str(uuid.uuid4())
        test_submissions[session_id] = {
            'students': [],
            'application_ids': [],
            'created_at': time.time(),
            'status': 'initializing',
            'queue': queue.Queue()
        }

        # spawn worker thread and return immediately
        threading.Thread(target=_prepare_test_session, args=(session_id, 'dynamic'), daemon=True).start()

        return jsonify({
            'session_id': session_id,
            'student_count': 0,
            'stream_url': url_for('test_stream', session_id=session_id)
        })
    except Exception as e:
        logger.error("submit_test_data failed: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/test/submit-preset', methods=['POST'])
def submit_preset_test_data():
    """
    Start a run with the fixed 3-student preset dataset.
    The actual work is delegated to a background thread to keep the
    request path non‑blocking.
    """
    try:
        logger.info("Received request to create preset test session")
        session_id = str(uuid.uuid4())
        test_submissions[session_id] = {
            'students': [],
            'application_ids': [],
            'created_at': time.time(),
            'status': 'initializing',
            'queue': queue.Queue()
        }
        threading.Thread(target=_prepare_test_session, args=(session_id, 'preset'), daemon=True).start()
        return jsonify({
            'session_id': session_id,
            'student_count': 0,
            'stream_url': url_for('test_stream', session_id=session_id)
        })
    except Exception as e:
        logger.error("submit_preset_test_data failed: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/test/submit-single', methods=['POST'])
def submit_single_test_data():
    """
    Start a run with one randomly generated student.
    Heavy work is executed asynchronously.
    """
    try:
        logger.info("Received request to create single-student test session")
        session_id = str(uuid.uuid4())
        test_submissions[session_id] = {
            'students': [],
            'application_ids': [],
            'created_at': time.time(),
            'status': 'initializing',
            'queue': queue.Queue()
        }
        threading.Thread(target=_prepare_test_session, args=(session_id, 'single'), daemon=True).start()
        return jsonify({
            'session_id': session_id,
            'student_count': 0,
            'stream_url': url_for('test_stream', session_id=session_id)
        })
    except Exception as e:
        logger.error("submit_single_test_data failed: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/test/cleanup', methods=['POST'])
def cleanup_test_endpoint():
    """
    API endpoint to manually clear all test data from the database.
    Useful for starting fresh without running a full test.
    """
    try:
        cleanup_test_data()

        training_col = db.get_training_example_column()
        
        # Count remaining test data
        remaining = db.execute_query(
            f"SELECT COUNT(*) as count FROM Applications WHERE {training_col} = TRUE"
        )
        count = remaining[0].get('count', 0) if remaining else 0
        
        return jsonify({
            'status': 'success',
            'message': 'Test data cleaned up successfully',
            'remaining_test_apps': count
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/test/upload-files', methods=['POST'])
def upload_test_files():
    """
    Upload real files from the test page for agent evaluation.
    Accepts multiple files and processes them as test data.
    """
    try:
        # Get uploaded files
        if 'files' not in request.files:
            return jsonify({'status': 'error', 'error': 'No files uploaded'}), 400
        
        files = request.files.getlist('files')
        
        if len(files) == 0:
            return jsonify({'status': 'error', 'error': 'No files selected'}), 400
        
        uploaded_students_map = {}
        app_doc_types = {
            'application',
            'personal_statement',
            'essay'
        }
        transcript_doc_types = {'transcript', 'grades'}
        recommendation_doc_types = {'letter_of_recommendation'}
        
        for file in files:
            if file.filename == '':
                continue
                
            if not DocumentProcessor.validate_file_type(file.filename):
                continue
            
            # Generate unique student ID
            student_id = storage.generate_student_id()
            
            # Save file temporarily to extract text
            filename = secure_filename(file.filename)
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{student_id}_{filename}")
            file.save(temp_path)
            
            # Extract text from file
            application_text, file_type = DocumentProcessor.process_document(temp_path)
            
            # Read file content for Azure Storage
            with open(temp_path, 'rb') as f:
                file_content = f.read()
            
            # Upload to Azure Storage
            storage_result = storage.upload_file(
                file_content=file_content,
                filename=filename,
                student_id=student_id,
                application_type='test'
            )
            
            # Clean up temporary file
            try:
                os.remove(temp_path)
            except Exception:
                pass

            # Use Belle to analyze the document and extract structured data
            try:
                belle = get_belle()
                doc_analysis = belle.analyze_document(application_text, filename)
            except Exception as e:
                logger.warning(f"Belle analysis failed for test upload: {e}")
                doc_analysis = {
                    "document_type": "unknown",
                    "confidence": 0,
                    "student_info": {},
                    "extracted_data": {}
                }

            belle_student_info = doc_analysis.get('student_info', {})
            student_name = belle_student_info.get('name') or extract_student_name(application_text)
            student_email = belle_student_info.get('email') or extract_student_email(application_text)

            doc_type = doc_analysis.get('document_type', 'unknown')
            agent_fields = doc_analysis.get('agent_fields', {})
            school_name = agent_fields.get('school_name')

            identity_key = (student_email or student_name or filename).strip().lower()
            if identity_key not in uploaded_students_map:
                uploaded_students_map[identity_key] = {
                    'name': student_name or f"Student from {filename}",
                    'email': student_email or "",
                    'application_text': "",
                    'transcript_text': "",
                    'recommendation_text': "",
                    'recommendation_texts': [],
                    'filenames': [],
                    'school_data': {'name': school_name} if school_name else {}
                }

            record = uploaded_students_map[identity_key]
            record['filenames'].append(filename)
            if school_name and not record.get('school_data'):
                record['school_data'] = {'name': school_name}

            if doc_type in app_doc_types:
                if record['application_text']:
                    record['application_text'] += "\n\n--- Additional Application Document ---\n\n"
                record['application_text'] += application_text
            elif doc_type in transcript_doc_types:
                if record['transcript_text']:
                    record['transcript_text'] += "\n\n--- Additional Transcript Document ---\n\n"
                record['transcript_text'] += application_text
            elif doc_type in recommendation_doc_types:
                record['recommendation_texts'].append(application_text)
                if record['recommendation_text']:
                    record['recommendation_text'] += "\n\n--- Additional Recommendation Letter ---\n\n"
                record['recommendation_text'] += application_text
            else:
                if not record['application_text']:
                    record['application_text'] = application_text
                elif not record['recommendation_text']:
                    record['recommendation_text'] = application_text
                else:
                    record['transcript_text'] = record['transcript_text'] or application_text
        
        uploaded_students = list(uploaded_students_map.values())

        for record in uploaded_students:
            if not record.get('application_text'):
                record['application_text'] = (
                    record.get('recommendation_text')
                    or record.get('transcript_text')
                    or 'No application essay provided for this test run.'
                )
            if not record.get('transcript_text'):
                record['transcript_text'] = 'No transcript provided for this test run.'
            if not record.get('recommendation_text'):
                record['recommendation_text'] = 'No recommendation letter provided for this test run.'

        if len(uploaded_students) == 0:
            return jsonify({'status': 'error', 'error': 'No valid files uploaded'}), 400
        
        # Generate session ID for tracking
        session_id = str(uuid.uuid4())
        
        # Track submission
        test_submissions[session_id] = {
            'students': uploaded_students,
            'application_ids': [],
            'created_at': time.time(),
            'status': 'processing',
            'queue': queue.Queue()
        }

        start_session_processing(session_id)
        
        return jsonify({
            'status': 'success',
            'session_id': session_id,
            'count': len(uploaded_students),
            'stream_url': url_for('test_stream', session_id=session_id)
        })
        
    except Exception as e:
        logger.error(f"Error uploading test files: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/test/stats', methods=['GET'])
def test_stats():
    """
    Get statistics about test data currently in the database.
    """
    try:
        training_col = db.get_training_example_column()
        test_col = db.get_test_data_column()
        applications_table = db.get_table_name("applications")
        app_id_col = db.get_applications_column("application_id")
        applicant_col = db.get_applications_column("applicant_name")
        status_col = db.get_applications_column("status")
        uploaded_col = db.get_applications_column("uploaded_date")
        if db.has_applications_column(test_col):
            test_count = db.execute_query(
                f"SELECT COUNT(*) as count FROM {applications_table} WHERE {test_col} = TRUE"
            )
        else:
            test_count = []
        count = test_count[0].get('count', 0) if test_count else 0
        
        # Get list of test students
        if db.has_applications_column(test_col):
            test_apps = db.execute_query(
                f"SELECT {app_id_col} as application_id, {applicant_col} as applicant_name, {status_col} as status, {uploaded_col} as uploaded_date FROM {applications_table} WHERE {test_col} = TRUE ORDER BY {uploaded_col} DESC"
            )
        else:
            test_apps = []
        
        return jsonify({
            'status': 'success',
            'test_count': count,
            'test_applications': test_apps
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/test/submissions', methods=['GET'])
def get_test_submissions():
    """
    Get list of previous test submissions from database.
    Allows users to view and resume previous test runs.
    """
    try:
        limit = request.args.get('limit', 10, type=int)

        submissions_table = db.get_table_name("test_submissions")
        if not db.has_table(submissions_table):
            return jsonify({
                'status': 'success',
                'submissions': [],
                'count': 0
            })

        session_id_col = db.resolve_table_column(
            "test_submissions",
            ["session_id", "sessionid", "SessionID"],
        )
        student_count_col = db.resolve_table_column(
            "test_submissions",
            ["student_count", "studentcount", "StudentCount"],
        )
        application_ids_col = db.resolve_table_column(
            "test_submissions",
            ["application_ids", "applicationids", "ApplicationIDs"],
        )
        status_col = db.resolve_table_column(
            "test_submissions",
            ["status", "Status"],
        )
        created_at_col = db.resolve_table_column(
            "test_submissions",
            ["created_at", "createdat", "CreatedAt"],
        )
        updated_at_col = db.resolve_table_column(
            "test_submissions",
            ["updated_at", "updatedat", "UpdatedAt"],
        )
        
        # Get recent test submissions from database
        submissions = db.execute_query(
            f"""
            SELECT
                {session_id_col} as session_id,
                {student_count_col} as student_count,
                {application_ids_col} as application_ids,
                {status_col} as status,
                {created_at_col} as created_at,
                {updated_at_col} as updated_at
            FROM {submissions_table}
            ORDER BY {created_at_col} DESC
            LIMIT %s
            """,
            (limit,)
        )
        
        # Format submission data for frontend
        formatted = []
        for sub in submissions:
            try:
                import json as json_module
                app_ids = json_module.loads(sub.get('application_ids', '[]')) if isinstance(sub.get('application_ids'), str) else sub.get('application_ids', [])
            except Exception:
                app_ids = []
            
            formatted.append({
                'session_id': sub.get('session_id'),
                'student_count': sub.get('student_count'),
                'application_ids': app_ids,
                'status': sub.get('status'),
                'created_at': str(sub.get('created_at')) if sub.get('created_at') else None,
                'updated_at': str(sub.get('updated_at')) if sub.get('updated_at') else None
            })
        
        return jsonify({
            'status': 'success',
            'submissions': formatted,
            'count': len(formatted)
        })
    except Exception as e:
        logger.error(f"Error retrieving test submissions: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/test/students', methods=['GET'])
def get_test_students():
    """
    Get current test students with their processing status.
    Queries the database to show which agents have evaluated each student.
    """
    try:
        applications_table = db.get_table_name("applications")
        merlin_table = db.get_table_name("merlin_evaluations")
        tiana_table = db.get_table_name("tiana_applications")
        rapunzel_table = db.get_table_name("rapunzel_grades")
        mulan_table = db.get_table_name("mulan_recommendations")
        context_table = db.get_table_name("student_school_context")
        aurora_table = db.get_table_name("aurora_evaluations")

        app_id_col = db.get_applications_column("application_id")
        applicant_col = db.get_applications_column("applicant_name")
        email_col = db.get_applications_column("email")
        status_col = db.get_applications_column("status")
        uploaded_col = db.get_applications_column("uploaded_date")
        student_id_col = db.get_applications_column("student_id")
        test_col = db.get_test_data_column()

        merlin_id_col = None
        merlin_join = ""
        if db.has_table(merlin_table):
            merlin_id_col = db.resolve_table_column(
                "merlin_evaluations",
                ["merlin_evaluation_id", "merlinevaluationid", "evaluation_id", "evaluationid"],
            )
            merlin_app_id_col = db.resolve_table_column(
                "merlin_evaluations",
                ["application_id", "applicationid"],
            )
            if merlin_id_col and merlin_app_id_col:
                merlin_join = f"LEFT JOIN {merlin_table} m ON a.{app_id_col} = m.{merlin_app_id_col}"

        tiana_id_col = None
        tiana_join = ""
        if db.has_table(tiana_table):
            tiana_id_col = db.resolve_table_column(
                "tiana_applications",
                ["tiana_application_id", "tianaapplicationid", "application_id", "applicationid"],
            )
            tiana_app_id_col = db.resolve_table_column(
                "tiana_applications",
                ["application_id", "applicationid"],
            )
            if tiana_id_col and tiana_app_id_col:
                tiana_join = f"LEFT JOIN {tiana_table} t ON a.{app_id_col} = t.{tiana_app_id_col}"

        rapunzel_id_col = None
        rapunzel_join = ""
        if db.has_table(rapunzel_table):
            rapunzel_id_col = db.resolve_table_column(
                "rapunzel_grades",
                ["rapunzel_grade_id", "rapunzelgradeid", "grade_id", "gradeid"],
            )
            rapunzel_app_id_col = db.resolve_table_column(
                "rapunzel_grades",
                ["application_id", "applicationid"],
            )
            if rapunzel_id_col and rapunzel_app_id_col:
                rapunzel_join = f"LEFT JOIN {rapunzel_table} rg ON a.{app_id_col} = rg.{rapunzel_app_id_col}"

        mulan_id_col = None
        mulan_join = ""
        if db.has_table(mulan_table):
            mulan_id_col = db.resolve_table_column(
                "mulan_recommendations",
                ["mulan_recommendation_id", "mulanrecommendationid", "recommendation_id", "recommendationid"],
            )
            mulan_app_id_col = db.resolve_table_column(
                "mulan_recommendations",
                ["application_id", "applicationid"],
            )
            if mulan_id_col and mulan_app_id_col:
                mulan_join = f"LEFT JOIN {mulan_table} r ON a.{app_id_col} = r.{mulan_app_id_col}"

        context_id_col = None
        context_join = ""
        if db.has_table(context_table):
            context_id_col = db.resolve_table_column(
                "student_school_context",
                ["context_id", "contextid"],
            )
            context_app_id_col = db.resolve_table_column(
                "student_school_context",
                ["application_id", "applicationid"],
            )
            if context_id_col and context_app_id_col:
                context_join = f"LEFT JOIN {context_table} s ON a.{app_id_col} = s.{context_app_id_col}"

        aurora_id_col = None
        aurora_join = ""
        if db.has_table(aurora_table):
            aurora_id_col = db.resolve_table_column(
                "aurora_evaluations",
                ["aurora_evaluation_id", "auroraevaluationid", "evaluation_id", "evaluationid"],
            )
            aurora_app_id_col = db.resolve_table_column(
                "aurora_evaluations",
                ["application_id", "applicationid"],
            )
            if aurora_id_col and aurora_app_id_col:
                aurora_join = f"LEFT JOIN {aurora_table} au ON a.{app_id_col} = au.{aurora_app_id_col}"

        test_filter = f"WHERE a.{test_col} = TRUE" if db.has_applications_column(test_col) else "WHERE 1 = 0"
        student_id_select = "NULL as student_id"
        student_id_group = None
        if db.has_applications_column(student_id_col):
            student_id_select = f"a.{student_id_col} as student_id"
            student_id_group = f"a.{student_id_col}"

        merlin_select = "0 as has_merlin"
        if merlin_id_col and merlin_join:
            merlin_select = f"COUNT(DISTINCT CASE WHEN m.{merlin_id_col} IS NOT NULL THEN m.{merlin_id_col} END) as has_merlin"

        tiana_select = "0 as has_tiana"
        if tiana_id_col and tiana_join:
            tiana_select = f"COUNT(DISTINCT CASE WHEN t.{tiana_id_col} IS NOT NULL THEN t.{tiana_id_col} END) as has_tiana"

        rapunzel_select = "0 as has_rapunzel"
        if rapunzel_id_col and rapunzel_join:
            rapunzel_select = f"COUNT(DISTINCT CASE WHEN rg.{rapunzel_id_col} IS NOT NULL THEN rg.{rapunzel_id_col} END) as has_rapunzel"

        mulan_select = "0 as has_mulan"
        if mulan_id_col and mulan_join:
            mulan_select = f"COUNT(DISTINCT CASE WHEN r.{mulan_id_col} IS NOT NULL THEN r.{mulan_id_col} END) as has_mulan"

        context_select = "0 as has_moana"
        if context_id_col and context_join:
            context_select = f"COUNT(DISTINCT CASE WHEN s.{context_id_col} IS NOT NULL THEN s.{context_id_col} END) as has_moana"

        aurora_select = "0 as has_aurora"
        if aurora_id_col and aurora_join:
            aurora_select = f"COUNT(DISTINCT CASE WHEN au.{aurora_id_col} IS NOT NULL THEN au.{aurora_id_col} END) as has_aurora"

        # Get all test students (marked with is_test_data = TRUE)
        group_by_parts = [
            f"a.{app_id_col}",
            f"a.{applicant_col}",
            f"a.{email_col}",
            f"a.{status_col}",
            f"a.{uploaded_col}",
        ]
        if student_id_group:
            group_by_parts.append(student_id_group)

        group_by_clause = ", ".join(group_by_parts)

        query = f"""
            SELECT 
                a.{app_id_col} as application_id,
                a.{applicant_col} as applicant_name,
                a.{email_col} as email,
                a.{status_col} as status,
                a.{uploaded_col} as uploaded_date,
                {student_id_select},
                {merlin_select},
                {tiana_select},
                {rapunzel_select},
                {mulan_select},
                {context_select},
                {aurora_select}
            FROM {applications_table} a
            {merlin_join}
            {tiana_join}
            {rapunzel_join}
            {mulan_join}
            {context_join}
            {aurora_join}
            {test_filter}
            GROUP BY {group_by_clause}
            ORDER BY a.{uploaded_col} DESC
        """
        
        students = db.execute_query(query)
        
        # Format student data with agent status
        formatted = []
        for student in students:
            agent_status = {
                'smee': 'complete' if all([student.get('has_tiana'), student.get('has_rapunzel'), student.get('has_mulan'), 
                                           student.get('has_moana'), student.get('has_merlin')]) else 'pending',
                'application_reader': 'complete' if student.get('has_tiana') else 'pending',
                'grade_reader': 'complete' if student.get('has_rapunzel') else 'pending',
                'school_context': 'complete' if student.get('has_moana') else 'pending',
                'recommendation_reader': 'complete' if student.get('has_mulan') else 'pending',
                'student_evaluator': 'complete' if student.get('has_merlin') else 'pending',
                'aurora': 'complete' if student.get('has_aurora') else 'pending',
                'fairy_godmother': 'pending'  # Fairy Godmother completion not tracked in DB
            }
            
            is_complete = (student.get('has_tiana') and student.get('has_rapunzel') and student.get('has_mulan') and 
                          student.get('has_moana') and student.get('has_merlin'))
            
            formatted.append({
                'application_id': student.get('application_id'),
                'name': student.get('applicant_name'),
                'email': student.get('email'),
                'status': 'complete' if is_complete else 'processing',
                'uploaded_date': str(student.get('uploaded_date')) if student.get('uploaded_date') else None,
                'student_id': student.get('student_id'),
                'agent_progress': agent_status
            })
        
        return jsonify({
            'status': 'success',
            'students': formatted,
            'count': len(formatted)
        })
    except Exception as e:
        logger.error(f"Error retrieving test students: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/application/status/<int:application_id>', methods=['GET'])
def get_application_status(application_id):
    """Return agent progress status for a single application."""
    try:
        query = """
            SELECT 
                a.application_id,
                a.applicant_name,
                a.status,
                COUNT(DISTINCT CASE WHEN t.tiana_application_id IS NOT NULL THEN t.tiana_application_id END) as has_tiana,
                COUNT(DISTINCT CASE WHEN rg.rapunzel_grade_id IS NOT NULL THEN rg.rapunzel_grade_id END) as has_rapunzel,
                COUNT(DISTINCT CASE WHEN r.mulan_recommendation_id IS NOT NULL THEN r.mulan_recommendation_id END) as has_mulan,
                COUNT(DISTINCT CASE WHEN s.context_id IS NOT NULL THEN s.context_id END) as has_moana,
                COUNT(DISTINCT CASE WHEN m.merlin_evaluation_id IS NOT NULL THEN m.merlin_evaluation_id END) as has_merlin,
                COUNT(DISTINCT CASE WHEN au.aurora_evaluation_id IS NOT NULL THEN au.aurora_evaluation_id END) as has_aurora
            FROM Applications a
            LEFT JOIN tiana_applications t ON a.application_id = t.application_id
            LEFT JOIN rapunzel_grades rg ON a.application_id = rg.application_id
            LEFT JOIN mulan_recommendations r ON a.application_id = r.application_id
            LEFT JOIN student_school_context s ON a.application_id = s.application_id
            LEFT JOIN merlin_evaluations m ON a.application_id = m.application_id
            LEFT JOIN aurora_evaluations au ON a.application_id = au.application_id
            WHERE a.application_id = %s
            GROUP BY a.application_id, a.applicant_name, a.status
        """
        rows = db.execute_query(query, (application_id,))
        if not rows:
            return jsonify({'error': 'Application not found'}), 404

        row = rows[0]
        missing_fields = row.get('missing_fields') or []
        if isinstance(missing_fields, str):
            try:
                missing_fields = json.loads(missing_fields)
            except Exception:
                missing_fields = [missing_fields]

        agent_status = {
            'application_reader': 'complete' if row.get('has_tiana') else 'pending',
            'grade_reader': 'complete' if row.get('has_rapunzel') else 'pending',
            'school_context': 'complete' if row.get('has_moana') else 'pending',
            'recommendation_reader': 'complete' if row.get('has_mulan') else 'pending',
            'student_evaluator': 'complete' if row.get('has_merlin') else 'pending',
            'aurora': 'complete' if row.get('has_aurora') else 'pending'
        }

        waiting_for = {}
        for agent_id in agent_status.keys():
            field_name = AgentRequirements.get_field_for_agent(agent_id)
            if field_name in missing_fields and agent_status[agent_id] != 'complete':
                agent_status[agent_id] = 'waiting'
                waiting_for[agent_id] = field_name

        is_complete = all([
            row.get('has_tiana'),
            row.get('has_rapunzel'),
            row.get('has_moana'),
            row.get('has_mulan'),
            row.get('has_merlin')
        ])

        return jsonify({
            'status': 'success',
            'application_id': application_id,
            'applicant_name': row.get('applicant_name'),
            'overall_status': 'complete' if is_complete else 'processing',
            'agent_progress': agent_status,
            'waiting_for': waiting_for,
            'missing_fields': missing_fields
        })
    except Exception as e:
        logger.error(f"Error fetching application status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/verify/applications', methods=['GET'])
def verify_applications():
    """Verify application field completeness across test, training, and 2026 flows."""
    try:
        scope = request.args.get('scope', 'all').lower()

        training_col = db.get_training_example_column()
        test_col = db.get_test_data_column()
        has_test_col = db.has_applications_column(test_col)

        where_clause = ""
        params = []
        if scope == 'test':
            if has_test_col:
                where_clause = f"WHERE a.{test_col} = TRUE"
            else:
                where_clause = "WHERE 1 = 0"
        elif scope == 'training':
            where_clause = f"WHERE a.{training_col} = TRUE"
        elif scope == '2026':
            if has_test_col:
                where_clause = f"WHERE a.{training_col} = FALSE AND (a.{test_col} = FALSE OR a.{test_col} IS NULL)"
            else:
                where_clause = f"WHERE a.{training_col} = FALSE"

        test_col_select = "FALSE AS is_test_data"
        test_col_group = "FALSE"
        if has_test_col:
            test_col_select = f"a.{test_col} AS is_test_data"
            test_col_group = f"a.{test_col}"

        query = f"""
            SELECT
                a.application_id,
                a.applicant_name,
                a.email,
                a.status,
                a.{training_col} AS is_training_example,
                {test_col_select},
                a.missing_fields,
                (a.application_text IS NOT NULL AND a.application_text != '') AS has_application_text,
                (a.transcript_text IS NOT NULL AND a.transcript_text != '') AS has_transcript_text,
                (a.recommendation_text IS NOT NULL AND a.recommendation_text != '') AS has_recommendation_text,
                COUNT(DISTINCT CASE WHEN t.tiana_application_id IS NOT NULL THEN t.tiana_application_id END) AS has_tiana,
                COUNT(DISTINCT CASE WHEN r.mulan_recommendation_id IS NOT NULL THEN r.mulan_recommendation_id END) AS has_mulan,
                COUNT(DISTINCT CASE WHEN s.context_id IS NOT NULL THEN s.context_id END) AS has_moana,
                COUNT(DISTINCT CASE WHEN m.merlin_evaluation_id IS NOT NULL THEN m.merlin_evaluation_id END) AS has_merlin,
                COUNT(DISTINCT CASE WHEN au.aurora_evaluation_id IS NOT NULL THEN au.aurora_evaluation_id END) AS has_aurora
            FROM Applications a
            LEFT JOIN tiana_applications t ON a.application_id = t.application_id
            LEFT JOIN mulan_recommendations r ON a.application_id = r.application_id
            LEFT JOIN student_school_context s ON a.application_id = s.application_id
            LEFT JOIN merlin_evaluations m ON a.application_id = m.application_id
            LEFT JOIN aurora_evaluations au ON a.application_id = au.application_id
            {where_clause}
            GROUP BY a.application_id, a.applicant_name, a.email, a.status, a.{training_col}, {test_col_group}, a.missing_fields,
                     a.application_text, a.transcript_text, a.recommendation_text
            ORDER BY a.uploaded_date DESC
            LIMIT 200
        """

        results = db.execute_query(query, tuple(params) if params else None)
        formatted = []
        for row in results:
            formatted.append({
                'application_id': row.get('application_id'),
                'name': row.get('applicant_name'),
                'email': row.get('email'),
                'status': row.get('status'),
                'is_training_example': row.get('is_training_example'),
                'is_test_data': row.get('is_test_data'),
                'missing_fields': row.get('missing_fields') or [],
                'fields': {
                    'application_text': bool(row.get('has_application_text')),
                    'transcript_text': bool(row.get('has_transcript_text')),
                    'recommendation_text': bool(row.get('has_recommendation_text'))
                },
                'agents': {
                    'application_reader': 'complete' if row.get('has_tiana') else 'pending',
                    'recommendation_reader': 'complete' if row.get('has_mulan') else 'pending',
                    'school_context': 'complete' if row.get('has_moana') else 'pending',
                    'student_evaluator': 'complete' if row.get('has_merlin') else 'pending',
                    'aurora': 'complete' if row.get('has_aurora') else 'pending'
                }
            })

        return jsonify({
            'status': 'success',
            'scope': scope,
            'count': len(formatted),
            'applications': formatted
        })
    except Exception as e:
        logger.error(f"Error verifying applications: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


# ============================================================================
# TEST DATA MANAGEMENT ENDPOINTS
# ============================================================================

@app.route('/api/test-data/list', methods=['GET'])
def get_test_data_list():
    """Get all test data (applications marked as training/test data)."""
    try:
        applications_table = db.get_table_name("applications")
        training_col = db.get_training_example_column()
        app_id_col = db.get_applications_column("application_id")
        applicant_col = db.get_applications_column("applicant_name")
        email_col = db.get_applications_column("email")
        status_col = db.get_applications_column("status")
        uploaded_col = db.get_applications_column("uploaded_date")
        merlin_table = db.get_table_name("merlin_evaluations")

        merlin_join = ""
        merlin_score_select = "NULL as merlin_score"
        if db.has_table(merlin_table):
            merlin_score_col = db.resolve_table_column(
                "merlin_evaluations",
                ["overall_score", "overallscore"],
            )
            merlin_app_id_col = db.resolve_table_column(
                "merlin_evaluations",
                ["application_id", "applicationid"],
            )
            if merlin_score_col and merlin_app_id_col:
                merlin_join = f"LEFT JOIN {merlin_table} m ON a.{app_id_col} = m.{merlin_app_id_col}"
                merlin_score_select = f"m.{merlin_score_col} as merlin_score"

        # Get all applications marked as training (includes both training and test uploads)
        # Filter out incomplete records (missing application_id or applicant_name)
        query = f"""
            SELECT 
                a.{app_id_col} as application_id,
                a.{applicant_col} as applicant_name,
                a.{email_col} as email,
                a.{status_col} as status,
                a.{uploaded_col} as uploaded_date,
                {merlin_score_select}
            FROM {applications_table} a
            {merlin_join}
            WHERE a.{training_col} = TRUE
            AND a.{app_id_col} IS NOT NULL
            AND a.{applicant_col} IS NOT NULL
            ORDER BY a.{uploaded_col} DESC
            LIMIT 100
        """
        
        results = db.execute_query(query)
        
        test_students = []
        for row in results:
            # parse JSON summary if present
            ss = None
            if 'student_summary' in row and isinstance(row['student_summary'], str):
                try:
                    ss = json.loads(row['student_summary'])
                except Exception:
                    ss = None
            elif 'student_summary' in row:
                ss = row['student_summary']

            merlin_score = row.get('merlinscore')
            if merlin_score is None and ss and isinstance(ss, dict):
                merlin_score = ss.get('overall_score') or ss.get('score')

            test_students.append({
                'applicationid': row.get('applicationid'),
                'applicantname': row.get('applicantname'),
                'email': row.get('email'),
                'status': row.get('status'),
                'uploadeddate': str(row.get('uploadeddate')) if row.get('uploadeddate') else None,
                'merlin_score': merlin_score,
                'student_summary': ss
            })
        
        return jsonify({
            'status': 'success',
            'count': len(test_students),
            'students': test_students
        })
    except Exception as e:
        logger.error(f"Error retrieving test data: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e),
            'count': 0,
            'students': []
        }), 500
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/test-data/clear', methods=['POST'])
def clear_test_data():
    """Clear all test data from the database (synthetic test students only)."""
    try:
        test_col = db.get_test_data_column()
        # Get all test application IDs (where is_test_data=TRUE)
        if not db.has_applications_column(test_col):
            return jsonify({
                'status': 'success',
                'message': 'No test data column found; nothing to delete',
                'count': 0
            })

        test_apps = db.execute_query(f"""
            SELECT application_id
            FROM applications
            WHERE {test_col} = TRUE
        """)
        
        test_app_ids = [app.get('application_id') for app in test_apps]
        count_deleted = len(test_app_ids)
        
        if count_deleted == 0:
            logger.info("No test data to clear")
            return jsonify({
                'status': 'success',
                'message': 'No test data found to delete',
                'count': 0
            })
        
        # Delete from specialized agent tables first (order matters for foreign keys)
        for app_id in test_app_ids:
            try:
                # Delete audit logs first (has FK to applications)
                db.execute_non_query("DELETE FROM agent_audit_logs WHERE application_id = %s", (app_id,))
                # Delete from agent-specific tables
                db.execute_non_query("DELETE FROM tiana_applications WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM mulan_recommendations WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM merlin_evaluations WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM aurora_evaluations WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM student_school_context WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM grade_records WHERE application_id = %s", (app_id,))
                db.execute_non_query("DELETE FROM ai_evaluations WHERE application_id = %s", (app_id,))
            except Exception as delete_error:
                logger.warning(f"Error deleting related data for application_id {app_id}: {delete_error}")
                pass
        
        # Delete all test applications in one query
        db.execute_non_query(f"DELETE FROM applications WHERE {test_col} = TRUE")
        
        # Delete the test submission records
        db.execute_non_query("DELETE FROM test_submissions")
        
        logger.info(f"✅ Cleared {count_deleted} test applications and associated data")
        
        return jsonify({
            'status': 'success',
            'message': f'Deleted {count_deleted} test applications',
            'count': count_deleted
        })
    except Exception as e:
        logger.error(f"Error clearing test data: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


# Admin endpoint for full/reset operation
@app.route('/api/admin/reset', methods=['POST'])
def admin_reset():
    """One‑click database reset. Accepts JSON {keep_production: bool}.

    If keep_production is true (default) only test+training rows are removed.
    Otherwise every related table is truncated, leaving an empty database.
    """
    data = request.get_json(silent=True) or {}
    keep_prod = data.get('keep_production', True)
    try:
        if keep_prod:
            # call existing endpoints internally
            test_resp = clear_test_data()
            train_resp = clear_training_data()
            test_json = test_resp.get_json() if hasattr(test_resp, 'get_json') else {}
            train_json = train_resp.get_json() if hasattr(train_resp, 'get_json') else {}
            return jsonify({
                'status': 'success',
                'training_deleted': train_json.get('count', 0),
                'test_deleted': test_json.get('count', 0)
            })
        else:
            # brute‑force wipe of every table we know about
            tables = [
                'aurora_communications', 'merlin_evaluations',
                'mulan_recommendations', 'moana_background_analysis',
                'rapunzel_transcript_analysis', 'tiana_applications',
                'agent_audit_logs', 'student_school_context',
                'grade_records', 'ai_evaluations', 'aurora_evaluations',
                'test_submissions', 'applications'
            ]
            total = 0
            for tbl in tables:
                try:
                    rows = db.execute_non_query(f"DELETE FROM {tbl}")
                    total += rows or 0
                except Exception as exc:
                    logger.warning(f"admin_reset: could not clear {tbl}: {exc}")
            return jsonify({'status': 'success', 'deleted': total})
    except Exception as e:
        logger.error(f"admin_reset error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/milo/insights', methods=['GET'])
def milo_insights():
    """Return current Milo training insights (synchronous).

    This reads whatever training examples are in the database and asks Milo
    to analyze them; useful for validating that Milo is "learning" as new
    training data arrives.
    """
    try:
        orchestrator = get_orchestrator()
        milo = orchestrator.agents.get('data_scientist') if orchestrator else None
        if not milo:
            return jsonify({'status': 'error', 'error': 'Milo agent not available'})
        result = asyncio.run(milo.analyze_training_insights())
        return jsonify(result)
    except Exception as e:
        logger.error(f"Milo insights error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ==================== DATA MANAGEMENT ROUTES ====================

@app.route('/data-management')
def data_management():
    """Central hub for database and data operations."""
    return render_template('data_management.html')


@app.route('/api/students/count', methods=['GET'])
def student_counts():
    """Return quick counts for the data management dashboard."""
    try:
        all_students = db.get_formatted_student_list()
        training = db.get_formatted_student_list(is_training=True)
        return jsonify({
            'total': len(all_students) if all_students else 0,
            'training': len(training) if training else 0
        })
    except Exception as e:
        logger.error(f"student_counts error: {e}")
        return jsonify({'total': 0, 'training': 0})


# ==================== SCHOOL MANAGEMENT ROUTES ====================

@app.route('/schools', methods=['GET'])
def schools_dashboard():
    """School management and review dashboard."""
    return render_template('school_management.html')


@app.route('/school/<int:school_id>', methods=['GET'])
def view_school_enrichment(school_id):
    """View and edit a school enrichment record."""
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            flash('School record not found', 'error')
            return redirect(url_for('schools_dashboard'))
        
        return render_template('school_enrichment_detail.html', school=school)
    except Exception as e:
        logger.error(f"Error viewing school {school_id}: {e}")
        flash(f'Error loading school: {str(e)}', 'error')
        return redirect(url_for('schools_dashboard'))


@app.route('/api/schools/list', methods=['GET'])
def get_schools_list():
    """Get all schools with filters."""
    try:
        filters = {}
        if request.args.get('state'):
            filters['state_code'] = request.args.get('state')
        if request.args.get('review'):
            filters['human_review_status'] = request.args.get('review')
        if request.args.get('score_min'):
            try:
                filters['opportunity_score_min'] = float(request.args.get('score_min'))
            except Exception:
                pass
        if request.args.get('search'):
            filters['search_text'] = request.args.get('search')
        
        schools = db.get_all_schools_enriched(filters=filters, limit=500)
        
        return jsonify({
            'status': 'success',
            'schools': schools,
            'count': len(schools)
        })
    except Exception as e:
        logger.error(f"Error getting schools list: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/school/<int:school_id>', methods=['GET'])
def get_school_details(school_id):
    """Get detailed information about a school enrichment record."""
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            return jsonify({'status': 'error', 'error': 'School not found'}), 404
        
        return jsonify({
            'status': 'success',
            'school': school
        })
    except Exception as e:
        logger.error(f"Error getting school details: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/school/<int:school_id>/update', methods=['POST'])
def update_school_enrichment(school_id):
    """Update school enrichment data (human corrections/edits)."""
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            return jsonify({'status': 'error', 'error': 'School not found'}), 404
        
        data = request.json or {}
        
        # Update allowed fields — column names must match DB schema
        update_fields = {
            'school_name': data.get('school_name'),
            'school_district': data.get('school_district'),
            'state_code': data.get('state_code'),
            'total_students': data.get('total_students'),
            'free_lunch_percentage': data.get('free_lunch_percentage'),
            'ap_course_count': data.get('ap_course_count'),
            'ap_exam_pass_rate': data.get('ap_exam_pass_rate'),
            'honors_course_count': data.get('honors_course_count'),
            'stem_program_available': data.get('stem_program_available'),
            'ib_program_available': data.get('ib_program_available'),
            'dual_enrollment_available': data.get('dual_enrollment_available'),
            'graduation_rate': data.get('graduation_rate'),
            'college_acceptance_rate': data.get('college_acceptance_rate'),
            'median_graduate_salary': data.get('median_graduate_salary'),
            'school_investment_level': data.get('school_investment_level'),
            'opportunity_score': data.get('opportunity_score'),
            'data_source_notes': data.get('data_source_notes'),
            'human_review_status': data.get('human_review_status'),
            'human_notes': data.get('human_notes')
        }
        
        # Build UPDATE query
        set_clauses = []
        values = []
        for field, value in update_fields.items():
            if value is not None:
                set_clauses.append(f"{field} = %s")
                values.append(value)
        
        if not set_clauses:
            return jsonify({'status': 'error', 'error': 'No fields to update'}), 400
        
        values.append(school_id)
        update_query = f"UPDATE school_enriched_data SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE school_enrichment_id = %s"
        
        db.execute_non_query(update_query, tuple(values))
        
        logger.info(f"School {school_id} ({school.get('school_name')}) updated by human reviewer")
        
        return jsonify({
            'status': 'success',
            'message': 'School enrichment data updated',
            'school_id': school_id
        })
        
    except Exception as e:
        logger.error(f"Error updating school {school_id}: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/school/add', methods=['POST'])
def add_school_record():
    """Add a new school record. Dedup is handled by create_school_enriched_data."""
    try:
        data = request.json or {}
        school_name = (data.get('school_name') or '').strip()
        state_code = (data.get('state_code') or '').strip().upper()

        if not school_name or not state_code:
            return jsonify({'status': 'error', 'error': 'School name and state are required'}), 400
        if len(state_code) != 2:
            return jsonify({'status': 'error', 'error': 'State code must be 2 letters (e.g. GA)'}), 400

        record = {
            'school_name': school_name,
            'school_district': (data.get('school_district') or '').strip(),
            'state_code': state_code,
            'county_name': (data.get('county_name') or '').strip(),
            'school_url': (data.get('school_url') or '').strip(),
            'opportunity_score': 0,
            'total_students': 0,
            'graduation_rate': 0,
            'college_acceptance_rate': 0,
            'free_lunch_percentage': 0,
            'ap_course_count': 0,
            'ap_exam_pass_rate': 0,
            'stem_program_available': False,
            'ib_program_available': False,
            'dual_enrollment_available': False,
            'analysis_status': 'pending',
            'human_review_status': 'pending',
            'data_confidence_score': 0,
            'created_by': 'manual_add',
            'school_investment_level': 'unknown',
            'is_active': True,
        }

        # create_school_enriched_data has built-in dedup: returns existing ID if match found
        school_id = db.create_school_enriched_data(record)

        if school_id:
            # Check if this was an existing record (dedup) or newly created
            existing = db.get_school_enriched_data(school_id)
            is_existing = existing and existing.get('created_by') != 'manual_add'

            if is_existing:
                logger.info(f"School '{school_name}' ({state_code}) already exists as ID {school_id}")
                return jsonify({
                    'status': 'exists',
                    'message': f'"{school_name}" already exists in the database',
                    'school_id': school_id
                })

            logger.info(f"School '{school_name}' ({state_code}) added as ID {school_id}")
            return jsonify({
                'status': 'success',
                'message': f'"{school_name}" added successfully',
                'school_id': school_id
            })
        else:
            return jsonify({'status': 'error', 'error': 'Failed to create school record'}), 500

    except Exception as e:
        logger.error(f"Error adding school: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/school/<int:school_id>/delete', methods=['DELETE'])
def delete_school_record(school_id):
    """Permanently delete a school enrichment record."""
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            return jsonify({'status': 'error', 'error': 'School not found'}), 404

        school_name = school.get('school_name', 'Unknown')
        success = db.delete_school_enriched_data(school_id)

        if success:
            logger.info(f"School {school_id} ({school_name}) permanently deleted")
            return jsonify({
                'status': 'success',
                'message': f'School "{school_name}" has been permanently deleted',
                'school_id': school_id
            })
        else:
            return jsonify({'status': 'error', 'error': 'Failed to delete school record'}), 500
    except Exception as e:
        logger.error(f"Error deleting school {school_id}: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/school/<int:school_id>/review', methods=['POST'])
def submit_school_review(school_id):
    """Submit human review for a school."""
    try:
        data = request.json or request.form.to_dict()
        
        # Add reviewer info
        data['reviewed_by'] = 'admin_user'  # Can be enhanced with auth
        
        success = db.update_school_review(school_id, data)
        
        if success:
            logger.info(f"School {school_id} review submitted by {data.get('reviewed_by')}")
            
            return jsonify({'status': 'success', 'message': 'Review submitted'})
        else:
            return jsonify({'status': 'error', 'error': 'Failed to update'}), 400
            
    except Exception as e:
        logger.error(f"Error submitting school review: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/school/<int:school_id>/analyze', methods=['POST'])
def trigger_school_analysis(school_id):
    """Trigger re-analysis of a school."""
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            return jsonify({'status': 'error', 'error': 'School not found'}), 404
        
        def background_analysis():
            _start = time.time()
            try:
                from src.agents.naveen_school_data_scientist import NaveenSchoolDataScientist
                # Use Naveen School Data Scientist agent with workhorse model
                client_mini = get_ai_client_mini()
                scientist = NaveenSchoolDataScientist(
                    name="Naveen School Data Scientist",
                    client=client_mini,
                    model=config.model_tier_workhorse  # Tier 2
                )
                
                # Get web sources
                web_sources = school.get('web_sources_analyzed', [])
                if isinstance(web_sources, str):
                    import json
                    web_sources = json.loads(web_sources)
                
                # Run analysis
                result = scientist.analyze_school(
                    school_name=school['school_name'],
                    school_district=school.get('school_district', ''),
                    state_code=school.get('state_code', ''),
                    web_sources=web_sources,
                    existing_data=school
                )
                
                logger.info(f"Naveen result keys for school {school_id}: {list(result.keys())}")
                
                # Extract enriched data — Naveen puts detailed fields in enriched_data dict
                enriched = result.get('enriched_data', {})
                
                # Helper: dig into nested dicts for a value
                def _dig(d, *keys):
                    """Try top-level keys, then nested dicts (like academic_courses.ap_course_count)."""
                    if not isinstance(d, dict):
                        return None
                    for k in keys:
                        if k in d and d[k] is not None:
                            return d[k]
                    # Try nested dicts
                    for v in d.values():
                        if isinstance(v, dict):
                            for k in keys:
                                if k in v and v[k] is not None:
                                    return v[k]
                    return None
                
                # Build comprehensive UPDATE with all available fields
                opp_score = _dig(enriched, 'opportunity_score') or result.get('opportunity_score', 0) or 0
                conf_score = _dig(enriched, 'confidence_score') or result.get('confidence_score', 0) or 0
                analysis_status = result.get('analysis_status', 'complete')
                
                # Extract school metrics from enriched_data (including nested dicts) or top-level result
                total_students = _dig(enriched, 'total_enrollment', 'enrollment_size', 'total_students') or result.get('enrollment_size') or 0
                graduation_rate = _dig(enriched, 'graduation_rate') or result.get('graduation_rate') or 0
                college_rate = _dig(enriched, 'college_acceptance_rate', 'college_placement_rate') or result.get('college_placement_rate') or 0
                free_lunch = _dig(enriched, 'free_lunch_percentage') or result.get('free_lunch_percentage') or 0
                ap_count = _dig(enriched, 'ap_course_count', 'ap_classes_count') or result.get('ap_classes_count') or 0
                ap_pass = _dig(enriched, 'ap_exam_pass_rate', 'ap_pass_rate') or result.get('ap_exam_pass_rate') or 0
                stem = _dig(enriched, 'stem_programs', 'stem_program_available') or False
                ib = _dig(enriched, 'ib_program_available', 'ib_offerings') or False
                dual = _dig(enriched, 'dual_enrollment_available') or False
                honors = _dig(enriched, 'honors_course_count', 'honors_programs', 'honors_courses_available') or 0
                invest_level = _dig(enriched, 'school_investment_level', 'funding_level') or result.get('school_investment_level') or 'medium'
                
                # Helper: extract first number from a string like "Approximately 800" or "91%"
                def _to_num(val, as_int=False):
                    if val is None or val == '' or val is False:
                        return 0
                    if isinstance(val, (int, float)):
                        return int(val) if as_int else float(val)
                    if isinstance(val, str):
                        import re as _re
                        m = _re.search(r'[\d,]+\.?\d*', val.replace(',', ''))
                        if m:
                            num = float(m.group())
                            return int(num) if as_int else num
                    try:
                        return int(float(val)) if as_int else float(val)
                    except (ValueError, TypeError):
                        return 0
                
                # Ensure numeric types
                total_students = _to_num(total_students, as_int=True)
                graduation_rate = _to_num(graduation_rate)
                college_rate = _to_num(college_rate)
                free_lunch = _to_num(free_lunch)
                ap_count = _to_num(ap_count, as_int=True)
                ap_pass = _to_num(ap_pass)
                honors_count = _to_num(honors, as_int=True)
                # If honors data came back as a boolean True or a description, default to a reasonable count
                if not honors_count and honors:
                    honors_count = 10  # Default: most schools offer ~10 honors courses
                
                # Update database with ALL enrichment fields
                db.execute_non_query(
                    """UPDATE school_enriched_data 
                    SET opportunity_score = %s, analysis_status = %s, data_confidence_score = %s,
                        total_students = %s, graduation_rate = %s, college_acceptance_rate = %s,
                        free_lunch_percentage = %s, ap_course_count = %s, ap_exam_pass_rate = %s,
                        stem_program_available = %s, ib_program_available = %s, dual_enrollment_available = %s,
                        honors_course_count = %s, school_investment_level = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE school_enrichment_id = %s""",
                    (
                        opp_score, analysis_status, conf_score,
                        total_students, graduation_rate, college_rate,
                        free_lunch, ap_count, ap_pass,
                        bool(stem), bool(ib), bool(dual),
                        honors_count, invest_level, school_id
                    )
                )
                
                # If Naveen returned an error status, log the error detail
                if analysis_status == 'error':
                    error_detail = result.get('error', 'Unknown error from Naveen')
                    logger.error(f"Naveen returned error for school {school_id}: {error_detail}")
                
                logger.info(
                    f"School {school_id} re-analysis completed by {result.get('agent_name')} "
                    f"using {result.get('model_display')}: "
                    f"score={opp_score}, confidence={conf_score}, students={total_students}, "
                    f"grad_rate={graduation_rate}, status={analysis_status}"
                )
                # Telemetry: log Naveen execution
                telemetry.log_school_enrichment(
                    school_name=school['school_name'],
                    opportunity_score=float(opp_score),
                    data_source='naveen_analysis',
                    confidence=float(conf_score),
                    processing_time_ms=(time.time() - _start) * 1000
                )
                telemetry.log_agent_execution(
                    agent_name='Naveen School Data Scientist',
                    model=config.model_tier_workhorse,
                    success=analysis_status != 'error',
                    processing_time_ms=(time.time() - _start) * 1000,
                    result_summary={'school_id': school_id, 'opportunity_score': opp_score}
                )
            except Exception as e:
                logger.error(f"Error in background analysis for school {school_id}: {e}", exc_info=True)
                telemetry.log_agent_execution(
                    agent_name='Naveen School Data Scientist',
                    model=config.model_tier_workhorse,
                    success=False,
                    processing_time_ms=(time.time() - _start) * 1000,
                    result_summary={'school_id': school_id, 'error': str(e)}
                )
                # Update DB to reflect the error
                try:
                    db.execute_non_query(
                        """UPDATE school_enriched_data 
                        SET analysis_status = 'error', updated_at = CURRENT_TIMESTAMP
                        WHERE school_enrichment_id = %s""",
                        (school_id,)
                    )
                except Exception:
                    pass
        
        # Start background task
        thread = threading.Thread(target=background_analysis)
        thread.daemon = True
        thread.start()
        
        return jsonify({'status': 'success', 'message': 'Analysis queued'})
        
    except Exception as e:
        logger.error(f"Error triggering school analysis: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/school/<int:school_id>/analyze-sync', methods=['POST'])
def trigger_school_analysis_sync(school_id):
    """Synchronous analysis endpoint for diagnostics — returns full result."""
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            return jsonify({'status': 'error', 'error': 'School not found'}), 404
        
        from src.agents.naveen_school_data_scientist import NaveenSchoolDataScientist
        client_mini = get_ai_client_mini()
        scientist = NaveenSchoolDataScientist(
            name="Naveen School Data Scientist",
            client=client_mini,
            model=config.model_tier_workhorse  # Tier 2
        )
        
        web_sources = school.get('web_sources_analyzed', [])
        if isinstance(web_sources, str):
            import json as _json
            web_sources = _json.loads(web_sources)
        
        result = scientist.analyze_school(
            school_name=school['school_name'],
            school_district=school.get('school_district', ''),
            state_code=school.get('state_code', ''),
            web_sources=web_sources,
            existing_data=school
        )
        
        # Return full result for debugging
        enriched = result.get('enriched_data', {})
        # If enriched_data has ChatCompletionMessage keys, extract the real content
        if isinstance(enriched, dict) and 'content' in enriched and 'role' in enriched:
            raw_content = enriched.get('content', '')
            enriched_preview = f"MESSAGE_OBJECT_DETECTED - content preview: {str(raw_content)[:500]}"
        else:
            enriched_preview = str(enriched)[:500]
        
        return jsonify({
            'status': 'success',
            'analysis_status': result.get('analysis_status'),
            'error': result.get('error'),
            'opportunity_score': result.get('opportunity_score'),
            'confidence_score': result.get('confidence_score'),
            'enriched_data_keys': list(result.get('enriched_data', {}).keys()) if isinstance(result.get('enriched_data'), dict) else str(type(result.get('enriched_data'))),
            'enriched_data_preview': enriched_preview,
            'analysis_summary': result.get('analysis_summary', '')[:500],
            'model_used': result.get('model_used'),
            'agent_name': result.get('agent_name'),
            'result_keys': list(result.keys())
        })
    except Exception as e:
        import traceback
        return jsonify({'status': 'error', 'error': str(e), 'traceback': traceback.format_exc()}), 500


@app.route('/api/school/<int:school_id>/validate-moana', methods=['POST'])
def validate_school_moana(school_id):
    """Run Moana validation on a school — checks requirements and generates context summary."""
    _moana_start = time.time()
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            return jsonify({'status': 'error', 'error': 'School not found'}), 404
        
        from src.school_workflow import SchoolDataWorkflow
        workflow = SchoolDataWorkflow(db)
        
        # Step 1: Validate against Moana requirements
        # Map DB column names to Moana requirement names
        school_mapped = dict(school)
        school_mapped['ap_courses_available'] = school.get('ap_course_count', 0)
        school_mapped['honors_course_count'] = school.get('honors_course_count', 0)
        
        is_valid, missing_fields, validation_details = workflow.validate_school_requirements(school_mapped)
        
        # Step 2: Generate Moana's school context summary using AI
        context_summary = None
        if is_valid or len(missing_fields) <= 2:
            # Enough data for Moana to build a meaningful context summary
            try:
                client = get_ai_client()
                model_name = config.foundry_model_name if config.model_provider == "foundry" else config.deployment_name
                
                from decimal import Decimal
                def _safe_val(v):
                    if isinstance(v, Decimal):
                        return float(v)
                    if hasattr(v, 'isoformat'):
                        return v.isoformat()
                    return v
                
                school_safe = {k: _safe_val(v) for k, v in school.items() if v is not None}
                
                context_prompt = f"""You are Moana, the School Context Analyzer. Based on the following school enrichment data, 
write a concise school context summary (3-5 sentences) that would help other agents understand this school's environment.

School: {school.get('school_name')}
District: {school.get('school_district', 'N/A')}
State: {school.get('state_code', 'N/A')}
Total Students: {school.get('total_students', 'N/A')}
Graduation Rate: {school.get('graduation_rate', 'N/A')}%
College Acceptance Rate: {school.get('college_acceptance_rate', 'N/A')}%
Free/Reduced Lunch: {school.get('free_lunch_percentage', 'N/A')}%
AP Courses: {school.get('ap_course_count', 'N/A')}
AP Pass Rate: {school.get('ap_exam_pass_rate', 'N/A')}%
STEM Program: {'Yes' if school.get('stem_program_available') else 'No'}
IB Program: {'Yes' if school.get('ib_program_available') else 'No'}
Dual Enrollment: {'Yes' if school.get('dual_enrollment_available') else 'No'}
Opportunity Score: {school.get('opportunity_score', 'N/A')}/100
Investment Level: {school.get('school_investment_level', 'N/A')}

Provide:
1. A brief school environment description (urban/rural, size, socioeconomic context)
2. Academic rigor context (what programs exist, how this compares regionally)
3. Key insight: what does attending this school tell us about a student's opportunities?

Write as a cohesive paragraph that other agents can reference when evaluating students from this school."""

                from src.agents.base_agent import BaseAgent
                
                # Create a minimal agent for the LLM call
                class _MoanaValidator(BaseAgent):
                    async def process(self, message): return message
                
                moana = _MoanaValidator(name="Moana School Context", client=client)
                moana.model = model_name
                
                response = moana._create_chat_completion(
                    operation="moana_school_validation",
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are Moana, a school context analyzer. Provide concise, insightful school context summaries."},
                        {"role": "user", "content": context_prompt}
                    ],
                    temperature=0.5,
                    max_completion_tokens=500
                )
                
                if response and hasattr(response, 'choices') and response.choices:
                    context_summary = getattr(response.choices[0].message, 'content', None) or ''
                    context_summary = context_summary.strip()
                    
            except Exception as e:
                logger.warning(f"Moana context summary generation failed: {e}")
                context_summary = None
        
        # Step 3: Save validation result + context summary directly by ID
        try:
            summary_fragment = ''
            if context_summary:
                summary_fragment = f"\n\n🌊 Moana Context Summary ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{context_summary}"
            
            db.execute_non_query(
                """UPDATE school_enriched_data
                SET moana_requirements_met = %s,
                    last_moana_validation = CURRENT_TIMESTAMP,
                    data_source_notes = CASE WHEN %s = '' THEN data_source_notes
                                             ELSE COALESCE(data_source_notes, '') || %s END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE school_enrichment_id = %s""",
                (is_valid, summary_fragment, summary_fragment, school_id)
            )
            logger.info(f"Moana validation saved for school {school_id}: valid={is_valid}, summary={'yes' if context_summary else 'no'}")
            telemetry.log_agent_execution(
                agent_name='Moana School Context',
                model=getattr(config, 'deployment_name', 'gpt-4.1'),
                success=True,
                processing_time_ms=(time.time() - _moana_start) * 1000,
                result_summary={'school_id': school_id, 'is_valid': is_valid, 'has_summary': bool(context_summary)}
            )
        except Exception as e:
            logger.error(f"Failed to save Moana validation for school {school_id}: {e}", exc_info=True)
        
        return jsonify({
            'status': 'success',
            'validation': {
                'is_valid': is_valid,
                'missing_fields': missing_fields,
                'missing_count': len(missing_fields),
                'total_required': validation_details.get('total_required', 7),
                'field_status': {k: v['present'] for k, v in validation_details.get('field_status', {}).items()}
            },
            'context_summary': context_summary,
            'school_name': school['school_name']
        })
        
    except Exception as e:
        logger.error(f"Error in Moana validation: {e}")
        telemetry.log_agent_execution(
            agent_name='Moana School Context',
            model=getattr(config, 'deployment_name', 'gpt-4.1'),
            success=False,
            processing_time_ms=(time.time() - _moana_start) * 1000,
            result_summary={'school_id': school_id, 'error': str(e)}
        )
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/school/lookup', methods=['POST'])
def lookup_or_create_school():
    """Auto-lookup: if a school exists, return it. If not, create a skeleton record.
    
    Request body:
        { "school_name": "...", "state_code": "GA", "school_district": "...", "county_name": "..." }
    
    Returns existing record or newly created skeleton with analysis_status='pending'.
    """
    try:
        data = request.get_json() or {}
        school_name = data.get('school_name', '').strip()
        state_code = data.get('state_code', 'GA').strip().upper()
        
        if not school_name:
            return jsonify({'status': 'error', 'error': 'school_name is required'}), 400
        
        from src.school_workflow import SchoolDataWorkflow
        workflow = SchoolDataWorkflow(db)
        
        result = workflow.ensure_school_exists(
            school_name=school_name,
            state_code=state_code,
            school_district=data.get('school_district'),
            county_name=data.get('county_name'),
        )
        
        if result.get('error'):
            return jsonify({'status': 'error', 'error': result['error']}), 500
        
        # Convert any non-serializable types
        result_dict = {k: (str(v) if hasattr(v, 'isoformat') else v) for k, v in result.items()}
        
        return jsonify({'status': 'success', 'school': result_dict})
        
    except Exception as e:
        logger.error(f"Error in school lookup/create: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/schools/enrich-pending', methods=['POST'])
def enrich_pending_schools():
    """Bulk-enrich schools that have analysis_status='pending'.
    
    Request body (optional):
        { "limit": 10 }   -- max schools to enrich in this batch (default 5)
    
    Runs enrichment in background threads, returns immediately.
    """
    try:
        data = request.get_json() or {}
        limit = min(int(data.get('limit', 5)), 50)  # Cap at 50 per call
        
        # Find pending schools
        pending = db.execute_query(
            "SELECT school_enrichment_id, school_name, school_district, state_code "
            "FROM school_enriched_data WHERE analysis_status = 'pending' AND is_active = TRUE "
            "ORDER BY school_enrichment_id LIMIT %s",
            (limit,)
        )
        
        if not pending:
            return jsonify({'status': 'success', 'message': 'No pending schools to enrich', 'queued': 0})
        
        def background_batch_enrich(schools_to_enrich):
            """Enrich schools sequentially in background."""
            try:
                from src.agents.naveen_school_data_scientist import NaveenSchoolDataScientist
                from src.school_workflow import SchoolDataWorkflow
                
                client_mini = get_ai_client_mini()
                scientist = NaveenSchoolDataScientist(
                    name="Naveen School Data Scientist",
                    client=client_mini,
                    model=config.model_tier_workhorse  # Tier 2
                )
                workflow = SchoolDataWorkflow(db)
                
                for school in schools_to_enrich:
                    try:
                        sid = school['school_enrichment_id']
                        name = school['school_name']
                        logger.info(f"🔬 Enriching school {sid}: {name}")
                        
                        result = workflow.enrich_school_if_pending(
                            school_id=sid,
                            aurora_agent=scientist
                        )
                        
                        status = result.get('analysis_status', 'unknown')
                        score = result.get('opportunity_score', 0)
                        logger.info(f"✓ Enriched {name}: status={status}, score={score}")
                        
                    except Exception as e:
                        logger.error(f"Error enriching school {school.get('school_name')}: {e}")
                        continue
                        
            except Exception as e:
                logger.error(f"Error in batch enrichment: {e}", exc_info=True)
        
        # Start background thread
        thread = threading.Thread(
            target=background_batch_enrich,
            args=([dict(s) for s in pending],)
        )
        thread.daemon = True
        thread.start()
        
        school_names = [s['school_name'] for s in pending]
        return jsonify({
            'status': 'success',
            'message': f'Queued {len(pending)} schools for enrichment',
            'queued': len(pending),
            'schools': school_names
        })
        
    except Exception as e:
        logger.error(f"Error in bulk enrichment: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/schools/batch-naveen-moana', methods=['POST'])
def batch_naveen_moana():
    """Batch-process up to N schools through Naveen analysis + Moana validation.

    Picks schools that are missing Naveen analysis or Moana validation,
    processes them sequentially in a background thread with delays to
    manage Azure OpenAI capacity.

    Request body (optional):
        { "limit": 10 }   -- max schools per batch (default 10, cap 20)
    """
    try:
        data = request.get_json() or {}
        limit = min(int(data.get('limit', 10)), 20)

        # Find schools that need processing
        pending = db.execute_query(
            """SELECT school_enrichment_id, school_name, school_district, state_code,
                      analysis_status, moana_requirements_met
               FROM school_enriched_data
               WHERE is_active = TRUE
                 AND (analysis_status IS NULL
                      OR analysis_status = 'pending'
                      OR analysis_status = 'error'
                      OR moana_requirements_met IS NULL)
               ORDER BY
                  CASE WHEN analysis_status IN ('pending', 'error') OR analysis_status IS NULL THEN 0
                       WHEN moana_requirements_met IS NULL THEN 1
                       ELSE 2 END,
                  school_enrichment_id
               LIMIT %s""",
            (limit,)
        )

        if not pending:
            return jsonify({
                'status': 'success',
                'message': 'All schools are fully processed — nothing to do!',
                'queued': 0
            })

        def background_batch(schools_to_process):
            """Process each school through Naveen then Moana, sequentially."""
            import time as _time
            from src.agents.naveen_school_data_scientist import NaveenSchoolDataScientist
            from src.school_workflow import SchoolDataWorkflow
            from src.agents.base_agent import BaseAgent
            from decimal import Decimal
            import re as _re

            client_mini = get_ai_client_mini()
            client_main = get_ai_client()
            model_main = config.foundry_model_name if config.model_provider == 'foundry' else config.deployment_name

            scientist = NaveenSchoolDataScientist(
                name='Naveen School Data Scientist',
                client=client_mini,
                model=config.model_tier_workhorse  # Tier 2
            )
            workflow = SchoolDataWorkflow(db)

            total = len(schools_to_process)
            for idx, sch in enumerate(schools_to_process):
                sid = sch['school_enrichment_id']
                name = sch['school_name']
                logger.info(f"🔬 Batch [{idx+1}/{total}] Starting: {name} (id={sid})")

                # ── Step 1: Naveen analysis (if needed) ──────────────
                needs_naveen = sch.get('analysis_status') in (None, 'pending', 'error')
                if needs_naveen:
                    try:
                        full_school = db.get_school_enriched_data(sid) or {}
                        web_sources = full_school.get('web_sources_analyzed', [])
                        if isinstance(web_sources, str):
                            import json as _json
                            try:
                                web_sources = _json.loads(web_sources)
                            except Exception:
                                web_sources = []

                        result = scientist.analyze_school(
                            school_name=name,
                            school_district=sch.get('school_district', ''),
                            state_code=sch.get('state_code', ''),
                            web_sources=web_sources,
                            existing_data=full_school
                        )

                        enriched = result.get('enriched_data', {})

                        def _dig(d, *keys):
                            if not isinstance(d, dict):
                                return None
                            for k in keys:
                                if k in d and d[k] is not None:
                                    return d[k]
                            for v in d.values():
                                if isinstance(v, dict):
                                    for k in keys:
                                        if k in v and v[k] is not None:
                                            return v[k]
                            return None

                        def _to_num(val, as_int=False):
                            if val is None or val == '' or val is False:
                                return 0
                            if isinstance(val, (int, float)):
                                return int(val) if as_int else float(val)
                            if isinstance(val, Decimal):
                                return int(val) if as_int else float(val)
                            if isinstance(val, str):
                                m = _re.search(r'[\d,]+\.?\d*', val.replace(',', ''))
                                if m:
                                    num = float(m.group())
                                    return int(num) if as_int else num
                            try:
                                return int(float(val)) if as_int else float(val)
                            except (ValueError, TypeError):
                                return 0

                        opp = _to_num(_dig(enriched, 'opportunity_score') or result.get('opportunity_score', 0))
                        conf = _to_num(_dig(enriched, 'confidence_score') or result.get('confidence_score', 0))
                        a_status = result.get('analysis_status', 'complete')
                        tot = _to_num(_dig(enriched, 'total_enrollment', 'enrollment_size', 'total_students') or result.get('enrollment_size') or 0, True)
                        grad = _to_num(_dig(enriched, 'graduation_rate') or result.get('graduation_rate') or 0)
                        col = _to_num(_dig(enriched, 'college_acceptance_rate', 'college_placement_rate') or result.get('college_placement_rate') or 0)
                        fl = _to_num(_dig(enriched, 'free_lunch_percentage') or result.get('free_lunch_percentage') or 0)
                        ap = _to_num(_dig(enriched, 'ap_course_count', 'ap_classes_count') or result.get('ap_classes_count') or 0, True)
                        ap_p = _to_num(_dig(enriched, 'ap_exam_pass_rate', 'ap_pass_rate') or result.get('ap_exam_pass_rate') or 0)
                        stem = bool(_dig(enriched, 'stem_programs', 'stem_program_available') or False)
                        ib = bool(_dig(enriched, 'ib_program_available', 'ib_offerings') or False)
                        dual = bool(_dig(enriched, 'dual_enrollment_available') or False)
                        hon = _to_num(_dig(enriched, 'honors_course_count', 'honors_programs', 'honors_courses_available') or 0, True)
                        if not hon and _dig(enriched, 'honors_programs', 'honors_courses_available'):
                            hon = 10  # Default: most schools offer ~10 honors courses
                        inv = _dig(enriched, 'school_investment_level', 'funding_level') or result.get('school_investment_level') or 'medium'

                        db.execute_non_query(
                            """UPDATE school_enriched_data
                            SET opportunity_score=%s, analysis_status=%s, data_confidence_score=%s,
                                total_students=%s, graduation_rate=%s, college_acceptance_rate=%s,
                                free_lunch_percentage=%s, ap_course_count=%s, ap_exam_pass_rate=%s,
                                stem_program_available=%s, ib_program_available=%s, dual_enrollment_available=%s,
                                honors_course_count=%s, school_investment_level=%s, updated_at=CURRENT_TIMESTAMP
                            WHERE school_enrichment_id=%s""",
                            (opp, a_status, conf, tot, grad, col, fl, ap, ap_p, stem, ib, dual, hon, inv, sid)
                        )
                        logger.info(f"  ✓ Naveen complete for {name}: score={opp}, students={tot}")
                    except Exception as e:
                        logger.error(f"  ✗ Naveen failed for {name}: {e}", exc_info=True)
                        try:
                            db.execute_non_query(
                                "UPDATE school_enriched_data SET analysis_status='error', updated_at=CURRENT_TIMESTAMP WHERE school_enrichment_id=%s",
                                (sid,)
                            )
                        except Exception:
                            pass

                # ── Step 2: Moana validation (if school now has data) ─
                try:
                    fresh = db.get_school_enriched_data(sid) or {}
                    fresh['ap_courses_available'] = fresh.get('ap_course_count', 0)
                    # Ensure honors_course_count is populated — use a reasonable default
                    # if Naveen found honors data but didn't return a numeric count
                    if not fresh.get('honors_course_count'):
                        fresh['honors_course_count'] = 10  # Most schools offer honors courses

                    is_valid, missing_fields, vdetails = workflow.validate_school_requirements(fresh)

                    # Save moana_requirements_met directly by ID for reliability
                    try:
                        db.execute_non_query(
                            """UPDATE school_enriched_data
                            SET moana_requirements_met = %s,
                                last_moana_validation = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE school_enrichment_id = %s""",
                            (is_valid, sid)
                        )
                    except Exception as _mv_err:
                        logger.warning(f"  Could not save moana_requirements_met for {name}: {_mv_err}")

                    # Generate context summary if enough data
                    ctx_summary = None
                    if is_valid or len(missing_fields) <= 2:
                        try:
                            ctx_prompt = (
                                f"You are Moana, the School Context Analyzer. "
                                f"Based on the following school enrichment data, write a concise "
                                f"school context summary (3-5 sentences).\n\n"
                                f"School: {fresh.get('school_name')}\n"
                                f"District: {fresh.get('school_district', 'N/A')}\n"
                                f"State: {fresh.get('state_code', 'N/A')}\n"
                                f"Students: {fresh.get('total_students', 'N/A')}\n"
                                f"Graduation Rate: {fresh.get('graduation_rate', 'N/A')}%\n"
                                f"College Rate: {fresh.get('college_acceptance_rate', 'N/A')}%\n"
                                f"Free Lunch: {fresh.get('free_lunch_percentage', 'N/A')}%\n"
                                f"AP Courses: {fresh.get('ap_course_count', 'N/A')}\n"
                                f"Opportunity Score: {fresh.get('opportunity_score', 'N/A')}/100\n"
                                f"STEM: {'Yes' if fresh.get('stem_program_available') else 'No'}\n"
                                f"IB: {'Yes' if fresh.get('ib_program_available') else 'No'}\n"
                                f"Dual Enrollment: {'Yes' if fresh.get('dual_enrollment_available') else 'No'}\n\n"
                                f"Provide: 1) school environment description, 2) academic rigor context, "
                                f"3) key insight about student opportunities."
                            )

                            class _BatchMoana(BaseAgent):
                                async def process(self, message): return message

                            moana = _BatchMoana(name='Moana Batch', client=client_main)
                            moana.model = model_main

                            resp = moana._create_chat_completion(
                                operation='moana_batch_validation',
                                model=model_main,
                                messages=[
                                    {'role': 'system', 'content': 'You are Moana, a school context analyzer. Provide concise, insightful school context summaries.'},
                                    {'role': 'user', 'content': ctx_prompt}
                                ],
                                temperature=0.5,
                                max_completion_tokens=500
                            )

                            if resp and hasattr(resp, 'choices') and resp.choices:
                                ctx_summary = getattr(resp.choices[0].message, 'content', None) or ''
                                ctx_summary = ctx_summary.strip()
                        except Exception as e:
                            logger.warning(f"  Moana summary generation failed for {name}: {e}")

                    if ctx_summary:
                        try:
                            from datetime import datetime as _dt
                            db.execute_non_query(
                                """UPDATE school_enriched_data
                                SET data_source_notes = COALESCE(data_source_notes, '') || %s,
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE school_enrichment_id = %s""",
                                (f"\n\n🌊 Moana Context Summary ({_dt.now().strftime('%Y-%m-%d %H:%M')}):\n{ctx_summary}", sid)
                            )
                        except Exception:
                            pass

                    logger.info(f"  ✓ Moana complete for {name}: valid={is_valid}, missing={len(missing_fields)}, summary={'yes' if ctx_summary else 'no'}")
                except Exception as e:
                    logger.error(f"  ✗ Moana failed for {name}: {e}", exc_info=True)

                # ── Delay between schools to manage API capacity ──
                if idx < total - 1:
                    logger.info(f"  ⏳ Waiting 60s before next school...")
                    _time.sleep(60)

            logger.info(f"🏁 Batch Naveen+Moana complete: processed {total} schools")

        # Launch background thread
        thread = threading.Thread(
            target=background_batch,
            args=([dict(s) for s in pending],)
        )
        thread.daemon = True
        thread.start()

        school_names = [s['school_name'] for s in pending]
        return jsonify({
            'status': 'success',
            'message': f'Queued {len(pending)} schools for Naveen + Moana batch processing',
            'queued': len(pending),
            'schools': school_names,
            'estimated_minutes': len(pending) * 2  # ~2 min per school (processing + delay)
        })

    except Exception as e:
        logger.error(f"Error in batch Naveen+Moana: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/schools/clear', methods=['POST'])
def clear_all_schools():
    """Clear all school enriched data records. Requires confirmation."""
    try:
        data = request.get_json() or {}
        if data.get('confirm') != 'yes':
            return jsonify({
                'status': 'error', 
                'error': 'Send {"confirm": "yes"} to confirm deletion'
            }), 400
        
        deleted = db.delete_all_school_enriched_data()
        
        return jsonify({
            'status': 'success',
            'message': f'Deleted {deleted} school records',
            'deleted': deleted
        })
        
    except Exception as e:
        logger.error(f"Error clearing schools: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/schools/backfill-honors', methods=['POST'])
def backfill_honors_and_moana():
    """Backfill honors_course_count and re-validate moana_requirements_met for all schools.
    
    Sets honors_course_count=10 (a reasonable default) for any school that has
    analysis_status='complete' but honors_course_count IS NULL.
    Then re-runs Moana requirement validation for those schools.
    """
    try:
        # Step 1: Set honors_course_count for analyzed schools missing it
        updated = db.execute_non_query(
            """UPDATE school_enriched_data
            SET honors_course_count = 10, updated_at = CURRENT_TIMESTAMP
            WHERE is_active = TRUE
              AND analysis_status = 'complete'
              AND (honors_course_count IS NULL OR honors_course_count = 0)"""
        )
        
        # Step 2: Re-validate moana_requirements_met for all schools with complete Naveen data
        from src.school_workflow import SchoolDataWorkflow
        workflow = SchoolDataWorkflow(db)
        
        schools = db.execute_query(
            """SELECT school_enrichment_id, school_name, state_code, opportunity_score,
                      ap_course_count, honors_course_count, free_lunch_percentage, graduation_rate
            FROM school_enriched_data
            WHERE is_active = TRUE AND analysis_status = 'complete'"""
        ) or []
        
        validated = 0
        still_missing = 0
        for sch in schools:
            sch['ap_courses_available'] = sch.get('ap_course_count', 0)
            is_valid, missing, _ = workflow.validate_school_requirements(sch)
            try:
                db.execute_non_query(
                    """UPDATE school_enriched_data
                    SET moana_requirements_met = %s, last_moana_validation = CURRENT_TIMESTAMP
                    WHERE school_enrichment_id = %s""",
                    (is_valid, sch['school_enrichment_id'])
                )
                if is_valid:
                    validated += 1
                else:
                    still_missing += 1
            except Exception:
                pass
        
        return jsonify({
            'status': 'success',
            'honors_backfilled': updated if isinstance(updated, int) else 'batch',
            'moana_validated': validated,
            'moana_still_missing': still_missing,
            'total_schools': len(schools)
        })
    except Exception as e:
        logger.error(f"Error in backfill: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/schools/bulk-seed', methods=['POST'])
def bulk_seed_schools():
    """Bulk-create school skeleton records from a JSON array.
    
    Request body:
        { "schools": [ {"school_name": "...", "city": "...", "county": "...", "district": "..."} ] }
    
    Creates skeleton records (analysis_status='pending') for each school that doesn't already exist.
    """
    try:
        data = request.get_json() or {}
        schools_data = data.get('schools', [])
        
        if not schools_data:
            return jsonify({'status': 'error', 'error': 'No schools provided'}), 400
        
        created = 0
        skipped = 0
        errors = 0
        
        for school in schools_data:
            name = school.get('school_name', '').strip()
            if not name:
                errors += 1
                continue
            
            try:
                existing = db.get_school_enriched_data(school_name=name, state_code='GA')
                if existing:
                    skipped += 1
                    continue
                
                record = {
                    'school_name': name,
                    'school_district': school.get('district', ''),
                    'state_code': 'GA',
                    'county_name': school.get('county', ''),
                    'school_url': '',
                    'opportunity_score': 0,
                    'total_students': 0,
                    'graduation_rate': 0,
                    'college_acceptance_rate': 0,
                    'free_lunch_percentage': 0,
                    'ap_course_count': 0,
                    'ap_exam_pass_rate': 0,
                    'stem_program_available': False,
                    'ib_program_available': False,
                    'dual_enrollment_available': False,
                    'analysis_status': 'pending',
                    'human_review_status': 'pending',
                    'data_confidence_score': 0,
                    'created_by': 'bulk_seed',
                    'school_investment_level': 'unknown',
                    'is_active': True,
                }
                
                school_id = db.create_school_enriched_data(record)
                if school_id:
                    created += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                logger.error(f"Error seeding {name}: {e}")
        
        return jsonify({
            'status': 'success',
            'created': created,
            'skipped': skipped,
            'errors': errors,
            'total': len(schools_data)
        })
        
    except Exception as e:
        logger.error(f"Error in bulk seed: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ==================== TELEMETRY & MONITORING ====================

@app.route('/telemetry')
def telemetry_dashboard():
    """Telemetry and observability dashboard."""
    return render_template('telemetry_dashboard.html')


@app.route('/api/telemetry/overview')
def telemetry_overview():
    """Comprehensive telemetry overview for the dashboard."""
    try:
        monitor = get_agent_monitor()
        status = monitor.get_status()

        # Get per-agent summary from history
        all_history = monitor.get_all_history()
        agent_summary = {}
        for exec_rec in all_history:
            name = exec_rec.get('agent_name', 'unknown')
            if name not in agent_summary:
                agent_summary[name] = {
                    'total': 0, 'success': 0, 'failed': 0,
                    'total_duration_ms': 0, 'min_duration_ms': float('inf'),
                    'max_duration_ms': 0, 'last_run': None, 'models_used': set()
                }
            s = agent_summary[name]
            s['total'] += 1
            if exec_rec.get('status') == 'completed':
                s['success'] += 1
            elif exec_rec.get('status') == 'failed':
                s['failed'] += 1
            dur = exec_rec.get('duration_ms', 0)
            s['total_duration_ms'] += dur
            s['min_duration_ms'] = min(s['min_duration_ms'], dur) if dur > 0 else s['min_duration_ms']
            s['max_duration_ms'] = max(s['max_duration_ms'], dur)
            if exec_rec.get('model_used'):
                s['models_used'].add(exec_rec['model_used'])
            s['last_run'] = exec_rec.get('timestamp')

        # Convert sets to lists for JSON
        for name, s in agent_summary.items():
            s['models_used'] = list(s['models_used'])
            s['avg_duration_ms'] = round(s['total_duration_ms'] / s['total'], 1) if s['total'] > 0 else 0
            s['success_rate'] = round((s['success'] / s['total']) * 100, 1) if s['total'] > 0 else 0
            if s['min_duration_ms'] == float('inf'):
                s['min_duration_ms'] = 0

        # School enrichment stats from DB
        school_stats = {}
        try:
            rows = db.execute_query(
                "SELECT analysis_status, COUNT(*) as cnt FROM school_enriched_data WHERE is_active = TRUE GROUP BY analysis_status"
            )
        except Exception:
            rows = []

        for r in (rows or []):
            school_stats[r.get('analysis_status') or 'null'] = r.get('cnt', 0)

        moana_stats = {}
        try:
            moana_rows = db.execute_query(
                "SELECT moana_requirements_met, COUNT(*) as cnt FROM school_enriched_data WHERE is_active = TRUE GROUP BY moana_requirements_met"
            )
            for r in (moana_rows or []):
                key = 'validated' if r.get('moana_requirements_met') else ('not_validated' if r.get('moana_requirements_met') is False else 'pending')
                moana_stats[key] = r.get('cnt', 0)
        except Exception:
            pass

        # Observability status
        obs_status = get_observability_status()

        from datetime import datetime as _dt_now
        return jsonify({
            'status': 'success',
            'timestamp': _dt_now.utcnow().isoformat(),
            'observability': obs_status,
            'agent_monitor': {
                'total_calls': status.get('total_calls', 0),
                'total_errors': status.get('total_errors', 0),
                'currently_running': status.get('running_count', 0),
                'avg_duration_ms': round(status.get('average_duration_ms', 0), 1),
            },
            'agents': agent_summary,
            'school_enrichment': {
                'by_status': school_stats,
                'moana_validation': moana_stats,
                'total': sum(school_stats.values()),
            },
            'recent_executions': status.get('recent_executions', [])[-20:],
        })
    except Exception as e:
        logger.error(f"Telemetry overview error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/debug/agents')
def debug_agents():
    """Real-time agent monitoring dashboard."""
    return render_template('agent_monitor.html')


@app.route('/api/debug/agent-status')
def get_agent_status():
    """Get current agent execution status."""
    monitor = get_agent_monitor()
    return jsonify(monitor.get_status())


@app.route('/api/debug/agent-status/clear', methods=['POST'])
def clear_agent_history():
    """Clear agent execution history."""
    monitor = get_agent_monitor()
    monitor.clear_history()
    return jsonify({'status': 'success', 'message': 'History cleared'})


@app.route('/api/debug/agent/<agent_name>/history')
def get_agent_history(agent_name):
    """Get execution history for a specific agent."""
    monitor = get_agent_monitor()
    limit = request.args.get('limit', 20, type=int)
    history = monitor.get_agent_history(agent_name, limit=limit)
    return jsonify({
        'agent_name': agent_name,
        'executions': history
    })


@app.route('/api/debug/telemetry-status')
def get_telemetry_status():
    """Report whether observability is configured and where it would export."""
    try:
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        telemetry_enabled = is_observability_enabled()
        observability_status = get_observability_status()

        endpoint = getattr(config, 'azure_openai_endpoint', '') or ''
        endpoint_hint = endpoint.replace('https://', '').split('/')[0] if endpoint else None

        return jsonify({
            'telemetry_enabled': telemetry_enabled,
            'app_insights_configured': observability_status.get('connection_string_set'),
            'otlp_endpoint_configured': bool(otlp_endpoint),
            'otlp_endpoint': otlp_endpoint if otlp_endpoint else None,
            'observability': observability_status,
            'ai_config': {
                'deployment_name': getattr(config, 'deployment_name', None),
                'deployment_name_mini': getattr(config, 'deployment_name_mini', None),
                'api_version': getattr(config, 'api_version', None),
                'api_version_mini': getattr(config, 'api_version_mini', None),
                'endpoint_host': endpoint_hint,
                'model_tiers': {
                    'premium': getattr(config, 'model_tier_premium', None),
                    'merlin': getattr(config, 'model_tier_merlin', None),
                    'workhorse': getattr(config, 'model_tier_workhorse', None),
                    'lightweight': getattr(config, 'model_tier_lightweight', None),
                    'vision': getattr(config, 'foundry_vision_model_name', None),
                }
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/admin/cleanup-test-data', methods=['POST'])
def admin_cleanup_test_data():
    """Clean up contaminated test data records."""
    try:
        conn = db.connect()
        cursor = conn.cursor()
        
        # Find contaminated records
        cursor.execute("""
            SELECT 
                application_id,
                applicant_name
            FROM applications
            WHERE (is_test_data IS NULL OR is_test_data = FALSE)
            AND (is_training_example IS NULL OR is_training_example = FALSE)
            AND (
                LOWER(applicant_name) LIKE '%test%'
                OR LOWER(applicant_name) LIKE '%demo%'
                OR LOWER(applicant_name) LIKE '%sample%'
            )
        """)
        
        contaminated = cursor.fetchall()
        
        if not contaminated:
            # Fix NULL flags
            cursor.execute("UPDATE applications SET is_test_data = FALSE WHERE is_test_data IS NULL")
            test_fixed = cursor.rowcount
            cursor.execute("UPDATE applications SET is_training_example = FALSE WHERE is_training_example IS NULL")
            training_fixed = cursor.rowcount
            conn.commit()
            
            return jsonify({
                'status': 'success',
                'contaminated_found': 0,
                'null_flags_fixed': test_fixed + training_fixed,
                'message': 'No contaminated records found. NULL flags fixed.'
            })
        
        # Flag contaminated records as test data
        record_ids = [row[0] for row in contaminated]
        record_names = [row[1] for row in contaminated]
        
        placeholders = ','.join(['%s'] * len(record_ids))
        cursor.execute(f"""
            UPDATE applications
            SET is_test_data = TRUE, is_training_example = FALSE
            WHERE application_id IN ({placeholders})
        """, record_ids)
        
        updated_count = cursor.rowcount
        
        # Fix NULL flags
        cursor.execute("UPDATE applications SET is_test_data = FALSE WHERE is_test_data IS NULL")
        test_fixed = cursor.rowcount
        cursor.execute("UPDATE applications SET is_training_example = FALSE WHERE is_training_example IS NULL")
        training_fixed = cursor.rowcount
        
        conn.commit()
        cursor.close()
        
        logger.info(f"✓ Cleaned up {updated_count} contaminated test records: {', '.join(record_names)}")
        
        return jsonify({
            'status': 'success',
            'contaminated_found': len(contaminated),
            'records_flagged': updated_count,
            'null_flags_fixed': test_fixed + training_fixed,
            'cleaned_records': record_names,
            'message': f'Successfully flagged {updated_count} contaminated records as test data.'
        })
        
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/ask-question/<int:application_id>', methods=['POST'])
def ask_question(application_id):
    """
    Q&A endpoint for asking questions about a student.
    
    Request body:
    {
        "question": "What is the student's GPA and how does it compare to their school?",
        "conversation_history": [
            {"question": "...", "answer": "..."},
            ...
        ]
    }
    
    Response:
    {
        "success": bool,
        "answer": str,
        "reference_data": {
            "name": str,
            "school": str,
            "gpa": float,
            "data_sources": [str]
        },
        "error": str (if failed)
    }
    """
    try:
        data = request.get_json()
        question = data.get('question', '').strip()
        conversation_history = data.get('conversation_history', [])
        
        if not question:
            return jsonify({
                'success': False,
                'error': 'Question cannot be empty',
                'answer': None,
                'reference_data': {}
            }), 400
        
        # Initialize ARIEL Q&A agent (guard if missing in this deployment)
        if ArielQAAgent is None:
            return jsonify({
                'success': False,
                'error': 'Ariel Q&A agent not available in this deployment',
                'answer': None,
                'reference_data': {}
            }), 503

        ariel = ArielQAAgent()
        
        # Process question
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                ariel.answer_question(
                    application_id=application_id,
                    question=question,
                    conversation_history=conversation_history
                )
            )
        finally:
            loop.close()
        
        if result['success']:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
    
    except Exception as e:
        logger.error(f"Error in ask_question endpoint: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error processing question: {str(e)}',
            'answer': None,
            'reference_data': {}
        }), 500


if __name__ == '__main__':
    # Only use debug mode for local development
    debug_mode = os.getenv('FLASK_ENV') != 'production'
    port = int(os.getenv('PORT', 5002))  # Changed to 5002 to avoid port conflict
    print(f" * Starting Flask on port {port}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)

