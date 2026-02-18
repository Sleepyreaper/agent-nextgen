"""
School Data Workflow Manager - Handles school data lookup, enrichment, and caching.

Ensures schools are analyzed once and reused:
1. Check if school exists in database
2. If not, call Naveen (school_data_scientist) for deep analysis
3. Store results persistently
4. Pass to Moana (moana_school_context) for contextual analysis with grades
"""

import logging
from typing import Dict, Any, Optional
from src.agents.agent_monitor import get_agent_monitor, AgentStatus

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
            model="o4miniagent"
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
        if enriched_result.get('status') == 'success':
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
