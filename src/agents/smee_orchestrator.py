"""Smee - The orchestrator agent that coordinates all other agents."""

from typing import Dict, List, Any, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.system_prompts import SMEE_ORCHESTRATOR_PROMPT


class SmeeOrchestrator(BaseAgent):
    """
    Smee is the top-level orchestrator agent that manages and coordinates 
    all other agents in the hiring evaluation pipeline.
    
    Responsibilities:
    - Route applications to appropriate agents
    - Manage the evaluation workflow
    - Synthesize results from specialized agents
    - Make final recommendations
    """
    
    def __init__(
        self,
        name: str,
        client: AzureOpenAI,
        model: str,
        db_connection: Optional[Any] = None
    ):
        """
        Initialize Smee orchestrator.
        
        Args:
            name: Agent name (typically "Smee")
            client: Azure OpenAI client
            model: Model deployment name
        """
        super().__init__(name, client)
        self.model = model
        self.db = db_connection
        self.agents: Dict[str, BaseAgent] = {}
        self.evaluation_results: Dict[str, Any] = {}
        self.workflow_state = "idle"  # idle, screening, evaluating, complete
    
    def register_agent(self, agent_id: str, agent: BaseAgent):
        """
        Register a specialized agent with Smee.
        
        Args:
            agent_id: Unique identifier for the agent (e.g., "grade_reader", "evaluator")
            agent: The agent instance to register
        """
        self.agents[agent_id] = agent
        print(f"✓ Smee registered agent: {agent_id} ({agent.name})")
    
    def get_registered_agents(self) -> Dict[str, str]:
        """Get list of registered agents."""
        return {agent_id: agent.name for agent_id, agent in self.agents.items()}
    
    async def coordinate_evaluation(
        self,
        application: Dict[str, Any],
        evaluation_steps: List[str]
    ) -> Dict[str, Any]:
        """
        Coordinate the evaluation of an application through multiple agents.
        
        Args:
            application: The application data to evaluate
            evaluation_steps: List of agent_ids to use in order
            
        Returns:
            Dictionary with results from all agents
        """
        self.workflow_state = "evaluating"
        applicant_name = application.get('ApplicantName', 'Unknown')
        
        print(f"\n{'='*60}")
        print(f"Smee: Starting evaluation for {applicant_name}")
        print(f"{'='*60}")
        
        evaluation_steps = self._ensure_merlin_last(evaluation_steps)

        self.evaluation_results = {
            'applicant_name': applicant_name,
            'application_id': application.get('ApplicationID'),
            'agents_used': evaluation_steps,
            'results': {}
        }

        merlin_run = False

        for step_idx, agent_id in enumerate(evaluation_steps, 1):
            if agent_id not in self.agents:
                print(f"⚠ Smee: Agent '{agent_id}' not found. Skipping.")
                continue
            
            agent = self.agents[agent_id]
            print(f"\n[Step {step_idx}] Smee: Delegating to {agent.name}...")
            
            try:
                # Call the agent's process or specialized method
                if hasattr(agent, 'evaluate_application'):
                    # For EvaluatorAgent
                    result = await agent.evaluate_application(application)
                elif hasattr(agent, 'parse_grades'):
                    # For RapunzelGradeReader
                    result = await agent.parse_grades(
                        application.get('ApplicationText', ''),
                        application.get('ApplicantName', '')
                    )
                elif hasattr(agent, 'parse_application'):
                    # For TianaApplicationReader
                    result = await agent.parse_application(application)
                elif hasattr(agent, 'parse_recommendation'):
                    # For MulanRecommendationReader
                    recommendation_text = application.get('RecommendationText') or application.get('ApplicationText', '')
                    result = await agent.parse_recommendation(
                        recommendation_text,
                        application.get('ApplicantName', ''),
                        application.get('ApplicationID')
                    )
                elif hasattr(agent, 'evaluate_student'):
                    # For MerlinStudentEvaluator
                    result = await agent.evaluate_student(
                        application,
                        self.evaluation_results['results']
                    )
                    merlin_run = True
                elif hasattr(agent, 'analyze_student_school_context'):
                    # For MoanaSchoolContext
                    # Get grade data from previous results if available
                    rapunzel_data = self.evaluation_results['results'].get('grade_reader')
                    result = await agent.analyze_student_school_context(
                        application=application,
                        transcript_text=application.get('ApplicationText', ''),
                        rapunzel_grades_data=rapunzel_data
                    )
                else:
                    # Generic process
                    result = await agent.process(
                        f"Evaluate this application:\n{application.get('ApplicationText', '')}"
                    )
                
                self.evaluation_results['results'][agent_id] = result
                self._write_audit(application, agent.name)
                print(f"✓ {agent.name} completed successfully")
                
            except Exception as e:
                print(f"✗ {agent.name} encountered an error: {str(e)}")
                self.evaluation_results['results'][agent_id] = {
                    'error': str(e),
                    'status': 'failed'
                }
                self._write_audit(application, agent.name)

        if not merlin_run and 'student_evaluator' in self.agents:
            await self._run_merlin_after_agents(application)
        
        self.workflow_state = "formatting"
        # Let Aurora format and summarize all results
        await self._run_aurora_after_merlin(application)
        
        self.workflow_state = "complete"
        print(f"\n{'='*60}")
        print(f"Smee: Evaluation complete for {applicant_name}")
        print(f"{'='*60}\n")
        
        return self.evaluation_results

    def _ensure_merlin_last(self, evaluation_steps: List[str]) -> List[str]:
        """Ensure Merlin runs after all other agents when present."""
        steps = [step for step in evaluation_steps if step != 'student_evaluator']
        if 'student_evaluator' in evaluation_steps:
            steps.append('student_evaluator')
        return steps

    async def _run_merlin_after_agents(self, application: Dict[str, Any]) -> None:
        """Run Merlin after all other agents and record its result."""
        merlin = self.agents.get('student_evaluator')
        if not merlin:
            return

        print("\n[Final] Smee: Delegating to Merlin Student Evaluator...")
        try:
            result = await merlin.evaluate_student(
                application,
                self.evaluation_results['results']
            )

            self.evaluation_results['results']['student_evaluator'] = result
            self._write_audit(application, merlin.name)
            print(f"✓ {merlin.name} completed successfully")
        except Exception as e:
            self.evaluation_results['results']['student_evaluator'] = {
                'error': str(e),
                'status': 'failed'
            }
            self._write_audit(application, merlin.name)

    async def _run_aurora_after_merlin(self, application: Dict[str, Any]) -> None:
        """
        Run Aurora after Merlin completes to format and summarize results for presentation.
        Aurora reads Merlin's evaluation and creates an elegant summary.
        """
        aurora = self.agents.get('aurora')
        if not aurora:
            print("⚠ Smee: Aurora agent not found. Skipping formatting.")
            return

        print("\n[Final] Smee: Delegating to Aurora for elegant presentation...")
        try:
            # Aurora formats all results based on Merlin's assessment
            merlin_result = self.evaluation_results['results'].get('student_evaluator', {})
            
            # Get all agent data for Aurora to work with
            aurora_summary = await aurora.format_results(
                application_data={
                    'name': application.get('ApplicantName'),
                    'email': application.get('Email'),
                    'applicationtext': application.get('ApplicationText')
                },
                agent_outputs={
                    'tiana': self.evaluation_results['results'].get('application_reader'),
                    'rapunzel': self.evaluation_results['results'].get('grade_reader'),
                    'moana': self.evaluation_results['results'].get('school_context'),
                    'mulan': self.evaluation_results['results'].get('recommendation_reader')
                },
                merlin_assessment=merlin_result
            )
            
            # Store Aurora's formatted summary
            self.evaluation_results['results']['aurora'] = aurora_summary
            self.evaluation_results['aurora_summary'] = aurora_summary.get('merlin_summary', {})
            self._write_audit(application, aurora.name)
            print(f"✓ {aurora.name} completed successfully - Results formatted for presentation")
            
        except Exception as e:
            print(f"✗ {aurora.name} encountered an error: {str(e)}")
            self.evaluation_results['results']['aurora'] = {
                'error': str(e),
                'status': 'failed'
            }
            self._write_audit(application, aurora.name)

    def determine_agents_for_upload(
        self,
        file_name: str,
        file_text: str,
        application: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Determine which agents should process an uploaded file."""
        application = application or {}
        categories = self._classify_upload(file_name, file_text)
        steps: List[str] = []

        if 'application' in categories:
            steps.append('application_reader')
        if 'transcript' in categories:
            steps.extend(['grade_reader', 'school_context'])
        if 'recommendation' in categories:
            steps.append('recommendation_reader')

        if self._should_add_merlin(categories, application):
            steps.append('student_evaluator')

        return steps

    async def process_uploaded_file(
        self,
        application: Dict[str, Any],
        file_name: str,
        file_text: str
    ) -> Dict[str, Any]:
        """Route and process a single uploaded file."""
        application = dict(application)
        application['ApplicationText'] = file_text
        application['OriginalFileName'] = file_name

        evaluation_steps = self.determine_agents_for_upload(
            file_name,
            file_text,
            application
        )

        return await self.coordinate_evaluation(application, evaluation_steps)

    def _classify_upload(self, file_name: str, file_text: str) -> List[str]:
        """Classify the uploaded file into one or more categories."""
        name = (file_name or '').lower()
        text = (file_text or '').lower()

        scores = {
            'application': 0,
            'transcript': 0,
            'recommendation': 0
        }

        transcript_keywords = [
            'transcript', 'gpa', 'credits', 'semester', 'course', 'grade',
            'honors', 'ap ', 'ib ', 'class rank'
        ]
        recommendation_keywords = [
            'recommendation', 'to whom it may concern', 'i recommend',
            'reference', 'counselor', 'teacher', 'principal'
        ]
        application_keywords = [
            'application', 'personal statement', 'essay', 'activities',
            'awards', 'leadership', 'goals', 'why', 'motivation'
        ]

        for keyword in transcript_keywords:
            if keyword in text or keyword in name:
                scores['transcript'] += 1
        for keyword in recommendation_keywords:
            if keyword in text or keyword in name:
                scores['recommendation'] += 1
        for keyword in application_keywords:
            if keyword in text or keyword in name:
                scores['application'] += 1

        max_score = max(scores.values())
        if max_score == 0:
            return ['application']

        categories = [k for k, v in scores.items() if v == max_score]
        return categories

    def _should_add_merlin(self, categories: List[str], application: Dict[str, Any]) -> bool:
        """Determine whether to include Merlin at the end of the flow."""
        if application.get('ForceFinalEvaluation'):
            return True
        if 'application' in categories and ('transcript' in categories or 'recommendation' in categories):
            return True
        return False

    def _write_audit(self, application: Dict[str, Any], agent_name: str) -> None:
        """Write an audit record for an agent action if DB is available."""
        if not self.db or not hasattr(self.db, 'save_agent_audit'):
            return

        application_id = application.get('ApplicationID')
        source_file_name = (
            application.get('OriginalFileName')
            or application.get('SourceFileName')
            or application.get('source_file_name')
        )

        if not application_id:
            return

        try:
            self.db.save_agent_audit(application_id, agent_name, source_file_name)
        except Exception as e:
            print(f"⚠ Smee audit write failed: {e}")
    
    async def _synthesize_results(
        self,
        application: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Synthesize results from all agents into a final recommendation.
        
        Args:
            application: The application data
            
        Returns:
            Final synthesized recommendation
        """
        # Build synthesis prompt from all agent results
        synthesis_prompt = self._build_synthesis_prompt(application)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are Smee, an expert at synthesizing evaluations from multiple specialist agents into clear, actionable recommendations."
                    },
                    {
                        "role": "user",
                        "content": synthesis_prompt
                    }
                ],
                max_completion_tokens=1500,
                temperature=1  # GPT-5.2 only supports default temperature
            )
            
            return {
                'status': 'success',
                'synthesis': response.choices[0].message.content,
                'synthesized_by': self.name
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'synthesized_by': self.name
            }
    
    def _build_synthesis_prompt(self, application: Dict[str, Any]) -> str:
        """Build the synthesis prompt from all agent results."""
        prompt_parts = [
            f"I've had multiple specialist agents evaluate an application for {application.get('ApplicantName', 'a candidate')}.",
            "",
            "# EVALUATIONS FROM SPECIALIST AGENTS:"
        ]
        
        for agent_id, result in self.evaluation_results.get('results', {}).items():
            if isinstance(result, dict) and 'error' not in result:
                prompt_parts.append(f"\n## {agent_id.upper()} Results:")
                
                # Format different types of results
                if 'grades' in result:
                    prompt_parts.append(f"**Parsed Grades:** {result['grades']}")
                if 'academic_strength' in result:
                    prompt_parts.append(f"**Academic Assessment:** {result['academic_strength']}")
                if 'transcript_quality' in result:
                    prompt_parts.append(f"**Transcript Quality:** {result['transcript_quality']}")
                if 'overall_score' in result:
                    prompt_parts.append(f"**Overall Score:** {result['overall_score']}/100")
                if 'recommendation' in result:
                    prompt_parts.append(f"**Agent Recommendation:** {result['recommendation']}")
                if 'strengths' in result:
                    prompt_parts.append(f"**Key Strengths:** {result['strengths']}")
                if 'summary' in result:
                    prompt_parts.append(f"**Summary:** {result['summary']}")
                if 'essay_summary' in result:
                    prompt_parts.append(f"**Essay Summary:** {result['essay_summary']}")
                if 'readiness_score' in result:
                    prompt_parts.append(f"**Readiness Score:** {result['readiness_score']}/100")
                if 'endorsement_strength' in result:
                    prompt_parts.append(f"**Endorsement Strength:** {result['endorsement_strength']}/100")
                if 'specificity_score' in result:
                    prompt_parts.append(f"**Recommendation Specificity:** {result['specificity_score']}/100")
        
        prompt_parts.extend([
            "",
            "# YOUR TASK:",
            "1. Synthesize all the specialist evaluations into a coherent overall assessment",
            "2. Identify patterns or conflicts in the evaluations",
            "3. Provide a clear, final recommendation with reasoning",
            "4. Highlight the most important factors from each specialist",
            "",
            "Format your response as a clear, executive summary suitable for hiring team review."
        ])
        
        return "\n".join(prompt_parts)
    
    async def process(self, message: str) -> str:
        """
        Process a message (for general conversation).
        
        Args:
            message: The input message
            
        Returns:
            Response from Smee
        """
        self.add_to_history("user", message)
        
        messages = [
            {
                "role": "system",
                "content": "You are Smee, an orchestrator agent coordinating a multi-agent hiring evaluation system. You are helpful, clear, and precise."
            }
        ] + self.conversation_history
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=1000,
                temperature=1  # GPT-5.2 only supports default temperature
            )
            
            assistant_message = response.choices[0].message.content
            self.add_to_history("assistant", assistant_message)
            return assistant_message
            
        except Exception as e:
            error_message = f"Smee encountered an error: {str(e)}"
            print(error_message)
            return error_message
    
    def get_workflow_status(self) -> Dict[str, Any]:
        """Get current workflow status."""
        return {
            'orchestrator': self.name,
            'state': self.workflow_state,
            'registered_agents': self.get_registered_agents(),
            'last_evaluation': self.evaluation_results if self.evaluation_results else None
        }
    
    def check_application_requirements(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check what information is available vs. what's needed for each agent.
        
        Args:
            application: The application data to check
            
        Returns:
            Dictionary with status for each agent and missing information
        """
        app_text = application.get('ApplicationText', '') or application.get('applicationtext', '')
        app_id = application.get('ApplicationID') or application.get('applicationid')
        
        # Check database for additional information if db connection exists
        has_tiana_data = False
        has_rapunzel_data = False
        has_moana_data = False
        has_mulan_data = False
        
        if self.db and app_id:
            try:
                # Check for existing agent data
                tiana_check = self.db.execute_query(
                    "SELECT COUNT(*) as count FROM TianaApplications WHERE ApplicationID = %s",
                    (app_id,)
                )
                has_tiana_data = tiana_check[0]['count'] > 0 if tiana_check else False
                
                rapunzel_check = self.db.execute_query(
                    "SELECT COUNT(*) as count FROM AIEvaluations WHERE ApplicationID = %s AND AgentName = 'Rapunzel'",
                    (app_id,)
                )
                has_rapunzel_data = rapunzel_check[0]['count'] > 0 if rapunzel_check else False
                
                moana_check = self.db.execute_query(
                    "SELECT COUNT(*) as count FROM StudentSchoolContext WHERE ApplicationID = %s",
                    (app_id,)
                )
                has_moana_data = moana_check[0]['count'] > 0 if moana_check else False
                
                mulan_check = self.db.execute_query(
                    "SELECT COUNT(*) as count FROM MulanRecommendations WHERE ApplicationID = %s",
                    (app_id,)
                )
                has_mulan_data = mulan_check[0]['count'] > 0 if mulan_check else False
            except Exception as e:
                print(f"Warning: Could not check database for existing agent data: {e}")
        
        # Analyze text content
        text_lower = app_text.lower()
        has_essay = 'essay' in text_lower or 'personal statement' in text_lower or len(app_text) > 500
        has_grades = any(keyword in text_lower for keyword in ['gpa', 'grade', 'transcript', 'course', 'a-', 'b+'])
        has_school_info = any(keyword in text_lower for keyword in ['high school', 'school name', 'school district'])
        has_recommendations = any(keyword in text_lower for keyword in ['recommendation', 'recommender', 'letter of', 'reference'])
        
        # Define agent requirements
        agents_status = {
            'application_reader': {
                'agent_name': '👸 Tiana - Application Reader',
                'required': ['Application essay or personal statement'],
                'status': 'ready' if (has_essay or has_tiana_data) else 'missing_info',
                'can_process': has_essay or has_tiana_data,
                'missing': [] if (has_essay or has_tiana_data) else ['Application essay, personal statement, or background information'],
                'data_source': 'already_processed' if has_tiana_data else 'from_uploaded_file' if has_essay else None
            },
            'grade_reader': {
                'agent_name': '💇 Rapunzel - Grade Reader',
                'required': ['Transcript with grades and GPA'],
                'status': 'ready' if (has_grades or has_rapunzel_data) else 'missing_info',
                'can_process': has_grades or has_rapunzel_data,
                'missing': [] if (has_grades or has_rapunzel_data) else ['Transcript file with courses and grades'],
                'data_source': 'already_processed' if has_rapunzel_data else 'from_uploaded_file' if has_grades else None
            },
            'school_context': {
                'agent_name': '🌊 Moana - School Context',
                'required': ['School name and location information'],
                'status': 'ready' if (has_school_info or has_grades or has_moana_data) else 'missing_info',
                'can_process': has_school_info or has_grades or has_moana_data,
                'missing': [] if (has_school_info or has_grades or has_moana_data) else ['School information (usually from transcript header)'],
                'data_source': 'already_processed' if has_moana_data else 'from_uploaded_file' if (has_school_info or has_grades) else None
            },
            'recommendation_reader': {
                'agent_name': '🗡️ Mulan - Recommendation Reader',
                'required': ['Recommendation letters or references'],
                'status': 'ready' if (has_recommendations or has_mulan_data) else 'missing_info',
                'can_process': has_recommendations or has_mulan_data,
                'missing': [] if (has_recommendations or has_mulan_data) else ['Teacher/counselor recommendation letters'],
                'data_source': 'already_processed' if has_mulan_data else 'from_uploaded_file' if has_recommendations else None
            },
            'student_evaluator': {
                'agent_name': '🧙 Merlin - Final Evaluator',
                'required': ['Results from other agents'],
                'status': 'waiting' if not (has_tiana_data or has_rapunzel_data or has_moana_data or has_mulan_data) else 'ready',
                'can_process': True,  # Merlin can always run, but works best with other agent data
                'missing': [],
                'data_source': 'synthesizes_all_agents'
            }
        }
        
        # Calculate overall readiness
        ready_agents = sum(1 for agent in agents_status.values() if agent['status'] == 'ready')
        total_agents = len(agents_status)
        
        # Collect all missing items
        all_missing = []
        for agent_id, status in agents_status.items():
            if status['missing']:
                all_missing.extend(status['missing'])
        
        return {
            'application_id': app_id,
            'agents': agents_status,
            'readiness': {
                'ready_count': ready_agents,
                'total_count': total_agents,
                'percentage': int((ready_agents / total_agents) * 100),
                'overall_status': 'ready' if ready_agents == total_agents else 'partial' if ready_agents > 0 else 'not_ready'
            },
            'missing_information': list(set(all_missing)),  # Remove duplicates
            'can_proceed': ready_agents >= 2,  # Need at least 2 agents ready to proceed
            'recommendation': self._get_upload_recommendation(all_missing)
        }
    
    def _get_upload_recommendation(self, missing_items: List[str]) -> str:
        """Generate a recommendation for what to upload next."""
        if not missing_items:
            return "All required information is available. Ready to process!"
        
        # Prioritize missing items
        if any('Transcript' in item for item in missing_items):
            return "📋 Upload transcript file next - this will help Rapunzel analyze grades and Moana identify the school."
        elif any('recommendation' in item.lower() for item in missing_items):
            return "📝 Upload recommendation letters next - this will help Mulan assess endorsements."
        elif any('essay' in item.lower() or 'statement' in item.lower() for item in missing_items):
            return "✍️ Upload application essay or personal statement next - Tiana needs this to analyze the student's story."
        else:
            return f"Upload missing documents: {', '.join(missing_items[:2])}"

