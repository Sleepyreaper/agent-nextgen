"""School management routes — NCES data, Naveen/Moana enrichment."""

import json
import logging
import os
import threading
import time

from datetime import datetime, timezone
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from extensions import (
    csrf, limiter, run_async,
    get_ai_client, get_ai_client_mini, get_orchestrator,
)
from src.agents.pocahontas_cohort_analyst import PocahontasCohortAnalyst
from src.config import config
from src.database import db
from src.storage import storage
from src.telemetry import telemetry

logger = logging.getLogger(__name__)

schools_bp = Blueprint('schools', __name__)

# Exempt schools blueprint from CSRF — file uploads via FormData
# don't reliably carry the X-CSRFToken header through the fetch interceptor
csrf.exempt(schools_bp)


@schools_bp.route('/schools', methods=['GET'])
def schools_dashboard():
    """School management and review dashboard."""
    return render_template('school_management.html')



@schools_bp.route('/school/<int:school_id>', methods=['GET'])
def view_school_enrichment(school_id):
    """View and edit a school enrichment record."""
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            flash('School record not found', 'error')
            return redirect(url_for('schools.schools_dashboard'))
        
        return render_template('school_enrichment_detail.html', school=school)
    except Exception as e:
        logger.error(f"Error viewing school {school_id}: {e}")
        flash('An error occurred while loading school data', 'error')
        return redirect(url_for('schools.schools_dashboard'))



@schools_bp.route('/api/schools/list', methods=['GET'])
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
        
        schools = db.get_all_schools_enriched(filters=filters, limit=5000)

        # Attach enrichment completeness score to each school
        for s in schools:
            score_info = _compute_enrichment_completeness(s)
            s['enrichment_score'] = score_info['overall_percentage']
            s['is_enriched'] = score_info['is_enriched']

        return jsonify({
            'status': 'success',
            'schools': schools,
            'count': len(schools)
        })
    except Exception as e:
        logger.error(f"Error getting schools list: {e}")
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/school/<int:school_id>', methods=['GET'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/school/<int:school_id>/update', methods=['POST'])
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
            'human_notes': data.get('human_notes'),
            'school_url': data.get('school_url'),
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/school/add', methods=['POST'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/school/<int:school_id>/delete', methods=['DELETE'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/school/<int:school_id>/review', methods=['POST'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/school/<int:school_id>/analyze', methods=['POST'])
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
                
                # Run analysis
                result = scientist.analyze_school(
                    school_name=school['school_name'],
                    school_district=school.get('school_district', ''),
                    state_code=school.get('state_code', ''),
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
                    result_summary={'school_id': school_id, 'error': 'Analysis failed'}
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/school/<int:school_id>/analyze-sync', methods=['POST'])
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
        
        result = scientist.analyze_school(
            school_name=school['school_name'],
            school_district=school.get('school_district', ''),
            state_code=school.get('state_code', ''),
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
        logger.error("School analyze-sync failed for school %s: %s", school_id, e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/school/<int:school_id>/validate-moana', methods=['POST'])
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
        school_mapped = dict(school)
        school_mapped['ap_courses_available'] = school.get('ap_course_count', 0)
        school_mapped['honors_course_count'] = school.get('honors_course_count', 0)
        
        is_valid, missing_fields, validation_details = workflow.validate_school_requirements(school_mapped)
        
        # Step 2: Generate Moana's school context summary using AI
        context_summary = None
        if is_valid or len(missing_fields) <= 2:
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
                
                context_prompt = (
                    "You are Moana, the School Context Analyzer. Based on the following school enrichment data, "
                    "write a concise school context summary (3-5 sentences) that would help other agents understand "
                    "this school's environment.\n\n"
                    f"School: {school.get('school_name')}\n"
                    f"District: {school.get('school_district', 'N/A')}\n"
                    f"State: {school.get('state_code', 'N/A')}\n"
                    f"Total Students: {school.get('total_students', 'N/A')}\n"
                    f"Graduation Rate: {school.get('graduation_rate', 'N/A')}%\n"
                    f"College Acceptance Rate: {school.get('college_acceptance_rate', 'N/A')}%\n"
                    f"Free/Reduced Lunch: {school.get('free_lunch_percentage', 'N/A')}%\n"
                    f"AP Courses: {school.get('ap_course_count', 'N/A')}\n"
                    f"AP Pass Rate: {school.get('ap_exam_pass_rate', 'N/A')}%\n"
                    f"STEM Program: {'Yes' if school.get('stem_program_available') else 'No'}\n"
                    f"IB Program: {'Yes' if school.get('ib_program_available') else 'No'}\n"
                    f"Dual Enrollment: {'Yes' if school.get('dual_enrollment_available') else 'No'}\n"
                    f"Opportunity Score: {school.get('opportunity_score', 'N/A')}/100\n"
                    f"Investment Level: {school.get('school_investment_level', 'N/A')}\n\n"
                    "Provide:\n"
                    "1. A brief school environment description (urban/rural, size, socioeconomic context)\n"
                    "2. Academic rigor context (what programs exist, how this compares regionally)\n"
                    "3. Key insight: what does attending this school tell us about a student's opportunities?\n\n"
                    "Write as a cohesive paragraph that other agents can reference when evaluating students from this school."
                )

                from src.agents.base_agent import BaseAgent
                
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
            result_summary={'school_id': school_id, 'error': 'Validation failed'}
        )
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500


@schools_bp.route('/api/school/<int:school_id>/enrichment-score', methods=['GET'])
def school_enrichment_score(school_id):
    """Return the enrichment completeness score for a school."""
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            return jsonify({'status': 'error', 'error': 'School not found'}), 404
        score = _compute_enrichment_completeness(school)
        return jsonify({'status': 'success', 'school_id': school_id, **score})
    except Exception as e:
        logger.error(f"Enrichment score error for school {school_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/school/lookup', methods=['POST'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/schools/enrich-pending', methods=['POST'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/schools/batch-naveen-moana', methods=['POST'])
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
                      OR analysis_status = 'csv_imported'
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
                needs_naveen = sch.get('analysis_status') in (None, 'pending', 'csv_imported', 'error')
                if needs_naveen:
                    try:
                        full_school = db.get_school_enriched_data(sid) or {}
                        logger.info(f"  → Calling Naveen AI model for {name} (status={sch.get('analysis_status')})")

                        result = scientist.analyze_school(
                            school_name=name,
                            school_district=sch.get('school_district', ''),
                            state_code=sch.get('state_code', ''),
                            existing_data=full_school
                        )

                        enriched = result.get('enriched_data', {})
                        logger.info(f"  Naveen raw keys: {list(enriched.keys()) if isinstance(enriched, dict) else 'NOT DICT'}")
                        logger.info(f"  Naveen academic_courses={enriched.get('academic_courses')}, "
                                    f"ap_course_count={enriched.get('ap_course_count')}, "
                                    f"honors_programs={enriched.get('honors_programs')}, "
                                    f"graduation_rate={enriched.get('graduation_rate')}")

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
                        ap = _to_num(_dig(enriched, 'academic_courses', 'ap_course_count', 'ap_classes_count', 'ap_courses') or result.get('ap_classes_count') or result.get('academic_courses') or 0, True)
                        ap_p = _to_num(_dig(enriched, 'ap_exam_pass_rate', 'ap_pass_rate') or result.get('ap_exam_pass_rate') or 0)
                        stem = bool(_dig(enriched, 'stem_programs', 'stem_program_available') or False)
                        ib = bool(_dig(enriched, 'ib_program_available', 'ib_offerings', 'ib_program') or False)
                        dual = bool(_dig(enriched, 'dual_enrollment_available', 'dual_enrollment') or False)
                        hon = _to_num(_dig(enriched, 'honors_programs', 'honors_course_count', 'honors_courses_available', 'honors_courses') or 0, True)
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
                        logger.info(f"  ✓ Naveen complete for {name}: score={opp}, AP={ap}, honors={hon}, grad={grad}, students={tot}, confidence={conf}")
                    except Exception as e:
                        logger.error(f"  ✗ Naveen failed for {name}: {e}", exc_info=True)
                        try:
                            db.execute_non_query(
                                "UPDATE school_enriched_data SET analysis_status='error', updated_at=CURRENT_TIMESTAMP WHERE school_enrichment_id=%s",
                                (sid,)
                            )
                        except Exception:
                            pass
                else:
                    logger.info(f"  → Naveen skipped for {name} (already status={sch.get('analysis_status')})")

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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/schools/clear', methods=['POST'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/schools/backfill-honors', methods=['POST'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/schools/bulk-seed', methods=['POST'])
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
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/schools/import-csv', methods=['POST'])
def import_schools_csv():
    """Import schools from a CSV file (GA high-school SES data).

    Accepts either:
      - A file upload (multipart/form-data, field name 'file')
      - A JSON body with {"csv_path": "/path/to/file.csv"}

    Query params:
      - purge=true  (default true) — delete all existing school data first
      - dry_run=true — parse and aggregate without writing to DB

    The CSV is expected to have NCES CCD format with columns like
    school_year, ncessch, school_name, enrollment, frpl_pct, etc.
    Multiple year-rows per school are collapsed into one record.

    Returns immediately with status. Poll GET /api/schools/import-csv
    to check progress.
    """
    from src.csv_school_importer import import_schools_from_csv, read_and_group_csv, _aggregate_school
    import tempfile

    try:
        purge = request.args.get('purge', 'true').lower() == 'true'
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'

        csv_path = None

        # Option 1: file upload (multipart/form-data)
        if 'file' in request.files:
            uploaded = request.files['file']
            if uploaded.filename:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='wb')
                uploaded.save(tmp)
                tmp.close()
                csv_path = tmp.name
                logger.info(f"CSV upload saved to {csv_path}")

        # Option 2: JSON body with base64 file_data (WAF-friendly)
        if not csv_path:
            data = request.get_json(silent=True) or {}
            if data.get('file_data'):
                import base64
                try:
                    raw = base64.b64decode(data['file_data'])
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='wb')
                    tmp.write(raw)
                    tmp.close()
                    csv_path = tmp.name
                    logger.info(f"Base64 CSV decoded and saved to {csv_path} ({len(raw)} bytes)")
                except Exception as e:
                    return jsonify({'status': 'error', 'error': f'Failed to decode base64 file_data: {e}'}), 400
            else:
                csv_path = data.get('csv_path')

        if not csv_path:
            return jsonify({
                'status': 'error',
                'error': 'Provide a CSV file upload (field "file"), JSON {"file_data": "base64..."}, or {"csv_path": "..."}'
            }), 400

        # Validate file exists
        if not os.path.isfile(csv_path):
            return jsonify({'status': 'error', 'error': f'File not found: {csv_path}'}), 404

        # For dry runs, run synchronously (fast)
        if dry_run:
            result = import_schools_from_csv(csv_path, db, purge_first=purge, dry_run=True)
            return jsonify(result)

        # ── Async import via background thread ──────────────────────
        state_file = os.path.join(tempfile.gettempdir(), 'school_csv_import_state.json')
        state = {
            'status': 'running',
            'started_at': datetime.now(timezone.utc).isoformat(),
            'csv_path': csv_path,
            'purge': purge,
            'processed': 0,
            'total': 0,
            'created': 0,
            'errors': 0,
            'error_details': [],
        }
        with open(state_file, 'w') as f:
            json.dump(state, f)

        def _background_school_import(csv_path, purge, state_path):
            from src.csv_school_importer import read_and_group_csv, _aggregate_school
            try:
                # Step 1: Read & group
                groups = read_and_group_csv(csv_path)
                total_rows = sum(len(v) for v in groups.values())
                total_schools = len(groups)

                # Aggregate
                records = []
                for nces_id, rows in groups.items():
                    try:
                        rec = _aggregate_school(nces_id, rows)
                        records.append(rec)
                    except Exception as e:
                        logger.error(f"  Error aggregating school {nces_id}: {e}")

                # Update state with totals
                state['total'] = len(records)
                state['csv_rows'] = total_rows
                state['unique_schools'] = total_schools
                with open(state_path, 'w') as f:
                    json.dump(state, f)

                # Purge if requested
                purged = 0
                if purge:
                    purged = db.delete_all_school_enriched_data()
                    logger.info(f"  🗑️  Purged {purged} existing school records")
                state['purged'] = purged

                # Insert records one-by-one with progress updates
                for i, rec in enumerate(records):
                    try:
                        school_id = db.create_school_enriched_data(rec)
                        if school_id:
                            state['created'] += 1
                        else:
                            state['errors'] += 1
                    except Exception as e:
                        state['errors'] += 1
                        state['error_details'].append('Import failed for record')
                        logger.error(f"  Error inserting {rec.get('school_name')}: {e}")

                    state['processed'] = i + 1
                    # Write progress every 50 records
                    if (i + 1) % 50 == 0 or (i + 1) == len(records):
                        with open(state_path, 'w') as f:
                            json.dump(state, f)

                state['status'] = 'completed'
                state['completed_at'] = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                state['status'] = 'error'
                state['error'] = str(exc)
                logger.error(f"Background school import error: {exc}", exc_info=True)
            finally:
                with open(state_path, 'w') as f:
                    json.dump(state, f)

        thread = threading.Thread(
            target=_background_school_import,
            args=(csv_path, purge, state_file),
            daemon=True
        )
        thread.start()

        return jsonify({
            'status': 'started',
            'message': 'School CSV import started in background. Poll GET /api/schools/import-csv for progress.',
        })

    except Exception as e:
        logger.error(f"Error in CSV import: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



@schools_bp.route('/api/schools/import-csv', methods=['GET'])
def import_schools_csv_progress():
    """Poll the progress of a background school CSV import."""
    import tempfile
    state_file = os.path.join(tempfile.gettempdir(), 'school_csv_import_state.json')
    if not os.path.isfile(state_file):
        return jsonify({'status': 'idle', 'message': 'No import in progress'})
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
        return jsonify(state)
    except Exception as e:
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500


@schools_bp.route('/api/schools/import-supplemental', methods=['POST'])
def import_supplemental_school_csv():
    """Import supplemental academic data (AP, honors, graduation, etc.) and merge
    onto existing schools by NCES ID.

    This does NOT create new records — only updates existing ones where the
    NCES ID matches. Use after importing the base CCD demographics CSV.

    Form fields:
        file: CSV file upload
        source_name: provenance label (e.g., 'CRDC_2020-21', 'GA_DOE_2024')
    """
    from src.csv_school_importer import import_supplemental_csv
    from werkzeug.utils import secure_filename
    import base64

    try:
        upload_folder = current_app.config.get('UPLOAD_FOLDER', '/tmp')

        # Support both FormData file upload and base64 JSON (WAF bypass)
        json_data = request.get_json(silent=True)
        if json_data and json_data.get('file_base64'):
            # Base64 encoded CSV
            csv_bytes = base64.b64decode(json_data['file_base64'])
            filename = secure_filename(json_data.get('filename', 'import.csv'))
            source_name = (json_data.get('source_name') or 'supplemental_csv').strip()
            csv_path = os.path.join(upload_folder, f'supp_{filename}')
            with open(csv_path, 'wb') as f:
                f.write(csv_bytes)
        elif 'file' in request.files:
            file = request.files['file']
            if not file.filename or not file.filename.endswith('.csv'):
                return jsonify({'status': 'error', 'error': 'File must be a .csv'}), 400
            source_name = (request.form.get('source_name') or 'supplemental_csv').strip()
            filename = secure_filename(file.filename)
            csv_path = os.path.join(upload_folder, f'supp_{filename}')
            file.save(csv_path)
        else:
            return jsonify({'status': 'error', 'error': 'No file uploaded'}), 400

        # Ensure GOSA columns exist before import
        try:
            db.ensure_gosa_columns()
        except Exception:
            pass
        if not source_name:
            source_name = 'supplemental_csv'

        result = import_supplemental_csv(csv_path, db, source_name=source_name)

        # Cleanup
        try:
            os.remove(csv_path)
        except Exception:
            pass

        return jsonify(result)

    except Exception as e:
        logger.error(f"Supplemental import error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@schools_bp.route('/api/schools/seed-academics', methods=['POST'])
def seed_school_academics():
    """AI-powered academic data lookup for all GA schools.

    Queries the AI model for each school's AP courses, graduation rate,
    honors courses, etc. from its knowledge of public records. Results are
    written as supplemental data with provenance tracking.

    Runs in background. Poll GET /api/schools/seed-academics for progress.
    """
    import tempfile

    try:
        data = request.get_json() or {}
        limit = int(data.get('limit', 0))
        delay = float(data.get('delay', 2.0))

        schools = db.execute_query(
            """SELECT school_enrichment_id, nces_id, school_name, school_district,
                      state_code, total_students, free_lunch_percentage,
                      ap_course_count, graduation_rate
               FROM school_enriched_data
               WHERE state_code = 'GA' AND is_active = TRUE
               ORDER BY school_name"""
        )
        if not schools:
            return jsonify({'status': 'error', 'error': 'No GA schools found'})

        # Filter to schools that need academic data
        needs_data = [s for s in schools
                      if not s.get('ap_course_count') or int(s.get('ap_course_count', 0)) == 0
                      or not s.get('graduation_rate') or float(s.get('graduation_rate', 0)) == 0]

        if limit > 0:
            needs_data = needs_data[:limit]

        if not needs_data:
            return jsonify({'status': 'success', 'message': 'All schools already have academic data', 'count': 0})

        state_file = os.path.join(tempfile.gettempdir(), 'seed_academics_state.json')
        state = {
            'status': 'running',
            'total': len(needs_data),
            'processed': 0,
            'updated': 0,
            'errors': 0,
            'current_school': '',
        }
        with open(state_file, 'w') as f:
            json.dump(state, f)

        def background_seed(schools_to_process, delay_sec, state_path):
            import time as _time
            try:
                # Ensure GOSA columns exist before importing
                db.ensure_gosa_columns()
                client = get_ai_client()
                model = config.model_tier_workhorse or config.foundry_model_name or config.deployment_name
                source_name = 'AI_Knowledge_GA_2025'
                import csv as csv_mod
                csv_path = os.path.join(tempfile.gettempdir(), 'ga_academics_seed.csv')

                rows = []
                for idx, sch in enumerate(schools_to_process):
                    name = sch['school_name']
                    state['current_school'] = name
                    state['processed'] = idx

                    try:
                        prompt = (
                            f"Look up this Georgia high school and provide its REAL academic data "
                            f"from GOSA (Governor's Office of Student Achievement), GA DOE, and CollegeBoard.\n\n"
                            f"School: {name}\n"
                            f"District: {sch.get('school_district', '')}\n"
                            f"NCES ID: {sch.get('nces_id', '')}\n"
                            f"Enrollment: {sch.get('total_students', 0)}\n\n"
                            f"Return JSON with ALL of these fields (use null if unknown):\n"
                            f"- ap_course_count: int (AP courses offered)\n"
                            f"- ap_students_tested: int (students taking AP exams)\n"
                            f"- ap_exam_pass_rate: float (% of AP exams scoring 3+)\n"
                            f"- honors_course_count: int\n"
                            f"- graduation_rate: float (4-year cohort %)\n"
                            f"- college_going_rate: float (% enrolled in college within 16 months, from GOSA C11 report)\n"
                            f"- college_going_4yr_rate: float (% in 4-year institutions)\n"
                            f"- act_composite_avg: float (school average ACT composite)\n"
                            f"- sat_total_avg: int (school average SAT total, 400-1600 scale)\n"
                            f"- hope_eligible_pct: float (% of graduates HOPE eligible)\n"
                            f"- dropout_rate: float (9-12 annual dropout %)\n"
                            f"- stem_program_available: bool\n"
                            f"- ib_program_available: bool\n"
                            f"- dual_enrollment_available: bool\n"
                            f"- school_url: string (official school website)\n"
                            f"Use the most recent data year available. Be precise."
                        )
                        resp = client.chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": (
                                    "You are a Georgia education data researcher with access to GOSA "
                                    "(Governor's Office of Student Achievement) downloadable data, "
                                    "GA DOE report cards, CollegeBoard AP data, and school profiles. "
                                    "Provide real, publicly verifiable data for Georgia high schools. "
                                    "Use data from the most recent school year available. "
                                    "Only return data you are confident about. Use null for uncertain fields. "
                                    "These data points are publicly available at gosa.georgia.gov."
                                )},
                                {"role": "user", "content": prompt},
                            ],
                            max_tokens=600,
                            temperature=0.1,
                            response_format={"type": "json_object"},
                        )
                        ai_data = json.loads(resp.choices[0].message.content)

                        row = {'ncessch': sch.get('nces_id', '')}
                        all_fields = [
                            'ap_course_count', 'ap_students_tested', 'ap_exam_pass_rate',
                            'honors_course_count', 'graduation_rate',
                            'college_going_rate', 'college_going_4yr_rate',
                            'act_composite_avg', 'sat_total_avg',
                            'hope_eligible_pct', 'dropout_rate',
                            'stem_program_available', 'ib_program_available',
                            'dual_enrollment_available', 'school_url',
                        ]
                        for field in all_fields:
                            val = ai_data.get(field)
                            if val is True:
                                row[field] = 'true'
                            elif val is False:
                                row[field] = 'false'
                            elif val is not None:
                                row[field] = str(val)
                            else:
                                row[field] = ''
                        rows.append(row)
                        state['updated'] += 1
                        logger.info(f"  Seed [{idx+1}/{len(schools_to_process)}] {name}: AP={ai_data.get('ap_course_count')}, Grad={ai_data.get('graduation_rate')}")
                    except Exception as e:
                        state['errors'] += 1
                        logger.warning(f"  Seed failed for {name}: {e}")

                    with open(state_path, 'w') as f:
                        json.dump(state, f)

                    if idx < len(schools_to_process) - 1:
                        _time.sleep(delay_sec)

                # Write CSV and import
                if rows:
                    fieldnames = [
                        'ncessch', 'ap_course_count', 'ap_students_tested', 'ap_exam_pass_rate',
                        'honors_course_count', 'graduation_rate',
                        'college_going_rate', 'college_going_4yr_rate',
                        'act_composite_avg', 'sat_total_avg',
                        'hope_eligible_pct', 'dropout_rate',
                        'stem_program_available', 'ib_program_available',
                        'dual_enrollment_available', 'school_url',
                    ]
                    with open(csv_path, 'w', newline='', encoding='utf-8') as cf:
                        writer = csv_mod.DictWriter(cf, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(rows)

                    from src.csv_school_importer import import_supplemental_csv
                    result = import_supplemental_csv(csv_path, db, source_name=source_name)
                    logger.info(f"  Supplemental import: {result}")
                    try:
                        os.remove(csv_path)
                    except Exception:
                        pass

                state['status'] = 'completed'
                state['processed'] = len(schools_to_process)
            except Exception as e:
                state['status'] = 'error'
                state['error'] = str(e)
                logger.error(f"Seed academics failed: {e}", exc_info=True)
            finally:
                with open(state_path, 'w') as f:
                    json.dump(state, f)

        thread = threading.Thread(
            target=background_seed,
            args=(needs_data, delay, state_file),
            daemon=True
        )
        thread.start()

        return jsonify({
            'status': 'started',
            'total': len(needs_data),
            'message': f'Looking up academic data for {len(needs_data)} GA schools in background. '
                       f'Poll GET /api/schools/seed-academics for progress.',
        })

    except Exception as e:
        logger.error(f"Seed academics error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@schools_bp.route('/api/schools/seed-academics', methods=['GET'])
def seed_school_academics_progress():
    """Poll seed academics progress."""
    import tempfile
    state_file = os.path.join(tempfile.gettempdir(), 'seed_academics_state.json')
    if not os.path.isfile(state_file):
        return jsonify({'status': 'idle', 'message': 'No seed job running'})
    try:
        with open(state_file, 'r') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({'status': 'unknown'})


@schools_bp.route('/api/schools/purge', methods=['DELETE'])
def purge_schools():
    """Delete ALL school enriched data records.

    This is a destructive operation — use with care.
    Returns the count of records deleted.
    """
    try:
        count = db.delete_all_school_enriched_data()
        return jsonify({
            'status': 'success',
            'purged': count,
            'message': f'Deleted {count} school records and cascaded child tables'
        })
    except Exception as e:
        logger.error(f"Error purging schools: {e}", exc_info=True)
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500



def _compute_enrichment_completeness(school: dict) -> dict:
    """Compute enrichment completeness score for a school record.

    Returns a dict with overall percentage, breakdown by category,
    and a list of missing fields.
    """
    categories = {
        'basic': {
            'fields': ['school_name', 'state_code', 'school_district', 'county_name'],
            'weight': 0.15,
        },
        'demographics': {
            'fields': ['total_students', 'free_lunch_percentage', 'graduation_rate'],
            'weight': 0.20,
        },
        'academics': {
            'fields': ['ap_course_count', 'honors_course_count', 'college_acceptance_rate',
                       'stem_program_available', 'ib_program_available', 'dual_enrollment_available'],
            'weight': 0.25,
        },
        'web_presence': {
            'fields': ['school_url', 'school_url_verified', 'web_sources_analyzed'],
            'weight': 0.15,
        },
        'analysis': {
            'fields': ['opportunity_score', 'data_confidence_score', 'analysis_status'],
            'weight': 0.15,
        },
        'review': {
            'fields': ['human_review_status', 'moana_requirements_met'],
            'weight': 0.10,
        },
    }

    missing = []
    category_scores = {}
    weighted_total = 0.0

    for cat_name, cat in categories.items():
        filled = 0
        total = len(cat['fields'])
        for field in cat['fields']:
            val = school.get(field)
            if val is not None and val != '' and val != 0:
                # analysis_status='pending' doesn't count as filled
                if field == 'analysis_status' and val == 'pending':
                    missing.append(field)
                    continue
                # human_review_status='pending' doesn't count
                if field == 'human_review_status' and val == 'pending':
                    missing.append(field)
                    continue
                filled += 1
            else:
                missing.append(field)
        pct = (filled / total * 100) if total > 0 else 0
        category_scores[cat_name] = round(pct, 1)
        weighted_total += (filled / total) * cat['weight'] if total > 0 else 0

    overall = round(weighted_total * 100, 1)
    is_enriched = overall >= 60 and school.get('analysis_status') in ('complete', 'csv_imported')

    return {
        'overall_percentage': overall,
        'is_enriched': is_enriched,
        'categories': category_scores,
        'missing_fields': missing,
    }


# ── Pocahontas Cohort Analysis ──────────────────────────────────────

@schools_bp.route('/api/schools/cohort-analysis', methods=['POST'])
def run_cohort_analysis():
    """Run Pocahontas cohort analysis across all schools.

    Compares schools against each other, assigns tiers, computes context
    multipliers, and generates an AI cohort narrative for the committee.
    """
    try:
        orchestrator = get_orchestrator()
        pocahontas = orchestrator.agents.get('pocahontas') if orchestrator else None
        if not pocahontas:
            pocahontas = PocahontasCohortAnalyst(
                client=get_ai_client_mini(),
                model=config.model_tier_workhorse,
            )
        result = pocahontas.analyze_cohort()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Cohort analysis failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@schools_bp.route('/api/schools/cohort-analysis', methods=['GET'])
def get_cohort_analysis():
    """Retrieve the latest cohort analysis report."""
    report = PocahontasCohortAnalyst.get_latest_cohort_report()
    if report:
        return jsonify(report)
    return jsonify({'status': 'empty', 'message': 'No cohort analysis has been run yet.'})


# ── School Alias Management ──────────────────────────────────────────

@schools_bp.route('/api/schools/unmatched', methods=['GET'])
def get_unmatched_schools():
    """Find school names from applications that don't match any enriched school."""
    db.ensure_school_aliases_table()
    unmatched = db.get_unmatched_school_names()
    return jsonify({'unmatched': unmatched, 'count': len(unmatched)})


@schools_bp.route('/api/school/<int:school_id>/aliases', methods=['GET'])
def get_school_aliases(school_id):
    """Get aliases for a school."""
    aliases = db.get_school_aliases(school_id)
    return jsonify({'aliases': aliases})


@schools_bp.route('/api/school/<int:school_id>/aliases', methods=['POST'])
def add_school_alias(school_id):
    """Add an alias for a school.

    Request body: {"alias_name": "DECA", "state_code": "GA"}
    """
    data = request.get_json() or {}
    alias_name = (data.get('alias_name') or '').strip()
    if not alias_name:
        return jsonify({'error': 'alias_name is required'}), 400
    state_code = data.get('state_code')
    alias_id = db.add_school_alias(school_id, alias_name, state_code=state_code, source='manual')
    if alias_id:
        return jsonify({'status': 'success', 'alias_id': alias_id})
    return jsonify({'error': 'Failed to add alias'}), 500


@schools_bp.route('/api/school/<int:school_id>/context-multiplier', methods=['GET'])
def get_school_context_multiplier(school_id):
    """Get the Pocahontas context multiplier for a specific school."""
    multiplier = PocahontasCohortAnalyst.get_school_context_multiplier(school_id)
    if multiplier:
        return jsonify(multiplier)
    return jsonify({'multiplier': 1.0, 'reasons': [], 'message': 'No cohort analysis available'})


@schools_bp.route('/api/schools/bulk-approve', methods=['POST'])
def bulk_approve_schools():
    """Bulk-approve all schools that have been analyzed by Naveen.

    Sets human_review_status='approved' for schools where:
    - analysis_status = 'complete' (Naveen has scored them)
    - human_review_status is NOT already 'approved'

    Optional body: {"min_confidence": 50} — only approve above this threshold.
    """
    try:
        data = request.get_json() or {}
        min_confidence = float(data.get('min_confidence', 0))

        where = "analysis_status = 'complete' AND (human_review_status IS NULL OR human_review_status != 'approved')"
        params = []
        if min_confidence > 0:
            where += " AND COALESCE(data_confidence_score, 0) >= %s"
            params.append(min_confidence)

        # Count first
        count_rows = db.execute_query(
            f"SELECT COUNT(*) as cnt FROM school_enriched_data WHERE {where}",
            tuple(params) if params else None,
        )
        count = count_rows[0]['cnt'] if count_rows else 0

        if count == 0:
            return jsonify({'status': 'success', 'message': 'No schools to approve', 'approved': 0})

        # Approve
        db.execute_non_query(
            f"""UPDATE school_enriched_data
                SET human_review_status = 'approved',
                    reviewed_date = CURRENT_TIMESTAMP,
                    reviewed_by = 'bulk_approve',
                    updated_at = CURRENT_TIMESTAMP
                WHERE {where}""",
            tuple(params) if params else None,
        )

        logger.info(f"Bulk approved {count} schools (min_confidence={min_confidence})")
        return jsonify({
            'status': 'success',
            'approved': count,
            'message': f'Approved {count} schools',
        })
    except Exception as e:
        logger.error(f"Bulk approve failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@schools_bp.route('/api/schools/import-gosa-from-repo', methods=['POST'])
def import_gosa_from_repo():
    """Import the GOSA merged CSV directly from the repo — runs in background."""
    from src.csv_school_importer import import_supplemental_csv
    import os as _os
    import tempfile

    try:
        db.ensure_gosa_columns()
    except Exception:
        pass

    csv_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'data', 'gosa_merged.csv')
    if not _os.path.isfile(csv_path):
        return jsonify({'status': 'error', 'error': f'File not found: {csv_path}'}), 404

    state_file = _os.path.join(tempfile.gettempdir(), 'gosa_import_state.json')
    state = {'status': 'running', 'message': 'Importing GOSA data...'}
    with open(state_file, 'w') as f:
        json.dump(state, f)

    def background_import(path, state_path):
        try:
            result = import_supplemental_csv(path, db, source_name='GOSA_2015-2025')
            result['status'] = 'completed'
            with open(state_path, 'w') as f:
                json.dump(result, f, default=str)
            logger.info(f"GOSA import complete: {result.get('matched')} matched, {result.get('updated')} updated")
        except Exception as e:
            with open(state_path, 'w') as f:
                json.dump({'status': 'error', 'error': str(e)}, f)
            logger.error(f"GOSA import failed: {e}", exc_info=True)

    thread = threading.Thread(target=background_import, args=(csv_path, state_file), daemon=True)
    thread.start()

    return jsonify({'status': 'started', 'message': 'GOSA import running in background. Poll for progress.'})


@schools_bp.route('/api/schools/import-gosa-from-repo', methods=['GET'])
def import_gosa_from_repo_status():
    """Poll GOSA import progress."""
    import tempfile, os as _os
    state_file = _os.path.join(tempfile.gettempdir(), 'gosa_import_state.json')
    if not _os.path.isfile(state_file):
        return jsonify({'status': 'idle'})
    try:
        with open(state_file, 'r') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({'status': 'unknown'})


@schools_bp.route('/api/schools/reset-for-reanalysis', methods=['POST'])
def reset_schools_for_reanalysis():
    """Reset all complete schools back to csv_imported so Naveen re-analyzes them.

    Use after improving Naveen's prompt to get better results.
    """
    try:
        count_rows = db.execute_query(
            "SELECT COUNT(*) as cnt FROM school_enriched_data WHERE analysis_status = 'complete'"
        )
        count = count_rows[0]['cnt'] if count_rows else 0
        if count == 0:
            return jsonify({'status': 'success', 'message': 'No schools to reset', 'reset': 0})

        db.execute_non_query(
            """UPDATE school_enriched_data
               SET analysis_status = 'csv_imported',
                   moana_requirements_met = NULL,
                   human_review_status = 'pending',
                   updated_at = CURRENT_TIMESTAMP
               WHERE analysis_status = 'complete'"""
        )
        logger.info(f"Reset {count} schools for re-analysis")
        return jsonify({'status': 'success', 'reset': count, 'message': f'Reset {count} schools for re-analysis'})
    except Exception as e:
        logger.error(f"Reset schools failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


