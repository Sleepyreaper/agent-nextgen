"""Gaston Evaluator - evaluates and assesses job/internship applications."""

import time
import json
from typing import Dict, List, Any, Optional
from src.utils import safe_load_json
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
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
            f"**Applicant:** {application.get('ApplicantName', 'Unknown')}",
            f"**Email:** {application.get('Email', 'N/A')}",
            f"**Student ID:** {application.get('StudentID', 'N/A')}",
            ""
        ]
        
        # Add training examples for reference
        if self.training_examples:
            prompt_parts.append("# COMPELLING EXAMPLES FROM OUR PROGRAM")
            prompt_parts.append("Study these examples of students who thrived in our program:")
            prompt_parts.append("")
            
            for idx, example in enumerate(self.training_examples[:3], 1):
                prompt_parts.append(f"## Example {idx}: {example.get('ApplicantName', 'Anonymous')}")
                prompt_parts.append(f"{example.get('ApplicationText', '')[:400]}...")
                prompt_parts.append("")
        
        prompt_parts.extend([
            "# APPLICATION CONTENT",
            application.get('ApplicationText', ''),
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
        
        prompt = self._build_evaluation_prompt(application)
        
        try:
            # Two-step: extract salient evidence and quotes, then synthesize the
            # final JSON evaluation using that extracted material.
            query_messages = [
                {"role": "system", "content": "You are an expert at extracting salient evidence and direct quotes from an application for an admissions evaluation."},
                {"role": "user", "content": f"Extract the 6 most important evidence snippets and any direct quotes from this application to support scoring:\n\n{application.get('ApplicationText', '')[:2500]}"}
            ]

            format_template = [
                {"role": "system", "content": "You are an expert hiring manager. Using the extracted facts, produce the JSON evaluation exactly matching the requested schema. Respond ONLY with valid JSON."},
                {"role": "user", "content": "Extracted facts and quotes: {found}\n\nNow return the JSON evaluation per the schema in the prompt."}
            ]

            q_resp, response = self.two_step_query_format(
                operation_base="gaston.evaluate_application",
                model=self.model,
                query_messages=query_messages,
                format_messages_template=format_template,
                query_kwargs={"max_completion_tokens": 300, "temperature": 0},
                format_kwargs={"max_completion_tokens": 2000, "temperature": 0.8, "response_format": {"type": "json_object"}}
            )

            processing_time_ms = int((time.time() - start_time) * 1000)

            # Parse the JSON response
            evaluation = safe_load_json(response.choices[0].message.content)
            
            # Add metadata
            evaluation['processing_time_ms'] = processing_time_ms
            evaluation['model_used'] = self.model
            evaluation['agent_name'] = self.name
            evaluation['application_id'] = application.get('ApplicationID')
            
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
