"""Gaston Evaluator - evaluates and assesses job/internship applications."""

import time
import json
from typing import Dict, List, Any, Optional
from src.utils import safe_load_json
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.telemetry_helpers import agent_run
from src.agents.system_prompts import GASTON_EVALUATOR_PROMPT


class GastonEvaluator(BaseAgent):
    """Gaston - AI agent that evaluates applications against excellence criteria."""
    
    def __init__(
        self,
        name: str,
        client: AzureOpenAI,
        model: Optional[str] = None,
        training_examples: List[Dict[str, Any]] = None
    ):
        """
        Initialize the evaluator agent.
        
        Args:
            name: Agent name
            client: Azure OpenAI client
            model: Model deployment name (optional, falls back to config)
            training_examples: List of excellent application examples
        """
        super().__init__(name, client)
        self.model = model or config.foundry_model_name or config.deployment_name
        self.training_examples = training_examples or []
    
    def set_training_examples(self, examples: List[Dict[str, Any]]):
        """Update the training examples."""
        self.training_examples = examples
    
    def _build_evaluation_prompt(self, application: Dict[str, Any]) -> str:
        """Build the evaluation prompt with context and deep reasoning."""
        prompt_parts = [
            GASTON_EVALUATOR_PROMPT,
            "",
            "# APPLICATION TO EVALUATE",
            f"**Applicant:** {application.get('applicant_name') or application.get('ApplicantName', 'Unknown')}",
            f"**Email:** {application.get('email') or application.get('Email', 'N/A')}",
            f"**Student ID:** {application.get('application_id') or application.get('StudentID', 'N/A')}",
            ""
        ]
        
        # Add training examples for reference
        if self.training_examples:
            prompt_parts.append("# COMPELLING EXAMPLES FROM OUR PROGRAM")
            prompt_parts.append("Study these examples of students who thrived in our program:")
            prompt_parts.append("")
            
            for idx, example in enumerate(self.training_examples[:3], 1):
                prompt_parts.append(f"## Example {idx}: {example.get('applicant_name') or example.get('ApplicantName', 'Anonymous')}")
                prompt_parts.append(f"{(example.get('application_text') or example.get('ApplicationText', ''))[:400]}...")
                prompt_parts.append("")
        
        prompt_parts.extend([
            "# APPLICATION CONTENT",
            application.get('application_text') or application.get('ApplicationText', ''),
            "",
            "# EVALUATION TASK",
            "Provide detailed evaluation in JSON format.",
            "Include specific quotes from the application to support each score.",
            "",
            "```json",
            "{",
            '  "technical_foundation_score": <0-100>,',
            '  "communication_score": <0-100>,',
            '  "intellectual_curiosity_score": <0-100>,',
            '  "growth_potential_score": <0-100>,',
            '  "team_contribution_score": <0-100>,',
            '  "overall_score": <0-100>,',
            '  "key_strengths": [<3-4 specific strengths with evidence>],',
            '  "growth_areas": [<2-3 areas for development>],',
            '  "evidence_quotes": [<direct quotes supporting your scores>],',
            '  "detailed_analysis": "<3-4 paragraph holistic assessment considering what this student COULD become>",',
            '  "fit_for_nextgen": "<Why this student will or won\'t thrive in our diverse STEM community>",',
            '  "recommendation": "<STRONG ADMIT|ADMIT|WAITLIST|RECONSIDER>",',
            '  "reasoning": "<Concise explanation of your recommendation>"',
            "}",
            "```",
            "",
            "**Important:** Be fair to students from all backgrounds. Look for potential, not pedigree."
        ])
        
        return "\n".join(prompt_parts)
    
    async def evaluate_application(self, application: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a single application.
        
        Args:
            application: Dictionary containing application data
            
        Returns:
            Dictionary containing evaluation results
        """
        start_time = time.time()
        
        with agent_run("Gaston", "evaluate_application", {"application_id": str(application.get("application_id") or application.get("ApplicationID", ""))}) as span:

            try:
                # Gather application text with aggressive fallbacks.
                # Try known text fields first, then fall back to the preserved
                # original document text, and finally search ALL string values
                # in the dict for substantial content.
                app_text_input = (
                    application.get('application_text') or
                    application.get('ApplicationText') or
                    application.get('transcript_text') or
                    application.get('TranscriptText') or
                    application.get('recommendation_text') or
                    application.get('_original_document_text') or ''
                )
                # Last resort: scan all values for any substantial text (lowered
                # threshold from 100 → 30 chars to catch short but real content)
                if not app_text_input or not app_text_input.strip():
                    for k, v in application.items():
                        if isinstance(v, str) and len(v.strip()) > 30 and k not in (
                            'status', 'email', 'file_type', 'file_name',
                            'original_file_name', 'applicant_name', 'student_id'
                        ):
                            app_text_input = v
                            print(f"[Gaston] Found text in fallback key '{k}' ({len(v)} chars)")
                            break
                app_text_input = (app_text_input or '').strip()[:8000]

                applicant_name = application.get('applicant_name') or application.get('ApplicantName', 'Unknown')
                applicant_email = application.get('email') or application.get('Email', 'N/A')
                application_id = application.get('application_id') or application.get('StudentID', 'N/A')

                print(f"[Gaston] evaluate_application: applicant={applicant_name}, text_length={len(app_text_input)}")
                # Log which text fields have content for debugging
                text_field_lengths = {
                    k: len(str(v)) for k, v in application.items()
                    if isinstance(v, str) and len(v) > 10
                    and k in ('application_text', 'ApplicationText', 'transcript_text',
                              'TranscriptText', 'recommendation_text', '_original_document_text',
                              'applicationtext', 'transcripttext', 'recommendationtext')
                }
                print(f"[Gaston] Text field lengths: {text_field_lengths}")

                if not app_text_input:
                    # ── EXTREME DIAGNOSTIC: dump EVERY key/value in the dict ──
                    print(f"[Gaston] ❌ CRITICAL: No text for {applicant_name}! app_id={application_id}")
                    print(f"[Gaston] ALL keys ({len(application)}): {sorted(application.keys())}")
                    for k, v in sorted(application.items()):
                        if isinstance(v, str):
                            print(f"[Gaston]   STR  key='{k}' len={len(v)} preview={repr(v[:120])}")
                        elif isinstance(v, (dict, list)):
                            print(f"[Gaston]   {type(v).__name__:4s} key='{k}' len={len(v)}")
                        elif v is None:
                            print(f"[Gaston]   NONE key='{k}'")
                        else:
                            print(f"[Gaston]   {type(v).__name__:4s} key='{k}' val={repr(v)[:80]}")
                    return {
                        'technical_foundation_score': 0,
                        'communication_score': 0,
                        'intellectual_curiosity_score': 0,
                        'growth_potential_score': 0,
                        'team_contribution_score': 0,
                        'overall_score': 0,
                        'key_strengths': [],
                        'growth_areas': ['No application text available for evaluation'],
                        'evidence_quotes': [],
                        'detailed_analysis': 'No application text was available for this student. Please upload the application essay or personal statement.',
                        'fit_for_nextgen': 'Cannot assess — no application text provided.',
                        'recommendation': 'REVIEW REQUIRED',
                        'reasoning': 'No application materials available to evaluate.',
                        'quick_pass': False,
                        'quick_pass_reason': 'No application text provided',
                        'processing_time_ms': int((time.time() - start_time) * 1000),
                        'model_used': self.model,
                        'agent_name': self.name,
                        'application_id': application.get('application_id')
                    }

                # Build training examples context
                training_context = ""
                if self.training_examples:
                    training_context = "\n\n# COMPELLING EXAMPLES FROM OUR PROGRAM\nStudy these examples of students who thrived in our program:\n"
                    for idx, example in enumerate(self.training_examples[:3], 1):
                        ex_name = example.get('applicant_name') or example.get('ApplicantName', 'Anonymous')
                        ex_text = (example.get('application_text') or example.get('ApplicationText', ''))[:400]
                        training_context += f"\n## Example {idx}: {ex_name}\n{ex_text}...\n"

                # Two-step: extract salient evidence and quotes, then synthesize the
                # final JSON evaluation using that extracted material.
                # Step 1 uses the Gaston system prompt so the LLM understands
                # the evaluation criteria while extracting evidence.
                query_messages = [
                    {"role": "system", "content": (
                        GASTON_EVALUATOR_PROMPT +
                        "\n\nYour task now is to carefully extract the most important "
                        "evidence and direct quotes from the application below. "
                        "These will be used for scoring in a follow-up step."
                        "\n\nIMPORTANT: The text may contain page markers like "
                        "'--- PAGE N of M ---'. Note which page evidence comes from. "
                        "Focus on application/essay content and ignore transcript "
                        "or recommendation sections if present."
                    )},
                    {"role": "user", "content": (
                        f"Applicant: {applicant_name}\n\n"
                        f"Extract the 6 most important evidence snippets and any "
                        f"direct quotes from this application to support scoring "
                        f"across all evaluation dimensions (Technical Foundation, "
                        f"Communication, Intellectual Curiosity, Growth Potential, "
                        f"Team Contribution):\n\n{app_text_input}"
                    )}
                ]

                # Step 2: produce the JSON evaluation with the full schema and
                # evaluation criteria so the LLM knows exactly what to output.
                json_schema = (
                    '{\n'
                    '  "quick_pass": true/false,\n'
                    '  "quick_pass_reason": "explanation if No",\n'
                    '  "age_eligible": true/false/"unknown",\n'
                    '  "underrepresented_background": true/false,\n'
                    '  "has_research_experience": true/false,\n'
                    '  "has_advanced_coursework": true/false,\n'
                    '  "technical_foundation_score": 0-100,\n'
                    '  "communication_score": 0-100,\n'
                    '  "intellectual_curiosity_score": 0-100,\n'
                    '  "growth_potential_score": 0-100,\n'
                    '  "team_contribution_score": 0-100,\n'
                    '  "overall_score": 0-100,\n'
                    '  "key_strengths": ["3-4 specific strengths with evidence"],\n'
                    '  "growth_areas": ["2-3 areas for development"],\n'
                    '  "evidence_quotes": ["direct quotes supporting scores"],\n'
                    '  "detailed_analysis": "3-4 paragraph holistic assessment",\n'
                    '  "fit_for_nextgen": "assessment of fit for STEM community",\n'
                    '  "recommendation": "STRONG ADMIT|ADMIT|WAITLIST|RECONSIDER",\n'
                    '  "reasoning": "concise explanation of recommendation"\n'
                    '}'
                )

                format_template = [
                    {"role": "system", "content": (
                        GASTON_EVALUATOR_PROMPT +
                        training_context +
                        "\n\nUsing the extracted evidence below, produce the final "
                        "JSON evaluation. Be fair to students from all backgrounds. "
                        "Look for potential, not pedigree. Respond ONLY with valid JSON."
                    )},
                    {"role": "user", "content": (
                        f"Applicant: {applicant_name}\n"
                        f"Email: {applicant_email}\n"
                        f"Application ID: {application_id}\n\n"
                        f"Extracted evidence and quotes:\n{{found}}\n\n"
                        f"Now produce the JSON evaluation using this exact schema:\n"
                        f"```json\n{json_schema}\n```"
                    )}
                ]

                q_resp, response = self.two_step_query_format(
                    operation_base="gaston.evaluate_application",
                    model=self.model,
                    query_messages=query_messages,
                    format_messages_template=format_template,
                    query_kwargs={"max_completion_tokens": 600, "temperature": 0},
                    format_kwargs={"max_completion_tokens": 2000, "temperature": 0.8, "response_format": {"type": "json_object"}}
                )

                processing_time_ms = int((time.time() - start_time) * 1000)

                # Parse the JSON response
                evaluation = safe_load_json(response.choices[0].message.content)
                
                # Add metadata
                evaluation['processing_time_ms'] = processing_time_ms
                evaluation['model_used'] = self.model
                evaluation['agent_name'] = self.name
                evaluation['application_id'] = application.get('application_id') or application.get('ApplicationID')
                
                if span:
                    span.set_attribute("agent.result.score", str(evaluation.get("overall_score", "")))
                return evaluation
                
            except json.JSONDecodeError as e:
                print(f"[{self.name}] Failed to parse JSON response: {str(e)}")
                # Return a default evaluation
                return {
                    'technical_skills_score': 0,
                    'communication_score': 0,
                    'experience_score': 0,
                    'cultural_fit_score': 0,
                    'overall_score': 0,
                    'strengths': 'Error: Could not evaluate',
                    'weaknesses': 'Error in evaluation process',
                    'recommendation': 'Review Required',
                    'detailed_analysis': f'Evaluation failed: {str(e)}',
                    'comparison_to_excellence': 'N/A',
                    'processing_time_ms': int((time.time() - start_time) * 1000),
                    'model_used': self.model,
                    'agent_name': self.name
                }
            
            except Exception as e:
                print(f"[{self.name}] Evaluation error: {str(e)}")
                raise
    
    async def process(self, message: str) -> str:
        """Process method for base agent compatibility."""
        return f"Evaluator agent ready. Use evaluate_application() for assessments."
