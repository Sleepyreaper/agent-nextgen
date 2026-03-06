"""Testing routes — test system, SSE streaming, test data management."""

import json
import logging
import os
import queue
import threading
import time
import uuid

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, stream_with_context, url_for
from werkzeug.utils import secure_filename

from extensions import (
    csrf, limiter, run_async,
    get_belle, get_orchestrator,
    _make_ocr_callback, start_application_processing,
    extract_student_name, extract_student_email,
    test_submissions, aurora,
)
from src.config import config
from src.database import db
from src.storage import storage
from src.document_processor import DocumentProcessor
from src.test_data_generator import test_data_generator
from src.agents.agent_requirements import AgentRequirements

logger = logging.getLogger(__name__)

testing_bp = Blueprint('testing', __name__)


@testing_bp.route('/test')
def test():
    """Test system page with quick test generation."""
    try:
        return render_template('test.html')
    except Exception as e:
        logger.error(f'Error loading test page: {e}', exc_info=True)
        return '<h1>Error loading test page</h1><p>An internal error occurred.</p>', 500



@testing_bp.route('/test-data')
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
        logger.error('Error loading test data: %s', e, exc_info=True)
        flash('An error occurred while loading test data', 'error')
        return render_template('test_data.html',
                             test_students=[],
                             total_count=0)



@testing_bp.route('/api/test/stream/<session_id>')
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




@testing_bp.route('/api/test/submit', methods=['POST'])
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
            'stream_url': url_for('testing.test_stream', session_id=session_id)
        })
    except Exception as e:
        logger.error("submit_test_data failed: %s", e, exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500



@testing_bp.route('/api/test/submit-preset', methods=['POST'])
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
            'stream_url': url_for('testing.test_stream', session_id=session_id)
        })
    except Exception as e:
        logger.error("submit_preset_test_data failed: %s", e, exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500



@testing_bp.route('/api/test/submit-single', methods=['POST'])
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
            'stream_url': url_for('testing.test_stream', session_id=session_id)
        })
    except Exception as e:
        logger.error("submit_single_test_data failed: %s", e, exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500



@testing_bp.route('/api/test/cleanup', methods=['POST'])
def cleanup_test_endpoint():
    """
    API endpoint to manually clear all test data from the database.
    Useful for starting fresh without running a full test.
    """
    try:
        cleanup_test_data()

        test_col = db.get_test_data_column()
        
        # Count remaining test data (should be 0 after cleanup)
        remaining = db.execute_query(
            f"SELECT COUNT(*) as count FROM Applications WHERE {test_col} = TRUE"
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
            'error': 'An internal error occurred'
        }), 500



@testing_bp.route('/api/test/upload-files', methods=['POST'])
def upload_test_files():
    """
    Upload real files from the test page for agent evaluation.
    Accepts chunked blob references (same WAF-friendly pattern as main upload).
    Falls back to direct file upload for local/dev environments.
    """
    try:
        # ── Determine upload source: chunked blobs or direct files ──
        blob_info_raw = (request.form.get('chunked_blob_info') or '').strip()
        has_blobs = False
        if blob_info_raw:
            import base64 as _b64
            try:
                decoded = _b64.b64decode(blob_info_raw).decode('utf-8')
            except Exception:
                decoded = blob_info_raw
            try:
                chunked_blobs = json.loads(decoded)
                has_blobs = isinstance(chunked_blobs, list) and len(chunked_blobs) > 0
            except Exception:
                chunked_blobs = []

        has_direct_files = (
            'files' in request.files
            and any(f.filename for f in request.files.getlist('files'))
        )

        if not has_blobs and not has_direct_files:
            return jsonify({'status': 'error', 'error': 'No files uploaded'}), 400
        
        uploaded_students_map = {}
        app_doc_types = {
            'application',
            'personal_statement',
            'essay'
        }
        transcript_doc_types = {'transcript', 'grades'}
        recommendation_doc_types = {'letter_of_recommendation'}

        # ── Process chunked blob references (WAF-safe path) ──
        if has_blobs:
            for cblob in chunked_blobs:
                blob_path = cblob.get('blob_path')
                cfilename = secure_filename(cblob.get('filename', 'file.bin'))
                if not blob_path:
                    continue

                student_id = storage.generate_student_id()
                temp_id = uuid.uuid4().hex
                temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"temp_{temp_id}_{cfilename}")

                try:
                    ok = storage.download_blob_to_file(
                        blob_path=blob_path,
                        local_path=temp_path,
                        application_type='test',
                    )
                    if not ok:
                        logger.warning(f"Could not retrieve {cfilename} from storage")
                        continue

                    ocr_callback = _make_ocr_callback()
                    application_text, file_type = DocumentProcessor.process_document(
                        temp_path, ocr_callback=ocr_callback
                    )

                    try:
                        belle = get_belle()
                        doc_analysis = belle.analyze_document(application_text, cfilename)
                    except Exception as e:
                        logger.warning(f"Belle analysis failed for test upload: {e}")
                        doc_analysis = {
                            "document_type": "unknown",
                            "confidence": 0,
                            "student_info": {},
                            "extracted_data": {}
                        }
                finally:
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

                belle_student_info = doc_analysis.get('student_info', {})
                student_name = belle_student_info.get('name') or extract_student_name(application_text)
                student_email = belle_student_info.get('email') or extract_student_email(application_text)

                doc_type = doc_analysis.get('document_type', 'unknown')
                agent_fields = doc_analysis.get('agent_fields', {})
                school_name = agent_fields.get('school_name')

                identity_key = (student_email or student_name or cfilename).strip().lower()
                if identity_key not in uploaded_students_map:
                    uploaded_students_map[identity_key] = {
                        'name': student_name or f"Student from {cfilename}",
                        'email': student_email or "",
                        'application_text': "",
                        'transcript_text': "",
                        'recommendation_text': "",
                        'recommendation_texts': [],
                        'filenames': [],
                        'school_data': {'name': school_name} if school_name else {}
                    }

                record = uploaded_students_map[identity_key]
                record['filenames'].append(cfilename)
                if school_name and not record.get('school_data'):
                    record['school_data'] = {'name': school_name}

                # ── Prefer Belle's section-detected agent_fields over doc_type ──
                # Belle's _detect_document_sections() routes individual pages to
                # transcript_text / recommendation_text / application_text.  Use
                # those when available for precise multi-section routing.
                used_agent_fields = False
                for af_field in ('application_text', 'transcript_text', 'recommendation_text'):
                    af_val = agent_fields.get(af_field)
                    if af_val and isinstance(af_val, str) and len(af_val.strip()) > 20:
                        label = af_field.replace('_text', '').title()
                        if record[af_field]:
                            record[af_field] += f"\n\n--- Additional {label} Document ---\n\n"
                        record[af_field] += af_val
                        if af_field == 'recommendation_text':
                            record['recommendation_texts'].append(af_val)
                        used_agent_fields = True

                if not used_agent_fields:
                    # Fallback: route whole document text by doc_type
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

        # ── Fallback: direct file upload (local dev without WAF) ──
        if has_direct_files and not has_blobs:
            files = request.files.getlist('files')
            for file in files:
                if file.filename == '':
                    continue
                if not DocumentProcessor.validate_file_type(file.filename):
                    continue

                student_id = storage.generate_student_id()
                filename = secure_filename(file.filename)
                temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"temp_{student_id}_{filename}")
                file.save(temp_path)

                ocr_callback = _make_ocr_callback()
                application_text, file_type = DocumentProcessor.process_document(
                    temp_path, ocr_callback=ocr_callback
                )

                with open(temp_path, 'rb') as f:
                    file_content = f.read()

                storage.upload_file(
                    file_content=file_content,
                    filename=filename,
                    student_id=student_id,
                    application_type='test'
                )

                try:
                    os.remove(temp_path)
                except Exception:
                    pass

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

                # ── Prefer Belle's section-detected agent_fields over doc_type ──
                used_agent_fields = False
                for af_field in ('application_text', 'transcript_text', 'recommendation_text'):
                    af_val = agent_fields.get(af_field)
                    if af_val and isinstance(af_val, str) and len(af_val.strip()) > 20:
                        label = af_field.replace('_text', '').title()
                        if record[af_field]:
                            record[af_field] += f"\n\n--- Additional {label} Document ---\n\n"
                        record[af_field] += af_val
                        if af_field == 'recommendation_text':
                            record['recommendation_texts'].append(af_val)
                        used_agent_fields = True

                if not used_agent_fields:
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
            'stream_url': url_for('testing.test_stream', session_id=session_id)
        })
        
    except Exception as e:
        logger.error(f"Error uploading test files: {str(e)}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@testing_bp.route('/api/test/stats', methods=['GET'])
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
            'error': 'An internal error occurred'
        }), 500



@testing_bp.route('/api/test/submissions', methods=['GET'])
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
            'error': 'An internal error occurred'
        }), 500



@testing_bp.route('/api/test/students', methods=['GET'])
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

        # Resolve file_type column for Mirabel (video) detection
        file_type_select = "NULL as file_type"
        file_type_group = None
        if db.has_applications_column('file_type'):
            file_type_select = "a.file_type"
            file_type_group = "a.file_type"

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
        if file_type_group:
            group_by_parts.append(file_type_group)

        group_by_clause = ", ".join(group_by_parts)

        query = f"""
            SELECT 
                a.{app_id_col} as application_id,
                a.{applicant_col} as applicant_name,
                a.{email_col} as email,
                a.{status_col} as status,
                a.{uploaded_col} as uploaded_date,
                {student_id_select},
                {file_type_select},
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
            has_merlin = bool(student.get('has_merlin'))
            has_any_downstream = any([
                student.get('has_tiana'), student.get('has_rapunzel'),
                student.get('has_mulan'), student.get('has_moana'), has_merlin
            ])
            is_video = (student.get('file_type') or '').lower() in ('mp4', 'video', 'mov', 'avi', 'webm')

            # When Merlin is done, the full pipeline completed — mark all agents done
            if has_merlin:
                agent_status = {
                    'belle': 'complete',
                    'mirabel': 'complete' if is_video else 'skipped',
                    'smee': 'complete',
                    'naveen': 'complete',
                    'application_reader': 'complete',
                    'grade_reader': 'complete',
                    'school_context': 'complete',
                    'recommendation_reader': 'complete',
                    'data_scientist': 'complete',
                    'student_evaluator': 'complete',
                    'aurora': 'complete' if student.get('has_aurora') else 'pending',
                    'fairy_godmother': 'complete' if student.get('has_aurora') else 'pending',
                }
            else:
                agent_status = {
                    'belle': 'complete' if has_any_downstream else 'pending',
                    'mirabel': ('complete' if has_any_downstream else 'pending') if is_video else 'skipped',
                    'smee': 'complete' if all([student.get('has_tiana'), student.get('has_rapunzel'), student.get('has_mulan'),
                                               student.get('has_moana'), has_merlin]) else 'pending',
                    'naveen': 'complete' if student.get('has_moana') else 'pending',
                    'application_reader': 'complete' if student.get('has_tiana') else 'pending',
                    'grade_reader': 'complete' if student.get('has_rapunzel') else 'pending',
                    'school_context': 'complete' if student.get('has_moana') else 'pending',
                    'recommendation_reader': 'complete' if student.get('has_mulan') else 'pending',
                    'data_scientist': 'pending',
                    'student_evaluator': 'pending',
                    'aurora': 'complete' if student.get('has_aurora') else 'pending',
                    'fairy_godmother': 'pending',
                }

            is_complete = (student.get('has_tiana') and student.get('has_rapunzel') and student.get('has_mulan') and
                          student.get('has_moana') and has_merlin)
            
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
            'error': 'An internal error occurred'
        }), 500

        return jsonify({
            'status': 'error',
            'error': 'An internal error occurred'
        }), 500



@testing_bp.route('/api/test-data/list', methods=['GET'])
def get_test_data_list():
    """Get all test data (applications marked with is_test_data = TRUE)."""
    try:
        applications_table = db.get_table_name("applications")
        test_col = db.get_test_data_column()
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

        # Get all applications marked as test data (is_test_data = TRUE)
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
            WHERE a.{test_col} = TRUE
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
            'error': 'An internal error occurred',
            'count': 0,
            'students': []
        }), 500
        return jsonify({
            'status': 'error',
            'error': 'An internal error occurred'
        }), 500



@testing_bp.route('/api/test-data/clear', methods=['POST'])
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
            'error': 'An internal error occurred'
        }), 500



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



# start_application_processing and start_training_processing moved to extensions.py (Issue #23)

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
            yield {'type': 'error', 'error': 'Failed to create student record'}

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

                    result = run_async(orchestrator.coordinate_evaluation(
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
                    update_queue.put({'_orchestration_error': True, 'error': 'An internal error occurred'})

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
                # Only save if Merlin actually produced meaningful content
                # (not an empty_response with null score and no recommendation)
                has_content = (
                    merlin_result.get('overall_score') is not None
                    or merlin_result.get('recommendation')
                    or merlin_result.get('rationale')
                )
                if merlin_result and merlin_result.get('status') == 'success' and has_content:
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
                elif merlin_result and merlin_result.get('status') == 'empty_response':
                    logger.warning(f"Merlin returned empty response for application {application_id} — skipping save")

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
                'error': 'Processing failed'
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
            'message': 'Data saved in memory but database save failed'
        }



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
            submission['queue'].put({'type': 'error', 'error': 'An internal error occurred'})


