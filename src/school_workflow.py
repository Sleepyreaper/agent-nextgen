"""
School Data Workflow Manager - Handles school data lookup, enrichment, caching, and validation.

Phase 2: Basic enrichment workflow
Ensures schools are analyzed once and reused:
1. Check if school exists in database
2. If not, call Naveen (school_data_scientist) for deep analysis
3. Store results persistently
4. Pass to Moana (moana_school_context) for contextual analysis with grades

Phase 3: Bidirectional NAVEEN ↔ MOANA validation loop
- Validate school enrichment against MOANA requirements
- Remediate missing fields by calling NAVEEN again with specific context
- Track validation attempts and remediation history
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from src.agents.agent_monitor import get_agent_monitor, AgentStatus
from src.config import config

logger = logging.getLogger(__name__)


class SchoolDataWorkflow:
    """Manages school data lifecycle in agent pipeline."""
    
    def __init__(self, db_connection):
        """
        Initialize workflow manager.
        
        Args:
            db_connection: Database connection for school lookups/storage
        """
        self.db = db_connection
    
    def get_or_enrich_school_data(
        self,
        school_name: str,
        school_district: Optional[str] = None,
        state_code: Optional[str] = None,
        aurora_agent = None
    ) -> Dict[str, Any]:
        """
        Get school data from cache or trigger enrichment.
        
        Workflow:
        1. Look up school_name + state in school_enriched_data table
        2. If found and recent (< 30 days): return cached data
        3. If not found or stale: call Aurora to analyze
        4. Store results in database
        5. Return enriched school data
        
        Args:
            school_name: High school name
            school_district: School district (optional)
            state_code: State code like 'GA', 'CA' (optional)
            aurora_agent: NaveenSchoolDataScientist instance for enrichment analysis (note: parameter name kept for backwards compatibility)
            
        Returns:
            Dictionary with enriched school data including:
            - school_name, state_code, school_district
            - enrollment_size, diversity_index, socioeconomic_level
            - academic_programs (AP/IB/Honors count)
            - graduation_rate, college_placement_rate
            - opportunity_score (0-100)
            - analysis_date, data_sources
        """
        if not school_name:
            logger.warning("School name required for workflow")
            return {'school_name': school_name, 'error': 'School name missing'}
        
        # Step 1: Check database for existing enriched data
        cached_school = self._lookup_school_in_database(
            school_name=school_name,
            state_code=state_code
        )
        
        if cached_school:
            logger.info(
                f"✓ Found cached school data",
                extra={'school': school_name, 'state': state_code, 'cached_date': cached_school.get('analysis_date')}
            )
            return cached_school
        
        # Step 2: School not in database - trigger Aurora enrichment
        if not aurora_agent:
            logger.warning(f"Aurora agent required to enrich new school: {school_name}")
            return {
                'school_name': school_name,
                'state_code': state_code,
                'error': 'Aurora agent not available for enrichment'
            }
        
        logger.info(
            f"→ Triggering Naveen (school data scientist) for new school enrichment",
            extra={'school': school_name, 'state': state_code}
        )
        
        # Call Naveen to do deep school analysis with monitoring
        monitor = get_agent_monitor()
        execution = monitor.start_execution(
            agent_name="Naveen (School Data Scientist)",
            model=config.deployment_name_mini
        )
        
        try:
            enriched_result = aurora_agent.analyze_school(
                school_name=school_name,
                school_district=school_district,
                state_code=state_code
            )
            monitor.end_execution("Naveen (School Data Scientist)", status=AgentStatus.COMPLETED)
        except Exception as e:
            logger.error(f"Naveen analysis failed: {e}", exc_info=True)
            monitor.end_execution(
                "Naveen (School Data Scientist)",
                status=AgentStatus.FAILED,
                error_message=str(e)
            )
            raise
        
        # Step 3: Store results in database
        if enriched_result.get('analysis_status') == 'complete':
            school_id = self._store_school_enrichment(
                school_data=enriched_result,
                school_name=school_name,
                school_district=school_district,
                state_code=state_code
            )
            
            enriched_result['school_enrichment_id'] = school_id
            logger.info(
                f"✓ Stored Naveen enrichment in database",
                extra={'school': school_name, 'id': school_id, 'opportunity_score': enriched_result.get('opportunity_score')}
            )
        else:
            logger.warning(
                f"Naveen enrichment failed for {school_name}",
                extra={'error': enriched_result.get('error')}
            )
        
        return enriched_result

    def ensure_school_exists(
        self,
        school_name: str,
        state_code: str = 'GA',
        school_district: Optional[str] = None,
        county_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Auto-lookup/create: Check if a school exists in the database.
        If not, create a skeleton record with analysis_status='pending'.
        
        This is the entry point for the user requirement:
        "Does this high school name exist? If not, create a new record."
        
        Args:
            school_name: High school name
            state_code: State code (default 'GA')
            school_district: School district (optional)
            county_name: County name (optional)
            
        Returns:
            The existing or newly created school record dict
        """
        if not school_name:
            return {'error': 'School name is required'}
        
        # Step 1: Look up by name + state
        existing = self._lookup_school_in_database(school_name, state_code)
        
        if existing:
            logger.info(f"✓ School exists: {school_name}", extra={'id': existing.get('school_enrichment_id')})
            return existing
        
        # Step 2: Not found — create skeleton record
        logger.info(f"→ School not found, creating skeleton: {school_name} ({state_code})")
        
        skeleton = {
            'school_name': school_name,
            'school_district': school_district or '',
            'state_code': state_code,
            'county_name': county_name or '',
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
            'created_by': 'auto_lookup',
            'school_investment_level': 'unknown',
            'is_active': True,
        }
        
        school_id = self.db.create_school_enriched_data(skeleton)
        
        if school_id:
            skeleton['school_enrichment_id'] = school_id
            logger.info(f"✓ Created skeleton school record", extra={'school': school_name, 'id': school_id})
            return skeleton
        else:
            logger.error(f"Failed to create school record for {school_name}")
            return {'school_name': school_name, 'error': 'Failed to create record'}

    def needs_enrichment(self, school_data: Dict[str, Any]) -> bool:
        """
        Check if a school record needs Naveen/Moana enrichment.
        
        A school needs enrichment if:
        - analysis_status is 'pending' or 'failed'
        - OR key fields are all zero/empty (skeleton record)
        
        Returns:
            True if enrichment is needed
        """
        status = school_data.get('analysis_status', 'pending')
        if status in ('pending', 'failed'):
            return True
        
        # Even if status says 'complete', check if data is actually populated
        key_fields = [
            school_data.get('total_students', 0),
            school_data.get('graduation_rate', 0),
            school_data.get('opportunity_score', 0),
        ]
        return all(v == 0 or v is None for v in key_fields)

    def enrich_school_if_pending(
        self,
        school_id: int,
        aurora_agent=None,
    ) -> Dict[str, Any]:
        """
        If a school has analysis_status='pending' and enrichment tables are blank,
        call Naveen to populate enrichment data.
        
        This is the entry point for the user requirement:
        "If the enrichment tables are blank, call Naveen and Moana to populate."
        "If the high school name is there and enrichment data exists, skip."
        
        Args:
            school_id: The school_enrichment_id
            aurora_agent: NaveenSchoolDataScientist instance
            
        Returns:
            Updated school data dict
        """
        school = self.db.get_school_enriched_data(school_id)
        if not school:
            return {'error': f'School {school_id} not found'}
        
        school_dict = dict(school) if hasattr(school, 'items') else school
        
        # Check if enrichment is needed
        if not self.needs_enrichment(school_dict):
            logger.info(
                f"⏭️  School already enriched, skipping",
                extra={'school': school_dict.get('school_name'), 'status': school_dict.get('analysis_status')}
            )
            return school_dict
        
        # Need enrichment — require agent
        if not aurora_agent:
            logger.warning(f"Naveen agent required to enrich school {school_id}")
            return {**school_dict, 'error': 'Naveen agent not available'}
        
        school_name = school_dict.get('school_name', '')
        school_district = school_dict.get('school_district', '')
        state_code = school_dict.get('state_code', 'GA')
        
        logger.info(f"→ Enriching school: {school_name}", extra={'id': school_id})
        
        # Call Naveen
        monitor = get_agent_monitor()
        monitor.start_execution(
            agent_name="Naveen (School Data Scientist)",
            model=config.deployment_name_mini
        )
        
        try:
            enriched_result = aurora_agent.analyze_school(
                school_name=school_name,
                school_district=school_district,
                state_code=state_code,
                existing_data=school_dict
            )
            monitor.end_execution("Naveen (School Data Scientist)", status=AgentStatus.COMPLETED)
        except Exception as e:
            logger.error(f"Naveen enrichment failed for {school_name}: {e}", exc_info=True)
            monitor.end_execution("Naveen (School Data Scientist)", status=AgentStatus.FAILED, error_message=str(e))
            # Mark as failed so we can retry later
            self.db.execute_non_query(
                "UPDATE school_enriched_data SET analysis_status = 'failed', updated_at = CURRENT_TIMESTAMP WHERE school_enrichment_id = %s",
                (school_id,)
            )
            return {**school_dict, 'analysis_status': 'failed', 'error': str(e)}
        
        # Update existing record with Naveen results (don't create a new one)
        if enriched_result.get('analysis_status') == 'complete':
            try:
                update_fields = {
                    'total_students': enriched_result.get('enrollment_size') or enriched_result.get('total_students', 0),
                    'graduation_rate': enriched_result.get('graduation_rate', 0),
                    'college_acceptance_rate': enriched_result.get('college_placement_rate') or enriched_result.get('college_acceptance_rate', 0),
                    'free_lunch_percentage': enriched_result.get('free_lunch_percentage', 0),
                    'ap_course_count': enriched_result.get('ap_classes_count') or enriched_result.get('ap_course_count', 0),
                    'ap_exam_pass_rate': enriched_result.get('ap_exam_pass_rate', 0),
                    'stem_program_available': enriched_result.get('stem_programs', False) or enriched_result.get('stem_program_available', False),
                    'ib_program_available': enriched_result.get('ib_offerings', False) or enriched_result.get('ib_program_available', False),
                    'dual_enrollment_available': enriched_result.get('honors_programs', False) or enriched_result.get('dual_enrollment_available', False),
                    'opportunity_score': enriched_result.get('opportunity_score', 0),
                    'data_confidence_score': enriched_result.get('confidence_score', 0) or enriched_result.get('data_confidence_score', 0),
                    'analysis_status': 'complete',
                    'school_investment_level': enriched_result.get('school_investment_level', 'medium'),
                }
                
                # Build UPDATE query
                set_parts = []
                values = []
                for col, val in update_fields.items():
                    set_parts.append(f"{col} = %s")
                    values.append(val)
                
                set_parts.append("updated_at = CURRENT_TIMESTAMP")
                values.append(school_id)
                
                query = f"UPDATE school_enriched_data SET {', '.join(set_parts)} WHERE school_enrichment_id = %s"
                self.db.execute_non_query(query, tuple(values))
                
                logger.info(
                    f"✓ School enrichment updated in-place",
                    extra={'school': school_name, 'id': school_id, 'score': update_fields['opportunity_score']}
                )
                
                # Return merged data
                school_dict.update(update_fields)
                return school_dict
                
            except Exception as e:
                logger.error(f"Error updating school enrichment: {e}", exc_info=True)
                return {**school_dict, 'error': f'Update failed: {e}'}
        else:
            logger.warning(f"Naveen returned non-complete status for {school_name}")
            return {**school_dict, 'analysis_status': enriched_result.get('analysis_status', 'failed')}

    def _lookup_school_in_database(
        self,
        school_name: str,
        state_code: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Look up school in enriched data table.
        
        Args:
            school_name: School name to search
            state_code: State code (optional filter)
            
        Returns:
            School enrichment record if found, None otherwise
        """
        try:
            # Query school_enriched_data table
            result = self.db.get_school_enriched_data(
                school_name=school_name,
                state_code=state_code
            )
            
            if result:
                # Convert database record to dictionary
                school_data = dict(result) if hasattr(result, 'items') else result
                
                logger.debug(
                    f"School lookup successful",
                    extra={'school': school_name, 'records_found': 1}
                )
                
                return school_data
            
            logger.debug(
                f"School not found in cache",
                extra={'school': school_name, 'state': state_code}
            )
            return None
            
        except Exception as e:
            logger.warning(
                f"Error looking up school in database: {e}",
                extra={'school': school_name, 'error': str(e)}
            )
            return None
    
    def _store_school_enrichment(
        self,
        school_data: Dict[str, Any],
        school_name: str,
        school_district: Optional[str] = None,
        state_code: Optional[str] = None
    ) -> Optional[int]:
        """
        Store enriched school data in database.
        
        Args:
            school_data: Enrichment data from Naveen
            school_name: School name
            school_district: School district
            state_code: State code
            
        Returns:
            Database ID of stored record, or None if failed
        """
        try:
            # Build comprehensive school record for storage
            enrichment_record = {
                'school_name': school_name,
                'school_district': school_district,
                'state_code': state_code,
                
                # Demographics
                'enrollment_size': school_data.get('enrollment_size'),
                'diversity_index': school_data.get('diversity_index'),
                'socioeconomic_level': school_data.get('socioeconomic_level'),
                
                # Academic programs
                'ap_classes_count': school_data.get('ap_classes_count'),
                'ib_offerings': school_data.get('ib_offerings'),
                'honors_programs': school_data.get('honors_programs'),
                'stem_programs': school_data.get('stem_programs'),
                
                # Performance metrics
                'graduation_rate': school_data.get('graduation_rate'),
                'college_placement_rate': school_data.get('college_placement_rate'),
                'avg_test_scores': school_data.get('avg_test_scores'),
                'school_investment_level': school_data.get('school_investment_level'),
                
                # Analysis results
                'opportunity_score': school_data.get('opportunity_score'),
                'analysis_summary': school_data.get('analysis_summary'),
                'web_sources_analyzed': school_data.get('web_sources', []),
                'analysis_date': school_data.get('analysis_date'),
                'human_review_status': 'pending',  # Allow human review/editing
            }
            
            # Store in database
            school_id = self.db.create_school_enriched_data(enrichment_record)
            
            if school_id:
                logger.info(
                    f"✓ School enrichment stored",
                    extra={'school': school_name, 'database_id': school_id}
                )
            
            return school_id
            
        except Exception as e:
            logger.error(
                f"Error storing school enrichment: {e}",
                exc_info=True,
                extra={'school': school_name, 'error': str(e)}
            )
            return None
    
    def validate_school_requirements(
        self,
        school_data: Dict[str, Any],
        required_fields: Optional[List[str]] = None
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        """
        PHASE 3 STEP 1: Validate school data against MOANA requirements.
        
        Default MOANA requirements:
        - school_name, state_code (identifiers)
        - opportunity_score (overall opportunity assessment)
        - ap_courses_available, honors_course_count (academic rigor indicators)
        - free_lunch_percentage (socioeconomic context)
        - graduation_rate (school performance)
        
        Args:
            school_data: School enrichment data dict to validate
            required_fields: Override default list of required fields
            
        Returns:
            Tuple of (is_valid, missing_fields_list, validation_details_dict)
        """
        # Default MOANA requirements if not specified
        if required_fields is None:
            required_fields = [
                'school_name',
                'state_code',
                'opportunity_score',
                'ap_courses_available',
                'honors_course_count',
                'free_lunch_percentage',
                'graduation_rate'
            ]
        
        missing = []
        field_status = {}
        
        for field in required_fields:
            value = school_data.get(field)
            # Field is present if it exists and is not None or empty string
            is_present = value is not None and value != ''
            field_status[field] = {
                'required': True,
                'present': is_present,
                'value': value
            }
            
            if not is_present:
                missing.append(field)
        
        is_valid = len(missing) == 0
        
        validation_details = {
            'is_valid': is_valid,
            'missing_count': len(missing),
            'total_required': len(required_fields),
            'field_status': field_status,
            'validated_at': datetime.now().isoformat()
        }
        
        logger.info(
            f"School validation result for {school_data.get('school_name')}",
            extra={
                'is_valid': is_valid,
                'missing_fields': missing,
                'missing_count': len(missing)
            }
        )
        
        return is_valid, missing, validation_details
    
    def remediate_school_enrichment(
        self,
        school_name: str,
        state_code: Optional[str],
        school_district: Optional[str],
        missing_fields: List[str],
        aurora_agent = None,
        remediation_attempt: int = 1
    ) -> Dict[str, Any]:
        """
        PHASE 3 STEP 2: Remediate missing school fields by calling NAVEEN again.
        
        Calls NAVEEN with specific context requesting the missing fields.
        This is the "loop back" mechanism in the NAVEEN ↔ MOANA validation loop.
        
        Args:
            school_name: School name
            state_code: State code
            school_district: District
            missing_fields: List of fields that validation found missing
            aurora_agent: Naveen agent instance for enrichment
            remediation_attempt: Attempt number (for tracking)
            
        Returns:
            Updated school enrichment data dict
        """
        if not aurora_agent:
            logger.warning(
                f"⚠️ Cannot remediate school - no NAVEEN agent available",
                extra={'school': school_name, 'missing_fields': missing_fields}
            )
            return {
                'error': 'NAVEEN agent not available for remediation',
                'remediation_attempt': remediation_attempt
            }
        
        logger.info(
            f"🔄 REMEDIATION ATTEMPT {remediation_attempt}: Calling NAVEEN to enrich missing fields",
            extra={
                'school': school_name,
                'missing_fields': missing_fields,
                'attempt': remediation_attempt
            }
        )
        
        # Create context-specific prompt for NAVEEN pointing to missing fields
        missing_context = f"Missing for MOANA validation: {', '.join(missing_fields)}"
        
        monitor = get_agent_monitor()
        execution = monitor.start_execution(
            agent_name=f"Naveen Remediation Attempt {remediation_attempt}",
            model=config.deployment_name_mini
        )
        
        try:
            # Call NAVEEN with specific focus on missing fields
            remediated_result = aurora_agent.analyze_school(
                school_name=school_name,
                school_district=school_district,
                state_code=state_code,
                enrichment_focus=missing_context  # Hint to focus on these fields
            )
            
            monitor.end_execution(
                f"Naveen Remediation Attempt {remediation_attempt}",
                status=AgentStatus.COMPLETED
            )
            
            remediated_result['remediation_attempt'] = remediation_attempt
            remediated_result['remediation_context'] = missing_context
            
            logger.info(
                f"✓ NAVEEN remediation attempt {remediation_attempt} complete",
                extra={'school': school_name}
            )
            
            return remediated_result
            
        except Exception as e:
            logger.error(
                f"❌ NAVEEN remediation attempt {remediation_attempt} failed: {e}",
                exc_info=True,
                extra={'school': school_name, 'attempt': remediation_attempt}
            )
            
            monitor.end_execution(
                f"Naveen Remediation Attempt {remediation_attempt}",
                status=AgentStatus.FAILED,
                error_message=str(e)
            )
            
            return {
                'error': f'Remediation failed: {str(e)}',
                'remediation_attempt': remediation_attempt
            }
    
    def validate_and_remediate_school(
        self,
        school_name: str,
        state_code: Optional[str],
        school_district: Optional[str] = None,
        aurora_agent = None,
        max_remediation_attempts: int = 2,
        required_fields: Optional[List[str]] = None
    ) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:
        """
        PHASE 3 COMPLETE LOOP: Validate school and remediate missing fields iteratively.
        
        This is the bidirectional NAVEEN ↔ MOANA validation loop:
        1. Get enriched school data (via get_or_enrich_school_data)
        2. Validate against MOANA requirements
        3. If missing fields: call NAVEEN again with specific context
        4. Repeat validation (max N attempts)
        5. Return result: (is_ready_for_MOANA, school_data, validation_log)
        
        Args:
            school_name: School name
            state_code: State code
            school_district: School district
            aurora_agent: NAVEEN agent for enrichment
            max_remediation_attempts: Max times to call NAVEEN for remediation
            required_fields: Fields MOANA requires (defaults: school_name, state_code, opportunity_score, etc)
            
        Returns:
            Tuple of:
            - is_ready: Boolean indicating if school data is ready for MOANA
            - school_data: Final enriched school data
            - validation_log: Dict with validation history and details
        """
        validation_log = {
            'school_name': school_name,
            'state_code': state_code,
            'validation_started': datetime.now().isoformat(),
            'attempts': []
        }
        
        logger.info(
            f"🏫 PHASE 3: Starting NAVEEN ↔ MOANA validation loop for {school_name}",
            extra={'state': state_code, 'max_attempts': max_remediation_attempts}
        )
        
        # Step 1: Initial enrichment
        school_data = self.get_or_enrich_school_data(
            school_name=school_name,
            school_district=school_district,
            state_code=state_code,
            aurora_agent=aurora_agent
        )
        
        if 'error' in school_data:
            logger.error(f"❌ Cannot enrich school: {school_data.get('error')}")
            return False, school_data, {**validation_log, 'error': school_data.get('error')}
        
        # Step 2: Validate against MOANA requirements
        for attempt in range(1, max_remediation_attempts + 1):
            is_valid, missing_fields, validation_details = self.validate_school_requirements(
                school_data=school_data,
                required_fields=required_fields
            )
            
            attempt_log = {
                'attempt_number': attempt,
                'is_valid': is_valid,
                'missing_fields': missing_fields,
                'validation_timestamp': datetime.now().isoformat(),
                'school_data_keys': list(school_data.keys())
            }
            
            validation_log['attempts'].append(attempt_log)
            
            if is_valid:
                logger.info(
                    f"✅ VALIDATION PASSED on attempt {attempt}: {school_name} ready for MOANA",
                    extra={'school': school_name, 'attempt': attempt}
                )
                validation_log['validation_complete'] = True
                validation_log['ready_for_moana'] = True
                validation_log['final_attempt'] = attempt
                
                # Update database to mark validation as complete
                if self.db and hasattr(self.db, 'mark_school_validation_complete'):
                    try:
                        self.db.mark_school_validation_complete(
                            school_name=school_name,
                            state_code=state_code,
                            validation_passed=True
                        )
                    except Exception as e:
                        logger.warning(f"Could not mark validation complete in DB: {e}")
                
                return True, school_data, validation_log
            
            # Validation failed - check if we should remediate
            if attempt < max_remediation_attempts:
                logger.warning(
                    f"⚠️ VALIDATION FAILED on attempt {attempt}: missing {len(missing_fields)} fields",
                    extra={'school': school_name, 'missing_fields': missing_fields}
                )
                
                # Step 3: Call NAVEEN to remediate missing fields
                remediated = self.remediate_school_enrichment(
                    school_name=school_name,
                    state_code=state_code,
                    school_district=school_district,
                    missing_fields=missing_fields,
                    aurora_agent=aurora_agent,
                    remediation_attempt=attempt
                )
                
                # Merge remediated fields into school_data
                if 'error' not in remediated:
                    school_data.update(remediated)
                    attempt_log['remediation_applied'] = True
                    attempt_log['remediated_fields'] = len(remediated)
                else:
                    logger.warning(
                        f"Remediation failed on attempt {attempt}",
                        extra={'error': remediated.get('error')}
                    )
                    attempt_log['remediation_error'] = remediated.get('error')
            
            # If this was the last attempt and validation failed
            if attempt == max_remediation_attempts and not is_valid:
                logger.error(
                    f"❌ VALIDATION FAILED after {max_remediation_attempts} attempts",
                    extra={
                        'school': school_name,
                        'still_missing': missing_fields
                    }
                )
                validation_log['validation_complete'] = True
                validation_log['ready_for_moana'] = False
                validation_log['final_attempt'] = attempt
                validation_log['final_missing_fields'] = missing_fields
                
                # Update database to mark validation as failed
                if self.db and hasattr(self.db, 'mark_school_validation_complete'):
                    try:
                        self.db.mark_school_validation_complete(
                            school_name=school_name,
                            state_code=state_code,
                            validation_passed=False
                        )
                    except Exception as e:
                        logger.warning(f"Could not mark validation failed in DB: {e}")
                
                return False, school_data, validation_log
        
        # Should not reach here
        return False, school_data, validation_log


def ensure_school_context_in_pipeline(
    school_name: str,
    school_district: Optional[str] = None,
    state_code: Optional[str] = None,
    db_connection = None,
    aurora_agent = None
) -> Dict[str, Any]:
    """
    Convenience function to check/enrich school data before Moana processing.
    
    Usage in agent pipeline:
        school_enrichment = ensure_school_context_in_pipeline(
            school_name=student_school,
            state_code=student_state,
            db_connection=db,
            aurora_agent=aurora
        )
        
        moana_result = moana.analyze_school_context(
            grades=rapunzel_output,
            school_enrichment=school_enrichment  # Use cached/enriched data
        )
    
    Args:
        school_name: High school name
        school_district: School district (optional)
        state_code: State code (optional)
        db_connection: Database connection
        aurora_agent: Naveen (school data scientist) agent for enrichment
        
    Returns:
        Enriched school data dictionary
    """
    if not db_connection:
        logger.warning("Database connection required for school workflow")
        return {'error': 'No database connection'}
    
    workflow = SchoolDataWorkflow(db_connection)
    return workflow.get_or_enrich_school_data(
        school_name=school_name,
        school_district=school_district,
        state_code=state_code,
        aurora_agent=aurora_agent
    )
