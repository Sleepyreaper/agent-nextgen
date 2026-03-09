"""Admin & data management routes."""

import json
import logging
import os
import tempfile
import threading
import time

from flask import Blueprint, flash, jsonify, render_template, request

from extensions import (
    ArielQAAgent, limiter, require_role, run_async,
    refresh_foundry_dataset_async,
)
from src.config import config
from src.database import db

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__)


# ── Background Task Registry ────────────────────────────────────────
# Centralised list of all background tasks and their state files/poll endpoints.
_BACKGROUND_TASKS = [
    {
        'id': 'gosa_import',
        'label': 'GOSA Data Import',
        'state_file': os.path.join(tempfile.gettempdir(), 'gosa_import_state.json'),
        'poll_url': '/api/schools/import-gosa-from-repo',
    },
    {
        'id': 'school_csv_import',
        'label': 'School CSV Import',
        'state_file': os.path.join(tempfile.gettempdir(), 'school_csv_import_state.json'),
        'poll_url': '/api/schools/import-csv',
    },
    {
        'id': 'batch_naveen',
        'label': 'Batch School Analysis',
        'state_file': os.path.join(tempfile.gettempdir(), 'batch_naveen_state.json'),
        'poll_url': '/api/schools/batch-naveen-moana',
    },
    {
        'id': 'milo_validation',
        'label': 'Milo Validation',
        'state_file': os.path.join(tempfile.gettempdir(), 'milo_validation_state.json'),
        'poll_url': '/api/milo/validate',
    },
    {
        'id': 'training_reprocess',
        'label': 'Training Reprocess',
        'state_file': os.path.join('uploads', 'reprocess_state.json'),
        'poll_url': '/api/training/reprocess',
    },
    {
        'id': 'training_reevaluate',
        'label': 'Training Re-evaluation',
        'state_file': os.path.join(tempfile.gettempdir(), 'training_reevaluate_state.json'),
        'poll_url': '/api/training/re-evaluate',
    },
    {
        'id': 'consistency_test',
        'label': 'Consistency Test',
        'state_file': os.path.join(tempfile.gettempdir(), 'consistency_test_state.json'),
        'poll_url': '/api/test/consistency',
    },
    {
        'id': 'regression_test',
        'label': 'Regression Test Suite',
        'state_file': os.path.join(tempfile.gettempdir(), 'regression_test_state.json'),
        'poll_url': '/api/test/regression',
    },
    {
        'id': 'cross_validation',
        'label': 'Milo Cross-Validation',
        'state_file': os.path.join(tempfile.gettempdir(), 'cross_validation_state.json'),
        'poll_url': '/api/calibration/cross-validate',
    },
]


@admin_bp.route('/api/tasks/status')
def background_task_status():
    """Return the status of all known background tasks.

    Used by the persistent task banner in base.html to show active work
    that survives page refreshes.
    """
    tasks = []
    for task in _BACKGROUND_TASKS:
        path = task['state_file']
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r') as f:
                state = json.load(f)
        except Exception:
            continue
        status = state.get('status') or state.get('state', 'unknown')
        if status in ('idle', 'unknown'):
            continue
        tasks.append({
            'id': task['id'],
            'label': task['label'],
            'status': status,
            'poll_url': task['poll_url'],
            'detail': state,
        })
    return jsonify({'tasks': tasks})


@admin_bp.route('/debug/dataset')
@require_role('admin')
def debug_dataset():
    """Debug view: show raw student_summary and agent_results for recent applications."""
    if os.getenv('WEBSITE_SITE_NAME') and not os.getenv('DEBUG_MODE'):
        return '<h1>404 — Page Not Found</h1>', 404
    try:
        applications_table = db.get_table_name("applications")
        if not applications_table:
            flash('Applications table not found', 'error')
            return render_template('debug_dataset.html', rows=[])

        query = f"SELECT application_id, applicant_name, email, uploaded_date, student_summary, agent_results FROM {applications_table} ORDER BY uploaded_date DESC LIMIT 200"
        rows = db.execute_query(query)

        for r in rows:
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
        logger.error('Error loading dataset: %s', e, exc_info=True)
        flash('An error occurred while loading the dataset', 'error')
        return render_template('debug_dataset.html', rows=[])


@admin_bp.route('/api/admin/reset', methods=['POST'])
@require_role('admin')
@limiter.limit("3 per minute")
def admin_reset():
    """One-click database reset."""
    data = request.get_json(silent=True) or {}
    keep_prod = data.get('keep_production', True)
    try:
        if keep_prod:
            from routes.testing import clear_test_data as _clear_test
            from routes.training import clear_training_data as _clear_train
            test_resp = _clear_test()
            train_resp = _clear_train()
            test_json = test_resp.get_json() if hasattr(test_resp, 'get_json') else {}
            train_json = train_resp.get_json() if hasattr(train_resp, 'get_json') else {}
            return jsonify({
                'status': 'success',
                'training_deleted': train_json.get('count', 0),
                'test_deleted': test_json.get('count', 0)
            })
        else:
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
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500


@admin_bp.route('/data-management')
def data_management():
    """Central hub for database and data operations."""
    return render_template('data_management.html')


@admin_bp.route('/api/students/count', methods=['GET'])
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


@admin_bp.route('/admin/cleanup-test-data', methods=['POST'])
@require_role('admin')
def admin_cleanup_test_data():
    """Clean up contaminated test data records."""
    try:
        conn = db.connect()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT application_id, applicant_name
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
            cursor.execute("UPDATE applications SET is_test_data = FALSE WHERE is_test_data IS NULL")
            test_fixed = cursor.rowcount
            cursor.execute("UPDATE applications SET is_training_example = FALSE WHERE is_training_example IS NULL")
            training_fixed = cursor.rowcount
            conn.commit()
            db._putconn(conn)
            return jsonify({
                'status': 'success',
                'contaminated_found': 0,
                'null_flags_fixed': test_fixed + training_fixed,
                'message': 'No contaminated records found. NULL flags fixed.'
            })

        record_ids = [row[0] for row in contaminated]
        record_names = [row[1] for row in contaminated]

        placeholders = ','.join(['%s'] * len(record_ids))
        cursor.execute(f"""
            UPDATE applications
            SET is_test_data = TRUE, is_training_example = FALSE
            WHERE application_id IN ({placeholders})
        """, record_ids)
        updated_count = cursor.rowcount

        cursor.execute("UPDATE applications SET is_test_data = FALSE WHERE is_test_data IS NULL")
        test_fixed = cursor.rowcount
        cursor.execute("UPDATE applications SET is_training_example = FALSE WHERE is_training_example IS NULL")
        training_fixed = cursor.rowcount

        conn.commit()
        cursor.close()
        db._putconn(conn)

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
        return jsonify({'status': 'error', 'message': 'An internal error occurred'}), 500


@admin_bp.route('/api/admin/retention-cleanup', methods=['POST'])
@require_role('admin')
def admin_retention_cleanup():
    """Purge old telemetry, audit logs, and test records beyond retention window."""
    try:
        retention_days = request.json.get('retention_days', 730) if request.is_json else 730
        retention_days = max(90, min(int(retention_days), 3650))
        result = db.cleanup_old_records(retention_days=retention_days)
        return jsonify({'status': 'success', **result})
    except Exception as e:
        logger.error(f"Retention cleanup failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500


@admin_bp.route('/api/ask-question/<int:application_id>', methods=['POST'])
def ask_question(application_id):
    """Q&A endpoint for asking questions about a student (Ariel agent)."""
    try:
        data = request.get_json()
        question = data.get('question', '').strip()
        conversation_history = data.get('conversation_history', [])

        if not question:
            return jsonify({'success': False, 'error': 'Question cannot be empty', 'answer': None, 'reference_data': {}}), 400
        if len(question) > 2000:
            return jsonify({'success': False, 'error': 'Question is too long (max 2000 characters)', 'answer': None, 'reference_data': {}}), 400

        if ArielQAAgent is None:
            return jsonify({'success': False, 'error': 'Ariel Q&A agent not available in this deployment', 'answer': None, 'reference_data': {}}), 503

        ariel = ArielQAAgent()
        result = run_async(ariel.answer_question(
            application_id=application_id,
            question=question,
            conversation_history=conversation_history
        ))
        if result['success']:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
    except Exception as e:
        logger.error(f"Error in ask_question endpoint: {str(e)}")
        return jsonify({'success': False, 'error': 'An error occurred while processing your question', 'answer': None, 'reference_data': {}}), 500


# ---------------------------------------------------------------------------
# Daily retention cleanup scheduler
# ---------------------------------------------------------------------------
def _daily_retention_cleanup():
    """Run retention cleanup if it hasn't been run today."""
    lock_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', '.retention_last_run')
    today = time.strftime('%Y-%m-%d')
    try:
        if os.path.exists(lock_path):
            with open(lock_path) as f:
                if f.read().strip() == today:
                    return
    except OSError:
        pass
    try:
        retention_days = int(os.getenv('RETENTION_DAYS', '730'))
        retention_days = max(90, min(retention_days, 3650))
        result = db.cleanup_old_records(retention_days=retention_days)
        logger.info(f"Daily retention cleanup completed: {result}")
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with open(lock_path, 'w') as f:
            f.write(today)
    except Exception as e:
        logger.debug(f"Daily retention cleanup skipped: {e}")


def _schedule_retention():
    """Schedule retention cleanup to run once per day."""
    _daily_retention_cleanup()
    t = threading.Timer(86400, _schedule_retention)
    t.daemon = True
    t.start()


def start_retention_scheduler():
    """Start the daily retention scheduler after a delay."""
    if os.getenv('WEBSITE_SITE_NAME'):
        _retention_timer = threading.Timer(60, _schedule_retention)
        _retention_timer.daemon = True
        _retention_timer.start()
