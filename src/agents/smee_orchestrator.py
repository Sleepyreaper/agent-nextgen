"""Smee - The orchestrator agent that coordinates all other agents."""

import asyncio
import json
from src.utils import safe_load_json
import logging
import os
from typing import Dict, List, Any, Optional, Tuple
from src.config import config
# Do not import `openai` at module import time. Accept the AI client as a runtime
# object (Any) to avoid ModuleNotFoundError during application startup when the
# `openai` package is not installed in the environment.
from src.agents.base_agent import BaseAgent
from src.agents.system_prompts import SMEE_ORCHESTRATOR_PROMPT
from src.agents.agent_requirements import AgentRequirements
from src.agents.belle_document_analyzer import BelleDocumentAnalyzer
from src.agents.agent_monitor import AgentStatus, get_agent_monitor
from src.telemetry import telemetry
from src.agents.telemetry_helpers import agent_run

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
        client: Any,
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
        self._agent_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._max_concurrent_per_agent = self._resolve_max_concurrency()

    def _resolve_max_concurrency(self) -> int:
        value = os.getenv("NEXTGEN_AGENT_MAX_CONCURRENCY", "2")
        try:
            resolved = int(value)
        except ValueError:
            resolved = 2
        return max(1, resolved)

    def _get_agent_semaphore(self, agent_id: str) -> asyncio.Semaphore:
        if agent_id not in self._agent_semaphores:
            self._agent_semaphores[agent_id] = asyncio.Semaphore(self._max_concurrent_per_agent)
        return self._agent_semaphores[agent_id]
    
    def _monitor_agent_execution(self, agent_id: str, agent_name: str, 
                                  model: Optional[str] = None, input_size: Optional[int] = None):
        """
        Context manager wrapper for monitoring agent execution.
        
        Usage:
            with self._monitor_agent_execution(agent_id, agent.name, model):
                result = await agent.some_method(...)
        """
        class AgentExecutionMonitor:
            def __init__(self, vm):
                self.vm = vm
                self.agent_id = agent_id
                self.agent_name = agent_name
                self.model = model
                self.execution = None
            
            def __enter__(self):
                self.execution = get_agent_monitor().start_execution(
                    self.agent_name, 
                    model=self.model,
                    input_size=input_size
                )
                return self
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                status = AgentStatus.FAILED if exc_type else AgentStatus.COMPLETED
                error_msg = f"{exc_type.__name__}: {exc_val}" if exc_type else None
                get_agent_monitor().end_execution(
                    self.agent_name,
                    status=status,
                    error_message=error_msg
                )
                return False  # Re-raise exceptions
        
        return AgentExecutionMonitor(self)
    
    def register_agent(self, agent_id: str, agent: BaseAgent):
        """
        Register a specialized agent with Smee.
        
        Args:
            agent_id: Unique identifier for the agent (e.g., "grade_reader", "evaluator")
            agent: The agent instance to register
        """
        self.agents[agent_id] = agent
        logger.info(f"Smee registered agent: {agent_id} ({agent.name})")

    def _normalize_agent_result(self, result: Any) -> Any:
        """
        Ensure agent result is JSON-serializable and in a predictable shape.
        - If dict/list: return as-is
        - If string: try to parse JSON, otherwise return string
        - If model/response-like object: try to extract message content
        - Fallback to string representation
        """
        try:
            if isinstance(result, (dict, list)):
                return result
            if isinstance(result, str):
                try:
                    return safe_load_json(result)
                except Exception:
                    return result

            # handle response-like objects with .choices
            choices = getattr(result, 'choices', None)
            if choices:
                try:
                    first = choices[0]
                    # openai style: first.message.content
                    content = None
                    if hasattr(first, 'message') and hasattr(first.message, 'content'):
                        content = first.message.content
                    elif isinstance(first, dict):
                        content = first.get('message', {}).get('content') or first.get('text')
                    if isinstance(content, (dict, list)):
                        return content
                    if isinstance(content, str):
                        try:
                            return safe_load_json(content)
                        except Exception:
                            return content
                except Exception:
                    pass

            # Last resort: try to json-serialize, else string
            try:
                return json.loads(json.dumps(result))
            except Exception:
                return str(result)
        except Exception:
            return {'error': 'could_not_normalize_result'}
    
    def get_registered_agents(self) -> Dict[str, str]:
        """Get list of registered agents."""
        return {agent_id: agent.name for agent_id, agent in self.agents.items()}
    
    # =====================================================================
    # PHASE 5: Audit Trail Logging
    # =====================================================================
    
    def _log_interaction(
        self,
        application_id: Optional[int],
        agent_name: str,
        interaction_type: str,
        question_text: str = "",
        user_response: str = "",
        file_name: str = "",
        file_size: int = 0,
        file_type: str = "",
        extracted_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a detailed interaction to the audit trail.
        
        PHASE 5: Comprehensive audit logging for every step and interaction.
        
        Args:
            application_id: Student application ID
            agent_name: Which agent/step (Belle, TIANA, RAPUNZEL, MOANA, MULAN, MERLIN, AURORA, etc)
            interaction_type: Type of interaction:
                - step_1_extraction: BELLE extraction
                - step_2_student_match: Student record matching
                - step_2_5_school_check: High school lookup/enrichment
                - step_3_naveen_enrichment: NAVEEN school enrichment
                - step_3_5_validation_attempt: School validation attempt
                - step_3_5_validation_passed: School validation passed
                - step_3_5_remediation: Remediation loop attempt
                - step_4_agent_execution: Agent (TIANA/RAPUNZEL/MOANA/MULAN) execution
                - step_4_5_validation: Per-agent pre-execution validation
                - step_5_milo_analysis: MILO analysis
                - step_6_merlin_synthesis: MERLIN synthesis
                - step_7_aurora_report: AURORA report generation
                - pause_for_documents: SMEE asking for more documents
                - resume_from_pause: Resume after user provides documents
                - file_upload: New file uploaded
            question_text: For pauses, the question asked
            user_response: User's text response
            file_name: Name of uploaded/processed file
            file_size: Size of file
            file_type: Type of file (pdf, text, image, etc)
            extracted_data: Structured data extracted/analyzed (JSONB)
        """
        if not self.db or not application_id:
            return
        
        try:
            self.db.log_agent_interaction(
                application_id=application_id,
                agent_name=agent_name,
                interaction_type=interaction_type,
                question_text=question_text,
                user_response=user_response,
                file_name=file_name,
                file_size=file_size,
                file_type=file_type,
                extracted_data=extracted_data
            )
        except Exception as e:
            logger.warning(f"Could not log interaction: {e}")
    
    # =====================================================================
    # PHASE 2: Workflow Helper Methods
    # =====================================================================
    
    def _match_or_create_student_record(
        self, 
        first_name: str, 
        last_name: str, 
        high_school: str, 
        state_code: str = "",
        application: Dict[str, Any] = None
    ) -> Optional[int]:
        """
        SMEE + BELLE collaboration: Match student to existing record OR create new.
        
        Primary match keys: first_name + last_name + high_school
        Optional refinement: state_code (used when Belle extracts it)
        
        Belle extracts identifying info from the uploaded document;
        Smee uses it here to verify whether the student already exists
        in the database, preventing duplicate records.
        
        Returns: application_id (existing or newly created)
        """
        # If the incoming application already has an `application_id`, prefer
        # that and skip matching/creation. Also try to resolve by `student_id`
        # if provided so we don't create a duplicate row when the frontend
        # already created a placeholder application earlier in the flow.
        if application:
            provided_app_id = application.get('application_id') or application.get('ApplicationID')
            if provided_app_id:
                logger.info(f"Using provided application_id: {provided_app_id} (skip matching)")
                return provided_app_id
            provided_student_id = application.get('student_id')
            if provided_student_id and self.db:
                try:
                    rows = self.db.execute_query(
                        "SELECT application_id FROM applications WHERE student_id = %s LIMIT 1",
                        (provided_student_id,)
                    )
                    if rows:
                        app_id = rows[0].get('application_id') if isinstance(rows[0], dict) else rows[0][0]
                        logger.info(f"Found existing application by student_id: {app_id}")
                        return app_id
                except Exception:
                    # fall through to normal matching if query fails
                    pass

        if not self.db:
            logger.warning("No database connection - cannot match student records")
            return None
        
        # 1. Normalize inputs for matching
        first_name_norm = first_name.strip() if first_name else ""
        last_name_norm = last_name.strip() if last_name else ""
        school_norm = high_school.strip() if high_school else ""
        state_norm = state_code.strip().upper() if state_code else ""
        
        # 2. Query database for exact match
        existing_app = self.db.find_student_by_match(
            first_name_norm, last_name_norm, school_norm, state_norm
        )
        
        if existing_app:
            app_id = existing_app['application_id']
            logger.info(
                f"🎯 Found existing student record: {app_id} "
                f"for {first_name} {last_name} from {high_school}, {state_code}"
            )
            return app_id
        
        # 3. Create new record
        new_app_id = self.db.create_student_record(
            first_name=first_name_norm,
            last_name=last_name_norm,
            high_school=school_norm,
            state_code=state_norm,
            application_text=application.get('application_text', '')
        )
        if new_app_id:
            logger.info(
                f"✨ Created new student record: {new_app_id} "
                f"for {first_name} {last_name} from {high_school}, {state_code}"
            )

        return new_app_id
    
    async def _extract_data_with_belle(
        self, 
        document_text: str, 
        document_name: str = "", 
        context: str = ""
    ) -> Dict[str, Any]:
        """
        REUSABLE: Extract data from document via BELLE.
        
        Can be called:
        - Initially to extract from uploaded document
        - Reactively when agents need more data from document
        - When user uploads new/additional files
        - With context hint (e.g., "extract grades" vs "extract recommendations")
        
        Returns extracted fields that SMEE can use for matching, validation, etc.
        """
        belle = BelleDocumentAnalyzer(client=self.client, model=self.model)
        
        # Log BELLE invocation
        if context:
            logger.info(f"📖 BELLE extracting {context} from document...")
        else:
            logger.info(f"📖 BELLE extracting data from {document_name or 'document'}...")
        
        try:
            analysis = await asyncio.to_thread(
                belle.analyze_document, document_text, document_name
            )
            
            # Log this extraction interaction if we have application context
            if hasattr(self, '_current_application_id') and self._current_application_id:
                self.db.log_agent_interaction(
                    application_id=self._current_application_id,
                    agent_name='Belle',
                    interaction_type='data_extraction',
                    file_name=document_name,
                    extracted_data=analysis
                )
            
            logger.info(f"✅ BELLE extraction complete: {len(analysis)} fields extracted")
            return analysis
        except Exception as e:
            logger.error(f"❌ BELLE extraction failed: {e}")
            return {}
    
    async def _run_naveen_enrichment(
        self, 
        high_school: str, 
        state_code: str, 
        application_id: int
    ) -> Dict[str, Any]:
        """
        STEP 3: Enrich school data via NAVEEN.
        Check if school already enriched (cached), else call NAVEEN.
        """
        from src.school_workflow import ensure_school_context_in_pipeline
        
        logger.info(f"🏫 NAVEEN enriching school: {high_school}, {state_code}...")
        
        naveen_agent = self.agents.get('naveen')
        
        try:
            school_enrichment = await asyncio.to_thread(
                ensure_school_context_in_pipeline,
                school_name=high_school,
                state_code=state_code,
                db_connection=self.db,
                aurora_agent=naveen_agent
            )
            
            logger.info(f"✅ School enrichment complete for {high_school}")
            return school_enrichment
        except Exception as e:
            logger.error(f"❌ NAVEEN enrichment failed: {e}")
            return {}
    
    async def _validate_school_context(
        self, 
        school_enrichment: Dict[str, Any], 
        school_name: str, 
        state_code: str
    ) -> Dict[str, Any]:
        """
        STEP 3.5: Validate NAVEEN provided all MOANA needs.
        Returns readiness status and any missing fields.
        """
        moana = self.agents.get('school_context')
        if not moana:
            logger.warning("MOANA not registered - cannot validate school context")
            return {'ready': True, 'missing': []}
        
        # Get MOANA's required school fields
        required_fields = [
            'school_name', 'state_code', 'opportunity_score',
            'ap_courses_available', 'honors_course_count',
            'free_lunch_percentage', 'graduation_rate'
        ]
        
        missing = []
        for field in required_fields:
            if field not in school_enrichment or school_enrichment.get(field) is None:
                missing.append(field)
        
        if missing:
            logger.warning(
                f"⚠️ School context incomplete. Missing: {', '.join(missing)}"
            )
            return {
                'ready': False,
                'missing': missing,
                'prompts': f"Please provide school documents showing: {', '.join(missing)}"
            }
        
        logger.info(f"✅ School context validation passed for {school_name}")
        return {'ready': True, 'missing': []}
    
    async def _check_or_enrich_high_school(
        self,
        high_school: str,
        state_code: str,
        school_district: Optional[str] = None,
        application_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        STEP 2.5: Check if high school exists, enrich if needed.
        
        Before proceeding to full validation loop (Step 3-3.5), ensure that
        the high school has at least basic enrichment data. This prevents
        MOANA validation from failing due to missing school data.
        
        Workflow:
        1. Query database for school_enriched_data
        2. If found: return cached data (ready for MOANA)
        3. If NOT found: call NAVEEN to create enrichment record
        4. Return enriched school data
        
        Args:
            high_school: High school name
            state_code: State code
            school_district: School district (optional)
            application_id: Application ID for tracking
            
        Returns:
            School enrichment dict or error dict
        """
        logger.info(f"📚 STEP 2.5: Checking/enriching high school: {high_school}, {state_code}")
        
        from src.school_workflow import SchoolDataWorkflow
        
        if not self.db:
            logger.warning("No database connection - cannot check high school")
            return {'error': 'No database connection', 'school_name': high_school}
        
        workflow = SchoolDataWorkflow(self.db)
        
        # Look up school in database
        cached_school = workflow._lookup_school_in_database(
            school_name=high_school,
            state_code=state_code
        )
        
        if cached_school and cached_school != {}:
            logger.info(
                f"✅ STEP 2.5 PASSED: Found cached high school data",
                extra={'school': high_school, 'state': state_code}
            )
            return cached_school
        
        # School not in database - call NAVEEN to enrich it
        logger.info(
            f"🔄 STEP 2.5: High school not cached, calling NAVEEN for enrichment...",
            extra={'school': high_school, 'state': state_code}
        )
        
        naveen_agent = self.agents.get('naveen')
        if not naveen_agent:
            logger.warning("NAVEEN agent not available for Step 2.5 enrichment")
            return {
                'error': 'NAVEEN agent not available',
                'school_name': high_school,
                'state_code': state_code
            }
        
        try:
            # Call NAVEEN to enrich the school
            enriched = await asyncio.to_thread(
                naveen_agent.analyze_school,
                school_name=high_school,
                school_district=school_district,
                state_code=state_code
            )
            
            if enriched.get('status') == 'success':
                # Store in database for caching
                school_id = workflow._store_school_enrichment(
                    school_data=enriched,
                    school_name=high_school,
                    school_district=school_district,
                    state_code=state_code
                )
                
                enriched['school_enrichment_id'] = school_id
                logger.info(
                    f"✅ STEP 2.5 COMPLETE: Enriched high school and stored in DB",
                    extra={'school': high_school, 'id': school_id}
                )
                
                return enriched
            else:
                logger.warning(
                    f"⚠️ STEP 2.5: NAVEEN enrichment returned non-success status",
                    extra={'school': high_school, 'status': enriched.get('status')}
                )
                return enriched
                
        except Exception as e:
            logger.error(
                f"❌ STEP 2.5: Error enriching high school: {e}",
                exc_info=True,
                extra={'school': high_school}
            )
            return {'error': str(e), 'school_name': high_school}
    
    async def _validate_agent_readiness(
        self, 
        agent_id: str, 
        application: Dict[str, Any], 
        application_id: int, 
        belle_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        STEP 4.5: Validate individual agent has its required fields.
        """
        agent = self.agents.get(agent_id)
        if not agent:
            return {'ready': False, 'missing': ['agent_not_found']}
        
        req = AgentRequirements.get_agent_requirements(agent_id)
        required_fields = req.get('required_fields', [])
        
        missing = []
        for field in required_fields:
            # Check application dict first, then belle_data (including nested structures)
            has_in_app = bool(application.get(field))
            has_in_belle = bool(belle_data.get(field) or 
                               belle_data.get('student_info', {}).get(field) or
                               belle_data.get('agent_fields', {}).get(field) or
                               belle_data.get('extracted_data', {}).get(field))
            if not has_in_app and not has_in_belle:
                missing.append(field)
        
        if missing:
            logger.warning(
                f"⚠️ Agent {agent_id} missing required fields: {missing}"
            )
            return {
                'ready': False,
                'missing': missing,
                'prompt': req.get('missing_prompt', f"Please provide {', '.join(missing)}")
            }
        
        logger.info(f"✅ Agent {agent_id} validation passed")
        return {'ready': True}
    
    async def _run_agent(
        self, 
        agent_id: str, 
        application: Dict[str, Any],
        school_enrichment: Dict[str, Any], 
        prior_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Run individual agent with appropriate context.
        Each agent is called with its specific required inputs.
        """
        agent = self.agents.get(agent_id)
        if not agent:
            logger.error(f"Agent {agent_id} not found")
            return {}
        
        logger.info(f"🤖 Running {agent.name} ({agent_id})...")
        
        try:
            # Route to correct agent method based on agent type
            if agent_id == 'application_reader':
                result = await agent.parse_application(application)
            elif agent_id == 'grade_reader':
                transcript = application.get('transcript_text', '')
                result = await agent.parse_grades(
                    transcript,
                    application.get('applicant_name', ''),
                    school_context=school_enrichment,
                    application_id=application.get('application_id')
                )
            elif agent_id == 'school_context':
                result = await agent.analyze_student_school_context(
                    application=application,
                    transcript_text=application.get('transcript_text', ''),
                    rapunzel_grades_data=prior_results.get('grade_reader'),
                    school_enrichment=school_enrichment,
                    application_id=application.get('application_id')
                )
            elif agent_id == 'recommendation_reader':
                recommendation = application.get('recommendation_text', '')
                result = await agent.parse_recommendation(
                    recommendation,
                    application.get('applicant_name', ''),
                    application.get('application_id')
                )
            elif agent_id == 'gaston':
                try:
                    result = await agent.evaluate_application(application)
                except AttributeError:
                    result = await agent.process(f"Evaluate: {application.get('applicant_name', '')}")
            else:
                result = await agent.process(
                    f"Evaluate: {application.get('applicant_name', '')}"
                )

            logger.info(f"✅ {agent.name} completed")
            logger.debug(f"{agent.name} output: {result}")

            # Always generate a human_summary for every agent result
            normalized_result = self._normalize_agent_result(result)
            try:
                ctx = normalized_result if isinstance(normalized_result, (dict, list, str)) else str(normalized_result)
                ctx_text = json.dumps(ctx, ensure_ascii=False) if not isinstance(ctx, str) else ctx
                prompt = [
                    {
                        "role": "user",
                        "content": (
                            f"You are given the output from the agent '{self.agents[agent_id].name}'. "
                            "Produce exactly three concise sentences that summarize the agent's output for a non-technical audience. "
                            "Keep the tone neutral and factual. If the agent included a recommendation or a key risk, include that in one of the sentences.\n\n"
                            "Agent output (JSON):\n" + str(ctx_text)
                        )
                    }
                ]
                resp = await asyncio.to_thread(
                    self._create_chat_completion,
                    f"{agent_id}.summary",
                    None,
                    prompt,
                    max_completion_tokens=200,
                    refinements=0,
                )
                summ = self._normalize_agent_result(resp)
                if isinstance(summ, (dict, list)):
                    try:
                        summ_text = json.dumps(summ, ensure_ascii=False)
                    except Exception:
                        summ_text = str(summ)
                else:
                    summ_text = str(summ)
                if isinstance(normalized_result, dict):
                    normalized_result['human_summary'] = summ_text
                else:
                    normalized_result = {
                        'result': normalized_result,
                        'human_summary': summ_text
                    }
            except Exception as e:
                logger.error(f"Failed to generate human_summary for agent={agent_id}: {e}")

            # Optionally supplement every agent's output with an explicit model call
            try:
                enabled = str(config.get('NEXTGEN_ALWAYS_MODEL_SUPPLEMENT', '')).lower() in ('1', 'true', 'yes')
            except Exception:
                enabled = False

            if enabled:
                try:
                    ctx = normalized_result
                    ctx_text = json.dumps(ctx, ensure_ascii=False) if not isinstance(ctx, str) else ctx
                    prompt = [
                        {
                            "role": "user",
                            "content": (
                                "Please provide any additional observations, clarifications, or structured "
                                "supplementary fields that would improve this agent's output.\n\nContext:\n"
                                + str(ctx_text)
                            )
                        }
                    ]
                    supp_resp = await asyncio.to_thread(
                        self._create_chat_completion,
                        f"{agent_id}.supplement",
                        None,
                        prompt,
                        max_completion_tokens=350,
                        refinements=1
                    )
                    supp_norm = self._normalize_agent_result(supp_resp)
                    if isinstance(normalized_result, dict):
                        normalized_result.setdefault('supplement', supp_norm)
                    else:
                        normalized_result = {
                            'result': normalized_result,
                            'supplement': supp_norm
                        }
                    logger.info(f"ℹ️ Supplemented {agent.name} output via model")
                except Exception as e:
                    logger.warning(f"Could not supplement agent {agent_id}: {e}")

            return normalized_result
        except Exception as e:
            logger.error(f"❌ {agent.name} failed: {e}")
            return {'error': str(e), 'status': 'failed'}
    
    def _create_student_summary(
        self,
        aurora_result: Dict[str, Any],
        merlin_result: Dict[str, Any],
        all_agent_results: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a concise student summary from Aurora and Merlin outputs for database storage.
        
        Args:
            aurora_result: Formatted report from Aurora agent
            merlin_result: Evaluation from Merlin agent
            all_agent_results: optional dict containing each agent's raw output;
                will be embedded under ``agent_details`` so that a single
                column on the ``applications`` table contains everything you
                need to understand what the agents have reasoned.
        
        Returns:
            Dictionary with summary information suitable for student_summary column
        """
        def _get_first(d: Dict[str, Any], candidates: list):
            for k in candidates:
                if not d:
                    continue
                if isinstance(d, dict) and k in d and d.get(k) is not None:
                    return d.get(k)
            return None

        # If merlin_result is a string, try to parse JSON
        if isinstance(merlin_result, str):
            try:
                merlin_result = safe_load_json(merlin_result)
            except Exception:
                merlin_result = {}

        overall = _get_first(merlin_result, ['overall_score', 'overall', 'score', 'overallScore', 'overallscore'])
        try:
            overall = float(overall) if overall is not None else None
        except Exception:
            overall = None

        recommendation = _get_first(merlin_result, ['recommendation', 'recommendation_text', 'recommendationText']) or ''
        rationale = _get_first(merlin_result, ['rationale', 'detailed_analysis', 'DetailedAnalysis']) or ''
        key_strengths = _get_first(merlin_result, ['key_strengths', 'strengths']) or []
        key_risks = _get_first(merlin_result, ['key_risks', 'considerations', 'risks']) or []
        confidence = _get_first(merlin_result, ['confidence'])

        summary = {
            'status': 'completed',
            'overall_score': overall,
            'recommendation': recommendation,
            'rationale': rationale,
            'key_strengths': key_strengths,
            'key_risks': key_risks,
            'confidence': confidence,
            'agents_completed': list(self.agents.keys()) if self.agents else [],
            'formatted_by_aurora': bool(aurora_result),
            'aurora_sections': list(aurora_result.keys()) if isinstance(aurora_result, dict) else []
        }

        if all_agent_results is not None:
            details = {}
            try:
                # Support multiple shapes: dict (canonical), list (legacy), or other.
                if isinstance(all_agent_results, dict):
                    iterable = all_agent_results.items()
                elif isinstance(all_agent_results, list):
                    # Try to interpret a list of single-key dicts (e.g. [{"merlin": {...}}, {"aurora": {...}}])
                    tmp = []
                    for i, entry in enumerate(all_agent_results):
                        if isinstance(entry, dict) and len(entry) == 1:
                            k = next(iter(entry.keys()))
                            v = entry[k]
                            tmp.append((k, v))
                        else:
                            # fallback: create synthetic key
                            tmp.append((f'agent_{i}', entry))
                    iterable = tmp
                else:
                    # Unknown shape - coerce to string-safe fallback
                    iterable = []

                for aid, val in iterable:
                    # canonicalize common agent ids
                    canon = {
                        'student_evaluator': 'merlin',
                        'report_generator': 'aurora'
                    }.get(aid, aid)
                    try:
                        details[canon] = self._normalize_agent_result(val)
                    except Exception:
                        # fallback to safe_load_json for strings
                        if isinstance(val, str):
                            try:
                                details[canon] = safe_load_json(val)
                            except Exception:
                                details[canon] = val
                        else:
                            details[canon] = val
                summary['agent_details'] = details
            except Exception:
                summary['agent_details'] = all_agent_results

        return summary
    
    async def coordinate_evaluation(
        self,
        application: Dict[str, Any],
        evaluation_steps: List[str],
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        PHASE 2: 8-Step Workflow Orchestration (+ Step 2.5)
        
        Step 1: BELLE extracts data from document (name, school, grades, etc.)
        Step 2: SMEE + BELLE verify student record (match by first_name + last_name + high_school)
        Step 2.5: Check or enrich high school data (lookup cached school data)
        Step 3: Enrich school data using NAVEEN (if not cached)
        Step 3.5: Validate school context (NAVEEN ↔ MOANA validation loop)
        Step 4: Core agents (TIANA, RAPUNZEL, MOANA, MULAN) analyze + write to student record
        Step 4.5: Per-agent validation before each agent runs
        Step 5: Run synthesis agents (MILO)
        Step 6: Run synthesis agent (MERLIN)
        Step 7: Run report generation (AURORA)
        
        Args:
            application: The application data to evaluate
            evaluation_steps: List of agent_ids to use in order
            progress_callback: Optional callback function to report progress
            
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
        
        # Register agent invocation with OpenTelemetry (GenAI Semantic Convention)
        self._otel_ctx = agent_run(
            "Smee Orchestrator", "coordinate_evaluation",
            context_data={"application_id": str(application_id or ""), "applicant_name": applicant_name},
            agent_id="smee-orchestrator",
        )
        self._otel_span = self._otel_ctx.__enter__()
        
        logger.info(
            f"🎯 SMEE starting 8-step workflow for {applicant_name}",
            extra={'application_id': application_id, 'student_id': student_id}
        )
        
        self._report_progress({
            'type': 'agent_progress',
            'agent': 'Smee Orchestrator',
            'agent_id': 'smee',
            'status': 'starting_8_step_workflow',
            'applicant': applicant_name,
            'message': '🎩 Smee is orchestrating the 8-step evaluation workflow...'
        })
        
        # Initialize workflow results
        self.evaluation_results = {
            'applicant_name': applicant_name,
            'application_id': application_id,
            'student_id': student_id,
            'agents_used': evaluation_steps,
            'results': {}
        }
        
        # ===== STEP 1: BELLE - Extract data from document =====
        print(f"\n{'='*80}")
        print(f"DEBUG: STARTING STEP 1 - BELLE extraction")
        print(f"DEBUG: application keys: {list(application.keys())}")
        print(f"DEBUG: application_id={application_id}, student_id={student_id}")
        logger.info("📋 STEP 1: Extracting data from document with BELLE...")
        print("📋 STEP 1: Extracting data from document with BELLE...")
        
        document_text = (application.get('application_text') or 
                        application.get('ApplicationText') or 
                        application.get('transcript_text') or 
                        application.get('TranscriptText') or '')
        
        document_name = application.get('file_name', 'application_document')
        # NOTE: avoid creating a placeholder application record here. We need
        # BELLE extraction to perform reliable student matching. Creating a
        # placeholder before matching can lead to two inserts (placeholder +
        # matched student record) and cause agent results to be persisted to a
        # different application_id. Defer creating an application row until
        # after student matching so a single record is created/used.
        print(f"DEBUG: document_name={document_name}, doc_length={len(document_text)}")
        belle_data = await self._extract_data_with_belle(document_text, document_name)
        print(f"DEBUG: BELLE returned: {list(belle_data.keys()) if isinstance(belle_data, dict) else 'NOT A DICT'}")
        self.evaluation_results['results']['belle_extraction'] = belle_data
        
        # PHASE 5: Log STEP 1 extraction to audit trail
        self._log_interaction(
            application_id=application_id,
            agent_name='Belle',
            interaction_type='step_1_extraction',
            question_text=f"Extract structured data from document: {document_name}",
            file_name=document_name,
            file_size=len(document_text),
            file_type=application.get('file_type', 'text/unknown'),
            extracted_data=belle_data
        )
        
        # Extract student info from BELLE extraction
        # BELLE returns nested structure: student_info, agent_fields, etc.
        belle_student_info = belle_data.get('student_info', {})
        belle_agent_fields = belle_data.get('agent_fields', {})
        
        first_name = (belle_student_info.get('first_name') or 
                     belle_agent_fields.get('first_name') or
                     application.get('first_name') or 
                     application.get('FirsName', '')).strip()
        last_name = (belle_student_info.get('last_name') or 
                    belle_agent_fields.get('last_name') or
                    application.get('last_name') or 
                    application.get('LastName', '')).strip()
        high_school = (belle_student_info.get('school_name') or 
                      belle_agent_fields.get('school_name') or
                      application.get('high_school') or 
                      application.get('HighSchool', '')).strip()
        state_code = (belle_student_info.get('state_code') or 
                     belle_agent_fields.get('state_code') or
                     application.get('state_code') or 
                     application.get('StateCode', '')).strip()
        
        # ===== STEP 2: SMEE + BELLE verify student record =====
        # Belle extracted name and high school from the document.
        # Smee now uses those fields to look up or create the student record.
        # Primary keys: first_name + last_name + high_school
        # Optional refinement: state_code (when Belle can extract it)
        print(f"\nDEBUG: STEP 2 - Smee+Belle student verification")
        print(f"DEBUG: first_name={first_name}, last_name={last_name}, school={high_school}, state={state_code}")
        logger.info("🎓 STEP 2: SMEE + BELLE verifying student record (name + high school)...")
        print("🎓 STEP 2: SMEE + BELLE verifying student record (name + high school)...")
        
        if first_name and last_name and high_school:
            student_app_id = self._match_or_create_student_record(
                first_name, last_name, high_school, state_code or "", application
            )
            if student_app_id:
                application_id = student_app_id
                self._current_application_id = student_app_id
                # CRITICAL: Update application dict so agents can access application_id
                application['application_id'] = student_app_id
                logger.info(f"✅ Student record ready: application_id={student_app_id}")
                
                # PHASE 5: Log STEP 2 student matching
                self._log_interaction(
                    application_id=application_id,
                    agent_name='Smee',
                    interaction_type='step_2_student_match',
                    question_text=f"Smee+Belle verify student: {first_name} {last_name} from {high_school}" + (f", {state_code}" if state_code else ""),
                    extracted_data={
                        'first_name': first_name,
                        'last_name': last_name,
                        'high_school': high_school,
                        'state_code': state_code or '',
                        'match_keys': 'name+high_school' + ('+state' if state_code else ''),
                        'action': 'created' if student_app_id else 'matched'
                    }
                )
        else:
            missing = []
            if not first_name: missing.append('first_name')
            if not last_name: missing.append('last_name')
            if not high_school: missing.append('high_school')
            logger.warning(
                f"⚠️ Belle could not extract required fields for student matching: "
                f"missing={missing}  (first={first_name}, last={last_name}, school={high_school})"
            )

        # If matching didn't produce an application_id, create one now so
        # downstream agents and persistence use the same record. Include
        # `student_id` to keep linkage between in-memory workflow and DB.
        if not application_id and self.db:
            try:
                created_id = self.db.create_application(
                    applicant_name=applicant_name,
                    email=application.get('email', ''),
                    application_text=document_text,
                    file_name=document_name,
                    file_type=application.get('file_type', 'text/plain'),
                    student_id=student_id
                )
                if created_id:
                    application_id = created_id
                    self._current_application_id = created_id
                    application['application_id'] = created_id
                    logger.info(f"✨ Created application record: {created_id} for {applicant_name}")
            except Exception as e:
                logger.warning(f"Could not create application record after matching: {e}")

        # ===== STEP 2.5/3/3.5: School enrichment via NAVEEN + MOANA =====
        school_enrichment = {}
        if high_school and state_code:
            logger.info(f"🏫 STEP 2.5: Checking school enrichment for {high_school}, {state_code}")
            print(f"🏫 STEP 2.5: Checking school enrichment for {high_school}, {state_code}")
            self._report_progress({
                'type': 'agent_progress',
                'agent_id': 'naveen',
                'agent': 'Naveen',
                'status': 'starting',
                'message': f'🧑‍🔬 Naveen is enriching school data for {high_school}...'
            })
            try:
                school_enrichment = await self._check_or_enrich_high_school(
                    high_school=high_school,
                    state_code=state_code,
                    school_district=application.get('school_district'),
                    application_id=application_id
                )
                if school_enrichment and not school_enrichment.get('error'):
                    logger.info(f"✅ School enrichment ready for {high_school}")
                    print(f"✅ School enrichment ready for {high_school}")
                    self._report_progress({
                        'type': 'agent_progress',
                        'agent_id': 'naveen',
                        'agent': 'Naveen',
                        'status': 'completed',
                        'message': f'🧑‍🔬 Naveen complete — school enrichment ready ✓'
                    })
                else:
                    logger.warning(f"⚠️ School enrichment incomplete: {school_enrichment.get('error', 'unknown')}")
                    print(f"⚠️ School enrichment incomplete for {high_school}")
                    self._report_progress({
                        'type': 'agent_progress',
                        'agent_id': 'naveen',
                        'agent': 'Naveen',
                        'status': 'skipped',
                        'message': f'School enrichment incomplete for {high_school}'
                    })
                    school_enrichment = {}
            except Exception as e:
                logger.error(f"❌ School enrichment failed: {e}", exc_info=True)
                print(f"❌ School enrichment failed: {e}")
                self._report_progress({
                    'type': 'agent_progress',
                    'agent_id': 'naveen',
                    'agent': 'Naveen',
                    'status': 'failed',
                    'message': f'School enrichment failed: {str(e)[:80]}'
                })
                school_enrichment = {}
        else:
            logger.warning(f"⚠️ No high school/state info available — skipping school enrichment")
            print(f"⚠️ No high school/state — skipping enrichment")
            self._report_progress({
                'type': 'agent_progress',
                'agent_id': 'naveen',
                'agent': 'Naveen',
                'status': 'skipped',
                'message': 'No school/state info — skipped'
            })

        self.evaluation_results['results']['school_enrichment'] = school_enrichment
        
        # ===== STEP 4: Core agents with per-agent validation =====
        print(f"\n{'='*80}")
        print(f"DEBUG: STEP 4 - Core agents (PARALLEL)")
        print(f"DEBUG: evaluation_steps={evaluation_steps}")
        print(f"DEBUG: Registered agents: {list(self.agents.keys())}")
        logger.info("🤖 STEP 4: Running core agents with PARALLEL execution...")
        print("🤖 STEP 4: Running core agents with PARALLEL execution...")
        
        core_agents = ['application_reader', 'grade_reader', 'school_context', 'recommendation_reader', 'gaston']
        print(f"DEBUG: core_agents list={core_agents}")
        prior_results = {}

        # --- Parallel Group 1: Independent document readers ---
        # Tiana (application), Rapunzel (transcript), Mulan (recommendations)
        # These read independent document sections and have no cross-dependencies
        parallel_group_1 = ['application_reader', 'grade_reader', 'recommendation_reader']
        parallel_group_1 = [a for a in parallel_group_1 if a in self.agents]
        
        if parallel_group_1:
            logger.info(f"⚡ PARALLEL GROUP 1: Running {parallel_group_1} concurrently...")
            print(f"⚡ PARALLEL GROUP 1: {[a.upper() for a in parallel_group_1]}")
            
            async def _validate_and_run_core_agent(agent_id, shared_prior):
                """Validate, run, and persist a single core agent. Thread-safe for parallel use."""
                if agent_id not in self.agents:
                    return agent_id, None, 'not_registered'
                
                self._report_progress({
                    'type': 'agent_progress',
                    'agent_id': agent_id,
                    'agent': self.agents[agent_id].name,
                    'status': 'starting',
                    'message': f'{self.agents[agent_id].name} is starting...'
                })
                
                # Validation gate
                readiness = await self._validate_agent_readiness(
                    agent_id, application, application_id, belle_data
                )
                
                if not readiness.get('ready'):
                    logger.warning(f"⚠️ Agent {agent_id} not ready: {readiness.get('missing')}")
                    print(f"❌ {agent_id.upper()}: VALIDATION FAILED - Missing {readiness.get('missing', [])}")
                    
                    self._log_interaction(
                        application_id=application_id,
                        agent_name=agent_id.title(),
                        interaction_type='step_4_5_validation',
                        question_text=f"Validation gate for {agent_id}",
                        extracted_data={
                            'agent_id': agent_id,
                            'validation_status': 'failed_gate_1',
                            'missing_fields': readiness.get('missing', []),
                            'gate_number': 1
                        }
                    )
                    
                    # Reactive BELLE call
                    logger.info(f"📖 Reactively calling BELLE to fill {agent_id} gap...")
                    belle_retry = await self._extract_data_with_belle(
                        document_text, document_name,
                        context=f"Focus on {', '.join(readiness.get('missing', []))}"
                    )
                    belle_data.update(belle_retry)
                    
                    readiness = await self._validate_agent_readiness(
                        agent_id, application, application_id, belle_data
                    )
                    
                    if not readiness.get('ready'):
                        logger.warning(f"⚠️ {agent_id} still not ready after BELLE retry. SKIPPING.")
                        self._log_interaction(
                            application_id=application_id,
                            agent_name=agent_id.title(),
                            interaction_type='skip_insufficient_data',
                            question_text=f"Agent {agent_id} skipped - insufficient data",
                            extracted_data={
                                'agent_id': agent_id,
                                'reason': 'missing_required_documents',
                                'validation_status': 'failed_gate_2_skipping',
                                'missing_fields': readiness.get('missing', []),
                                'gate_number': 2,
                                'action': 'skipped_continue_workflow'
                            }
                        )
                        self._report_progress({
                            'type': 'agent_progress',
                            'agent_id': agent_id,
                            'agent': self.agents[agent_id].name,
                            'status': 'skipped',
                            'message': f'Skipped — missing {readiness.get("missing", [])}'
                        })
                        return agent_id, None, 'skipped'
                
                self._log_interaction(
                    application_id=application_id,
                    agent_name=agent_id.title(),
                    interaction_type='step_4_5_validation',
                    question_text=f"Validation gate for {agent_id}",
                    extracted_data={
                        'agent_id': agent_id,
                        'validation_status': 'passed',
                        'ready_to_execute': True
                    }
                )
                
                # Run the agent
                logger.info(f"🚀 Running {agent_id}...")
                print(f"▶️  RUNNING {agent_id.upper()}: {self.agents[agent_id].name}")
                self._report_progress({
                    'type': 'agent_progress',
                    'agent_id': agent_id,
                    'agent': self.agents[agent_id].name,
                    'status': 'processing',
                    'message': f'{self.agents[agent_id].name} is analyzing...'
                })
                
                try:
                    agent_result = await self._run_agent(
                        agent_id, application, school_enrichment, shared_prior
                    )
                    normalized_result = self._normalize_agent_result(agent_result)
                    
                    logger.info(f"✅ Agent {agent_id} completed")
                    print(f"✅ {agent_id.upper()}: COMPLETED")
                    self._report_progress({
                        'type': 'agent_progress',
                        'agent_id': agent_id,
                        'agent': self.agents[agent_id].name,
                        'status': 'completed',
                        'message': f'{self.agents[agent_id].name} complete ✓'
                    })
                    
                    return agent_id, normalized_result, 'completed'
                except Exception as agent_exec_error:
                    logger.error(f"❌ {agent_id} execution error: {agent_exec_error}")
                    print(f"❌ {agent_id.upper()}: FAILED - {str(agent_exec_error)[:100]}")
                    self._report_progress({
                        'type': 'agent_progress',
                        'agent_id': agent_id,
                        'agent': self.agents[agent_id].name,
                        'status': 'failed',
                        'message': f'Error: {str(agent_exec_error)[:80]}'
                    })
                    return agent_id, {'error': str(agent_exec_error)}, 'error'
            
            # Run parallel group 1 concurrently
            group1_tasks = [_validate_and_run_core_agent(aid, prior_results) for aid in parallel_group_1]
            group1_results = await asyncio.gather(*group1_tasks, return_exceptions=True)
            
            # Collect results from parallel group 1
            for item in group1_results:
                if isinstance(item, Exception):
                    logger.error(f"Parallel agent task failed: {item}")
                    continue
                aid, result, status = item
                if result is not None:
                    self.evaluation_results['results'][aid] = result
                    prior_results[aid] = result
            
            logger.info(f"✅ PARALLEL GROUP 1 complete: {[a.upper() for a in parallel_group_1]}")
            print(f"✅ PARALLEL GROUP 1 DONE")
        
        # --- Sequential: Moana (school_context) - depends on Rapunzel grades ---
        if 'school_context' in self.agents:
            logger.info("🌊 Running Moana (depends on Rapunzel grades)...")
            print("🌊 RUNNING MOANA (sequential — needs Rapunzel grades)")
            aid, result, status = await _validate_and_run_core_agent('school_context', prior_results)
            if result is not None:
                self.evaluation_results['results'][aid] = result
                prior_results[aid] = result
        
        # --- Sequential: Gaston (evaluator) - benefits from all prior results ---
        if 'gaston' in self.agents:
            logger.info("💪 Running Gaston (needs all prior context)...")
            print("💪 RUNNING GASTON (sequential — needs prior results)")
            aid, result, status = await _validate_and_run_core_agent('gaston', prior_results)
            if result is not None:
                self.evaluation_results['results'][aid] = result
                prior_results[aid] = result

        # --- Persist all core agent results to database ---
        for agent_id in core_agents:
            normalized_result = self.evaluation_results['results'].get(agent_id)
            if not normalized_result or not isinstance(normalized_result, dict):
                continue
            try:
                if self.db and application_id:
                    # Persist to agent_results column
                    stored = {}
                    try:
                        existing = self.db.get_application(application_id) or {}
                        stored = existing.get('agent_results') or {}
                        if isinstance(stored, str):
                            stored = safe_load_json(stored)
                    except Exception:
                        stored = {}
                    canonical_map = {
                        'student_evaluator': 'merlin',
                        'report_generator': 'aurora'
                    }
                    stored_key = canonical_map.get(agent_id, agent_id)
                    stored[stored_key] = normalized_result
                    self.db.update_application(
                        application_id=application_id,
                        agent_results=json.dumps(stored)
                    )
                    
                    # Save agent audit
                    try:
                        self.db.save_agent_audit(application_id, self.agents[agent_id].name, None)
                    except Exception:
                        pass

                    # Extract scores for evaluation persistence
                    overall_score = None
                    try:
                        overall_score = normalized_result.get('overall_score') or normalized_result.get('readiness_score') or normalized_result.get('score')
                        if overall_score is not None:
                            overall_score = float(overall_score)
                    except Exception:
                        overall_score = None
                    
                    model_used = getattr(self.agents[agent_id], 'model', None) or self.model
                    processing_ms = int(normalized_result.get('processing_time_ms', 0)) if isinstance(normalized_result, dict) else 0
                    detailed = None
                    try:
                        detailed = json.dumps(normalized_result, ensure_ascii=True)
                    except Exception:
                        try:
                            detailed = str(normalized_result)
                        except Exception:
                            pass
                    
                    try:
                        self.db.save_evaluation(
                            application_id,
                            self.agents[agent_id].name,
                            overall_score or 0.0,
                            0.0, 0.0, 0.0, 0.0,
                            normalized_result.get('strengths', normalized_result.get('key_strengths', '')),
                            normalized_result.get('weaknesses', normalized_result.get('key_risks', '')),
                            normalized_result.get('recommendation', ''),
                            detailed or '',
                            '',
                            model_used or '',
                            processing_ms
                        )
                    except Exception as _eval_err:
                        logger.warning(f"Could not persist evaluation for {agent_id}: {_eval_err}")
                    
                    # Log agent execution
                    self._log_interaction(
                        application_id=application_id,
                        agent_name=agent_id.title(),
                        interaction_type='step_4_agent_execution',
                        question_text=f"Execute core agent: {agent_id}",
                        extracted_data={
                            'agent_id': agent_id,
                            'execution_status': 'completed',
                            'result_keys': list(normalized_result.keys()) if isinstance(normalized_result, dict) else []
                        }
                    )
            except Exception:
                logger.debug(f"Skipping DB persistence for {agent_id}")

        
        # ===== STEP 5: MILO - training analysis =====
        logger.info("📊 STEP 5: Running Milo training analysis...")
        if 'data_scientist' in evaluation_steps and 'data_scientist' in self.agents:
            milo = self.agents['data_scientist']
            self._report_progress({
                'type': 'agent_progress',
                'agent_id': 'data_scientist',
                'agent': 'Milo',
                'status': 'starting',
                'message': '📊 Milo is analyzing training data patterns...'
            })
            try:
                milo_result = await milo.analyze_training_insights()
                self.evaluation_results['results']['data_scientist'] = milo_result

                # persist Milo output into the application record for downstream use
                try:
                    if self.db and application_id:
                        existing = {}
                        try:
                            rec = self.db.get_application(application_id) or {}
                            existing = rec.get('agent_results') or {}
                            if isinstance(existing, str):
                                existing = safe_load_json(existing)
                        except Exception:
                            existing = {}
                        existing['data_scientist'] = milo_result
                        try:
                            self.db.update_application(
                                application_id=application_id,
                                agent_results=json.dumps(existing)
                            )
                        except Exception:
                            logger.debug('Could not persist milo to agent_results')
                except Exception:
                    pass

                self._report_progress({
                    'type': 'agent_progress',
                    'agent_id': 'data_scientist',
                    'agent': 'Milo',
                    'status': 'completed',
                    'message': '📊 Milo complete — training patterns analyzed ✓'
                })

                # Log STEP 5 MILO analysis
                self._log_interaction(
                    application_id=application_id,
                    agent_name='Milo',
                    interaction_type='step_5_milo_analysis',
                    question_text='Analyze training examples to generate insights',
                    extracted_data={
                        'analysis_status': 'completed',
                        'result_keys': list(milo_result.keys()) if isinstance(milo_result, dict) else [],
                        'insights_generated': 'insights' in str(milo_result).lower() or 'analysis' in str(milo_result).lower()
                    }
                )

                # compute alignment for this application if the method exists
                try:
                    if hasattr(milo, 'compute_alignment'):
                        alignment = await milo.compute_alignment(application)
                        self.evaluation_results['results']['milo_alignment'] = alignment
                        # also persist alignment so UI/tests can access it easily
                        if self.db and application_id:
                            try:
                                existing = {}
                                rec = self.db.get_application(application_id) or {}
                                existing = rec.get('agent_results') or {}
                                if isinstance(existing, str):
                                    existing = safe_load_json(existing)
                                existing['milo_alignment'] = alignment
                                self.db.update_application(
                                    application_id=application_id,
                                    agent_results=json.dumps(existing)
                                )
                            except Exception:
                                pass
                except Exception as align_err:
                    logger.debug(f"Milo compute_alignment failed during orchestration: {align_err}")
            except Exception as e:
                logger.error(f"❌ MILO analysis failed: {e}")
                self.evaluation_results['results']['data_scientist'] = {'error': str(e)}
                self._report_progress({
                    'type': 'agent_progress',
                    'agent_id': 'data_scientist',
                    'agent': 'Milo',
                    'status': 'failed',
                    'message': f'Milo failed: {str(e)[:80]}'
                })
                # still log failure for auditing
                self._log_interaction(
                    application_id=application_id,
                    agent_name='Milo',
                    interaction_type='step_5_milo_analysis',
                    question_text='Analyze training examples to generate insights',
                    extracted_data={
                        'analysis_status': 'failed',
                        'error': str(e)
                    }
                )
        else:
            # when the step isn't requested or the agent is missing we mark as skipped
            self.evaluation_results['results']['data_scientist'] = {'skipped': True}

        # ===== STEP 6: MERLIN - Synthesis =====
        print(f"DEBUG: About to start STEP 6. evaluation_steps={evaluation_steps}")
        print(f"DEBUG: student_evaluator in evaluation_steps? {'student_evaluator' in evaluation_steps}")
        print(f"DEBUG: student_evaluator in agents? {'student_evaluator' in self.agents}")
        logger.info("🧙 STEP 6: Synthesizing evaluation with MERLIN...")
        print("🧙 STEP 6: Synthesizing evaluation with MERLIN...")
        
        if 'student_evaluator' in evaluation_steps and 'student_evaluator' in self.agents:
            merlin = self.agents['student_evaluator']
            self._report_progress({
                'type': 'agent_progress',
                'agent_id': 'student_evaluator',
                'agent': 'Merlin',
                'status': 'starting',
                'message': '🧙 Merlin is synthesizing all agent evaluations...'
            })
            try:
                merlin_result = await merlin.evaluate_student(
                    application, self.evaluation_results['results']
                )
                merlin_result = self._normalize_agent_result(merlin_result)
                # store under both internal and canonical keys
                self.evaluation_results['results']['student_evaluator'] = merlin_result
                self.evaluation_results['results']['merlin'] = merlin_result
                # Persist MERLIN into applications.agent_results for UI/backfill
                try:
                    if self.db and application_id:
                        existing = {}
                        try:
                            rec = self.db.get_application(application_id) or {}
                            existing = rec.get('agent_results') or {}
                            if isinstance(existing, str):
                                existing = safe_load_json(existing)
                        except Exception:
                            existing = {}
                        existing_key = 'merlin'
                        existing[existing_key] = merlin_result
                        # also keep legacy key
                        existing['student_evaluator'] = merlin_result
                        try:
                            self.db.update_application(application_id=application_id, agent_results=json.dumps(existing))
                        except Exception:
                            logger.debug('Could not persist merlin to agent_results')
                except Exception:
                    pass
                
                # ===== Persist Next Gen Match to application record =====
                # Resolve nextgen_match from Merlin first, then fall back to Milo
                nextgen_match = None
                if isinstance(merlin_result, dict):
                    nextgen_match = merlin_result.get('nextgen_match')
                if nextgen_match is None:
                    milo_align = self.evaluation_results['results'].get('milo_alignment', {})
                    if isinstance(milo_align, dict):
                        nextgen_match = milo_align.get('nextgen_match')
                if nextgen_match is not None and self.db and application_id:
                    try:
                        self.db.update_application(
                            application_id=application_id,
                            nextgen_match=nextgen_match
                        )
                        logger.info(f"🎯 Next Gen Match persisted: {nextgen_match}% for application {application_id}")
                    except Exception as ngm_err:
                        logger.debug(f"Could not persist nextgen_match: {ngm_err}")

                # PHASE 5: Log STEP 6 MERLIN synthesis
                self._log_interaction(
                    application_id=application_id,
                    agent_name='Merlin',
                    interaction_type='step_6_merlin_synthesis',
                    question_text='Synthesize all agent evaluations into comprehensive assessment',
                    extracted_data={
                        'synthesis_status': 'completed',
                        'result_keys': list(merlin_result.keys()) if isinstance(merlin_result, dict) else [],
                        'has_overall_score': 'overall_score' in str(merlin_result).lower() or 'score' in str(merlin_result).lower(),
                        'recommendations_generated': 'recommendation' in str(merlin_result).lower()
                    }
                )
                
                logger.info("✅ MERLIN synthesis complete")
                self._report_progress({
                    'type': 'agent_progress',
                    'agent_id': 'student_evaluator',
                    'agent': 'Merlin',
                    'status': 'completed',
                    'message': '🧙 Merlin complete — final evaluation ready ✓'
                })
            except Exception as e:
                logger.error(f"❌ MERLIN synthesis failed: {e}")
                self._report_progress({
                    'type': 'agent_progress',
                    'agent_id': 'student_evaluator',
                    'agent': 'Merlin',
                    'status': 'failed',
                    'message': f'Merlin failed: {str(e)[:80]}'
                })
                # PHASE 5: Log STEP 6 MERLIN failure
                self._log_interaction(
                    application_id=application_id,
                    agent_name='Merlin',
                    interaction_type='step_6_merlin_synthesis',
                    question_text='Synthesize all agent evaluations into comprehensive assessment',
                    extracted_data={
                        'synthesis_status': 'failed',
                        'error': str(e)
                    }
                )
        
        # ===== STEP 7: AURORA - Report generation =====
        print(f"DEBUG: About to start STEP 7. evaluation_steps={evaluation_steps}")
        print(f"DEBUG: aurora in evaluation_steps? {'aurora' in evaluation_steps}")
        print(f"DEBUG: aurora in agents? {'aurora' in self.agents}")
        logger.info("📄 STEP 7: Generating report with AURORA...")
        print("📄 STEP 7: Generating report with AURORA...")
        
        if 'aurora' in evaluation_steps and 'aurora' in self.agents:
            aurora = self.agents['aurora']
            self._report_progress({
                'type': 'agent_progress',
                'agent_id': 'aurora',
                'agent': 'Aurora',
                'status': 'starting',
                'message': '✨ Aurora is formatting the executive summary...'
            })
            try:
                aurora_result = await asyncio.to_thread(
                    aurora.format_evaluation_report,
                    self.evaluation_results['results']
                )
                aurora_result = self._normalize_agent_result(aurora_result)
                # store under both internal and canonical keys
                self.evaluation_results['results']['report_generator'] = aurora_result
                self.evaluation_results['results']['aurora'] = aurora_result
                
                # PHASE 5: Log STEP 7 AURORA report generation
                self._log_interaction(
                    application_id=application_id,
                    agent_name='Aurora',
                    interaction_type='step_7_aurora_report',
                    question_text='Generate formatted evaluation report',
                    extracted_data={
                        'report_status': 'generated',
                        'report_length': len(str(aurora_result)) if aurora_result else 0,
                        'sections_included': list(aurora_result.keys()) if isinstance(aurora_result, dict) else [],
                        'report_generated': True
                    }
                )
                
                # Save Aurora evaluation to database with student summary
                if self.db and application_id:
                    try:
                        merlin_result = self.evaluation_results['results'].get('student_evaluator', {})
                        merlin_result = self._normalize_agent_result(merlin_result)
                        aurora_eval_id = self.db.save_aurora_evaluation(
                            application_id=application_id,
                            formatted_evaluation=aurora_result,
                            merlin_score=merlin_result.get('overall_score'),
                            merlin_recommendation=merlin_result.get('recommendation'),
                            agents_completed=','.join(evaluation_steps)
                        )
                        logger.info(f"✅ Aurora evaluation saved: {aurora_eval_id}")
                        
                        # Create student summary from Aurora output
                        # include every agent's raw output in the summary so
                        # the row contains both high‑level and detailed
                        # reasoning that can be surfaced later.
                        student_summary = self._create_student_summary(
                            aurora_result,
                            merlin_result,
                            all_agent_results=self.evaluation_results['results']
                        )
                        # Persist AURORA into applications.agent_results as well
                        try:
                            existing = {}
                            try:
                                rec = self.db.get_application(application_id) or {}
                                existing = rec.get('agent_results') or {}
                                if isinstance(existing, str):
                                    existing = safe_load_json(existing)
                            except Exception:
                                existing = {}
                            existing_key = 'aurora'
                            existing[existing_key] = aurora_result
                            existing['report_generator'] = aurora_result
                            try:
                                self.db.update_application(application_id=application_id, agent_results=json.dumps(existing))
                            except Exception:
                                logger.debug('Could not persist aurora to agent_results')
                        except Exception:
                            pass
                        if student_summary and application_id:
                            self.db.update_application(
                                application_id=application_id,
                                student_summary=json.dumps(student_summary)
                            )
                    except Exception as e:
                        logger.warning(f"Could not save Aurora evaluation: {e}")
                
                logger.info("✅ AURORA report generation complete")
                self._report_progress({
                    'type': 'agent_progress',
                    'agent_id': 'aurora',
                    'agent': 'Aurora',
                    'status': 'completed',
                    'message': '✨ Aurora complete — executive summary ready ✓'
                })
            except Exception as e:
                logger.error(f"❌ AURORA report generation failed: {e}")
                self._report_progress({
                    'type': 'agent_progress',
                    'agent_id': 'aurora',
                    'agent': 'Aurora',
                    'status': 'failed',
                    'message': f'Aurora failed: {str(e)[:80]}'
                })
                # PHASE 5: Log STEP 7 AURORA failure
                self._log_interaction(
                    application_id=application_id,
                    agent_name='Aurora',
                    interaction_type='step_7_aurora_report',
                    question_text='Generate formatted evaluation report',
                    extracted_data={
                        'report_status': 'failed',
                        'error': str(e)
                    }
                )
        
        # ===== Workflow complete =====
        logger.info("✅ 8-step workflow completed successfully")
        
        self._report_progress({
            'type': 'workflow_complete',
            'agent': 'Smee Orchestrator',
            'agent_id': 'smee',
            'status': 'completed',
            'applicant': applicant_name,
            'message': '✅ 8-step evaluation workflow completed'
        })
        
        # Mark application as complete in database
        if self.db and application_id:
            try:
                self.db.update_application_status(application_id, 'Completed')
            except Exception as e:
                logger.warning(f"Could not mark application as complete: {e}")
        
        self.workflow_state = "complete"
        # Close the invoke_agent span
        try:
            self._otel_ctx.__exit__(None, None, None)
        except Exception:
            pass
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
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        lower_keys = self._build_field_index(application)

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
                variant_val = self._field_has_value(application, field, lower_keys)
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

    def _pause_for_missing_fields(
        self,
        applicant_name: str,
        application_id: Optional[Any],
        student_id: Optional[Any],
        missing_fields: List[str],
        agent_questions: List[Dict[str, Any]],
        application_snapshot: Dict[str, Any]
    ) -> Dict[str, Any]:
        missing_prompts = self._build_missing_field_prompts(
            application_snapshot,
            missing_fields,
            agent_questions
        )
        logger.info(f"Evaluation paused for {applicant_name}: Agents need {len(missing_fields)} items: {missing_fields}")

        if self.db and application_id:
            try:
                self.db.set_missing_fields(application_id, missing_fields)
            except Exception as e:
                logger.warning(f"Could not save missing fields: {e}")

        self._report_progress({
            'type': 'evaluation_paused',
            'agent': 'Smee Orchestrator',
            'agent_id': 'smee',
            'status': 'asking_for_info',
            'applicant': applicant_name,
            'student_id': student_id,
            'missing_fields': missing_fields,
            'agent_questions': agent_questions,
            'missing_prompts': missing_prompts,
            'message': f'❓ Agents need {len(missing_fields)} items to proceed'
        })

        for agent_info in agent_questions:
            field_name = agent_info.get('field_name')
            if field_name not in missing_fields:
                continue
            prompt = self._get_prompt_for_field(missing_prompts, field_name)
            questions = agent_info.get('questions') or []
            waiting_message = prompt or (questions[0] if questions else f"Waiting for {field_name}")
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
            'missing_prompts': missing_prompts,
            'message': 'Information needed before evaluation can proceed',
            'detailed_message': 'The following agents need information:'
        }

    def _get_missing_fields_for_agent(
        self,
        agent_id: str,
        application: Dict[str, Any]
    ) -> List[str]:
        requirements = AgentRequirements.get_agent_requirements(agent_id)
        required_fields = requirements.get('required_fields', [])
        field_name = requirements.get('field_name', agent_id)
        lower_keys = self._build_field_index(application)

        missing_required = [
            field for field in required_fields
            if not self._field_has_value(application, field, lower_keys)
        ]

        return [field_name] if missing_required else []

    def _get_application_snapshot(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Merge in-database application data with in-memory application data."""
        snapshot = dict(application or {})

        if not self.db:
            return snapshot

        application_id = (
            application.get('application_id')
            or application.get('ApplicationID')
            or getattr(self, '_current_application_id', None)
        )
        if not application_id:
            return snapshot

        try:
            db_record = self.db.get_application(application_id)
            if db_record:
                merged = dict(db_record)
                merged.update(snapshot)
                return merged
        except Exception as e:
            logger.debug(f"Could not load application record for missing field checks: {e}")

        return snapshot

    def _build_field_index(self, application: Dict[str, Any]) -> Dict[str, Any]:
        return {str(key).lower(): key for key in (application or {}).keys()}

    def _field_has_value(
        self,
        application: Dict[str, Any],
        field_name: str,
        lower_keys: Optional[Dict[str, Any]] = None
    ) -> bool:
        if not lower_keys:
            lower_keys = self._build_field_index(application)
        variants = [field_name, field_name.replace('_', ''), field_name.title()]
        for variant in variants:
            key = lower_keys.get(variant.lower())
            if key is not None and application.get(key):
                return True
        return False

    def _build_missing_field_prompts(
        self,
        application: Dict[str, Any],
        missing_fields: List[str],
        agent_questions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        prompts = []
        lower_keys = self._build_field_index(application)

        for agent_info in agent_questions:
            # Defensive: handle if agent_info is a string instead of dict
            if isinstance(agent_info, str):
                logger.warning(f"agent_info is string instead of dict: {agent_info}")
                continue
            
            field_name = agent_info.get('field_name')
            if field_name not in missing_fields:
                continue

            requirements = AgentRequirements.get_agent_requirements(agent_info.get('agent_id'))
            required_fields = requirements.get('required_fields', [])
            missing_required = [
                field for field in required_fields
                if not self._field_has_value(application, field, lower_keys)
            ]
            prompt = requirements.get('missing_prompt')
            if not prompt:
                questions = requirements.get('questions', [])
                prompt = questions[0] if questions else f"Please provide {field_name}"

            prompt = self._generate_missing_prompt_with_ai(
                field_name=field_name,
                missing_required=missing_required,
                application=application,
                fallback_prompt=prompt
            )

            prompts.append({
                'field_name': field_name,
                'agent_id': agent_info.get('agent_id'),
                'agent_name': agent_info.get('agent_name'),
                'prompt': prompt,
                'accepts_formats': requirements.get('accepts_formats', []),
                'required_fields': required_fields,
                'missing_required_fields': missing_required,
            })

        return prompts

    def _generate_missing_prompt_with_ai(
        self,
        field_name: str,
        missing_required: List[str],
        application: Dict[str, Any],
        fallback_prompt: str
    ) -> str:
        """Use AI to generate a concise, specific prompt for missing evidence."""
        try:
            applicant_name = application.get('applicant_name') or application.get('ApplicantName')
            summary = {
                'applicant_name': applicant_name,
                'missing_required_fields': missing_required,
                'available_fields': list(application.keys())[:30]
            }
            prompt = f"""You are Smee. Write a single, concise request (1 sentence) asking the user to provide missing evidence for {field_name}.
Be specific about the document and acceptable formats if relevant. Avoid redundant questions.

Context: {json.dumps(summary)}

Return only the request sentence."""

            response = self._create_chat_completion(
                operation="missing_evidence_prompt",
                model=self.model,
                messages=[
                    {"role": "system", "content": "You create precise document requests for missing evidence."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_completion_tokens=60
            )
            if response and hasattr(response, 'choices') and response.choices and getattr(response.choices[0].message, 'content', None):
                generated_prompt = response.choices[0].message.content.strip()
                telemetry.track_event(
                    "smee_missing_evidence_prompt",
                    properties={
                        "field_name": field_name,
                        "missing_required_fields": ",".join(missing_required),
                        "prompt_source": "ai",
                    },
                    metrics_data={
                        "prompt_length": float(len(generated_prompt)),
                    },
                )
                return generated_prompt
        except Exception as e:
            logger.debug(f"Missing prompt generation failed: {e}")

        telemetry.track_event(
            "smee_missing_evidence_prompt",
            properties={
                "field_name": field_name,
                "missing_required_fields": ",".join(missing_required),
                "prompt_source": "fallback",
            },
            metrics_data={
                "prompt_length": float(len(fallback_prompt)),
            },
        )
        return fallback_prompt

    def _get_prompt_for_field(self, prompts: List[Dict[str, Any]], field_name: str) -> Optional[str]:
        for prompt in prompts:
            if prompt.get('field_name') == field_name:
                return prompt.get('prompt')
        return None

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

    def _order_evaluation_steps(
        self,
        evaluation_steps: List[str],
        pre_core_agents: List[str],
        core_agents: List[str],
        optional_agents: List[str],
        merlin_agent: str
    ) -> List[str]:
        """Order the evaluation pipeline to match the desired workflow."""
        steps = list(evaluation_steps or [])
        ordered = []

        def append_group(group: List[str]) -> None:
            for agent_id in group:
                if agent_id in steps and agent_id not in ordered:
                    ordered.append(agent_id)

        append_group(pre_core_agents)
        append_group(core_agents)

        for agent_id in steps:
            if agent_id in ordered:
                continue
            if agent_id in optional_agents or agent_id == merlin_agent:
                continue
            ordered.append(agent_id)

        append_group(optional_agents)

        if merlin_agent in steps and merlin_agent not in ordered:
            ordered.append(merlin_agent)

        return ordered
    
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

    async def _run_milo(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """Helper invoked during STEP 5 to execute Milo's training analysis.

        Returns a dictionary containing Milo's insights. If the agent is not
        registered the method returns an empty dict. Any exceptions are caught
        and surfaced in an ``error`` key so callers can continue gracefully.
        """
        milo = self.agents.get('data_scientist')
        if not milo:
            return {}
        try:
            result = await milo.analyze_training_insights()
            # optionally compute alignment for the given application
            if hasattr(milo, 'compute_alignment'):
                try:
                    alignment = await milo.compute_alignment(application)
                    result['computed_alignment'] = alignment
                except Exception:
                    pass
            return result
        except Exception as e:
            return {'error': str(e)}

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
            'naveen',
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

