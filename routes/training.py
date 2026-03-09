"""Training routes — training data management, Milo, historical scores, evaluations."""

import json
import logging
import os
import statistics
import tempfile
import threading
import time
from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from extensions import (
    csrf, limiter, run_async,
    get_ai_client, get_orchestrator, refresh_foundry_dataset_async,
    _collect_documents_from_storage, _aggregate_documents,
)
from src.agents.belle_document_analyzer import BelleDocumentAnalyzer
from src.config import config
from src.database import db
from src.storage import storage
from src.telemetry import telemetry

logger = logging.getLogger(__name__)

training_bp = Blueprint('training', __name__)

# --- Milo Validation state files (file-based for multi-worker compat) ---
_VALIDATION_STATE_FILE = os.path.join(tempfile.gettempdir(), "milo_validation_state.json")
_VALIDATION_RESULT_FILE = os.path.join(tempfile.gettempdir(), "milo_validation_result.json")

# --- Agent Evaluations state files ---
_EVAL_STATE_FILE = os.path.join(tempfile.gettempdir(), "agent_evaluation_state.json")
_EVAL_RESULT_FILE = os.path.join(tempfile.gettempdir(), "agent_evaluation_result.json")


@training_bp.route('/training')
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

        # Re-sort training data by high school, then state (from school enrichment), then last name
        def _sort_key(s):
            hs = (s.get('high_school') or '').strip().lower()
            ln = (s.get('last_name') or '').strip().lower()
            fn = (s.get('first_name') or '').strip().lower()
            return (hs == '', hs, ln, fn)  # blanks sort last
        training_data.sort(key=_sort_key)

        # Fetch school enrichment data for the Schools tab
        school_data = db.get_all_schools_enriched(limit=5000)
        school_data.sort(key=lambda s: (
            (s.get('state_code') or '').lower(),
            (s.get('school_name') or '').lower()
        ))
        school_count = len(school_data)

        return render_template('training.html',
                             training_data=training_data,
                             school_data=school_data,
                             search_query=search_query,
                             filter_selected=filter_selected,
                             total_count=total_count,
                             selected_count=selected_count,
                             not_selected_count=not_selected_count,
                             matched_count=matched_count,
                             school_count=school_count,
                             is_training_view=True)
    except Exception as e:
        logger.error('Error loading training data: %s', e, exc_info=True)
        flash('An error occurred while loading training data', 'error')
        return render_template('training.html', 
                             training_data=[], 
                             school_data=[],
                             search_query='',
                             filter_selected='',
                             total_count=0,
                             selected_count=0,
                             not_selected_count=0,
                             school_count=0)



@training_bp.route('/training/<int:application_id>')
def view_training_detail(application_id):
    """View details of a training example."""
    try:
        application = db.get_application(application_id)
        if not application or not application.get('is_training_example'):
            flash('Training example not found', 'error')
            return redirect(url_for('training.training'))

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
        logger.error('Error loading training example: %s', e, exc_info=True)
        flash('An error occurred while loading the training example', 'error')
        return redirect(url_for('training.training'))



@training_bp.route('/training/<int:application_id>/delete', methods=['POST'])
def delete_training(application_id):
    """Delete a training example."""
    try:
        application = db.get_application(application_id)
        if not application or not application.get('is_training_example'):
            flash('Training example not found', 'error')
            return redirect(url_for('training.training'))

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
        
        return redirect(url_for('training.training'))
        
    except Exception as e:
        logger.error('Error deleting training example: %s', e, exc_info=True)
        flash('An error occurred while deleting the training example', 'error')
        return redirect(url_for('training.training'))



@training_bp.route('/api/training-data/clear', methods=['POST'])
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
            'error': 'An internal error occurred'
        }), 500



@training_bp.route('/api/training-data/duplicates', methods=['GET'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/training-data/bulk-delete', methods=['POST'])
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
                logger.error('Error deleting app_id %s: %s', app_id, e, exc_info=True)
                errors.append(f"ID {app_id}: delete failed")

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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/import-scores')
def import_scores_page():
    """Page for importing 2024 historical scoring spreadsheet."""
    stats = db.get_historical_stats(2024)
    return render_template('import_scores.html', stats=stats)



@training_bp.route('/api/import-scores', methods=['POST'])
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
        temp_path = os.path.join(current_app.config.get('UPLOAD_FOLDER', '/tmp'), f"import_{uuid.uuid4().hex}.xlsx")
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/historical-scores/stats')
def api_historical_stats():
    """Get aggregate stats for historical scores."""
    cohort_year = int(request.args.get('cohort_year', 2024))
    stats = db.get_historical_stats(cohort_year)
    return jsonify(stats)



@training_bp.route('/api/historical-scores/search')
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



@training_bp.route('/api/historical-scores/clear', methods=['POST'])
def api_clear_historical_scores():
    """Clear all historical scores for a cohort year."""
    cohort_year = int(request.form.get('cohort_year', 2024))
    deleted = db.clear_historical_scores(cohort_year)
    return jsonify({'status': 'success', 'deleted': deleted})


@training_bp.route('/api/training/reset-agent-outputs', methods=['POST'])
def reset_training_agent_outputs():
    """Reset agent_results, student_summary, nextgen_match, and status
    for all training records so they can be re-evaluated through the
    current pipeline.

    This preserves the original document text (application_text,
    transcript_text, recommendation_text) and student info — it only
    wipes the AI evaluation outputs.

    Use this after pipeline changes to get a clean-slate re-evaluation.
    """
    try:
        training_col = db.get_training_example_column()
        test_col = db.get_test_data_column()

        where = f"{training_col} = TRUE"
        if db.has_applications_column(test_col):
            where += f" AND ({test_col} = FALSE OR {test_col} IS NULL)"

        count_rows = db.execute_query(f"SELECT COUNT(*) as cnt FROM applications WHERE {where}")
        count = count_rows[0]['cnt'] if count_rows else 0

        if count == 0:
            return jsonify({'status': 'success', 'message': 'No training records found', 'reset': 0})

        # Reset AI outputs but keep document text and student info
        db.execute_non_query(f"""
            UPDATE applications
            SET agent_results = NULL,
                student_summary = NULL,
                nextgen_match = NULL,
                status = 'Pending',
                updated_date = CURRENT_TIMESTAMP
            WHERE {where}
        """)

        # Also clear dependent agent tables for these records
        app_ids = db.execute_query(f"SELECT application_id FROM applications WHERE {where}")
        for row in (app_ids or []):
            aid = row['application_id']
            for table in ('ai_evaluations', 'aurora_evaluations', 'merlin_evaluations',
                          'agent_audit_logs'):
                try:
                    db.execute_non_query(f"DELETE FROM {table} WHERE application_id = %s", (aid,))
                except Exception:
                    pass  # Table may not exist

        logger.info(f"Reset agent outputs for {count} training records")
        return jsonify({
            'status': 'success',
            'reset': count,
            'message': f'Reset AI outputs for {count} training records. Document text preserved. Re-evaluate to regenerate.',
        })
    except Exception as e:
        logger.error(f"Error resetting training outputs: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@training_bp.route('/api/training/re-evaluate', methods=['POST'])
def re_evaluate_training():
    """Re-run the full evaluation pipeline on all training records that
    have status='Pending' (i.e., after a reset-agent-outputs call).

    Processes sequentially in a background thread with progress tracking.
    Each record goes through the full Smee orchestrator pipeline.

    Optional body: {"limit": 20} — max records per batch (default 50, cap 100)
    """
    import tempfile as _tempfile

    data = request.get_json(silent=True) or {}
    limit = min(int(data.get('limit', 50)), 100)

    training_col = db.get_training_example_column()
    test_col = db.get_test_data_column()
    test_filter = ""
    if db.has_applications_column(test_col):
        test_filter = f" AND ({test_col} = FALSE OR {test_col} IS NULL)"

    pending = db.execute_query(f"""
        SELECT application_id, applicant_name
        FROM applications
        WHERE {training_col} = TRUE{test_filter}
          AND (status = 'Pending' OR agent_results IS NULL)
        ORDER BY application_id
        LIMIT %s
    """, (limit,))

    if not pending:
        return jsonify({'status': 'success', 'message': 'No pending training records to re-evaluate', 'queued': 0})

    state_file = os.path.join(_tempfile.gettempdir(), 'training_reevaluate_state.json')
    state = {
        'status': 'running',
        'total': len(pending),
        'completed': 0,
        'succeeded': 0,
        'failed': 0,
        'current': '',
        'message': f'Starting re-evaluation of {len(pending)} training records...',
    }
    with open(state_file, 'w') as f:
        json.dump(state, f)

    def _background_reevaluate(records, state_path):
        from extensions import start_training_processing, run_async, get_orchestrator
        import time as _time

        for idx, rec in enumerate(records):
            app_id = rec['application_id']
            name = rec.get('applicant_name', f'ID#{app_id}')
            state['completed'] = idx
            state['current'] = name
            state['message'] = f'Evaluating {name} ({idx+1}/{len(records)})'
            try:
                with open(state_path, 'w') as f:
                    json.dump(state, f)
            except Exception:
                pass

            try:
                # Run full orchestrator evaluation
                application = db.get_application(app_id)
                if not application:
                    state['failed'] += 1
                    continue

                orchestrator = get_orchestrator()
                result = run_async(orchestrator.coordinate_evaluation(
                    application=application,
                    evaluation_steps=[
                        'application_reader', 'grade_reader', 'recommendation_reader',
                        'school_context', 'data_scientist', 'student_evaluator', 'aurora'
                    ]
                ))

                if isinstance(result, dict) and result.get('status') != 'error':
                    db.update_application_status(app_id, 'Completed')
                    state['succeeded'] += 1
                else:
                    state['failed'] += 1

                logger.info(f"Re-eval [{idx+1}/{len(records)}] {name}: "
                           f"{'OK' if state['succeeded'] > idx else 'FAIL'}")

            except Exception as e:
                logger.error(f"Re-eval failed for {name}: {e}", exc_info=True)
                state['failed'] += 1

            # Rate limit
            if idx < len(records) - 1:
                _time.sleep(5)

        state['status'] = 'completed'
        state['completed'] = len(records)
        state['message'] = f'Re-evaluation complete: {state["succeeded"]} succeeded, {state["failed"]} failed'
        try:
            with open(state_path, 'w') as f:
                json.dump(state, f)
        except Exception:
            pass

    thread = threading.Thread(
        target=_background_reevaluate,
        args=([dict(r) for r in pending], state_file),
        daemon=True
    )
    thread.start()

    return jsonify({
        'status': 'started',
        'message': f'Re-evaluating {len(pending)} training records in background',
        'queued': len(pending),
        'poll_url': '/api/training/re-evaluate',
    })


@training_bp.route('/api/training/re-evaluate', methods=['GET'])
def re_evaluate_training_status():
    """Poll training re-evaluation progress."""
    import tempfile as _tempfile
    state_file = os.path.join(_tempfile.gettempdir(), 'training_reevaluate_state.json')
    if not os.path.isfile(state_file):
        return jsonify({'status': 'idle'})
    try:
        with open(state_file, 'r') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({'status': 'unknown'})


# ──────────────────────────────────────────────────────────────────────────────
# Overnight full reprocess — reset + re-extract + re-evaluate ALL training data
# ──────────────────────────────────────────────────────────────────────────────

_OVERNIGHT_STATE_FILE = os.path.join(tempfile.gettempdir(), 'overnight_reprocess_state.json')


def _write_overnight_state(state: dict):
    try:
        with open(_OVERNIGHT_STATE_FILE, 'w') as f:
            json.dump(state, f, default=str)
    except Exception:
        pass


@training_bp.route('/api/training/overnight-reprocess', methods=['POST'])
def overnight_reprocess():
    """Full overnight reprocess: reset agent outputs, re-extract documents,
    then re-evaluate every training record through the complete agent pipeline.

    This is designed for overnight / off-hours runs when you want every
    training record freshly processed end-to-end.

    Phases:
      1. Reset AI outputs (agent_results, summaries, status → Pending)
      2. Re-extract documents from blob storage (Belle + DocProcessor)
      3. Re-evaluate every record through Smee orchestrator (all agents)

    Optional JSON body:
      skip_extraction: bool — skip phase 2 if documents are already current (default false)
      delay_seconds: int  — seconds to sleep between evaluations (default 3, min 1, max 30)
    """

    # Prevent concurrent overnight jobs
    if os.path.isfile(_OVERNIGHT_STATE_FILE):
        try:
            with open(_OVERNIGHT_STATE_FILE) as f:
                existing = json.load(f)
            if existing.get('status') == 'running':
                return jsonify({
                    'status': 'error',
                    'error': 'An overnight reprocess is already running.',
                    'progress': existing,
                }), 409
        except Exception:
            pass

    data = request.get_json(silent=True) or {}
    skip_extraction = bool(data.get('skip_extraction', False))
    delay_seconds = max(1, min(30, int(data.get('delay_seconds', 3))))

    # Count training records
    training_col = db.get_training_example_column() or 'is_training_example'
    test_col = db.get_test_data_column() or 'is_test_data'
    where = f"{training_col} = TRUE"
    if db.has_applications_column(test_col):
        where += f" AND ({test_col} = FALSE OR {test_col} IS NULL)"

    rows = db.execute_query(
        f"SELECT application_id, student_id, applicant_name FROM applications WHERE {where} ORDER BY application_id"
    )
    if not rows:
        return jsonify({'status': 'success', 'message': 'No training records found', 'count': 0})

    upload_folder = current_app.config.get('UPLOAD_FOLDER', '/tmp')

    state = {
        'status': 'running',
        'phase': 'initializing',
        'total': len(rows),
        'started_at': datetime.now(timezone.utc).isoformat(),
        'skip_extraction': skip_extraction,
        'delay_seconds': delay_seconds,
        # Phase 1 — reset
        'reset_count': 0,
        # Phase 2 — extraction
        'extraction_processed': 0,
        'extraction_updated': 0,
        'extraction_errors': [],
        # Phase 3 — evaluation
        'eval_completed': 0,
        'eval_succeeded': 0,
        'eval_failed': 0,
        'current_student': '',
        'message': f'Starting overnight reprocess of {len(rows)} training records...',
    }
    _write_overnight_state(state)

    def _run_overnight(records, upload_folder, skip_extraction, delay_seconds):
        import time as _time
        from extensions import run_async, get_orchestrator, _collect_documents_from_storage, _aggregate_documents

        try:
            # ── PHASE 1: Reset AI outputs ──────────────────────────────────
            state['phase'] = 'reset'
            state['message'] = 'Phase 1/3: Resetting agent outputs...'
            _write_overnight_state(state)

            app_ids_list = [r['application_id'] for r in records]

            db.execute_non_query(f"""
                UPDATE applications
                SET agent_results = NULL,
                    student_summary = NULL,
                    nextgen_match = NULL,
                    status = 'Pending',
                    updated_date = CURRENT_TIMESTAMP
                WHERE {where}
            """)
            state['reset_count'] = len(records)

            # Clear dependent agent tables
            for aid in app_ids_list:
                for table in ('ai_evaluations', 'aurora_evaluations',
                              'merlin_evaluations', 'agent_audit_logs'):
                    try:
                        db.execute_non_query(f"DELETE FROM {table} WHERE application_id = %s", (aid,))
                    except Exception:
                        pass

            logger.info(f"Overnight: Phase 1 complete — reset {len(records)} records")

            # ── PHASE 2: Re-extract documents ──────────────────────────────
            if not skip_extraction:
                state['phase'] = 'extraction'
                state['message'] = 'Phase 2/3: Re-extracting documents from blob storage...'
                _write_overnight_state(state)

                belle = BelleDocumentAnalyzer(
                    client=get_ai_client(),
                    model=config.model_tier_lightweight or config.foundry_model_name,
                    db_connection=db
                )

                for idx, rec in enumerate(records):
                    app_id = rec['application_id']
                    student_id = rec.get('student_id')
                    name = rec.get('applicant_name', f'ID#{app_id}')
                    state['extraction_processed'] = idx + 1
                    state['current_student'] = name
                    state['message'] = f'Phase 2/3: Extracting {name} ({idx+1}/{len(records)})'
                    _write_overnight_state(state)

                    try:
                        if not student_id:
                            state['extraction_errors'].append({
                                'application_id': app_id, 'error': 'no student_id'
                            })
                            continue

                        documents = _collect_documents_from_storage(
                            student_id, 'training', belle, upload_folder=upload_folder
                        )
                        if not documents:
                            documents = _collect_documents_from_storage(
                                student_id, 'application', belle, upload_folder=upload_folder
                            )
                        if not documents:
                            state['extraction_errors'].append({
                                'application_id': app_id, 'error': 'no files in storage'
                            })
                            continue

                        aggregated = _aggregate_documents(documents)
                        updates = {}
                        for field in ['application_text', 'transcript_text', 'recommendation_text']:
                            val = aggregated.get(field)
                            if val:
                                updates[field] = val

                        if updates:
                            db.update_application_fields(app_id, updates)
                            state['extraction_updated'] += 1

                            missing_fields = []
                            if not updates.get('transcript_text'):
                                missing_fields.append('transcript')
                            if not updates.get('recommendation_text'):
                                missing_fields.append('letters_of_recommendation')
                            db.set_missing_fields(app_id, missing_fields)

                    except Exception as exc:
                        logger.error(f"Overnight extraction error for {name}: {exc}", exc_info=True)
                        state['extraction_errors'].append({
                            'application_id': app_id, 'error': str(exc)
                        })

                logger.info(
                    f"Overnight: Phase 2 complete — extracted {state['extraction_updated']}/{len(records)}, "
                    f"{len(state['extraction_errors'])} errors"
                )
            else:
                state['phase'] = 'extraction'
                state['message'] = 'Phase 2/3: Skipped (skip_extraction=true)'
                _write_overnight_state(state)
                logger.info("Overnight: Phase 2 skipped (documents already current)")

            # ── PHASE 3: Full agent evaluation ─────────────────────────────
            state['phase'] = 'evaluation'
            state['message'] = 'Phase 3/3: Running full agent pipeline...'
            _write_overnight_state(state)

            for idx, rec in enumerate(records):
                app_id = rec['application_id']
                name = rec.get('applicant_name', f'ID#{app_id}')
                state['eval_completed'] = idx
                state['current_student'] = name
                state['message'] = (
                    f'Phase 3/3: Evaluating {name} ({idx+1}/{len(records)}) — '
                    f'{state["eval_succeeded"]} OK, {state["eval_failed"]} failed'
                )
                _write_overnight_state(state)

                try:
                    application = db.get_application(app_id)
                    if not application:
                        state['eval_failed'] += 1
                        continue

                    orchestrator = get_orchestrator()
                    result = run_async(orchestrator.coordinate_evaluation(
                        application=application,
                        evaluation_steps=[
                            'application_reader', 'grade_reader', 'recommendation_reader',
                            'school_context', 'data_scientist', 'student_evaluator', 'aurora'
                        ]
                    ))

                    if isinstance(result, dict) and result.get('status') != 'error':
                        db.update_application_status(app_id, 'Completed')
                        state['eval_succeeded'] += 1
                    else:
                        state['eval_failed'] += 1

                    logger.info(
                        f"Overnight eval [{idx+1}/{len(records)}] {name}: "
                        f"{'OK' if isinstance(result, dict) and result.get('status') != 'error' else 'FAIL'}"
                    )

                except Exception as e:
                    logger.error(f"Overnight eval failed for {name}: {e}", exc_info=True)
                    state['eval_failed'] += 1

                # Pacing — avoid hammering the AI endpoints
                if idx < len(records) - 1:
                    _time.sleep(delay_seconds)

            # ── Done ───────────────────────────────────────────────────────
            state['status'] = 'completed'
            state['phase'] = 'done'
            state['eval_completed'] = len(records)
            state['completed_at'] = datetime.now(timezone.utc).isoformat()
            state['message'] = (
                f'Overnight reprocess complete: {state["eval_succeeded"]} succeeded, '
                f'{state["eval_failed"]} failed out of {len(records)} records'
            )

        except Exception as exc:
            state['status'] = 'error'
            state['error'] = str(exc)
            state['message'] = f'Overnight reprocess failed: {exc}'
            logger.error(f"Overnight reprocess fatal error: {exc}", exc_info=True)

        finally:
            _write_overnight_state(state)

    thread = threading.Thread(
        target=_run_overnight,
        args=(
            [dict(r) for r in rows],
            upload_folder,
            skip_extraction,
            delay_seconds,
        ),
        daemon=True,
    )
    thread.start()

    return jsonify({
        'status': 'started',
        'message': (
            f'Overnight reprocess launched for {len(rows)} training records. '
            f'Phases: reset → {"extraction → " if not skip_extraction else ""}evaluation. '
            f'GET /api/training/overnight-reprocess to monitor progress.'
        ),
        'total': len(rows),
        'skip_extraction': skip_extraction,
        'delay_seconds': delay_seconds,
        'poll_url': '/api/training/overnight-reprocess',
    })


@training_bp.route('/api/training/overnight-reprocess', methods=['GET'])
def overnight_reprocess_status():
    """Poll overnight reprocess progress."""
    if not os.path.isfile(_OVERNIGHT_STATE_FILE):
        return jsonify({'status': 'idle', 'message': 'No overnight reprocess has been started.'})
    try:
        with open(_OVERNIGHT_STATE_FILE) as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({'status': 'unknown'})


@training_bp.route('/api/training/reprocess', methods=['POST'])
def api_reprocess_training():
    """Re-extract document fields for training records.

    Re-downloads every file from blob storage for each training student,
    re-runs DocumentProcessor + Belle section detection, and updates
    application_text / transcript_text / recommendation_text in the DB.

    This is essential after improving the extraction pipeline so that
    existing training data benefits from the fixes.

    Optional JSON body:
        application_ids: list of ints — restrict to specific records
    """
    import threading

    try:
        data = request.get_json(silent=True) or {}
        requested_ids = data.get('application_ids')

        training_col = db.get_training_example_column() or 'is_training_example'
        test_col = db.get_test_data_column() or 'is_test_data'

        where = f"{training_col} = TRUE AND ({test_col} = FALSE OR {test_col} IS NULL)"
        if requested_ids:
            placeholders = ', '.join(['%s'] * len(requested_ids))
            where += f" AND application_id IN ({placeholders})"
            rows = db.execute_query(
                f"SELECT application_id, student_id, applicant_name FROM applications WHERE {where}",
                tuple(requested_ids)
            )
        else:
            rows = db.execute_query(
                f"SELECT application_id, student_id, applicant_name FROM applications WHERE {where}"
            )

        if not rows:
            return jsonify({'status': 'success', 'message': 'No training records found', 'count': 0})

        # Capture Flask config before spawning background thread
        upload_folder = current_app.config.get('UPLOAD_FOLDER', '/tmp')
        results_file = os.path.join(upload_folder, 'reprocess_state.json')
        state = {
            'status': 'running',
            'total': len(rows),
            'processed': 0,
            'updated': 0,
            'errors': [],
            'started_at': datetime.now(timezone.utc).isoformat()
        }
        with open(results_file, 'w') as f:
            json.dump(state, f)

        def _background_reprocess(records, state_path, upload_folder):
            try:
                belle = BelleDocumentAnalyzer(
                    client=get_ai_client(),
                    model=config.model_tier_lightweight or config.foundry_model_name,
                    db_connection=db
                )
                for rec in records:
                    app_id = rec['application_id']
                    student_id = rec.get('student_id')
                    name = rec.get('applicant_name', f'ID#{app_id}')
                    try:
                        if not student_id:
                            logger.warning(f"Reprocess: skipping {name} — no student_id")
                            state['errors'].append({'application_id': app_id, 'error': 'no student_id'})
                            state['processed'] += 1
                            continue

                        # Re-download and re-analyze files from blob storage
                        documents = _collect_documents_from_storage(student_id, 'training', belle, upload_folder=upload_folder)
                        if not documents:
                            documents = _collect_documents_from_storage(student_id, 'application', belle, upload_folder=upload_folder)
                        if not documents:
                            logger.warning(f"Reprocess: no files in storage for {name}")
                            state['errors'].append({'application_id': app_id, 'error': 'no files in storage'})
                            state['processed'] += 1
                            continue

                        aggregated = _aggregate_documents(documents)
                        updates = {}
                        for field in ['application_text', 'transcript_text', 'recommendation_text']:
                            val = aggregated.get(field)
                            if val:
                                updates[field] = val

                        if updates:
                            db.update_application_fields(app_id, updates)
                            state['updated'] += 1
                            logger.info(
                                f"Reprocess: updated {name} (app={app_id}) — "
                                f"fields: {list(updates.keys())}, "
                                f"sizes: {', '.join(f'{k}={len(v)}' for k, v in updates.items())}"
                            )

                            # Update missing_fields marker
                            missing_fields = []
                            if not updates.get('transcript_text'):
                                missing_fields.append('transcript')
                            if not updates.get('recommendation_text'):
                                missing_fields.append('letters_of_recommendation')
                            db.set_missing_fields(app_id, missing_fields)

                    except Exception as exc:
                        logger.error(f"Reprocess error for {name}: {exc}", exc_info=True)
                        state['errors'].append({'application_id': app_id, 'error': str(exc)})

                    state['processed'] += 1
                    # Persist progress
                    with open(state_path, 'w') as f:
                        json.dump(state, f)

                state['status'] = 'completed'
                state['completed_at'] = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                state['status'] = 'error'
                state['error'] = str(exc)
            finally:
                with open(state_path, 'w') as f:
                    json.dump(state, f)

        thread = threading.Thread(target=_background_reprocess, args=(rows, results_file, upload_folder), daemon=True)
        thread.start()

        return jsonify({
            'status': 'success',
            'message': f'Reprocessing {len(rows)} training records in background. '
                       f'GET /api/training/reprocess to check progress.',
            'total': len(rows)
        })

    except Exception as e:
        logger.error(f"Error starting reprocess: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': f'Reprocess failed: {str(e)}'}), 500



@training_bp.route('/api/training/reprocess', methods=['GET'])
def api_reprocess_training_status():
    """Check progress of a running reprocess job."""
    results_file = os.path.join(current_app.config.get('UPLOAD_FOLDER', '/tmp'), 'reprocess_state.json')
    if not os.path.exists(results_file):
        return jsonify({'status': 'idle', 'message': 'No reprocess job has been started.'})
    try:
        with open(results_file) as f:
            state = json.load(f)
        return jsonify(state)
    except Exception as e:
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/training/diagnostic', methods=['GET'])
def api_training_diagnostic():
    """Return field sizes and section detection info for training records.

    Shows application_text, transcript_text, recommendation_text lengths
    for each training student so you can quickly find records with missing data.
    """
    try:
        training_col = db.get_training_example_column() or 'is_training_example'
        test_col = db.get_test_data_column() or 'is_test_data'
        selected_col = db.get_applications_column('was_selected') or 'was_selected'

        rows = db.execute_query(f"""
            SELECT application_id, applicant_name, first_name, last_name,
                   {selected_col} AS was_selected,
                   COALESCE(LENGTH(application_text), 0) AS app_text_len,
                   COALESCE(LENGTH(transcript_text), 0) AS transcript_len,
                   COALESCE(LENGTH(recommendation_text), 0) AS rec_len,
                   status, high_school
            FROM applications
            WHERE {training_col} = TRUE
              AND ({test_col} = FALSE OR {test_col} IS NULL)
            ORDER BY {selected_col} DESC NULLS LAST, applicant_name
        """)

        summary = {
            'total': len(rows),
            'has_application': sum(1 for r in rows if r.get('app_text_len', 0) > 50),
            'has_transcript': sum(1 for r in rows if r.get('transcript_len', 0) > 50),
            'has_recommendation': sum(1 for r in rows if r.get('rec_len', 0) > 50),
            'missing_all': sum(1 for r in rows if (
                r.get('app_text_len', 0) < 50 and
                r.get('transcript_len', 0) < 50 and
                r.get('rec_len', 0) < 50
            ))
        }

        return jsonify({
            'status': 'success',
            'summary': summary,
            'students': rows
        })

    except Exception as e:
        logger.error(f"Training diagnostic error: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/training/unmatched')
def api_unmatched_training():
    """Get training students with no linked historical XLSX score."""
    try:
        students = db.get_unmatched_training_students()
        return jsonify({'status': 'success', 'students': students, 'count': len(students)})
    except Exception as e:
        logger.error(f"Error getting unmatched training students: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/historical-scores/unlinked')
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/training/link-score', methods=['POST'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/milo/insights', methods=['GET'])
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
        result = run_async(milo.analyze_training_insights())
        return jsonify(result)
    except Exception as e:
        logger.error(f"Milo insights error: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/milo/rank', methods=['POST'])
def milo_rank_candidates():
    """Trigger Milo to rank all 2026 candidates and return Top 50 / Top 25.

    POST body (optional):
        {"force_refresh": true}  -- bypass cache
    """
    try:
        orchestrator = get_orchestrator()
        milo = orchestrator.agents.get('data_scientist') if orchestrator else None
        if not milo:
            return jsonify({'status': 'error', 'error': 'Milo agent not available'}), 500
        if not hasattr(milo, 'rank_all_candidates'):
            return jsonify({'status': 'error', 'error': 'Milo does not support ranking (upgrade required)'}), 500

        body = request.get_json(silent=True) or {}
        force_refresh = body.get('force_refresh', False)

        result = run_async(milo.rank_all_candidates(force_refresh=force_refresh))
        return jsonify(result)
    except Exception as e:
        logger.error(f"Milo ranking error: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/milo/ranking', methods=['GET'])
def milo_get_ranking():
    """Return the cached ranking without triggering a new evaluation.

    Query params:
        top=50  -- how many to return (default 50)
    """
    try:
        orchestrator = get_orchestrator()
        milo = orchestrator.agents.get('data_scientist') if orchestrator else None
        if not milo:
            return jsonify({'status': 'error', 'error': 'Milo agent not available'}), 500

        # Check if we have a cached ranking
        if hasattr(milo, '_cached_ranking') and milo._cached_ranking:
            top_n = request.args.get('top', 50, type=int)
            ranking = dict(milo._cached_ranking)
            ranking['top_n'] = ranking.get('all_ranked', [])[:top_n]
            ranking['cached'] = True
            return jsonify(ranking)

        return jsonify({
            'status': 'no_ranking',
            'message': 'No ranking available yet. POST to /api/milo/rank to generate one.'
        })
    except Exception as e:
        logger.error(f"Milo get ranking error: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/milo/validate', methods=['POST'])
def milo_validate_model():
    """Start Milo model validation as a background job.

    POST body: {"threshold": 65}
    Returns immediately. Poll GET /api/milo/validate for results.
    """
    current = _read_validation_state()
    if current.get("state") == "running":
        return jsonify({
            'status': 'already_running',
            'message': 'Validation is already in progress. GET /api/milo/validate to check status.',
            'progress': current.get('progress', ''),
        })

    body = request.get_json(silent=True) or {}
    threshold = body.get('threshold', 65)

    thread = threading.Thread(
        target=_run_milo_validation_job,
        args=(threshold,),
        daemon=True,
    )
    thread.start()

    return jsonify({
        'status': 'started',
        'message': 'Validation started. Poll GET /api/milo/validate for results.',
        'threshold': threshold,
    })



@training_bp.route('/api/milo/validate', methods=['GET'])
def milo_validate_status():
    """Check the status/results of the Milo validation job."""
    current = _read_validation_state()
    state = current.get("state", "idle")

    if state == "idle":
        return jsonify({
            'status': 'idle',
            'message': 'No validation has been run yet. POST /api/milo/validate to start one.',
        })

    if state == "running":
        elapsed = time.time() - current.get("started_at", time.time())
        return jsonify({
            'status': 'running',
            'progress': current.get('progress', ''),
            'elapsed_seconds': round(elapsed, 1),
        })

    if state == "error":
        return jsonify({
            'status': 'error',
            'error': current.get('error', 'Unknown error'),
        }), 500

    # state == "done"
    result = _read_validation_result()
    if result:
        return jsonify(result)

    return jsonify({'status': 'error', 'error': 'Results not available'}), 500



@training_bp.route('/api/evaluations/run', methods=['POST'])
def start_agent_evaluations():
    """Start agent quality evaluations as a background job.

    POST body (optional): {"agents": ["Merlin", "Tiana"], "max_students": 10}
    Returns immediately. Poll GET /api/evaluations/status for progress.
    """
    current = _read_eval_state()
    if current.get("state") == "running":
        return jsonify({
            'status': 'already_running',
            'message': 'Evaluation is already in progress.',
            'progress': current.get('progress', ''),
        })

    body = request.get_json(silent=True) or {}
    agents = body.get('agents')  # None = all
    max_students = body.get('max_students', 0)

    thread = threading.Thread(
        target=_run_agent_evaluation_job,
        args=(agents, max_students),
        daemon=True,
    )
    thread.start()

    return jsonify({
        'status': 'started',
        'message': 'Evaluation started. Poll GET /api/evaluations/status for progress.',
    })



@training_bp.route('/api/evaluations/status', methods=['GET'])
def agent_evaluation_status():
    """Poll the status of a running evaluation job."""
    current = _read_eval_state()
    state = current.get("state", "idle")

    if state == "idle":
        return jsonify({'status': 'idle', 'message': 'No evaluation running. POST /api/evaluations/run to start.'})

    if state == "running":
        elapsed = time.time() - current.get("started_at", time.time())
        return jsonify({
            'status': 'running',
            'progress': current.get('progress', ''),
            'agent': current.get('agent', ''),
            'student_index': current.get('student_index'),
            'total_students': current.get('total_students'),
            'elapsed_seconds': round(elapsed, 1),
        })

    if state == "error":
        return jsonify({'status': 'error', 'error': current.get('error', 'Unknown error')}), 500

    # state == "done"
    try:
        with open(_EVAL_RESULT_FILE, 'r') as f:
            result = json.load(f)
        return jsonify(result)
    except Exception:
        return jsonify({'status': 'error', 'error': 'Results not available'}), 500



@training_bp.route('/api/evaluations/results', methods=['GET'])
def agent_evaluation_results():
    """Get the latest stored evaluation results from the database."""
    try:
        from src.evaluations.agent_evaluator import AgentEvaluator
        evaluator = AgentEvaluator(db)
        return jsonify(evaluator.get_latest_results())
    except Exception as e:
        logger.error(f"Error fetching evaluation results: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/evaluations/consistency', methods=['GET'])
def agent_evaluation_consistency():
    """Get consistency metrics (Merlin vs Gaston, outcome accuracy) — no AI calls needed."""
    try:
        from src.evaluations.agent_evaluator import AgentEvaluator
        evaluator = AgentEvaluator(db)
        metrics = evaluator.compute_consistency_metrics()
        return jsonify({'status': 'success', **metrics})
    except Exception as e:
        logger.error(f"Error computing consistency metrics: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@training_bp.route('/api/evaluations/history', methods=['GET'])
def agent_evaluation_history():
    """Get historical evaluation runs for trend analysis."""
    try:
        from src.evaluations.agent_evaluator import AgentEvaluator
        evaluator = AgentEvaluator(db)
        limit = request.args.get('limit', 10, type=int)
        return jsonify({'status': 'success', 'runs': evaluator.get_run_history(limit)})
    except Exception as e:
        logger.error(f"Error fetching evaluation history: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



def _write_validation_state(state: dict):
    """Write validation state to a shared temp file (visible to all workers)."""
    try:
        with open(_VALIDATION_STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception:
        pass



def _read_validation_state() -> dict:
    """Read validation state from shared temp file."""
    try:
        with open(_VALIDATION_STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {"state": "idle"}



def _write_validation_result(result: dict):
    """Write validation result to a shared temp file."""
    try:
        with open(_VALIDATION_RESULT_FILE, 'w') as f:
            json.dump(result, f, default=str)
    except Exception:
        pass



def _read_validation_result() -> dict:
    """Read validation result from shared temp file."""
    try:
        with open(_VALIDATION_RESULT_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}



def _run_milo_validation_job(threshold: int):
    """Background thread: score all training students with Milo."""
    import statistics

    try:
        _write_validation_state({"state": "running", "started_at": time.time(), "progress": "initializing"})

        orchestrator = get_orchestrator()
        milo = orchestrator.agents.get('data_scientist') if orchestrator else None
        if not milo:
            _write_validation_state({"state": "error", "error": "Milo agent not available"})
            return

        # Step 1: Get training examples
        training = db.get_training_examples()
        if not training:
            _write_validation_state({"state": "error", "error": "No training data found"})
            return

        total_students = len(training)
        start_time = time.time()
        _write_validation_state({"state": "running", "started_at": start_time,
                                 "progress": f"building insights from {total_students} students"})

        # Step 2: Build insights (may already be cached)
        try:
            insights = run_async(milo.analyze_training_insights())
        except Exception as e:
            _write_validation_state({"state": "error", "error": f"Insights failed: {e}"})
            return

        # Step 3: Evaluate in batches
        from src.agents.milo_data_scientist import MAX_BATCH_SIZE
        all_results = []
        num_batches = (total_students + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE
        for batch_idx in range(0, total_students, MAX_BATCH_SIZE):
            batch_num = batch_idx // MAX_BATCH_SIZE + 1
            batch = training[batch_idx:batch_idx + MAX_BATCH_SIZE]
            _write_validation_state({
                "state": "running",
                "started_at": start_time,
                "progress": f"scoring batch {batch_num}/{num_batches} ({len(all_results)}/{total_students} done)",
            })

            try:
                batch_results = run_async(milo._evaluate_batch(batch, insights))
            except Exception as e:
                logger.error(f"Milo validation batch {batch_num} failed: {e}")
                batch_results = [
                    {"nextgen_match": 0, "tier": "ERROR", "explanation": "Validation failed"}
                    for _ in batch
                ]

            for j, result in enumerate(batch_results):
                app_data = batch[j]
                was_selected = app_data.get('was_selected', False)
                if isinstance(was_selected, str):
                    was_selected = was_selected.lower() in ('true', 'yes', '1', 'selected')
                result['actual_selected'] = was_selected
                result['application_id'] = app_data.get('application_id')
                result['applicant_name'] = (
                    app_data.get('applicant_name') or
                    f"{app_data.get('first_name', '')} {app_data.get('last_name', '')}".strip()
                )
                all_results.append(result)

        # Step 4: Compute metrics
        accepted_scores = []
        not_selected_scores = []
        tp = fp = tn = fn = 0

        for r in all_results:
            score = r.get('nextgen_match', 0) or 0
            actual = r.get('actual_selected', False)
            predicted = score >= threshold

            if actual:
                accepted_scores.append(score)
                if predicted:
                    tp += 1
                else:
                    fn += 1
            else:
                not_selected_scores.append(score)
                if predicted:
                    fp += 1
                else:
                    tn += 1

        total = len(all_results)
        accuracy = (tp + tn) / total if total else 0
        precision = tp / (tp + fp) if (tp + fp) else 0
        recall = tp / (tp + fn) if (tp + fn) else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

        accepted_mean = statistics.mean(accepted_scores) if accepted_scores else 0
        not_selected_mean = statistics.mean(not_selected_scores) if not_selected_scores else 0
        separation = accepted_mean - not_selected_mean

        all_results.sort(key=lambda x: x.get('nextgen_match', 0), reverse=True)

        validation_result = {
            'status': 'success',
            'agent': 'Milo Data Scientist',
            'model_display': milo.model_display if hasattr(milo, 'model_display') else milo.model,
            'threshold': threshold,
            'total_training_students': total,
            'accepted_count': len(accepted_scores),
            'not_selected_count': len(not_selected_scores),
            'metrics': {
                'accuracy': round(accuracy, 3),
                'precision': round(precision, 3),
                'recall': round(recall, 3),
                'f1_score': round(f1, 3),
            },
            'confusion_matrix': {
                'true_positives': tp,
                'false_positives': fp,
                'true_negatives': tn,
                'false_negatives': fn,
            },
            'score_distribution': {
                'accepted_mean': round(accepted_mean, 1),
                'accepted_min': round(min(accepted_scores), 1) if accepted_scores else 0,
                'accepted_max': round(max(accepted_scores), 1) if accepted_scores else 0,
                'accepted_median': round(statistics.median(accepted_scores), 1) if accepted_scores else 0,
                'not_selected_mean': round(not_selected_mean, 1),
                'not_selected_min': round(min(not_selected_scores), 1) if not_selected_scores else 0,
                'not_selected_max': round(max(not_selected_scores), 1) if not_selected_scores else 0,
                'not_selected_median': round(statistics.median(not_selected_scores), 1) if not_selected_scores else 0,
                'separation': round(separation, 1),
            },
            'students': [
                {
                    'rank': i + 1,
                    'name': r.get('applicant_name', 'Unknown'),
                    'application_id': r.get('application_id'),
                    'actual': 'ACCEPTED' if r.get('actual_selected') else 'NOT SELECTED',
                    'score': r.get('nextgen_match', 0),
                    'tier': r.get('tier', '?'),
                    'predicted_correct': (
                        (r.get('nextgen_match', 0) >= threshold) == r.get('actual_selected', False)
                    ),
                    'explanation': r.get('explanation', ''),
                }
                for i, r in enumerate(all_results)
            ],
            'elapsed_seconds': round(time.time() - start_time, 1),
        }
        _write_validation_result(validation_result)
        _write_validation_state({"state": "done", "finished_at": time.time()})

    except Exception as e:
        logger.error(f"Milo validation job error: {e}", exc_info=True)
        _write_validation_state({"state": "error", "error": "An internal error occurred"})



def _write_eval_state(state: dict):
    try:
        with open(_EVAL_STATE_FILE, 'w') as f:
            json.dump(state, f, default=str)
    except Exception:
        pass



def _read_eval_state() -> dict:
    try:
        with open(_EVAL_STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {"state": "idle"}



def _run_agent_evaluation_job(agents=None, max_students=0):
    """Background thread: run agent quality evaluations."""
    try:
        from src.evaluations.agent_evaluator import AgentEvaluator

        _write_eval_state({"state": "running", "started_at": time.time(), "progress": "initialising evaluators"})

        evaluator = AgentEvaluator(db)

        def progress_cb(state_dict):
            _write_eval_state({**state_dict, "started_at": time.time()})

        result = evaluator.run_batch_evaluation(
            agents=agents,
            max_students=max_students,
            progress_callback=progress_cb,
        )

        # Persist result to temp file for polling
        try:
            with open(_EVAL_RESULT_FILE, 'w') as f:
                json.dump(result, f, default=str)
        except Exception:
            pass

        _write_eval_state({"state": "done", "finished_at": time.time()})

    except Exception as e:
        logger.error(f"Agent evaluation job error: {e}", exc_info=True)
        _write_eval_state({"state": "error", "error": "An internal error occurred"})


