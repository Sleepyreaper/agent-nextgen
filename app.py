"""Flask web application for application evaluation system."""

import os
import asyncio
import time
import uuid
import json
import re
import difflib
import threading
import queue
from typing import Optional, Dict, Any
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
from openai import AzureOpenAI
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from src.config import config
from src.database import db
from src.document_processor import DocumentProcessor
from src.storage import storage
from src.test_data_generator import test_data_generator
from src.logger import app_logger as logger, audit_logger
from src.telemetry import init_telemetry
from src.observability import is_observability_enabled, get_observability_status
from src.agents import (
    GastonEvaluator,
    SmeeOrchestrator,
    RapunzelGradeReader,
    MoanaSchoolContext,
    TianaApplicationReader,
    MulanRecommendationReader,
    MerlinStudentEvaluator,
    AuroraAgent,
    BelleDocumentAnalyzer,
    MiloDataScientist,
    FeedbackTriageAgent,
    NaveenSchoolDataScientist,
    BashfulAgent,
    ScuttleFeedbackTriageAgent
)
from src.agents.ariel_qa_agent import ArielQAAgent
from src.agents.agent_requirements import AgentRequirements
from src.agents.fairy_godmother_document_generator import FairyGodmotherDocumentGenerator
from src.agents.agent_monitor import get_agent_monitor

# Initialize Flask app
app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
app.secret_key = config.flask_secret_key or 'dev-secret-key-change-in-production'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'


@app.context_processor
def inject_app_metadata():
    return {
        'app_version': config.app_version
    }

# Instrument Flask and outbound HTTP calls for App Insights.
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
logger.info("Flask app initialized", extra={'upload_folder': app.config['UPLOAD_FOLDER']})

# Initialize telemetry (prompt capture controlled by NEXTGEN_CAPTURE_PROMPTS)
init_telemetry(service_name="nextgen-agents-web")

# Initialize Azure OpenAI client
def get_ai_client(api_version: str = None):
    """
    Get Azure OpenAI client with specified API version.
    
    Args:
        api_version: API version to use. If None, uses config.api_version
    """
    if api_version is None:
        api_version = config.api_version
        
    if config.azure_openai_api_key:
        return AzureOpenAI(
            api_key=config.azure_openai_api_key,
            api_version=api_version,
            azure_endpoint=config.azure_openai_endpoint
        )

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_ad_token_provider=token_provider,
        api_version=api_version,
        azure_endpoint=config.azure_openai_endpoint
    )

def get_ai_client_mini():
    """Get Azure OpenAI client for o4-mini deployment with correct API version."""
    return get_ai_client(api_version=config.api_version_mini)

# Initialize evaluator agent
evaluator_agent = None
orchestrator_agent = None
belle_analyzer = None
feedback_agent = None

def get_evaluator():
    """Get or create Gaston evaluator agent."""
    global evaluator_agent
    if not evaluator_agent:
        client = get_ai_client()
        training_examples = db.get_training_examples()
        evaluator_agent = GastonEvaluator(
            name="GastonEvaluator",
            client=client,
            model=config.deployment_name,
            training_examples=training_examples
        )
    return evaluator_agent


def get_belle():
    """Get or create Belle document analyzer."""
    global belle_analyzer
    if not belle_analyzer:
        client = get_ai_client()
        belle_analyzer = BelleDocumentAnalyzer(
            client=client,
            model=config.deployment_name
        )
    return belle_analyzer


def get_feedback_agent():
    """Get or create feedback triage agent."""
    global feedback_agent
    if not feedback_agent:
        client = get_ai_client()
        feedback_agent = FeedbackTriageAgent(
            name="Scuttle Feedback Triage",
            client=client,
            model=config.deployment_name
        )
    return feedback_agent


def get_orchestrator():
    """Get or create Smee orchestrator with registered agents."""
    global orchestrator_agent
    if not orchestrator_agent:
        client = get_ai_client()
        client_mini = get_ai_client_mini()
        orchestrator_agent = SmeeOrchestrator(
            name="Smee",
            client=client,
            model=config.deployment_name,
            db_connection=db
        )

        # Register specialist agents with DB connections where supported
        orchestrator_agent.register_agent(
            "application_reader",
            TianaApplicationReader(
                name="Tiana Application Reader",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "grade_reader",
            RapunzelGradeReader(
                name="Rapunzel Grade Reader",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "school_context",
            MoanaSchoolContext(
                name="Moana School Context",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "recommendation_reader",
            MulanRecommendationReader(
                name="Mulan Recommendation Reader",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "student_evaluator",
            MerlinStudentEvaluator(
                name="Merlin Student Evaluator",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "data_scientist",
            MiloDataScientist(
                name="Milo Data Scientist",
                client=client_mini,
                model=config.deployment_name_mini,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "naveen",
            NaveenSchoolDataScientist(
                name="Naveen School Data Scientist",
                client=client_mini,
                model=config.deployment_name_mini
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
            "gaston",
            GastonEvaluator(
                name="Gaston Evaluator",
                client=client,
                model=config.deployment_name
            )
        )
        orchestrator_agent.register_agent(
            "bashful",
            BashfulAgent(
                name="Bashful Agent",
                client=client,
                model=config.deployment_name,
                system_prompt="You are Bashful, a helpful assistant in the evaluation system."
            )
        )
        orchestrator_agent.register_agent(
            "belle",
            BelleDocumentAnalyzer(
                name="Belle Document Analyzer",
                client=client,
                model=config.deployment_name,
                db_connection=db
            )
        )
        orchestrator_agent.register_agent(
            "scuttle",
            ScuttleFeedbackTriageAgent(
                name="Scuttle Feedback Triage",
                client=client,
                model=config.deployment_name
            )
        )

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


@app.route('/')
def index():
    """Home page - Dashboard."""
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


@app.route('/feedback', methods=['POST'])
def submit_feedback():
    """Capture user feedback and create a GitHub issue."""
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
        return jsonify({'error': 'Unable to submit feedback right now.'}), 500


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
                    flash(f"Invalid file type: {file.filename}. Please upload PDF, DOCX, or TXT files.", 'error')
                    continue

                valid_files += 1
                filename = secure_filename(file.filename)
                temp_id = uuid.uuid4().hex
                temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{temp_id}_{filename}")
                file.save(temp_path)

                application_text, file_type = DocumentProcessor.process_document(temp_path)

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
    
    return render_template('upload.html')


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
    except:
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
        target_field = doc_type_map.get(doc_type)
        text = doc.get('text') or ""
        filename = doc.get('filename') or "document"

        if target_field:
            fields[target_field] = _merge_uploaded_text(
                fields.get(target_field),
                text,
                label_map.get(target_field, 'Document'),
                filename
            )
            continue

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
        
        return render_template('students.html', 
                             students=students,
                             search_query=search_query)
    except Exception as e:
        flash(f'Error loading students: {str(e)}', 'error')
        return render_template('students.html', students=[], search_query='')


@app.route('/training')
def training():
    """Training data management page - historical applications for agent learning."""
    try:
        search_query = request.args.get('search', '').strip()
        filter_selected = request.args.get('filter', '')
        
        # Get formatted student list for training examples, sorted by last name
        training_data = db.get_formatted_student_list(is_training=True, search_query=search_query if search_query else None)
        
        # Apply filter if specified
        if filter_selected == 'selected':
            training_data = [t for t in training_data if t.get('was_selected')]
        elif filter_selected == 'not_selected':
            training_data = [t for t in training_data if not t.get('was_selected')]
        
        # Calculate statistics
        total_count = len(training_data)
        selected_count = len([t for t in training_data if t.get('was_selected')])
        not_selected_count = total_count - selected_count
        
        return render_template('training.html',
                             training_data=training_data,
                             search_query=search_query,
                             filter_selected=filter_selected,
                             total_count=total_count,
                             selected_count=selected_count,
                             not_selected_count=not_selected_count)
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
        flash(f'Error loading test page: {str(e)}', 'error')
        return render_template('test.html')


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

        test_students = []
        if db.has_applications_column(test_col):
            test_students_query = f"""
                SELECT
                    a.{app_id_col} as application_id,
                    a.{applicant_col} as applicant_name,
                    a.{email_col} as email,
                    a.{status_col} as status,
                    a.{uploaded_col} as uploaded_date
                FROM {applications_table} a
                WHERE a.{test_col} = TRUE
                ORDER BY a.{uploaded_col} DESC
            """
            test_students = db.execute_query(test_students_query)
        
        # Format for display
        formatted_students = []
        for student in test_students:
            formatted_students.append({
                'application_id': student.get('application_id'),
                'applicant_name': student.get('applicant_name'),
                'email': student.get('email'),
                'status': student.get('status'),
                'uploaded_date': student.get('uploaded_date')
            })
        
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
                        except:
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
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM mulan_recommendations WHERE application_id = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM merlin_evaluations WHERE application_id = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM student_school_context WHERE application_id = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM grade_records WHERE application_id = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM ai_evaluations WHERE application_id = %s", (app_id,))
            except:
                pass
            
            try:
                db.execute_non_query("DELETE FROM agent_audit_logs WHERE application_id = %s", (app_id,))
            except:
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
        except:
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
        except:
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
                        parsed = json.loads(agent_results['rapunzel']['parsed_json'])
                        if isinstance(parsed, dict):
                            # Merge parsed data into a safe copy
                            for key, value in parsed.items():
                                if key not in agent_results['rapunzel'] or not agent_results['rapunzel'].get(key):
                                    # Ensure we're not creating circular references
                                    if key != 'rapunzel' and key != 'agent_results':
                                        agent_results['rapunzel'][key] = value
                    except Exception as parse_err:
                        logger.debug(f"Error parsing rapunzel JSON: {parse_err}")
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
                agent_results['mulan'] = dict(mulan_results[0])  # Create explicit copy
        except Exception as e:
            logger.debug(f"No Mulan data: {e}")
        
        # Merlin - Student Evaluator
        try:
            merlin_results = db.execute_query(
                "SELECT * FROM merlin_evaluations WHERE application_id = %s ORDER BY created_at DESC LIMIT 1",
                (application_id,)
            )
            if merlin_results:
                agent_results['merlin'] = dict(merlin_results[0])  # Create explicit copy
                # Parse JSON for additional fields
                if agent_results['merlin'].get('parsed_json'):
                    try:
                        import json
                        parsed = json.loads(agent_results['merlin']['parsed_json'])
                        agent_results['merlin']['parsed_data'] = parsed
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
                        except:
                            pass
            except:
                pass
        
        logger.debug(f"About to render template with application_id={application.get('application_id')}")
        return render_template('application.html', 
                             application=application,
                             agent_results=agent_results,
                             document_available=document_available,
                             document_path=document_path,
                             aurora_evaluation=aurora_evaluation,  # For backward compatibility
                             merlin_evaluation=merlin_evaluation,  # For backward compatibility
                             is_training=application.get('is_training_example', False),
                             reprocess_notice=reprocess_notice,
                             school_context=school_context)  # School data for training context
        
    except Exception as e:
        logger.error(f"Error in student_detail: {str(e)}", exc_info=True)
        flash(f'Error loading student: {str(e)}', 'error')
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

# ============================================================================
# REAL-TIME TEST SYSTEM WITH SERVER-SENT EVENTS (SSE)
# ============================================================================

# In-memory tracking of test submissions and processing status
test_submissions = {}  # {session_id: {students, queue, processor_started}}
aurora = AuroraAgent()


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
        yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
        return

    if 'queue' not in submission:
        submission['queue'] = queue.Queue()

    start_session_processing(session_id)

    yield f"data: {json.dumps({'type': 'connected', 'message': 'Connected to test stream'})}\n\n"

    last_sent = time.time()
    while True:
        try:
            update = submission['queue'].get(timeout=0.5)
        except queue.Empty:
            if time.time() - last_sent >= 10:
                yield "event: keepalive\ndata: {}\n\n"
                last_sent = time.time()
            continue

        if update.get('_session_complete'):
            break

        yield f"data: {json.dumps(update)}\n\n"
        last_sent = time.time()


def _process_session(session_id):
    submission = test_submissions.get(session_id)
    if not submission:
        return

    students = submission['students']
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
                    logger.debug(f"Starting orchestration thread for {applicant_name}")
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
        generate_session_updates(session_id),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/test/submit', methods=['POST'])
def submit_test_data():
    """
    Generate synthetic test students and start processing pipeline.
    Cleans up old test data first, then creates new test students.
    Returns a session ID to stream updates from.
    """
    try:
        # CLEANUP: Delete old test data (all applications marked as is_test_data=TRUE)
        logger.info("Cleaning up old test data...")
        cleanup_test_data()
        logger.info("Test data cleanup complete. Generating new students...")
        
        # Generate 3 random test students with realistic data
        students = test_data_generator.generate_batch()
        logger.info(f"Generated {len(students)} test students")
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Track submission
        test_submissions[session_id] = {
            'students': students,
            'application_ids': [],
            'created_at': time.time(),
            'status': 'processing',
            'queue': queue.Queue()
        }

        start_session_processing(session_id)
        
        return jsonify({
            'session_id': session_id,
            'student_count': len(students),
            'stream_url': url_for('test_stream', session_id=session_id)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/test/submit-preset', methods=['POST'])
def submit_preset_test_data():
    """
    Submit randomized test students for quick testing.
    Always generates fresh data.
    """
    try:
        # CLEANUP: Delete old test data
        logger.info("Cleaning up old test data...")
        cleanup_test_data()
        logger.info("Test data cleanup complete. Creating randomized students...")

        preset_students = test_data_generator.generate_batch(count=3)
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Track submission
        test_submissions[session_id] = {
            'students': preset_students,
            'application_ids': [],
            'created_at': time.time(),
            'status': 'processing',
            'queue': queue.Queue()
        }

        start_session_processing(session_id)
        
        return jsonify({
            'session_id': session_id,
            'student_count': len(preset_students),
            'stream_url': url_for('test_stream', session_id=session_id)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/test/submit-single', methods=['POST'])
def submit_single_test_data():
    """
    Submit a single randomized test student for quick testing.
    """
    try:
        # CLEANUP: Delete old test data
        logger.info("Cleaning up old test data...")
        cleanup_test_data()
        logger.info("Test data cleanup complete. Creating single student...")

        single_student = test_data_generator.generate_batch(count=1)
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Track submission
        test_submissions[session_id] = {
            'students': single_student,
            'application_ids': [],
            'created_at': time.time(),
            'status': 'processing',
            'queue': queue.Queue()
        }

        start_session_processing(session_id)
        
        return jsonify({
            'session_id': session_id,
            'student_count': len(single_student),
            'stream_url': url_for('test_stream', session_id=session_id)
        })
        
    except Exception as e:
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
            except:
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
            except:
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
            test_students.append({
                'applicationid': row.get('applicationid'),
                'applicantname': row.get('applicantname'),
                'email': row.get('email'),
                'status': row.get('status'),
                'uploadeddate': str(row.get('uploadeddate')) if row.get('uploadeddate') else None,
                'merlin_score': row.get('merlinscore')
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
            except:
                pass
        if request.args.get('search'):
            filters['search_text'] = request.args.get('search')
        
        schools = db.get_all_schools_enriched(filters=filters, limit=200)
        
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
        
        # Update allowed fields
        update_fields = {
            'school_name': data.get('school_name'),
            'school_district': data.get('school_district'),
            'state_code': data.get('state_code'),
            'enrollment_size': data.get('enrollment_size'),
            'diversity_index': data.get('diversity_index'),
            'socioeconomic_level': data.get('socioeconomic_level'),
            'ap_classes_count': data.get('ap_classes_count'),
            'ib_offerings': data.get('ib_offerings'),
            'honors_programs': data.get('honors_programs'),
            'stem_programs': data.get('stem_programs'),
            'graduation_rate': data.get('graduation_rate'),
            'college_placement_rate': data.get('college_placement_rate'),
            'avg_test_scores': data.get('avg_test_scores'),
            'school_investment_level': data.get('school_investment_level'),
            'opportunity_score': data.get('opportunity_score'),
            'analysis_summary': data.get('analysis_summary'),
            'human_review_status': data.get('human_review_status'),
            'human_review_notes': data.get('human_review_notes')
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
            try:
                # Use Naveen School Data Scientist agent with mini model and client
                client_mini = get_ai_client_mini()
                scientist = NaveenSchoolDataScientist(
                    name="Naveen School Data Scientist",
                    client=client_mini,
                    model=config.deployment_name_mini
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
                
                # Update database with results
                db.execute_non_query(
                    "UPDATE school_enriched_data SET opportunity_score = %s, analysis_status = %s, "
                    "data_confidence_score = %s, updated_at = CURRENT_TIMESTAMP WHERE school_enrichment_id = %s",
                    (
                        result.get('opportunity_metrics', {}).get('overall_opportunity_score'),
                        result.get('analysis_status'),
                        result.get('confidence_score'),
                        school_id
                    )
                )
                
                logger.info(f"School {school_id} re-analysis completed by {result.get('agent_name')} using {result.get('model_display')}")
            except Exception as e:
                logger.error(f"Error in background analysis for school {school_id}: {e}")
        
        # Start background task
        thread = threading.Thread(target=background_analysis)
        thread.daemon = True
        thread.start()
        
        return jsonify({'status': 'success', 'message': 'Analysis queued'})
        
    except Exception as e:
        logger.error(f"Error triggering school analysis: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ============================================================================
# DEBUG & MONITORING ENDPOINTS
# ============================================================================

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
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    telemetry_enabled = is_observability_enabled()
    observability_status = get_observability_status()

    endpoint = config.azure_openai_endpoint or ""
    endpoint_hint = endpoint.replace("https://", "").split("/")[0] if endpoint else None

    return jsonify({
        'telemetry_enabled': telemetry_enabled,
        'app_insights_configured': observability_status.get("connection_string_set"),
        'otlp_endpoint_configured': bool(otlp_endpoint),
        'otlp_endpoint': otlp_endpoint if otlp_endpoint else None,
        'observability': observability_status,
        'ai_config': {
            'deployment_name': config.deployment_name,
            'deployment_name_mini': config.deployment_name_mini,
            'api_version': config.api_version,
            'api_version_mini': config.api_version_mini,
            'endpoint_host': endpoint_hint,
        }
    })


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
        
        # Initialize ARIEL Q&A agent
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

