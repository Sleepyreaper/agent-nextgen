"""
ARIEL - Q&A Agent
Answers questions about students based on extracted data from other agents.

Uses GPT-4 to reason over student profiles and provide informed responses about:
- Academic performance and grades
- School capabilities and resources
- Qualifications and achievements
- Context-aware analysis
"""

import json
import logging
from typing import Optional
from datetime import datetime
from src.agents.base_agent import BaseAgent
from src.agents.telemetry_helpers import agent_run
from src.database import Database
from openai import AzureOpenAI
from src.config import config

logger = logging.getLogger(__name__)


class ArielQAAgent(BaseAgent):
    """Q&A Agent for answering questions about student profiles."""
    
    def __init__(self, client: AzureOpenAI = None, model: str = None):
        """Initialize ARIEL Q&A Agent.

        Args:
            client: Optional pre-configured AzureOpenAI or Foundry client. If None,
                    the agent will construct a client from `config` values.
            model: Optional model/deployment name to prefer for calls.
        """
        super().__init__("ARIEL", "Q&A Agent")
        # resolved model name for transparency/telemetry
        # Ariel is Tier 2 (workhorse) — conversational Q&A with 30s latency target
        self.model = model or config.model_tier_workhorse or config.foundry_model_name or config.deployment_name
        # Use the module-level `db` singleton to ensure we share the same
        # database connection used by the Flask app and upload endpoints.
        from src.database import db as shared_db
        self.db = shared_db

        # Allow injection of a client (preferred). Otherwise configure one from `config`.
        if client:
            self.client = client
        else:
            # Defer imports that may not be available in all runtime contexts
            from src.config import config
            # If Foundry is the configured provider, use the Foundry adapter
            if config.model_provider and config.model_provider.lower() == "foundry":
                try:
                    from src.agents.foundry_client import FoundryClient
                    # Do not pass an API key so the FoundryClient will prefer
                    # Entra ID managed identity (DefaultAzureCredential) when available.
                    self.client = FoundryClient(endpoint=config.foundry_project_endpoint)
                except Exception:
                    # Fallback to a generic AzureOpenAI client if Foundry adapter isn't available
                    self.client = AzureOpenAI()
            else:
                # Prefer explicit API key when available
                azure_deployment = model or config.deployment_name
                if config.azure_openai_api_key:
                    self.client = AzureOpenAI(
                        api_key=config.azure_openai_api_key,
                        api_version=config.api_version,
                        azure_endpoint=config.azure_openai_endpoint,
                        azure_deployment=azure_deployment,
                    )
                else:
                    # Use managed identity token provider when no API key is present
                    try:
                        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                        token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
                        self.client = AzureOpenAI(
                            azure_ad_token_provider=token_provider,
                            api_version=config.api_version,
                            azure_endpoint=config.azure_openai_endpoint,
                            azure_deployment=azure_deployment,
                        )
                    except Exception:
                        # Last-resort fallback
                        self.client = AzureOpenAI()
    
    async def answer_question(
        self,
        application_id: str,
        question: str,
        conversation_history: Optional[list] = None
    ) -> dict:
        """
        Answer a question about a student using GPT-4.
        
        Args:
            application_id: Student's application ID
            question: User's question about the student
            conversation_history: Previous Q&A exchanges (for context)
        
        Returns:
            {
                "success": bool,
                "answer": str,
                "reference_data": dict (what data was used),
                "error": str (if failed)
            }
        """
        with agent_run("Ariel", "answer_question", {"application_id": str(application_id)}) as span:
            try:
                # Fetch comprehensive student profile
                student_profile = await self._build_student_profile(application_id)
                
                if not student_profile:
                    student_profile = {
                        'name': 'Unknown Student',
                        'school': 'Unknown School',
                        'state': 'Unknown',
                        'gpa': None,
                        'test_scores': None,
                        'application_status': 'Missing',
                        'school_context': {},
                        'rigor_analysis': {},
                        'agent_evaluations': {},
                        '_data_sources': []
                    }
                
                # Build context for GPT-4
                system_prompt = self._build_system_prompt(student_profile)
                user_message = self._build_user_message(question, student_profile)
                
                # Build messages with conversation history
                messages = [
                    {"role": "system", "content": system_prompt}
                ]
                
                if conversation_history:
                    for exchange in conversation_history:
                        messages.append({"role": "user", "content": exchange["question"]})
                        messages.append({"role": "assistant", "content": exchange["answer"]})
                
                messages.append({"role": "user", "content": user_message})
                
                response = self._create_chat_completion(
                    operation="ariel.answer_question",
                    model=(config.foundry_model_name if config.model_provider == "foundry" else config.deployment_name),
                    messages=messages,
                    temperature=0.7,
                    max_completion_tokens=1000,
                    timeout=30
                )
                
                answer = response.choices[0].message.content
                
                await self._log_qa_interaction(
                    application_id=application_id,
                    question=question,
                    answer=answer,
                    student_profile=student_profile
                )
                
                return {
                    "success": True,
                    "answer": answer,
                    "reference_data": {
                        "name": student_profile.get("name"),
                        "school": student_profile.get("school"),
                        "gpa": student_profile.get("gpa"),
                        "data_sources": student_profile.get("_data_sources", [])
                    }
                }
                
            except Exception as e:
                logger.error(f"Error answering question for {application_id}: {str(e)}")
                return {
                    "success": False,
                    "error": str(e),
                    "answer": None,
                    "reference_data": {}
                }
    
    async def _build_student_profile(self, application_id: str) -> Optional[dict]:
        """
        Fetch and compile comprehensive student profile from database.
        
        Gathers:
        - Basic application info
        - School context and capabilities
        - Grade data with contextual rigor
        - Evaluations from other agents
        - Audit trail of interactions
        """
        try:
            # Get application via database helper to handle schema variants
            app = None
            try:
                app = self.db.get_application(application_id) if application_id else None
            except Exception:
                app = None

            if not app:
                return None
            
            # Get school context
            school_results = self.db.execute_query(
                """
                SELECT ap_count, honors_count, community_opportunity_score,
                       free_reduced_lunch_pct, total_students, demographics
                FROM student_school_context
                WHERE application_id = %s
                """,
                (application_id,)
            )
            school_context = school_results[0] if school_results else None
            
            # Get RAPUNZEL grades analysis
            rapunzel_results = self.db.execute_query(
                """
                SELECT contextual_rigor_index, grade_distribution, 
                       ap_performance, honors_performance
                FROM rapunzel_grades
                WHERE application_id = %s
                """,
                (application_id,)
            )
            rapunzel_grades = rapunzel_results[0] if rapunzel_results else None
            
            # Get AI evaluations
            evaluations = self.db.execute_query(
                """
                SELECT agent_name, evaluation_score, recommendation, 
                       key_insights
                FROM ai_evaluations
                WHERE application_id = %s
                ORDER BY created_at DESC
                """,
                (application_id,)
            )
            
            # Get recent agent interactions (audit trail)
            interactions = self.db.execute_query(
                """
                SELECT agent_name, step, action, output_json
                FROM agent_interactions
                WHERE application_id = %s
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (application_id,)
            )
            
            # Build comprehensive profile
            profile = {
                "name": f"{app.get('first_name', 'Unknown')} {app.get('last_name', '')}".strip(),
                "school": app.get('high_school', 'Unknown'),
                "state": app.get('state_code', 'Unknown'),
                "gpa": app.get('gpa'),
                "test_scores": app.get('test_scores'),
                "application_status": app.get('status', 'Pending'),
                "school_context": {
                    "ap_courses_available": school_context.get('ap_count', 0) if school_context else None,
                    "honors_courses_available": school_context.get('honors_count', 0) if school_context else None,
                    "community_opportunity_score": school_context.get('community_opportunity_score', 0) if school_context else None,
                    "free_reduced_lunch_pct": school_context.get('free_reduced_lunch_pct', 0) if school_context else None,
                    "total_students": school_context.get('total_students', 0) if school_context else None,
                } if school_context else {},
                "rigor_analysis": {
                    "contextual_rigor_index": rapunzel_grades.get('contextual_rigor_index') if rapunzel_grades else None,
                    "grade_distribution": rapunzel_grades.get('grade_distribution') if rapunzel_grades else None,
                    "ap_performance": rapunzel_grades.get('ap_performance') if rapunzel_grades else None,
                } if rapunzel_grades else {},
                "agent_evaluations": {
                    eval['agent_name']: {
                        "score": eval.get('evaluation_score'),
                        "recommendation": eval.get('recommendation'),
                        "insights": eval.get('key_insights')
                    }
                    for eval in evaluations
                } if evaluations else {},
                "_data_sources": [
                    "Application Data",
                    "School Context" if school_context else None,
                    "Grade Analysis" if rapunzel_grades else None,
                    "Agent Evaluations" if evaluations else None
                ]
            }
            
            # Filter out None values
            profile["_data_sources"] = [s for s in profile["_data_sources"] if s]
            
            return profile
            
        except Exception as e:
            logger.error(f"Error building student profile: {str(e)}")
            return None
    
    def _build_system_prompt(self, student_profile: dict) -> str:
        """
        Build system prompt with student context for GPT-4.
        
        Provides:
        - Role description
        - Student data overview
        - Analysis guidelines
        - Response guidelines
        """
        return f"""You are ARIEL, a helpful Q&A assistant for student evaluations.

You have access to comprehensive student data that has been analyzed by specialized evaluation agents:
- BELLE: Document and information extraction
- TIANA: Application and essay analysis
- RAPUNZEL: Academic performance and contextual rigor assessment
- NAVEEN: School enrichment and opportunity analysis
- MOANA: School context and fairness weighting
- MULAN: Recommendation letter analysis
- MILO: Pattern analysis and training data insights
- MERLIN: Comprehensive evaluation synthesis

Student: {student_profile['name']}
School: {student_profile['school']} ({student_profile.get('state', 'Unknown')})
Overall GPA: {student_profile.get('gpa', 'N/A')}
Application Status: {student_profile.get('application_status', 'Pending')}

School Context:
- AP Courses Available: {student_profile['school_context'].get('ap_courses_available', 'Unknown')}
- Honors Courses Available: {student_profile['school_context'].get('honors_courses_available', 'Unknown')}
- Community Opportunity Score: {student_profile['school_context'].get('community_opportunity_score', 'Unknown')}/100
- Free/Reduced Lunch %: {student_profile['school_context'].get('free_reduced_lunch_pct', 'Unknown')}%

Rigor Analysis:
- Contextual Rigor Index: {student_profile['rigor_analysis'].get('contextual_rigor_index', 'Pending')}/5

Your role:
1. Answer questions about the student based on the data provided
2. Cite specific data points when relevant (GPA, courses, school resources, etc.)
3. Explain academic rigor in context of school opportunities
4. Provide a balanced, fair assessment
5. Be specific and evidence-based
6. If you don't have information about a topic, say so clearly

Keep responses concise, clear, and focused on the specific question."""
    
    def _build_user_message(self, question: str, student_profile: dict) -> str:
        """Build the user message with question and context."""
        
        # Format agent evaluations for context
        eval_context = ""
        if student_profile.get('agent_evaluations'):
            eval_context = "\n\nAgent Evaluations:\n"
            for agent_name, eval_data in student_profile['agent_evaluations'].items():
                eval_context += f"- {agent_name}: Score {eval_data.get('score', 'N/A')}, "
                eval_context += f"Recommendation: {eval_data.get('recommendation', 'N/A')}\n"
        
        return f"""Question about student {student_profile['name']}:

{question}{eval_context}

Please provide a detailed, evidence-based response based on the student's data."""
    
    async def _log_qa_interaction(
        self,
        application_id: str,
        question: str,
        answer: str,
        student_profile: dict
    ) -> None:
        """Log Q&A interaction to database for audit trail."""
        try:
            output_json = json.dumps({
                "question": question,
                "answer": answer,
                "student": student_profile['name'],
                "time": datetime.utcnow().isoformat()
            })
            
            self.db.execute_non_query(
                """
                INSERT INTO agent_interactions 
                (application_id, agent_name, step, action, output_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    application_id,
                    "ARIEL",
                    8.5,  # Between synthesis (6) and reporting (7)
                    "qa_response",
                    output_json,
                    datetime.utcnow()
                )
            )
        except Exception as e:
            logger.error(f"Error logging Q&A interaction: {str(e)}")
