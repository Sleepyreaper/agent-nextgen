"""Application routes — student evaluation, processing, status, detail views."""

import json
import logging
import os
import queue
import threading
import time

from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, stream_with_context, url_for

from extensions import (
    csrf, limiter, run_async,
    get_ai_client, get_ai_client_mini,
    get_evaluator, get_belle, get_mirabel, get_orchestrator,
    _make_ocr_callback, refresh_foundry_dataset_async,
    start_application_processing,
    extract_student_name, extract_student_email,
    _split_name_parts, _build_identity_key,
    _aggregate_documents, _collect_documents_from_storage,
    find_high_probability_match,
    AuroraAgent,
)
from src.config import config
from src.database import db
from src.storage import storage
from src.document_processor import DocumentProcessor
from src.utils import safe_load_json
from src.agents.agent_requirements import AgentRequirements

logger = logging.getLogger(__name__)

applications_bp = Blueprint('applications', __name__)


@applications_bp.route('/evaluate/<int:application_id>', methods=['POST'])
def evaluate(application_id):
    """Evaluate a single application."""
    try:
        # Get application
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Application not found'}), 404
        
        # Get evaluator and run evaluation
        evaluator = get_evaluator()
        evaluation = run_async(evaluator.evaluate_application(application))
        
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500



@applications_bp.route('/evaluate_all', methods=['POST'])
def evaluate_all():
    """Evaluate all pending applications."""
    try:
        pending = db.get_pending_applications()
        evaluator = get_evaluator()
        
        results = []
        for application in pending:
            evaluation = run_async(evaluator.evaluate_application(application))
            
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500



@applications_bp.route('/students')
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
        logger.error('Error loading students: %s', e, exc_info=True); flash('An error occurred while loading students', 'error')
        return render_template('students.html', students=[], search_query='')



@applications_bp.route('/process/<int:application_id>')
def process_student(application_id):
    """Process student through Smee orchestrator."""
    try:
        application = db.get_application(application_id)
        if not application:
            flash('Student not found', 'error')
            return redirect(url_for('applications.students'))
        
        # Show processing page with progress
        return render_template('process_student.html', 
                             application=application,
                             application_id=application_id)
        
    except Exception as e:
        logger.error('Operation failed: %s', e, exc_info=True)
        flash('An error occurred', 'error')
        return redirect(url_for('applications.students'))



@applications_bp.route('/api/process/<int:application_id>', methods=['POST'])
def api_process_student(application_id):
    """API endpoint to process student with Smee orchestrator."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'error': 'Student not found'}), 404
        
        # Get orchestrator
        orchestrator = get_orchestrator()
        
        # Run full agent pipeline
        result = run_async(
            orchestrator.coordinate_evaluation(
                application=application,
                evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'data_scientist', 'student_evaluator', 'aurora']
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
        logger.error("API process failed for application %s: %s", application_id, e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500



@applications_bp.route('/api/process/stream/<int:application_id>')
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



@applications_bp.route('/api/status/<int:application_id>')
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
        logger.error("API debug model_test failed: %s", e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500



@applications_bp.route('/api/missing-fields/<int:application_id>', methods=['GET'])
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
            'error': 'An internal error occurred'
        }), 500



@applications_bp.route('/api/debug/model_test', methods=['POST'])
def api_debug_model_test():
    """Debug endpoint: perform a lightweight model call and log payload/response.

    This endpoint is intended for short-lived diagnostics only. It uses the
    configured `get_ai_client()` so the call will exercise the same client
    wiring as the running application (Foundry or Azure OpenAI).
    """
    if os.getenv('WEBSITE_SITE_NAME'):
        return jsonify({'error': 'Not found'}), 404
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

        logger.info("Model test result: %s", result_text)
        return jsonify({
            "success": True,
            "model": model_name,
            "result": result_text,
            "client_type": client_type,
            "client_candidate_attrs": candidate_attrs,
            "configured_provider": config.model_provider
        })

    except Exception as e:
        logger.exception("Debug model test endpoint error: %s", e)
        return jsonify({"success": False, "error": "An internal error occurred"}), 500



@applications_bp.route('/api/missing-fields/<int:application_id>', methods=['POST'])
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
            'error': 'An internal error occurred'
        }), 500



@applications_bp.route('/api/agent-questions/<int:application_id>', methods=['GET'])
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
            'error': 'An internal error occurred'
        }), 500



@applications_bp.route('/api/categorize-upload/<int:application_id>', methods=['POST'])
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
            'error': 'An internal error occurred'
        }), 500



@applications_bp.route('/api/resume-evaluation/<int:application_id>', methods=['POST'])
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
        result = run_async(
            orchestrator.coordinate_evaluation(
                application=application,
                evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'data_scientist', 'student_evaluator', 'aurora']
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
            'error': 'An internal error occurred'
        }), 500

@applications_bp.route('/application/<int:application_id>')
def student_detail(application_id):
    """View details of a student application with all agent evaluations."""
    try:
        logger.debug(f"student_detail called with application_id={application_id}")
        application = db.get_application(application_id)
        logger.debug(f"db.get_application returned: {application is not None}")
        
        if not application:
            logger.warning(f"Application {application_id} not found")
            flash('Student not found', 'error')
            return redirect(url_for('applications.students'))
        
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

                        # Detect message-object-shaped parsed_json (has 'role'
                        # and 'refusal' from Foundry adapter) and try to unwrap
                        # the nested 'content' to find actual evaluation data.
                        if isinstance(parsed, dict) and 'role' in parsed and 'refusal' in parsed:
                            inner_content = parsed.get('content', '')
                            if isinstance(inner_content, str) and inner_content.strip():
                                try:
                                    unwrapped = json.loads(inner_content)
                                    if isinstance(unwrapped, dict):
                                        parsed = unwrapped
                                        agent_results['merlin']['parsed_data'] = parsed
                                except Exception:
                                    pass
                            elif isinstance(inner_content, dict):
                                parsed = inner_content
                                agent_results['merlin']['parsed_data'] = parsed

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
            if isinstance(app_agent_results, str):
                app_agent_results = safe_load_json(app_agent_results)
            if isinstance(app_agent_results, dict) and app_agent_results:
                for k, v in app_agent_results.items():
                    if k not in agent_results:
                        # Agent not in per-table results — use applications.agent_results
                        agent_results[k] = v
                    elif k == 'merlin' and isinstance(v, dict):
                        # Special handling: if merlin_evaluations row exists but has
                        # no meaningful data (empty response saved earlier), prefer
                        # the richer data from applications.agent_results
                        existing = agent_results.get('merlin', {})
                        existing_has_content = (
                            existing.get('overall_score') is not None
                            or existing.get('recommendation')
                            or existing.get('executive_summary')
                            or existing.get('human_summary')
                        )
                        app_has_content = (
                            v.get('overall_score') is not None
                            or v.get('recommendation')
                            or v.get('executive_summary')
                            or v.get('applicant_summary')
                        )
                        if not existing_has_content and app_has_content:
                            logger.info(f"Merlin: preferring applications.agent_results (has content) over empty merlin_evaluations row")
                            agent_results['merlin'] = v
                        elif existing_has_content:
                            # Merge supplementary keys from agent_results that
                            # might not exist in the per-table row
                            for mk, mv in v.items():
                                if mk not in existing or not existing.get(mk):
                                    existing[mk] = mv
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

        # Pull Milo insights from already-persisted results — do NOT make
        # live AI calls during page load as that blocks the worker for 10-30s
        # and causes the page to hang/timeout under Front Door.
        milo_insights = {}
        milo_alignment = None
        alignment_score = None
        try:
            # Check persisted agent_results on the application row
            stored = application.get('agent_results') or {}
            if isinstance(stored, str):
                stored = safe_load_json(stored)
            if isinstance(stored, dict):
                milo_alignment = stored.get('milo_alignment') or \
                    (stored.get('data_scientist') or {}).get('computed_alignment')
                # Extract cached training insights from data_scientist result
                ds = stored.get('data_scientist') or {}
                if isinstance(ds, dict) and ds.get('status') == 'success':
                    milo_insights = ds

            # Simple numeric alignment from Merlin score vs stored average
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
            logger.debug(f"Milo insights load failed in student_detail: {e}")

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
        flash('An error occurred while loading student details', 'error')
        return redirect(url_for('applications.students'))



@applications_bp.route('/student/<int:application_id>/agent-results')
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500



@applications_bp.route('/student/<int:application_id>/summary-json')
def student_summary_json(application_id):
    """Render a compact student summary page directly from agent-results JSON."""
    try:
        application = db.get_application(application_id)
        if not application:
            flash('Student not found', 'error')
            return redirect(url_for('applications.students'))

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
        flash('An error occurred while loading the summary', 'error')
        return redirect(url_for('applications.students'))



@applications_bp.route('/student/<int:application_id>/download-evaluation')
def download_evaluation(application_id):
    """Download the evaluation document for a student from Azure Storage or local backup."""
    try:
        application = db.get_application(application_id)
        if not application:
            flash('Student not found', 'error')
            return redirect(url_for('applications.students'))
        
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
        return redirect(url_for('applications.student_detail', application_id=application_id))
        
    except Exception as e:
        logger.error(f"Error downloading evaluation: {str(e)}", exc_info=True)
        flash('An error occurred while downloading the document', 'error')
        return redirect(url_for('applications.student_detail', application_id=application_id))



@applications_bp.route('/api/student/<int:application_id>/edit', methods=['PATCH'])
def edit_student_record(application_id):
    """Update editable fields on a student record (name, school, email, was_selected)."""
    try:
        application = db.get_application(application_id)
        if not application:
            return jsonify({'status': 'error', 'error': 'Student not found'}), 404

        body = request.get_json(silent=True) or {}
        if not body:
            return jsonify({'status': 'error', 'error': 'No fields provided'}), 400

        # Whitelist of editable fields
        editable = {
            'first_name', 'last_name', 'high_school', 'email',
            'applicant_name', 'was_selected',
        }
        updates = {}
        for key, value in body.items():
            if key in editable:
                # Coerce was_selected to boolean
                if key == 'was_selected':
                    if isinstance(value, str):
                        value = value.lower() in ('true', '1', 'yes')
                    else:
                        value = bool(value)
                updates[key] = value

        if not updates:
            return jsonify({'status': 'error', 'error': 'No valid editable fields provided'}), 400

        # If first_name or last_name changed, also update applicant_name for consistency
        if 'first_name' in updates or 'last_name' in updates:
            fn = updates.get('first_name') or application.get('first_name') or ''
            ln = updates.get('last_name') or application.get('last_name') or ''
            updates['applicant_name'] = f"{fn} {ln}".strip()

        db.update_application(application_id, **updates)

        logger.info(f"Student {application_id} updated: {list(updates.keys())}")
        return jsonify({
            'status': 'success',
            'message': f'Student record updated',
            'updated_fields': list(updates.keys())
        })
    except Exception as e:
        logger.error(f"Error editing student {application_id}: {e}")
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@applications_bp.route('/api/student/<int:application_id>/delete', methods=['DELETE'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@applications_bp.route('/api/application/status/<int:application_id>', methods=['GET'])
def get_application_status(application_id):
    """Return agent progress status for a single application."""
    try:
        query = """
            SELECT 
                a.application_id,
                a.applicant_name,
                a.status,
                a.file_type,
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
            GROUP BY a.application_id, a.applicant_name, a.status, a.file_type
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

        has_merlin = bool(row.get('has_merlin'))
        has_any_downstream = any([
            row.get('has_tiana'), row.get('has_rapunzel'),
            row.get('has_mulan'), row.get('has_moana'), has_merlin
        ])
        is_video = (row.get('file_type') or '').lower() in ('mp4', 'video', 'mov', 'avi', 'webm')

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
                'aurora': 'complete' if row.get('has_aurora') else 'pending',
                'fairy_godmother': 'complete' if row.get('has_aurora') else 'pending',
            }
        else:
            agent_status = {
                'belle': 'complete' if has_any_downstream else 'pending',
                'mirabel': ('complete' if has_any_downstream else 'pending') if is_video else 'skipped',
                'smee': 'pending',
                'naveen': 'complete' if row.get('has_moana') else 'pending',
                'application_reader': 'complete' if row.get('has_tiana') else 'pending',
                'grade_reader': 'complete' if row.get('has_rapunzel') else 'pending',
                'school_context': 'complete' if row.get('has_moana') else 'pending',
                'recommendation_reader': 'complete' if row.get('has_mulan') else 'pending',
                'data_scientist': 'pending',
                'student_evaluator': 'pending',
                'aurora': 'complete' if row.get('has_aurora') else 'pending',
                'fairy_godmother': 'pending',
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
            has_merlin
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'error': 'An internal error occurred'}), 500


@applications_bp.route('/api/applications/reprocess-2026', methods=['POST'])
def reprocess_2026_applications():
    """Reprocess all 2026 applicants through the full agent pipeline.
    
    This re-runs all agents on every 2026 student (non-training, non-test).
    Processing happens in background threads — one student at a time to
    avoid overwhelming the AI models.
    
    POST body (optional): {"delay_seconds": 30}  — delay between students
    """
    try:
        training_col = db.get_training_example_column()
        test_col = db.get_test_data_column()
        
        # Get all 2026 application IDs
        where = f"{training_col} = FALSE"
        if db.has_applications_column(test_col):
            where += f" AND ({test_col} = FALSE OR {test_col} IS NULL)"
        
        apps = db.execute_query(
            f"SELECT application_id, applicant_name, status FROM applications WHERE {where} ORDER BY application_id"
        )
        
        if not apps:
            return jsonify({'status': 'success', 'message': 'No 2026 applications found', 'count': 0})
        
        body = request.get_json(silent=True) or {}
        delay_seconds = int(body.get('delay_seconds', 30))
        
        app_ids = [a['application_id'] for a in apps]
        app_names = [a.get('applicant_name', 'Unknown') for a in apps]
        
        def background_reprocess(ids, delay):
            """Process students sequentially with delays to manage API capacity."""
            for i, app_id in enumerate(ids):
                try:
                    logger.info(f"Reprocess 2026 [{i+1}/{len(ids)}]: starting application {app_id}")
                    application = db.get_application(app_id)
                    if not application:
                        continue
                    
                    orchestrator = get_orchestrator()
                    result = run_async(orchestrator.coordinate_evaluation(
                        application=application,
                        evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader',
                                         'school_context', 'data_scientist', 'student_evaluator', 'aurora']
                    ))
                    
                    db.update_application_status(app_id, 'Completed')
                    logger.info(f"Reprocess 2026 [{i+1}/{len(ids)}]: completed application {app_id}")
                    
                    if i < len(ids) - 1:
                        time.sleep(delay)
                        
                except Exception as e:
                    logger.error(f"Reprocess 2026: failed for {app_id}: {e}", exc_info=True)
                    db.update_application_status(app_id, 'Uploaded')
            
            logger.info(f"Reprocess 2026: COMPLETE — processed {len(ids)} applications")
        
        # Start in background thread
        threading.Thread(
            target=background_reprocess,
            args=(app_ids, delay_seconds),
            daemon=True
        ).start()
        
        return jsonify({
            'status': 'success',
            'message': f'Reprocessing {len(app_ids)} 2026 applications in background',
            'count': len(app_ids),
            'students': [{'id': a['application_id'], 'name': a.get('applicant_name', 'Unknown')} for a in apps],
            'estimated_minutes': len(app_ids) * (delay_seconds + 120) // 60  # ~2 min per student + delay
        })
    except Exception as e:
        logger.error(f"Reprocess 2026 error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': f'Reprocess failed: {str(e)}'}), 500



@applications_bp.route('/api/verify/applications', methods=['GET'])
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
            'error': 'An internal error occurred'
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

            result = run_async(orchestrator.coordinate_evaluation(
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
            result = run_async(
                orchestrator.coordinate_evaluation(
                    application=application,
                    evaluation_steps=['application_reader', 'grade_reader', 'recommendation_reader', 'school_context', 'data_scientist', 'student_evaluator', 'aurora']
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
            'error': 'An internal error occurred'
        }), 500


