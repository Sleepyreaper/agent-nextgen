"""Agent requirements and communication - Agents tell Smee what they need"""

from typing import Dict, List, Any, Optional

class AgentRequirements:
    """Tracks what each agent needs and can provide feedback"""
    
    # Define what each agent needs
    AGENT_NEEDS = {
        'application_reader': {
            'required_fields': ['application_text'],
            'questions': [
                "Do you have a written application or essay?",
                "Can you provide the student's application statement?"
            ],
            'accepts_formats': ['txt', 'pdf', 'docx'],
            'field_name': 'application_essay'
        },
        'grade_reader': {
            'required_fields': ['transcript_text'],
            'questions': [
                "Do you have the student's transcript or grades?",
                "Can you provide academic records showing GPA, courses, and grades?"
            ],
            'accepts_formats': ['pdf', 'docx', 'txt'],
            'field_name': 'transcript'
        },
        'school_context': {
            'required_fields': ['school_name', 'transcript_text'],
            'questions': [
                "What is the student's high school name?",
                "Can you provide transcript or school documents to identify the school?",
                "Do you know the school's demographics or location?"
            ],
            'accepts_formats': ['txt', 'pdf', 'docx'],
            'field_name': 'school_context'
        },
        'recommendation_reader': {
            'required_fields': ['recommendation_text'],
            'questions': [
                "Do you have letters of recommendation?",
                "Can you provide recommendation letters from teachers or mentors?",
                "How many recommendation letters do you have?"
            ],
            'accepts_formats': ['pdf', 'docx', 'txt'],
            'field_name': 'letters_of_recommendation'
        },
        'student_evaluator': {
            'required_fields': ['application_text'],
            'questions': [
                "Ready to have Merlin evaluate the student?"
            ],
            'accepts_formats': ['txt'],
            'field_name': 'student_evaluation'
        }
    }
    
    @classmethod
    def get_agent_requirements(cls, agent_id: str) -> Dict[str, Any]:
        """Get what a specific agent needs"""
        return cls.AGENT_NEEDS.get(agent_id, {})
    
    @classmethod
    def get_all_questions(cls, agents: List[str]) -> List[Dict[str, Any]]:
        """Get all questions from agents in the pipeline"""
        questions = []
        for agent_id in agents:
            req = cls.get_agent_requirements(agent_id)
            if req:
                questions.append({
                    'agent_id': agent_id,
                    'agent_name': agent_id.replace('_', ' ').title(),
                    'questions': req.get('questions', []),
                    'required_fields': req.get('required_fields', []),
                    'field_name': req.get('field_name', agent_id)
                })
        return questions
    
    @classmethod
    def get_field_for_agent(cls, agent_id: str) -> str:
        """Get the field name that tracks this agent's needs"""
        req = cls.get_agent_requirements(agent_id)
        return req.get('field_name', agent_id)
