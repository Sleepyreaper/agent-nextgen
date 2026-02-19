"""
Aurora Agent - Elegantly formats and presents final evaluation results.
Works with Merlin and Smee to ensure uniform, polished presentation across evaluations.
"""

import asyncio
import json
from typing import Dict, Any, Optional, List
from src.agents.base_agent import BaseAgent


class AuroraAgent(BaseAgent):
    """
    Aurora Agent - Elegantly formats and presents final evaluation results.
    
    This agent:
    1. Takes outputs from all agents (Tiana, Rapunzel, Moana, Mulan)
    2. Formats them consistently with Merlin's assessment
    3. Validates that all required fields are present
    4. Creates the final result page structure
    5. Ensures visual consistency across all student evaluations
    """
    
    def __init__(self):
        # Note: We don't need Azure OpenAI client for Aurora since it just formats data
        # Pass None for client - Aurora doesn't make API calls
        super().__init__(name="Aurora", client=None)
        self.emoji = "👑"
        self.description = "Elegantly presents polished final results with Merlin and Smee"
        
        # Template for consistent result structure
        self.result_template = {
            'student_info': {
                'name': None,
                'email': None,
                'status': None
            },
            'merlin_summary': {
                'score': None,
                'recommendation': None,
                'overall': None,
                'key_strengths': [],
                'considerations': []
            },
            'agents': {
                'tiana': None,
                'rapunzel': None,
                'moana': None,
                'mulan': None
            },
            'application_text': None,
            'processing_metadata': {
                'agents_completed': [],
                'smee_verified': False,
                'merlin_signed_off': False,
                'presenter_formatted': False
            }
        }
    
    async def format_results(self, application_data: Dict[str, Any], 
                           agent_outputs: Dict[str, Any],
                           merlin_assessment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format all agent outputs into a consistent result page structure.
        
        Args:
            application_data: Student application information
            agent_outputs: Outputs from Tiana, Rapunzel, Moana, Mulan
            merlin_assessment: Merlin's final assessment
            
        Returns:
            Consistent result page data
        """
        result = self.result_template.copy()
        
        # Populate student info
        result['student_info'] = {
            'name': application_data.get('name'),
            'email': application_data.get('email'),
            'status': self._determine_status(agent_outputs)
        }
        
        # Populate Merlin's summary
        overall_text = (
            merlin_assessment.get('rationale')
            or merlin_assessment.get('overall_narrative')
            or ''
        )
        considerations = (
            merlin_assessment.get('key_risks')
            or merlin_assessment.get('context_factors')
            or []
        )
        decision_drivers = (
            merlin_assessment.get('decision_drivers')
            or merlin_assessment.get('key_strengths')
            or []
        )
        top_risk = (
            merlin_assessment.get('top_risk')
            or (considerations[0] if considerations else None)
        )
        result['merlin_summary'] = {
            'score': merlin_assessment.get('overall_score', 0),
            'recommendation': merlin_assessment.get('recommendation', 'PENDING'),
            'overall': overall_text,
            'key_strengths': merlin_assessment.get('key_strengths', []),
            'considerations': considerations,
            'decision_drivers': decision_drivers,
            'top_risk': top_risk
        }
        
        # Format each agent's output consistently
        tiana_output = self._format_tiana_output(agent_outputs.get('tiana'))
        rapunzel_output = self._format_rapunzel_output(agent_outputs.get('rapunzel'))
        moana_output = self._format_moana_output(agent_outputs.get('moana'))
        mulan_output = self._format_mulan_output(agent_outputs.get('mulan'))

        rapunzel_output['contextual_comparison'] = self._build_grade_context(
            agent_outputs.get('rapunzel'),
            agent_outputs.get('moana')
        )

        result['agents'] = {
            'tiana': tiana_output,
            'rapunzel': rapunzel_output,
            'moana': moana_output,
            'mulan': mulan_output
        }
        
        # Include application text
        result['application_text'] = application_data.get('application_text')
        
        # Mark processing metadata
        result['processing_metadata'] = {
            'agents_completed': list(agent_outputs.keys()),
            'smee_verified': agent_outputs.get('smee_verified', False),
            'merlin_signed_off': merlin_assessment.get('signed_off', False),
            'presenter_formatted': True
        }
        
        return result
    
    def _determine_status(self, agent_outputs: Dict[str, Any]) -> str:
        """Determine overall status based on which agents completed."""
        total_agents = 4  # Tiana, Rapunzel, Moana, Mulan
        completed = len([k for k, v in agent_outputs.items() if v is not None])
        
        if completed == total_agents:
            return 'COMPLETE'
        elif completed > 0:
            return 'PARTIAL'
        else:
            return 'PENDING'
    
    def _format_tiana_output(self, tiana_data: Optional[Dict]) -> Dict[str, Any]:
        """Format Tiana's (Application Reader) output consistently."""
        if not tiana_data:
            return {
                'name': '👸 Tiana - Application Reader',
                'status': '⏳ Waiting',
                'score': None
            }
        
        return {
            'name': '👸 Tiana - Application Reader',
            'status': '✅ Complete',
            'score': tiana_data.get('readiness_score') or tiana_data.get('score'),
            'analysis': tiana_data.get('analysis') or tiana_data.get('essay_summary'),
            'key_qualities': tiana_data.get('key_qualities') or tiana_data.get('qualities', []),
            'strengths_found': tiana_data.get('strengths_found') or ''
        }
    
    def _format_rapunzel_output(self, rapunzel_data: Optional[Dict]) -> Dict[str, Any]:
        """Format Rapunzel's (Grade Reader) output consistently."""
        if not rapunzel_data:
            return {
                'name': '💇 Rapunzel - Grade Reader',
                'status': '⏳ Waiting',
                'gpa': None
            }
        
        return {
            'name': '💇 Rapunzel - Grade Reader',
            'status': '✅ Complete',
            'gpa': rapunzel_data.get('gpa'),
            'academic_score': rapunzel_data.get('academic_score') or rapunzel_data.get('overall_score'),
            'courses_analyzed': rapunzel_data.get('courses_analyzed') or '',
            'grade_trends': rapunzel_data.get('grade_pattern') or rapunzel_data.get('grade_trends'),
            'key_findings': rapunzel_data.get('key_findings', []),
            'summary': rapunzel_data.get('summary'),
            'course_rigor_index': rapunzel_data.get('course_rigor_index'),
            'grade_table_headers': rapunzel_data.get('grade_table_headers'),
            'grade_table_rows': rapunzel_data.get('grade_table_rows'),
            'grade_table_markdown': rapunzel_data.get('grade_table_markdown')
        }
    
    def _format_moana_output(self, moana_data: Optional[Dict]) -> Dict[str, Any]:
        """Format Moana's (School Context) output consistently."""
        if not moana_data:
            return {
                'name': '🌊 Moana - School Context',
                'status': '⏳ Waiting'
            }
        
        return {
            'name': '🌊 Moana - School Context',
            'status': '✅ Complete' if moana_data.get('school_name') else '⚠️ Partial',
            'school_name': moana_data.get('school_name') or moana_data.get('SchoolName'),
            'location': moana_data.get('location') or moana_data.get('city'),
            'school_ranking': moana_data.get('school_ranking') or moana_data.get('ranking'),
            'school_info': moana_data.get('school_info') or moana_data.get('description'),
            'key_context': moana_data.get('key_context', []),
            'context': moana_data.get('contextual_summary') or moana_data.get('comparison_notes'),
            'ses_level': (moana_data.get('ses_context') or {}).get('ses_level'),
            'resource_tier': (moana_data.get('school_resources') or {}).get('resource_tier'),
            'ap_courses_available': (moana_data.get('school_resources') or {}).get('ap_courses_available'),
            'honors_courses_available': (moana_data.get('school_resources') or {}).get('honors_courses_available'),
            'ib_courses_available': (moana_data.get('school_resources') or {}).get('ib_courses_available'),
            'stem_programs_count': (moana_data.get('school_resources') or {}).get('stem_programs_count'),
            'opportunity_score': (moana_data.get('opportunity_scores') or {}).get('overall_opportunity_score'),
            'ap_courses_taken': len((moana_data.get('program_participation') or {}).get('ap_courses_taken', []))
        }

    def _build_grade_context(
        self,
        rapunzel_data: Optional[Dict[str, Any]],
        moana_data: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """Create a grade context note based on school resources and SES."""
        if not rapunzel_data or not moana_data:
            return None

        school_name = (moana_data.get('school', {}) or {}).get('name') or moana_data.get('school_name')
        ses_level = (moana_data.get('ses_context') or {}).get('ses_level')
        resource_tier = (moana_data.get('school_resources') or {}).get('resource_tier')
        ap_available = (moana_data.get('school_resources') or {}).get('ap_courses_available')

        context_bits = []
        if school_name:
            context_bits.append(f"{school_name}")
        if resource_tier:
            context_bits.append(f"{resource_tier} resources")
        if ses_level:
            context_bits.append(f"SES: {ses_level}")
        if ap_available is not None:
            context_bits.append(f"AP available: {ap_available}")

        base_context = ", ".join(context_bits) if context_bits else "School context available"
        return (
            f"{base_context}. Interpret grades against opportunity: a B in a high-rigor environment can be as meaningful as an A in a low-rigor setting."
        )
    
    def _format_mulan_output(self, mulan_data: Optional[Dict]) -> Dict[str, Any]:
        """Format Mulan's (Recommendation Reader) output consistently."""
        if not mulan_data:
            return {
                'name': '🗡️ Mulan - Recommendation Reader',
                'status': '⏳ Waiting'
            }
        
        # Handle both single rec and list of recs
        recs = mulan_data if isinstance(mulan_data, list) else [mulan_data]
        
        return {
            'name': '🗡️ Mulan - Recommendation Reader',
            'status': '✅ Complete' if recs else '⏳ Waiting',
            'recommendation_count': len(recs),
            'endorsement_strength': recs[0].get('endorsement_strength') if recs else None,
            'rec_text': recs[0].get('summary') if recs else '',
            'key_endorsements': mulan_data.get('key_endorsements', []) if isinstance(mulan_data, dict) else []
        }
    
    def format_evaluation_report(self, evaluation_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        PHASE 4: Format all evaluation results into a polished final report.
        
        This method is called by SMEE STEP 7 to generate the final report that combines:
        - Step 1 BELLE extractions
        - Step 2 Student record
        - Step 3/3.5 School enrichment & validation
        - Step 4 Core agent analyses (TIANA, RAPUNZEL, MOANA, MULAN)
        - Step 5 MILO training analysis
        - Step 6 MERLIN synthesis
        - Step 7 AURORA formatting
        
        Args:
            evaluation_results: Dict with results from all 8 steps of workflow
                Keys: {
                    'applicant_name', 'application_id', 'student_id',
                    'agents_used', 'results': {
                        'belle_extraction', 'naveen_enrichment', 'school_validation_log',
                        'application_reader', 'grade_reader', 'school_context',
                        'recommendation_reader', 'data_scientist', 'student_evaluator'
                    }
                }
        
        Returns:
            Formatted report dict ready for dashboard/export
        """
        try:
            # Extract key data from evaluation results
            results = evaluation_results.get('results', {})
            applicant_name = evaluation_results.get('applicant_name', 'Unknown')
            application_id = evaluation_results.get('application_id')
            student_id = evaluation_results.get('student_id')
            
            # Build report sections
            report = {
                'status': 'success',
                'applicant': applicant_name,
                'application_id': application_id,
                'student_id': student_id,
                'report_type': 'comprehensive_evaluation',
                'generated_by': 'Aurora',
                'timestamp': __import__('datetime').datetime.now().isoformat(),
                
                # Applicant identification
                'applicant_info': {
                    'name': applicant_name,
                    'id': application_id
                },
                
                # Step 1: BELLE extraction summary
                'document_analysis': {
                    'extraction_complete': 'belle_extraction' in results,
                    'extracted_fields': len(results.get('belle_extraction', {}))
                },
                
                # Steps 3-3.5: School context
                'school_context': {
                    'school': results.get('naveen_enrichment', {}).get('school_name'),
                    'state': results.get('naveen_enrichment', {}).get('state_code'),
                    'validation_passed': results.get('school_validation_log', {}).get('ready_for_moana'),
                    'opportunity_score': results.get('naveen_enrichment', {}).get('opportunity_score'),
                    'enrichment_summary': results.get('naveen_enrichment', {}).get('analysis_summary')
                },
                
                # Step 4: Core analyses
                'candidate_profile': {
                    # TIANA: Application analysis
                    'application_review': {
                        'complete': 'application_reader' in results,
                        'extracted_schools': results.get('application_reader', {}).get('schools', []),
                        'extracted_interests': results.get('application_reader', {}).get('interests', []),
                        'summary': results.get('application_reader', {}).get('summary')
                    },
                    
                    # RAPUNZEL: Grade analysis with school context
                    'academic_performance': {
                        'complete': 'grade_reader' in results,
                        'gpa': results.get('grade_reader', {}).get('gpa'),
                        'academic_strength': results.get('grade_reader', {}).get('academic_strength'),
                        'course_rigor_index': results.get('grade_reader', {}).get('course_rigor_index'),
                        'contextual_rigor_index': results.get('grade_reader', {}).get('contextual_rigor_index'),
                        'school_context_used': results.get('grade_reader', {}).get('school_context_used'),
                        'transcript_quality': results.get('grade_reader', {}).get('transcript_quality'),
                        'notable_patterns': results.get('grade_reader', {}).get('notable_patterns', []),
                        'confidence_level': results.get('grade_reader', {}).get('confidence_level')
                    },
                    
                    # MOANA: School context analysis
                    'school_analysis': {
                        'complete': 'school_context' in results,
                        'school_name': results.get('school_context', {}).get('school_name'),
                        'opportunity_score': results.get('school_context', {}).get('opportunity_scores', {}).get('overall_opportunity_score'),
                        'contextual_summary': results.get('school_context', {}).get('contextual_summary'),
                        'program_access_score': results.get('school_context', {}).get('opportunity_scores', {}).get('program_access_score'),
                        'relative_advantage_score': results.get('school_context', {}).get('opportunity_scores', {}).get('relative_advantage_score')
                    },
                    
                    # MULAN: Recommendations analysis
                    'recommendations_analysis': {
                        'complete': 'recommendation_reader' in results,
                        'author_count': len(results.get('recommendation_reader', {}).get('recommenders', [])) if results.get('recommendation_reader') else 0,
                        'strength_indicators': results.get('recommendation_reader', {}).get('strength_indicators', []),
                        'summary': results.get('recommendation_reader', {}).get('summary')
                    }
                },
                
                # Step 5: MILO Analysis
                'training_insights': {
                    'complete': 'data_scientist' in results,
                    'insights': results.get('data_scientist', {}).get('insights', []) if results.get('data_scientist') else []
                },
                
                # Step 6: MERLIN Synthesis
                'merlin_assessment': {
                    'complete': 'student_evaluator' in results and 'error' not in results.get('student_evaluator', {}),
                    'overall_evaluation': results.get('student_evaluator', {}).get('overall_evaluation'),
                    'recommendation': results.get('student_evaluator', {}).get('recommendation'),
                    'key_strengths': results.get('student_evaluator', {}).get('key_strengths', []),
                    'areas_for_growth': results.get('student_evaluator', {}).get('areas_for_growth', []),
                    'context_considerations': results.get('student_evaluator', {}).get('context_factors', [])
                },
                
                # Workflow metadata
                'workflow_status': {
                    'steps_completed': len([k for k in results.keys() if 'error' not in results.get(k, {})]),
                    'total_steps': len(evaluation_results.get('agents_used', [])),
                    'all_complete': all('error' not in results.get(k, {}) for k in results.keys() if k not in ['belle_extraction', 'naveen_enrichment', 'school_validation_log'])
                }
            }
            
            return report
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'generated_by': 'Aurora',
                'message': 'Error formatting evaluation report'
            }
    
    async def validate_result_structure(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that result meets all formatting requirements."""
        issues = []
        
        # Check student info
        if not result['student_info']['name']:
            issues.append('Missing student name')
        if not result['student_info']['email']:
            issues.append('Missing student email')
        
        # Check Merlin summary (critical)
        if result['merlin_summary']['score'] is None:
            issues.append('Missing Merlin score')
        if not result['merlin_summary']['recommendation']:
            issues.append('Missing Merlin recommendation')
        if not result['merlin_summary']['overall']:
            issues.append('Missing Merlin overall narrative')
        
        # Check that agents have data
        agents_with_data = sum(1 for v in result['agents'].values() if v and v.get('status') == '✅ Complete')
        if agents_with_data < 2:
            issues.append('Too few agents completed')
        
        # Check processing metadata
        if not result['processing_metadata'].get('merlin_signed_off'):
            issues.append('Merlin has not signed off')
        if not result['processing_metadata'].get('smee_verified'):
            issues.append('Smee has not verified')
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'result': result
        }
    
    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point for Presenter Agent processing.
        
        Expected input:
        {
            'application': {...student data...},
            'agent_outputs': {...outputs from all agents...},
            'merlin_assessment': {...Merlin's evaluation...}
        }
        """
        try:
            application = data.get('application', {})
            agent_outputs = data.get('agent_outputs', {})
            merlin_assessment = data.get('merlin_assessment', {})
            
            # Format results
            formatted_result = await self.format_results(
                application,
                agent_outputs,
                merlin_assessment
            )
            
            # Validate structure
            validation = await self.validate_result_structure(formatted_result)
            
            return {
                'status': 'success' if validation['valid'] else 'partial',
                'result': formatted_result,
                'validation': validation,
                'agent': self.name,
                'message': 'Result page formatted and ready' if validation['valid'] 
                          else f"Formatting complete with issues: {', '.join(validation['issues'])}"
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'agent': self.name
            }
