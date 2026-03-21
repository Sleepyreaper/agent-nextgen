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


# ── Agent Team Registry (for team page) ─────────────────────────────
# Portraits that exist in web/static/images/agents/
_PORTRAIT_FILES = {'ariel', 'aurora', 'gaston', 'merlin', 'moana', 'rapunzel', 'smee'}

AGENT_TEAM = [
    {"name": "Smee", "slug": "smee", "emoji": "🎩", "title": "Chief Orchestrator", "tier": "orchestrator",
     "model": "o3", "color": "#F2A900", "step": 0, "foundry_slug": "nextgen-smee",
     "output_summary": "Pipeline coordination",
     "bio": "Captain Hook's loyal first mate keeps the entire crew running smoothly. Smee coordinates 12 agents, manages checkpoints, handles cancellations, and ensures every student gets a fair, thorough evaluation.",
     "mission_role": "Routes documents to the right agents, ensures school context is built before academic evaluation, and manages the quality gate so nothing falls through the cracks."},
    {"name": "Belle", "slug": "belle", "emoji": "📖", "title": "Document Intelligence Specialist", "tier": "workhorse",
     "model": "gpt-5.4", "color": "#5b21b6", "step": 1, "foundry_slug": "nextgen-belle",
     "output_summary": "Section detection, text extraction",
     "bio": "The bookworm who reads everything. Belle analyzes uploaded PDFs and documents, detects sections (transcript, essay, recommendation), and extracts complete text for every downstream agent.",
     "mission_role": "Extracts FULL text — never truncates. Downstream agents need every word to find the Diamond signals that summaries would miss."},
    {"name": "Tiana", "slug": "tiana", "emoji": "📝", "title": "Application Content Specialist", "tier": "workhorse",
     "model": "gpt-5.4", "color": "#0d9488", "step": 2, "foundry_slug": "nextgen-tiana",
     "output_summary": "Essay analysis, diamond indicators",
     "bio": "Hardworking and determined, Tiana reads every application looking for genuine passion — not polished prose. She scores essays, activities, leadership, and identifies the Diamond in the Rough indicators that metrics can't capture.",
     "mission_role": "Finds authentic voice and resilience signals. Asks: does the essay lack polish because of limited access to editing help, or limited capability?"},
    {"name": "Rapunzel", "slug": "rapunzel", "emoji": "👑", "title": "Academic Record Specialist", "tier": "premium",
     "model": "gpt-5.4-pro", "color": "#7c3aed", "step": 3, "foundry_slug": "nextgen-rapunzel",
     "output_summary": "GPA, courses, rigor, trends",
     "bio": "Curious and analytical, Rapunzel doesn't just read grades — she reads the story behind them. A 3.95 GPA at a school with 3 AP courses means something very different than a 3.95 at a school with 25.",
     "mission_role": "Contextualizes grades within school resources. Identifies students performing at the ceiling of what their school offers — the strongest Diamond signal in academics."},
    {"name": "Mulan", "slug": "mulan", "emoji": "💌", "title": "Recommendation Letter Specialist", "tier": "workhorse",
     "model": "gpt-5.4", "color": "#991b1b", "step": 4, "foundry_slug": "nextgen-mulan",
     "output_summary": "Endorsement strength, authenticity",
     "bio": "Mulan looks beyond the words to understand what recommenders REALLY think. A specific anecdote from a teacher who clearly knows the student is worth more than ten generic superlatives.",
     "mission_role": "Detects whether generic recommendations reflect an unremarkable student or an overloaded teacher with 180 students. The difference changes the evaluation."},
    {"name": "Naveen", "slug": "naveen", "emoji": "🏫", "title": "School Data Scientist", "tier": "workhorse",
     "model": "gpt-5.4", "color": "#1e40af", "step": 5, "foundry_slug": None,
     "output_summary": "School component scores, opportunity score",
     "bio": "Naveen evaluates school context using public NCES data — AP availability, per-pupil funding, student-teacher ratios, graduation rates, and free lunch percentages. Every school gets a data-driven opportunity score.",
     "mission_role": "Quantifies the resources available to each student's school so the committee can understand what opportunities existed — and what didn't."},
    {"name": "Moana", "slug": "moana", "emoji": "🌊", "title": "School Context Narrator", "tier": "workhorse",
     "model": "gpt-5.4", "color": "#115e59", "step": 6, "foundry_slug": None,
     "output_summary": "School narrative, equity context",
     "bio": "Moana builds the story of each student's school environment — weaving Naveen's data with Rapunzel's grades to create a narrative the committee can feel. Not just numbers, but what it's LIKE to learn there.",
     "mission_role": "Answers: 'What was this student's world like?' A school with no AP STEM courses and 70% free lunch tells a different story than a magnet school in the suburbs."},
    {"name": "Pocahontas", "slug": "pocahontas", "emoji": "🪶", "title": "Cohort Equity Analyst", "tier": "workhorse",
     "model": "gpt-5.4", "color": "#854d0e", "step": 7, "foundry_slug": None,
     "output_summary": "Equity tier, context multiplier",
     "bio": "Pocahontas looks across the entire applicant pool to ensure fairness. She assigns equity tiers based on school resources and calculates context multipliers that adjust scores for students from under-resourced schools.",
     "mission_role": "The equity engine. A student from a Tier 5 (severely under-resourced) school gets a context multiplier up to 1.25x — because their B means more than others' A."},
    {"name": "Mirabel", "slug": "mirabel", "emoji": "🔮", "title": "Video Intelligence Specialist", "tier": "vision",
     "model": "gpt-4o", "color": "#0891b2", "step": 8, "foundry_slug": "nextgen-mirabel",
     "output_summary": "Video transcription, presentation quality",
     "bio": "Like her Encanto namesake who sees the extraordinary in what others overlook, Mirabel analyzes video submissions — extracting spoken content, assessing communication skills, and finding what documents can't capture.",
     "mission_role": "Videos reveal authenticity, confidence, and passion that paper applications can't. Mirabel finds the Diamond signals that only show when a student speaks in their own voice."},
    {"name": "Merlin", "slug": "merlin", "emoji": "🧙", "title": "Synthesis Evaluator", "tier": "premium",
     "model": "gpt-5.4-pro", "color": "#6d28d9", "step": 9, "foundry_slug": "nextgen-merlin",
     "output_summary": "Final score, recommendation, rationale",
     "bio": "The wise synthesizer who brings everything together. Merlin integrates all agent outputs into a final evaluation, answering: would I fight for this student? Before scoring, he answers five fairness questions to ensure equity.",
     "mission_role": "Asks: Is this student at the ceiling of their opportunities? Would they thrive with MORE access? Is this the student the committee would miss? If yes — ADMIT."},
    {"name": "Gaston", "slug": "gaston", "emoji": "💪", "title": "Quality & Bias Auditor", "tier": "reasoning",
     "model": "o3", "color": "#dc2626", "step": 10, "foundry_slug": "nextgen-gaston",
     "output_summary": "Review flags, consistency, bias check",
     "bio": "No one audits like Gaston. He's learned humility and now uses his keen eye to catch bias, inconsistency, and unfairness in evaluations. He reviews every core agent's output AND audits Merlin's final evaluation.",
     "mission_role": "The fairness guardian. Catches when evaluations penalize students for things beyond their control — fewer AP courses, generic recommendations from overloaded teachers, unpolished essays from students without editing access."},
    {"name": "Milo", "slug": "milo", "emoji": "📊", "title": "Data Scientist", "tier": "premium",
     "model": "gpt-5.4-pro", "color": "#065f46", "step": 11, "foundry_slug": None,
     "output_summary": "ML prediction, training insights",
     "bio": "Milo brings machine learning to scholarship evaluation — training models on historical data to identify patterns the committee has rewarded before, and flagging where the current applicant differs from past selections.",
     "mission_role": "Spots students who don't fit the traditional mold but show the same patterns as past Diamonds in the Rough who were ultimately selected."},
    {"name": "Aurora", "slug": "aurora", "emoji": "✨", "title": "Report Formatter", "tier": "workhorse",
     "model": "gpt-5.4", "color": "#db2777", "step": 12, "foundry_slug": "nextgen-aurora",
     "output_summary": "Executive summary, formatted report",
     "bio": "Aurora brings clarity to complexity. She formats all agent outputs into a compelling, committee-ready report that tells the student's story — not a data dump, but a narrative that helps the committee make confident decisions.",
     "mission_role": "Formats the 'What the Committee Might Miss' callout and the Diamond in the Rough assessment into the language that gets students a second look."},
    {"name": "Ariel", "slug": "ariel", "emoji": "🧜", "title": "Conversational Q&A", "tier": "workhorse",
     "model": "gpt-5.4", "color": "#2563eb", "step": "-", "foundry_slug": None,
     "output_summary": "Interactive Q&A over applicant data",
     "bio": "Curious about the human world above, Ariel answers the committee's questions in natural language. Ask her anything about a student's evaluation and she'll dive into the data to find the answer.",
     "mission_role": "Lets committee members explore any student's data conversationally — 'Why was this student waitlisted?' or 'What did the recommender say about their STEM interest?'"},
]

# Add has_portrait flag
for _a in AGENT_TEAM:
    _a['has_portrait'] = _a['slug'] in _PORTRAIT_FILES


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


@admin_bp.route('/api/admin/reset-2026', methods=['POST'])
@require_role('admin')
@limiter.limit("2 per minute")
def admin_reset_2026():
    """v2.0 Fresh Start — Reset all 2026 application data and student evaluations.
    PRESERVES: schools, school_enriched_data, historical_scores.
    DELETES: applications, agent results, training examples, test data, blob PDFs."""
    data = request.get_json(silent=True) or {}
    if data.get('confirm') != 'RESET-2026-FRESH-START':
        return jsonify({'error': 'Send {"confirm": "RESET-2026-FRESH-START"}'}), 400
    results = {'tables': {}, 'blobs': {}, 'errors': []}
    for tbl in ['aurora_communications', 'merlin_evaluations', 'mulan_recommendations',
                'rapunzel_grades', 'tiana_applications', 'student_school_context',
                'ai_evaluations', 'aurora_evaluations', 'agent_audit_logs',
                'agent_evaluation_results', 'agent_evaluation_runs', 'test_submissions',
                'grade_records', 'user_feedback', 'selection_decisions', 'training_feedback']:
        try:
            results['tables'][tbl] = db.execute_non_query(f"DELETE FROM {tbl}") or 0
        except Exception as e:
            results['errors'].append(f"{tbl}: {str(e)[:80]}")
    try:
        results['tables']['applications'] = db.execute_non_query("DELETE FROM applications") or 0
    except Exception as e:
        results['errors'].append(f"applications: {str(e)[:80]}")
    try:
        from azure.storage.blob import BlobServiceClient
        from azure.identity import DefaultAzureCredential
        if config.storage_account_name:
            bc = BlobServiceClient(account_url=f"https://{config.storage_account_name}.blob.core.windows.net", credential=DefaultAzureCredential())
            for cn in ['applications-2026', 'applications-test']:
                try:
                    c = bc.get_container_client(cn)
                    blobs = list(c.list_blobs())
                    for b in blobs: c.delete_blob(b.name)
                    results['blobs'][cn] = len(blobs)
                except Exception as e:
                    results['errors'].append(f"blob {cn}: {str(e)[:80]}")
    except Exception as e:
        results['errors'].append(f"blob init: {str(e)[:80]}")
    total = sum(results['tables'].values()) + sum(results['blobs'].values())
    logger.warning("v2.0 RESET: %d deleted, errors=%s", total, results['errors'])
    return jsonify({'status': 'success' if not results['errors'] else 'partial', 'total_deleted': total, **results})


@admin_bp.route('/api/admin/reset-training', methods=['POST'])
@require_role('admin')
@limiter.limit("3 per minute")
def admin_reset_training():
    """Reset training data only. Milo rebuilds from scratch. historical_scores preserved."""
    data = request.get_json(silent=True) or {}
    if data.get('confirm') != 'RESET-TRAINING':
        return jsonify({'error': 'Send {"confirm": "RESET-TRAINING"}'}), 400
    try:
        apps = db.execute_query("SELECT application_id FROM applications WHERE is_training_example = TRUE")
        ids = [r.get('application_id', r) for r in (apps or [])]
        deleted = 0
        if ids:
            id_list = ','.join(str(a) for a in ids)
            for tbl in ['merlin_evaluations', 'tiana_applications', 'rapunzel_grades', 'mulan_recommendations', 'student_school_context', 'aurora_evaluations', 'ai_evaluations', 'agent_audit_logs']:
                try: db.execute_non_query(f"DELETE FROM {tbl} WHERE application_id IN ({id_list})")
                except: pass
            deleted = db.execute_non_query("DELETE FROM applications WHERE is_training_example = TRUE") or 0
        return jsonify({'status': 'success', 'training_deleted': deleted, 'historical_scores': 'preserved'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)[:200]}), 500


@admin_bp.route('/api/admin/data-inventory', methods=['GET'])
def admin_data_inventory():
    """Quick inventory of all data — check before reset."""
    try:
        counts = {}
        for tbl in ['applications', 'merlin_evaluations', 'schools', 'school_enriched_data', 'historical_scores']:
            try:
                r = db.execute_query(f"SELECT COUNT(*) as cnt FROM {tbl}")
                counts[tbl] = r[0].get('cnt', 0) if r else 0
            except: counts[tbl] = 'n/a'
        try:
            bd = db.execute_query("SELECT COUNT(*) as total, SUM(CASE WHEN is_training_example=TRUE THEN 1 ELSE 0 END) as training, SUM(CASE WHEN is_test_data=TRUE THEN 1 ELSE 0 END) as test FROM applications")
            counts['breakdown'] = bd[0] if bd else {}
        except: pass
        return jsonify({'status': 'ok', 'counts': counts})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


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


@admin_bp.route('/team')
def team_page():
    """Meet the evaluation team — agent profiles and pipeline visualization."""
    return render_template('team.html', agents=AGENT_TEAM)


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
# Uses a PostgreSQL advisory lock to prevent duplicate runs across gunicorn
# workers. The lock is session-level (released when the connection returns to
# the pool), so only one worker runs cleanup per day.
_RETENTION_ADVISORY_LOCK_ID = 8675309  # arbitrary unique int

def _daily_retention_cleanup():
    """Run retention cleanup if it hasn't been run today.

    Uses pg_try_advisory_lock to ensure only one worker runs cleanup,
    even with multiple gunicorn workers.
    """
    try:
        # Try to acquire advisory lock — returns immediately, no blocking
        rows = db.execute_query(
            "SELECT pg_try_advisory_lock(%s) AS acquired",
            (_RETENTION_ADVISORY_LOCK_ID,)
        )
        if not rows or not rows[0].get('acquired'):
            return  # Another worker has the lock

        # Check if we already ran today (using DB time, not filesystem)
        today_check = db.execute_query(
            "SELECT EXISTS(SELECT 1 FROM telemetry_events "
            "WHERE event_name = 'retention_cleanup' "
            "AND created_at >= CURRENT_DATE) AS ran_today"
        )
        if today_check and today_check[0].get('ran_today'):
            # Release lock and skip
            db.execute_query("SELECT pg_advisory_unlock(%s)", (_RETENTION_ADVISORY_LOCK_ID,))
            return

        retention_days = int(os.getenv('RETENTION_DAYS', '730'))
        retention_days = max(90, min(retention_days, 3650))
        result = db.cleanup_old_records(retention_days=retention_days)
        logger.info(f"Daily retention cleanup completed: {result}")

        # Record that we ran (so other workers/restarts skip today)
        try:
            db.execute_non_query(
                "INSERT INTO telemetry_events (event_name, event_data, created_at) "
                "VALUES ('retention_cleanup', %s, NOW())",
                (json.dumps(result, default=str),)
            )
        except Exception:
            pass  # telemetry_events table may not exist yet

        # Release advisory lock
        db.execute_query("SELECT pg_advisory_unlock(%s)", (_RETENTION_ADVISORY_LOCK_ID,))
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


# ---------------------------------------------------------------------------
# Database Server Management — Start stopped PostgreSQL Flexible Server
# ---------------------------------------------------------------------------
@admin_bp.route('/api/admin/db-status', methods=['GET'])
def db_status():
    """Check if the database is reachable."""
    try:
        db.execute_query("SELECT 1")
        return jsonify({'status': 'online'})
    except Exception as e:
        return jsonify({'status': 'offline', 'error': str(e)}), 503


@admin_bp.route('/api/admin/start-database', methods=['POST'])
@require_role('admin')
@limiter.limit("3 per hour")
def start_database():
    """Start the Azure PostgreSQL Flexible Server if it was stopped (nightly policy).

    Uses Azure REST API with managed identity to issue the start command.
    """
    import requests as _requests

    server_name = os.getenv('POSTGRES_SERVER_NAME', 'nextgenagentpostgres')
    resource_group = os.getenv('AZURE_RESOURCE_GROUP', 'NextGen_Agents')
    subscription_id = os.getenv('AZURE_SUBSCRIPTION_ID', '')

    if not subscription_id:
        # Try to get from config
        subscription_id = getattr(config, 'azure_subscription_id', '')
    if not subscription_id:
        return jsonify({'status': 'error', 'error': 'AZURE_SUBSCRIPTION_ID not configured'}), 500

    try:
        # Get managed identity token for ARM
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        token = credential.get_token("https://management.azure.com/.default")

        # Call Azure REST API to start the server
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.DBforPostgreSQL/flexibleServers/{server_name}"
            f"/start?api-version=2022-12-01"
        )
        resp = _requests.post(url, headers={
            'Authorization': f'Bearer {token.token}',
            'Content-Type': 'application/json',
        }, timeout=30)

        if resp.status_code in (200, 202):
            logger.info(f"Database start initiated: {server_name} (HTTP {resp.status_code})")
            return jsonify({
                'status': 'success',
                'message': f'Database server {server_name} is starting. It may take 1-2 minutes to become available.',
            })
        else:
            logger.error(f"Database start failed: HTTP {resp.status_code} — {resp.text[:200]}")
            return jsonify({
                'status': 'error',
                'error': f'Azure returned HTTP {resp.status_code}',
            }), resp.status_code

    except Exception as e:
        logger.error(f"Database start error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': 'Failed to start database server'}), 500
