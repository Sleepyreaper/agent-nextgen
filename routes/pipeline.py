"""Pipeline routes — batch processing, observatory API, concurrent execution."""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from extensions import csrf, get_ai_client, run_async
from src.agents.smee_orchestrator import SmeeOrchestrator
from src.agents.tiana_application_reader import TianaApplicationReader
from src.agents.rapunzel_grade_reader import RapunzelGradeReader
from src.agents.mulan_recommendation_reader import MulanRecommendationReader
from src.agents.merlin_student_evaluator import MerlinStudentEvaluator
from src.agents.gaston_evaluator import GastonEvaluator
from src.agents.aurora_agent import AuroraAgent
from src.agents.moana_school_context import MoanaSchoolContext
from src.agents.milo_data_scientist import MiloDataScientist
from src.agents.naveen_school_data_scientist import NaveenSchoolDataScientist
from src.agents.pocahontas_cohort_analyst import PocahontasCohortAnalyst
from src.agents.belle_document_analyzer import BelleDocumentAnalyzer
from src.agents.bashful_agent import BashfulAgent
from src.config import config
from src.database import db

logger = logging.getLogger(__name__)

pipeline_bp = Blueprint('pipeline', __name__)


@pipeline_bp.route('/pipeline')
def pipeline_dashboard():
    """Pipeline observatory dashboard."""
    if not session.get('authenticated'):
        return redirect(url_for('auth.login'))
    return render_template('pipeline.html')


# ---------------------------------------------------------------------------
# Concurrent pipeline pool — each slot has its own Smee instance
# ---------------------------------------------------------------------------
MAX_CONCURRENT = int(os.getenv("PIPELINE_MAX_CONCURRENT", "4"))
_pool_semaphore = threading.Semaphore(MAX_CONCURRENT)

# Track active/completed evaluations for the observatory
_pipeline_state: Dict[int, Dict[str, Any]] = {}
_pipeline_lock = threading.Lock()


def _create_orchestrator() -> SmeeOrchestrator:
    """Create a fresh Smee orchestrator instance (thread-safe, not shared).\n    
    Model tier assignments (optimized March 22 2026):
      gpt-5.4 (500 RPM): Smee, Tiana, Mulan, Pocahontas
      gpt-5.4-mini (200 RPM): Belle, Moana
      gpt-5.4-nano (200 RPM): Naveen, Aurora, Bashful
      gpt-5.4-pro (160 RPM): Rapunzel, Milo
      o3 (100 RPM): Merlin (the judgment call)
      o4-mini (100 RPM): Gaston interleaved quality checks
    """
    client = get_ai_client()
    orchestrator = SmeeOrchestrator(
        name="Smee",
        client=client,
        model=config.model_tier_orchestrator,  # gpt-5.4
        db_connection=db
    )
    orchestrator.register_agent("application_reader",
        TianaApplicationReader(name="Tiana", client=client, model=config.model_tier_workhorse, db_connection=db))
    orchestrator.register_agent("grade_reader",
        RapunzelGradeReader(name="Rapunzel", client=client, model=config.model_tier_premium, db_connection=db))
    orchestrator.register_agent("school_context",
        MoanaSchoolContext(name="Moana", client=client, model=config.model_tier_fast, db_connection=db))
    orchestrator.register_agent("recommendation_reader",
        MulanRecommendationReader(name="Mulan", client=client, model=config.model_tier_workhorse, db_connection=db))
    orchestrator.register_agent("student_evaluator",
        MerlinStudentEvaluator(name="Merlin", client=client, model=config.model_tier_merlin, db_connection=db))
    orchestrator.register_agent("data_scientist",
        MiloDataScientist(name="Milo", client=client, model=config.model_tier_premium, db_connection=db))
    orchestrator.register_agent("naveen",
        NaveenSchoolDataScientist(name="Naveen", client=client, model=config.model_tier_lightweight))
    orchestrator.register_agent("pocahontas",
        PocahontasCohortAnalyst(name="Pocahontas", client=client, model=config.model_tier_workhorse))
    orchestrator.register_agent("aurora", AuroraAgent())
    orchestrator.register_agent("gaston",
        GastonEvaluator(name="Gaston", client=client, model=config.model_tier_reasoning))
    orchestrator.register_agent("belle",
        BelleDocumentAnalyzer(name="Belle", client=client, model=config.model_tier_fast, db_connection=db))
    orchestrator.register_agent("bashful",
        BashfulAgent(name="Bashful", client=client, model=config.model_tier_lightweight,
                     system_prompt="You are Bashful, a helpful summarizer."))
    return orchestrator


def _run_pipeline(application_id: int, batch_mode: bool = False):
    """Run the full pipeline for one application. Thread-safe — uses pool semaphore."""
    # Update observatory state
    with _pipeline_lock:
        _pipeline_state[application_id] = {
            'status': 'queued',
            'application_id': application_id,
            'queued_at': datetime.now(timezone.utc).isoformat(),
            'started_at': None,
            'completed_at': None,
            'current_agent': None,
            'agents_completed': [],
            'agent_timings': {},
            'error': None,
            'batch_mode': batch_mode,
        }

    db.update_application_status(application_id, 'Processing')

    _pool_semaphore.acquire()
    try:
        application = db.get_application(application_id)
        if not application:
            logger.error("Pipeline: application %d not found", application_id)
            with _pipeline_lock:
                _pipeline_state[application_id]['status'] = 'error'
                _pipeline_state[application_id]['error'] = 'Application not found'
            db.update_application_status(application_id, 'Uploaded')
            return

        with _pipeline_lock:
            _pipeline_state[application_id]['status'] = 'running'
            _pipeline_state[application_id]['started_at'] = datetime.now(timezone.utc).isoformat()
            _pipeline_state[application_id]['applicant_name'] = application.get('applicant_name', '')

        # Create a FRESH orchestrator for this evaluation (not shared)
        orchestrator = _create_orchestrator()

        # Wire progress callback to update observatory state
        def _progress_cb(update):
            with _pipeline_lock:
                state = _pipeline_state.get(application_id, {})
                if update.get('type') == 'agent_progress':
                    agent_id = update.get('agent_id', '')
                    status = update.get('status', '')
                    state['current_agent'] = agent_id if status in ('starting', 'processing') else state.get('current_agent')
                    if status == 'completed' and agent_id not in state.get('agents_completed', []):
                        state.setdefault('agents_completed', []).append(agent_id)

        orchestrator._progress_callback = _progress_cb

        eval_steps = ['application_reader', 'grade_reader', 'recommendation_reader',
                      'school_context', 'data_scientist', 'student_evaluator', 'aurora']

        start_time = time.time()
        result = run_async(orchestrator.coordinate_evaluation(
            application=application,
            evaluation_steps=eval_steps
        ))
        elapsed = time.time() - start_time

        result_status = result.get('status') if isinstance(result, dict) else 'unknown'

        with _pipeline_lock:
            _pipeline_state[application_id]['status'] = 'completed'
            _pipeline_state[application_id]['completed_at'] = datetime.now(timezone.utc).isoformat()
            _pipeline_state[application_id]['elapsed_seconds'] = round(elapsed, 1)
            _pipeline_state[application_id]['result_status'] = result_status

        if result_status == 'paused':
            db.update_application_status(application_id, 'Needs Docs')
        else:
            db.update_application_status(application_id, 'Completed')

        logger.info("Pipeline: %d completed in %.1fs (status=%s)",
                    application_id, elapsed, result_status)

    except Exception as e:
        logger.error("Pipeline FAILED for %d: %s", application_id, e, exc_info=True)
        with _pipeline_lock:
            _pipeline_state[application_id]['status'] = 'error'
            _pipeline_state[application_id]['error'] = str(e)[:200]
            _pipeline_state[application_id]['completed_at'] = datetime.now(timezone.utc).isoformat()
        db.update_application_status(application_id, 'Uploaded')
    finally:
        _pool_semaphore.release()


# ---------------------------------------------------------------------------
# Batch endpoint — kick off N applications at once
# ---------------------------------------------------------------------------
@pipeline_bp.route('/api/pipeline/batch', methods=['POST'])
@csrf.exempt
def start_batch():
    """Start batch processing for multiple applications.

    Body: {"application_ids": [1008, 1009, ...]}
    Or: {"status_filter": "Uploaded"} to process all uploaded apps.
    """
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    if session.get('role') != 'admin':
        return jsonify({'error': 'Admin only'}), 403

    data = request.get_json() or {}

    app_ids = data.get('application_ids', [])

    # If no explicit IDs, filter by status
    if not app_ids:
        status_filter = data.get('status_filter', 'Uploaded')
        try:
            all_apps = db.execute_query(
                "SELECT application_id, applicant_name, status, is_training_example "
                "FROM applications ORDER BY application_id DESC LIMIT 500"
            ) or []
            app_ids = [
                a.get('application_id') or a.get('applicationid')
                for a in all_apps
                if (a.get('status') or '').lower() == status_filter.lower()
                and not (a.get('is_training_example') or a.get('istrainingexample'))
            ]
        except Exception as e:
            return jsonify({'error': f'Failed to query applications: {e}'}), 500

    if not app_ids:
        return jsonify({'error': 'No applications to process'}), 400

    # Cap batch size
    max_batch = int(os.getenv("PIPELINE_MAX_BATCH", "50"))
    if len(app_ids) > max_batch:
        return jsonify({'error': f'Batch size {len(app_ids)} exceeds max {max_batch}'}), 400

    # Launch all in background threads — semaphore controls concurrency
    launched = []
    for app_id in app_ids:
        app_id = int(app_id)
        # Skip if already running
        with _pipeline_lock:
            existing = _pipeline_state.get(app_id, {})
            if existing.get('status') in ('running', 'queued'):
                continue

        threading.Thread(
            target=_run_pipeline,
            args=(app_id, True),
            daemon=True
        ).start()
        launched.append(app_id)

    return jsonify({
        'launched': len(launched),
        'application_ids': launched,
        'max_concurrent': MAX_CONCURRENT,
        'message': f'Started {len(launched)} applications ({MAX_CONCURRENT} concurrent slots)'
    }), 202


# ---------------------------------------------------------------------------
# Observatory API — watch the pipeline
# ---------------------------------------------------------------------------
@pipeline_bp.route('/api/pipeline/status')
def pipeline_status():
    """Get status of all active/recent pipeline evaluations."""
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401

    with _pipeline_lock:
        # Return recent state (last 100 entries)
        entries = sorted(
            _pipeline_state.values(),
            key=lambda x: x.get('queued_at', ''),
            reverse=True
        )[:100]

    # If no in-memory state, fall back to DB for recent applications
    if not entries:
        try:
            all_apps = db.execute_query(
                "SELECT application_id, applicant_name, status, uploaded_date, updated_date "
                "FROM applications ORDER BY application_id DESC LIMIT 20"
            ) or []
            for app in (all_apps or [])[:20]:
                status = (app.get('status') or '').lower()
                if status in ('processing', 'completed', 'uploaded', 'needs docs'):
                    app_id = app.get('application_id') or app.get('applicationid')
                    entries.append({
                        'application_id': app_id,
                        'applicant_name': app.get('applicant_name') or app.get('applicantname', ''),
                        'status': 'completed' if status == 'completed' else ('running' if status == 'processing' else status),
                        'queued_at': app.get('uploaded_date') or app.get('uploadeddate', ''),
                        'completed_at': app.get('updated_date') or '',
                        'current_agent': '-',
                        'agents_completed': [],
                        'from_db': True,
                    })
        except Exception:
            pass

    # Summary counts
    summary = {
        'active': len([e for e in entries if e.get('status') in ('running', 'queued')]),
        'completed': len([e for e in entries if e.get('status') == 'completed']),
        'failed': len([e for e in entries if e.get('status') == 'error']),
        'queued': len([e for e in entries if e.get('status') == 'queued']),
        'max_concurrent': MAX_CONCURRENT,
        'pool_available': _pool_semaphore._value,
    }

    return jsonify({
        'summary': summary,
        'evaluations': entries,
    })


@pipeline_bp.route('/api/pipeline/<int:application_id>/agents')
def pipeline_agents(application_id):
    """Get per-agent status and timing for a specific evaluation."""
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401

    with _pipeline_lock:
        state = _pipeline_state.get(application_id)

    if not state:
        return jsonify({'error': 'No pipeline data for this application'}), 404

    return jsonify(state)


@pipeline_bp.route('/api/pipeline/clear', methods=['POST'])
@csrf.exempt
def pipeline_clear():
    """Clear completed pipeline state (admin only)."""
    if session.get('role') != 'admin':
        return jsonify({'error': 'Admin only'}), 403

    with _pipeline_lock:
        to_remove = [
            k for k, v in _pipeline_state.items()
            if v.get('status') in ('completed', 'error')
        ]
        for k in to_remove:
            del _pipeline_state[k]

    return jsonify({'cleared': len(to_remove)})
