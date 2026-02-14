"""
Presenter Agent - Formats and validates consistent result pages for all students.
Works with Merlin and Smee to ensure uniform presentation across evaluations.
"""

import asyncio
import json
from typing import Dict, Any, Optional, List
from src.agents.base_agent import BaseAgent


class PresenterAgent(BaseAgent):
    """
    Presenter Agent - Ensures consistent formatting of result pages.
    
    This agent:
    1. Takes outputs from all agents (Tiana, Rapunzel, Moana, Mulan)
    2. Formats them consistently with Merlin's assessment
    3. Validates that all required fields are present
    4. Creates the final result page structure
    5. Ensures visual consistency across all student evaluations
    """
    
    def __init__(self):
        # Note: We don't need Azure OpenAI client for Presenter since it just formats data
        # Pass None for client - Presenter doesn't make API calls
        super().__init__(name="Presenter", client=None)
        self.emoji = "🎨"
        self.description = "Formats consistent result pages with Merlin and Smee"
        
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
        result['merlin_summary'] = {
            'score': merlin_assessment.get('overall_score', 0),
            'recommendation': merlin_assessment.get('recommendation', 'PENDING'),
            'overall': merlin_assessment.get('overall_narrative', ''),
            'key_strengths': merlin_assessment.get('key_strengths', []),
            'considerations': merlin_assessment.get('considerations', [])
        }
        
        # Format each agent's output consistently
        result['agents'] = {
            'tiana': self._format_tiana_output(agent_outputs.get('tiana')),
            'rapunzel': self._format_rapunzel_output(agent_outputs.get('rapunzel')),
            'moana': self._format_moana_output(agent_outputs.get('moana')),
            'mulan': self._format_mulan_output(agent_outputs.get('mulan'))
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
            'key_findings': rapunzel_data.get('key_findings', [])
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
            'key_context': moana_data.get('key_context', [])
        }
    
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
