"""Smee - The orchestrator agent that coordinates all other agents."""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.system_prompts import SMEE_ORCHESTRATOR_PROMPT
from src.agents.agent_requirements import AgentRequirements
from src.agents.belle_document_analyzer import BelleDocumentAnalyzer

logger = logging.getLogger(__name__)


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
        logger.info(f"Smee registered agent: {agent_id} ({agent.name})")
    
    def get_registered_agents(self) -> Dict[str, str]:
        """Get list of registered agents."""
        return {agent_id: agent.name for agent_id, agent in self.agents.items()}
    
    async def coordinate_evaluation(
        self,
        application: Dict[str, Any],
        evaluation_steps: List[str],
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Coordinate the evaluation of an application through multiple agents.
        
        Args:
            application: The application data to evaluate
            evaluation_steps: List of agent_ids to use in order
            progress_callback: Optional callback function to report progress (called with dict updates)
            
        Returns:
            Dictionary with results from all agents
        """
        import uuid
        
        self.workflow_state = "evaluating"
        applicant_name = application.get('applicant_name') or application.get('ApplicantName', 'Unknown')
        application_id = application.get('application_id') or application.get('ApplicationID')
        
        # Generate unique student ID if not already present
        if not application.get('student_id'):
            application['student_id'] = f"student_{uuid.uuid4().hex[:16]}"
        
        student_id = application.get('student_id')
        self._progress_callback = progress_callback
        self._current_application_id = application_id
        self._current_student_id = student_id
        self._current_applicant_name = applicant_name
        
        logger.info(f"Starting evaluation for {applicant_name} (ID: {student_id})", extra={'application_id': application_id, 'student_id': student_id})
        
        # ===== ASK AGENTS WHAT THEY NEED =====
        # Before determining missing fields, ask each agent in the pipeline what they need
        logger.info(f"🎩 Smee asking agents what they need for {applicant_name}...")
        
        # Debug: Log all available fields in application
        available_fields = list(application.keys()) if isinstance(application, dict) else []
        logger.debug(f"Available fields in application: {available_fields}")
        
        missing_fields, agent_questions = self._compute_missing_fields(application, evaluation_steps)
        
        # ===== CHECK MISSING INFORMATION =====
        # Determine what information is required for the evaluation pipeline
        if missing_fields:
            # Ask Belle to fill missing details before pausing
            if self._attempt_belle_fill(application, missing_fields):
                missing_fields, agent_questions = self._compute_missing_fields(application, evaluation_steps)

        if missing_fields:
            logger.info(f"Evaluation paused for {applicant_name}: Agents need {len(missing_fields)} items: {missing_fields}")
            
            # Save missing fields to database for UI to display
            if self.db and application_id:
                try:
                    self.db.set_missing_fields(application_id, missing_fields)
                except Exception as e:
                    logger.warning(f"Could not save missing fields: {e}")
            
            # Report pause status with agent questions
            self._report_progress({
                'type': 'evaluation_paused',
                'agent': 'Smee Orchestrator',
                'agent_id': 'smee',
                'status': 'asking_for_info',
                'applicant': applicant_name,
                'student_id': student_id,
                'missing_fields': missing_fields,
                'agent_questions': agent_questions,
                'message': f'❓ Agents need {len(missing_fields)} items to proceed'
            })

            for agent_info in agent_questions:
                field_name = agent_info.get('field_name')
                if field_name not in missing_fields:
                    continue
                questions = agent_info.get('questions') or []
                waiting_message = questions[0] if questions else f"Waiting for {field_name}"
                self._report_progress({
                    'type': 'agent_progress',
                    'agent': agent_info.get('agent_name'),
                    'agent_id': agent_info.get('agent_id'),
                    'status': 'blocked',
                    'applicant': applicant_name,
                    'student_id': student_id,
                    'waiting_for': field_name,
                    'message': waiting_message
                })
            
            return {
                'status': 'paused',
                'applicant_name': applicant_name,
                'application_id': application_id,
                'student_id': student_id,
                'missing_fields': missing_fields,
                'agent_questions': agent_questions,
                'message': 'Information needed before evaluation can proceed',
                'detailed_message': 'The following agents need information:'
            }
        
        # Report Smee starting orchestration
        self._report_progress({
            'type': 'agent_progress',
            'agent': 'Smee Orchestrator',
            'agent_id': 'smee',
            'status': 'starting',
            'applicant': applicant_name,
            'student_id': student_id,
            'message': '🎩 Smee is coordinating the evaluation process...'
        })
        
        evaluation_steps = self._ensure_merlin_last(evaluation_steps)

        self.evaluation_results = {
            'applicant_name': applicant_name,
            'application_id': application_id,
            'student_id': student_id,
            'agents_used': evaluation_steps,
            'results': {}
        }

        merlin_run = False
        failed_agents = []
        required_agents = ['application_reader', 'grade_reader', 'recommendation_reader', 'school_context']

        def is_success(result: Optional[Dict[str, Any]]) -> bool:
            if not isinstance(result, dict):
                return False
            if 'status' not in result:
                return True
            return result.get('status') in {'success', 'completed'}

        for step_idx, agent_id in enumerate(evaluation_steps, 1):
            if agent_id not in self.agents:
                logger.warning(f"Agent '{agent_id}' not found. Skipping.")
                continue
            
            agent = self.agents[agent_id]
            logger.debug(f"[Step {step_idx}] Delegating to {agent.name}...")
            
            # Report agent starting
            self._report_progress({
                'type': 'agent_progress',
                'agent': agent.name,
                'agent_id': agent_id,
                'status': 'starting',
                'step': step_idx,
                'total_steps': len(evaluation_steps),
                'applicant': applicant_name
            })
            
            try:
                # Call the agent's process or specialized method
                if agent_id == 'student_evaluator' and failed_agents:
                    logger.warning(f"Skipping Merlin due to upstream failures: {failed_agents}")
                    self._report_progress({
                        'type': 'agent_progress',
                        'agent': agent.name,
                        'agent_id': agent_id,
                        'status': 'blocked',
                        'applicant': applicant_name,
                        'message': 'Blocked until required agents complete'
                    })
                    continue

                if hasattr(agent, 'evaluate_application'):
                    # For EvaluatorAgent
                    result = await agent.evaluate_application(application)
                elif hasattr(agent, 'parse_grades'):
                    # For RapunzelGradeReader
                    transcript_text = application.get('transcript_text') or application.get('TranscriptText') or application.get('application_text') or application.get('ApplicationText', '')
                    result = await agent.parse_grades(
                        transcript_text,
                        application.get('applicant_name') or application.get('ApplicantName', '')
                    )
                elif hasattr(agent, 'parse_application'):
                    # For TianaApplicationReader
                    result = await agent.parse_application(application)
                elif hasattr(agent, 'parse_recommendation'):
                    # For MulanRecommendationReader
                    recommendation_text = application.get('recommendation_text') or application.get('RecommendationText') or application.get('application_text') or application.get('ApplicationText', '')
                    result = await agent.parse_recommendation(
                        recommendation_text,
                        application.get('applicant_name') or application.get('ApplicantName', ''),
                        application_id
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
                    transcript_text = application.get('transcript_text') or application.get('TranscriptText') or application.get('application_text') or application.get('ApplicationText', '')
                    result = await agent.analyze_student_school_context(
                        application=application,
                        transcript_text=transcript_text,
                        rapunzel_grades_data=rapunzel_data
                    )
                elif hasattr(agent, 'analyze_training_insights'):
                    # For MiloDataScientist
                    result = await agent.analyze_training_insights()
                else:
                    # Generic process
                    result = await agent.process(
                        f"Evaluate this application:\n{application.get('application_text') or application.get('ApplicationText', '')}"
                    )
                
                self.evaluation_results['results'][agent_id] = result
                self._write_audit(application, agent.name)

                if agent_id in required_agents and not is_success(result):
                    failed_agents.append(agent_id)
                
                # Save agent results to database
                if self.db and application_id:
                    try:
                        import json
                        if agent_id == 'grade_reader':
                            # Save Rapunzel grades and remove from missing fields
                            self.db.save_rapunzel_grades(
                                application_id=application_id,
                                agent_name=agent.name,
                                gpa=result.get('gpa'),
                                academic_strength=result.get('academic_strength'),
                                course_levels=result.get('course_levels'),
                                transcript_quality=result.get('transcript_quality'),
                                notable_patterns=result.get('notable_patterns'),
                                confidence_level=result.get('confidence_level'),
                                summary=result.get('summary'),
                                parsed_json=json.dumps(result) if result else None
                            )
                            self.db.remove_missing_field(application_id, 'transcript')
                            
                        elif agent_id == 'school_context':
                            # Save Moana school context and remove from missing fields
                            moana_results = result.get('opportunity_scores', {})
                            self.db.save_moana_school_context(
                                application_id=application_id,
                                agent_name=agent.name,
                                school_name=result.get('school', {}).get('name'),
                                program_access_score=moana_results.get('program_access_score'),
                                program_participation_score=moana_results.get('program_participation_score'),
                                relative_advantage_score=moana_results.get('relative_advantage_score'),
                                ap_courses_available=result.get('school_profile', {}).get('ap_courses_available'),
                                ap_courses_taken=result.get('program_participation', {}).get('ap_courses_taken'),
                                contextual_summary=result.get('contextual_summary'),
                                parsed_json=json.dumps(result) if result else None
                            )
                            self.db.remove_missing_field(application_id, 'school_context')
                            
                        elif agent_id == 'recommendation_reader':
                            # Recommendation completed
                            self.db.remove_missing_field(application_id, 'letters_of_recommendation')
                            
                        elif agent_id == 'student_evaluator':
                            # Evaluation completed - clear all remaining fields
                            self.db.set_missing_fields(application_id, [])
                            
                    except Exception as save_err:
                        logger.warning(f"Could not save {agent_id} results to database: {str(save_err)}")
                
                # Report agent success
                self._report_progress({
                    'type': 'agent_progress',
                    'agent': agent.name,
                    'agent_id': agent_id,
                    'status': 'completed',
                    'step': step_idx,
                    'total_steps': len(evaluation_steps),
                    'applicant': applicant_name,
                    'message': f'✓ {agent.name} completed successfully'
                })
                logger.info(f"{agent.name} completed successfully")
                
            except Exception as e:
                logger.error(f"{agent.name} encountered an error: {str(e)}", exc_info=True)
                
                # Report agent error
                self._report_progress({
                    'type': 'agent_progress',
                    'agent': agent.name,
                    'agent_id': agent_id,
                    'status': 'failed',
                    'step': step_idx,
                    'total_steps': len(evaluation_steps),
                    'applicant': applicant_name,
                    'error': str(e)
                })
                
                self.evaluation_results['results'][agent_id] = {
                    'error': str(e),
                    'status': 'failed'
                }
                self._write_audit(application, agent.name)

        if not merlin_run and 'student_evaluator' in self.agents:
            if failed_agents:
                self._report_progress({
                    'type': 'evaluation_blocked',
                    'agent': 'Smee Orchestrator',
                    'agent_id': 'smee',
                    'status': 'blocked',
                    'applicant': applicant_name,
                    'message': f"Blocked until required agents complete: {', '.join(failed_agents)}"
                })
                return self.evaluation_results
            await self._run_merlin_after_agents(application)
        
        if failed_agents:
            return self.evaluation_results

        self.workflow_state = "formatting"
        # Let Aurora format and summarize all results
        logger.info(f"Running Aurora to format results for {applicant_name}")
        await self._run_aurora_after_merlin(application)
        
        self.workflow_state = "generating_document"
        # Let Fairy Godmother create the final document (ALWAYS LAST)
        logger.info(f"Running Fairy Godmother to generate final document for {applicant_name}")
        await self._run_fairy_godmother_document_generation(application)
        
        self.workflow_state = "complete"
        logger.info(f"✅ Complete evaluation for {applicant_name} - All agents finished")
        
        # Report final completion
        self._report_progress({
            'type': 'evaluation_complete',
            'applicant': applicant_name,
            'message': f'✅ All agents completed for {applicant_name}',
            'agents_completed': list(self.evaluation_results['results'].keys()),
            'document_generated': 'fairy_godmother' in self.evaluation_results['results']
        })
        
        return self.evaluation_results

    async def _determine_missing_fields(
        self,
        application: Dict[str, Any],
        evaluation_steps: List[str]
    ) -> List[str]:
        """
        Determine what information/documents are missing for evaluation.
        
        Returns:
            List of missing field names needed before agents can proceed
        """
        missing = []
        applicant_name = application.get('applicant_name', '')
        
        # Check what information we have available
        has_application_text = bool(application.get('application_text') or application.get('ApplicationText'))
        has_transcript = bool(application.get('transcript_text') or application.get('TranscriptText'))
        has_recommendations = bool(application.get('recommendation_text') or application.get('RecommendationText'))
        
        # Determine what's needed based on evaluation pipeline
        if 'application_reader' in evaluation_steps and not has_application_text:
            missing.append('application_essay')
        
        if 'grade_reader' in evaluation_steps and not has_transcript:
            missing.append('transcript')
        
        if 'school_context' in evaluation_steps and not has_transcript:
            missing.append('transcript')
        
        if 'recommendation_reader' in evaluation_steps and not has_recommendations:
            missing.append('letters_of_recommendation')
        
        if missing:
            logger.info(f"🎩 Smee determined {applicant_name} is missing: {missing}")
        
        return missing

    def _compute_missing_fields(
        self,
        application: Dict[str, Any],
        evaluation_steps: List[str]
    ) -> (List[str], List[Dict[str, Any]]):
        lower_keys = {str(key).lower(): key for key in (application or {}).keys()}

        def field_has_value(field_name: str) -> bool:
            variants = [field_name, field_name.replace('_', '')]
            for variant in variants:
                key = lower_keys.get(variant.lower())
                if key is not None and application.get(key):
                    return True
            return False

        agent_questions = AgentRequirements.get_all_questions(evaluation_steps)
        consolidated_missing = []

        for agent_info in agent_questions:
            agent_id = agent_info['agent_id']
            field_name = agent_info['field_name']

            requirements = AgentRequirements.get_agent_requirements(agent_id)
            required_fields = requirements.get('required_fields', [])

            logger.debug(f"Checking {agent_id}: needs {required_fields}")

            field_status = {}
            for field in required_fields:
                lowercase_val = bool(application.get(field))
                titlecase_val = bool(application.get(field.title()))
                variant_val = field_has_value(field)
                field_status[field] = {
                    'lowercase': lowercase_val,
                    'titlecase': titlecase_val,
                    'has': lowercase_val or titlecase_val or variant_val
                }
                logger.debug(f"  Field '{field}': lowercase={lowercase_val}, titlecase={titlecase_val}")

            has_required = all(field_status[f]['has'] for f in required_fields)

            if not has_required:
                consolidated_missing.append(field_name)
                logger.info(f"  ❓ {agent_info['agent_name']} needs: {', '.join(agent_info['questions'][0:1])}")
                logger.debug(f"     Field status: {field_status}")

        return consolidated_missing, agent_questions

    def _attempt_belle_fill(self, application: Dict[str, Any], missing_fields: List[str]) -> bool:
        if application.get('_belle_attempted'):
            return False

        text = application.get('application_text') or application.get('ApplicationText')
        if not text:
            return False

        try:
            self._report_progress({
                'type': 'agent_progress',
                'agent': 'Belle',
                'agent_id': 'belle',
                'status': 'starting',
                'message': '📖 Belle is scanning for missing details'
            })

            belle = BelleDocumentAnalyzer(client=self.client, model=self.model)
            analysis = belle.analyze_document(text, application.get('original_file_name') or '')
            agent_fields = analysis.get('agent_fields', {})
            student_info = analysis.get('student_info', {})

            for key, value in agent_fields.items():
                if value and not application.get(key):
                    application[key] = value

            if student_info.get('school_name') and not application.get('school_name'):
                application['school_name'] = student_info.get('school_name')

            if student_info.get('name') and not application.get('applicant_name'):
                application['applicant_name'] = student_info.get('name')

            application['_belle_attempted'] = True

            self._report_progress({
                'type': 'agent_progress',
                'agent': 'Belle',
                'agent_id': 'belle',
                'status': 'completed',
                'message': '📖 Belle finished scanning'
            })

            return True
        except Exception as e:
            logger.warning(f"Belle fill attempt failed: {e}")
            application['_belle_attempted'] = True
            self._report_progress({
                'type': 'agent_progress',
                'agent': 'Belle',
                'agent_id': 'belle',
                'status': 'failed',
                'error': str(e)
            })
            return False

    def _ensure_merlin_last(self, evaluation_steps: List[str]) -> List[str]:
        """Ensure Merlin runs after all other agents when present."""
        steps = [step for step in evaluation_steps if step != 'student_evaluator']
        if 'student_evaluator' in evaluation_steps:
            steps.append('student_evaluator')
        return steps
    
    def _report_progress(self, update: Dict[str, Any]) -> None:
        """Report progress via callback if registered."""
        if update.get('application_id') is None and getattr(self, '_current_application_id', None):
            update['application_id'] = self._current_application_id
        if update.get('student_id') is None and getattr(self, '_current_student_id', None):
            update['student_id'] = self._current_student_id
        if update.get('applicant') is None and getattr(self, '_current_applicant_name', None):
            update['applicant'] = self._current_applicant_name
        if hasattr(self, '_progress_callback') and self._progress_callback:
            try:
                self._progress_callback(update)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    async def _run_merlin_after_agents(self, application: Dict[str, Any]) -> None:
        """Run Merlin after all other agents and record its result with heartbeat check-ins."""
        merlin = self.agents.get('student_evaluator')
        if not merlin:
            return

        logger.info("Delegating to Merlin Student Evaluator for final assessment")
        
        # Create the Merlin evaluation task
        merlin_task = asyncio.create_task(
            merlin.evaluate_student(
                application,
                self.evaluation_results['results']
            )
        )
        
        # Create and run heartbeat task concurrently
        heartbeat_task = asyncio.create_task(self._heartbeat_during_merlin())
        
        try:
            # Wait for Merlin to complete, heartbeat runs in background
            result = await merlin_task
            
            self.evaluation_results['results']['student_evaluator'] = result
            self._write_audit(application, merlin.name)
            logger.info(f"{merlin.name} completed successfully")
            
        except Exception as e:
            self.evaluation_results['results']['student_evaluator'] = {
                'error': str(e),
                'status': 'failed'
            }
            self._write_audit(application, merlin.name)
        finally:
            # Cancel the heartbeat task
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_during_merlin(self) -> None:
        """Print periodic check-in messages while Merlin is evaluating."""
        check_in_interval = 120  # Check in every 2 minutes
        check_in_count = 0
        
        try:
            while True:
                await asyncio.sleep(check_in_interval)
                check_in_count += 1
                elapsed_minutes = check_in_count * (check_in_interval // 60)
                logger.info(f" Merlin is still working hard ({elapsed_minutes}+ minutes elapsed, evaluating all specialist reports...)")
        except asyncio.CancelledError:
            pass

    async def _run_aurora_after_merlin(self, application: Dict[str, Any]) -> None:
        """
        Run Aurora after Merlin completes to format and summarize results for presentation.
        Aurora reads Merlin's evaluation and creates an elegant summary.
        """
        aurora = self.agents.get('aurora')
        if not aurora:
            logger.warning("Aurora agent not found. Skipping formatting.")
            return

        applicant_name = application.get('applicant_name') or application.get('ApplicantName', 'Unknown')
        
        # Report Aurora starting
        self._report_progress({
            'type': 'agent_progress',
            'agent': 'Aurora',
            'agent_id': 'aurora',
            'status': 'starting',
            'applicant': applicant_name,
            'message': 'Aurora is creating elegant summary...'
        })
        
        logger.info("Delegating to Aurora for elegant presentation...")
        try:
            # Aurora formats all results based on Merlin's assessment
            merlin_result = self.evaluation_results['results'].get('student_evaluator', {})
            
            # Get all agent data for Aurora to work with
            aurora_summary = await aurora.format_results(
                application_data={
                    'name': application.get('applicant_name') or application.get('ApplicantName'),
                    'email': application.get('email') or application.get('Email'),
                    'applicationtext': application.get('application_text') or application.get('ApplicationText')
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
            
            # Save Aurora evaluation to database
            application_id = application.get('application_id') or application.get('ApplicationID')
            if self.db and application_id:
                try:
                    agents_completed = ','.join(self.evaluation_results['results'].keys())
                    self.db.save_aurora_evaluation(
                        application_id=application_id,
                        formatted_evaluation=aurora_summary,
                        merlin_score=merlin_result.get('overall_score'),
                        merlin_recommendation=merlin_result.get('recommendation'),
                        agents_completed=agents_completed
                    )
                except Exception as save_err:
                    logger.warning(f" {str(save_err)}")
            
            self._write_audit(application, aurora.name)
            logger.info(f"{aurora.name} completed successfully - Results formatted for presentation")
            
            # Report Aurora success
            self._report_progress({
                'type': 'agent_progress',
                'agent': 'Aurora',
                'agent_id': 'aurora',
                'status': 'completed',
                'applicant': applicant_name,
                'message': '✓ Aurora completed - Final summary ready'
            })
            
        except Exception as e:
            logger.error(f"Aurora error: {str(e)}")
            self.evaluation_results['results']['aurora'] = {
                'error': str(e),
                'status': 'failed'
            }
            self._write_audit(application, aurora.name)
            
            # Report Aurora error
            self._report_progress({
                'type': 'agent_progress',
                'agent': 'Aurora',
                'agent_id': 'aurora',
                'status': 'failed',
                'applicant': applicant_name,
                'error': str(e)
            })

    async def _run_fairy_godmother_document_generation(self, application: Dict[str, Any]) -> None:
        """
        Run Fairy Godmother to generate the final evaluation document.
        This ALWAYS runs last after all other agents complete.
        """
        fairy_godmother = self.agents.get('fairy_godmother')
        if not fairy_godmother:
            logger.warning("Fairy Godmother agent not found. Skipping document generation.")
            return

        applicant_name = application.get('applicant_name') or application.get('ApplicantName', 'Unknown')
        application_id = application.get('application_id') or application.get('ApplicationID')
        
        # Generate student ID for storage
        student_id = f"student_{application_id}"
        
        # Report Fairy Godmother starting
        self._report_progress({
            'type': 'agent_progress',
            'agent': 'Fairy Godmother',
            'agent_id': 'fairy_godmother',
            'status': 'starting',
            'applicant': applicant_name,
            'message': '🪄 Fairy Godmother is creating evaluation document...'
        })
        
        logger.info("🪄 Delegating to Fairy Godmother for document generation...")
        try:
            # Generate document with all results
            result = await fairy_godmother.generate_evaluation_document(
                application=application,
                agent_results=self.evaluation_results['results'],
                student_id=student_id
            )
            
            self.evaluation_results['results']['fairy_godmother'] = result
            self.evaluation_results['document_path'] = result.get('document_path')
            self.evaluation_results['document_url'] = result.get('document_url')
            
            self._write_audit(application, fairy_godmother.name)
            logger.info(f"{fairy_godmother.name} completed successfully - Document created")
            
            # Report Fairy Godmother success
            self._report_progress({
                'type': 'agent_progress',
                'agent': 'Fairy Godmother',
                'agent_id': 'fairy_godmother',
                'status': 'completed',
                'applicant': applicant_name,
                'message': '✨ Fairy Godmother completed - Document ready for download',
                'document_path': result.get('document_path')
            })
            
        except Exception as e:
            logger.error(f"Fairy Godmother error: {str(e)}", exc_info=True)
            self.evaluation_results['results']['fairy_godmother'] = {
                'error': str(e),
                'status': 'failed'
            }
            self._write_audit(application, fairy_godmother.name)
            
            # Report Fairy Godmother error
            self._report_progress({
                'type': 'agent_progress',
                'agent': 'Fairy Godmother',
                'agent_id': 'fairy_godmother',
                'status': 'failed',
                'applicant': applicant_name,
                'error': str(e)
            })

    def determine_agents_for_upload(
        self,
        file_name: str,
        file_text: str,
        application: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Determine which agents should process an uploaded file."""
        _ = file_name
        _ = file_text
        _ = application
        return [
            'application_reader',
            'grade_reader',
            'school_context',
            'recommendation_reader',
            'data_scientist',
            'student_evaluator'
        ]

    async def process_uploaded_file(
        self,
        application: Dict[str, Any],
        file_name: str,
        file_text: str
    ) -> Dict[str, Any]:
        """Route and process a single uploaded file."""
        application = dict(application)
        application['application_text'] = file_text
        application['transcript_text'] = file_text
        application['recommendation_text'] = file_text
        application['original_file_name'] = file_name

        try:
            belle = BelleDocumentAnalyzer(client=self.client, model=self.model)
            analysis = belle.analyze_document(file_text, file_name)
            agent_fields = analysis.get('agent_fields', {})
            for key, value in agent_fields.items():
                if value is not None:
                    application[key] = value
        except Exception as exc:
            logger.warning(f"Belle upload analysis failed: {exc}")

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

        application_id = application.get('application_id') or application.get('ApplicationID')
        source_file_name = (
            application.get('original_file_name')
            or application.get('OriginalFileName')
            or application.get('source_file_name')
            or application.get('SourceFileName')
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
            response = self._create_chat_completion(
                operation="smee.synthesize_results",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": SMEE_ORCHESTRATOR_PROMPT
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
            f"I've had multiple specialist agents evaluate an application for {application.get('applicant_name') or application.get('ApplicantName', 'a candidate')}.",
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
                "content": SMEE_ORCHESTRATOR_PROMPT
            }
        ] + self.conversation_history
        
        try:
            response = self._create_chat_completion(
                operation="smee.process",
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
        app_text = application.get('application_text') or application.get('ApplicationText', '') or application.get('applicationtext', '')
        app_id = application.get('application_id') or application.get('ApplicationID') or application.get('applicationid')
        
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

