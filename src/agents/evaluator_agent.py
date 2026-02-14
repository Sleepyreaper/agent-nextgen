"""Evaluator agent for assessing job/internship applications."""

import time
import json
from typing import Dict, List, Any, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent


class EvaluatorAgent(BaseAgent):
    """AI agent that evaluates applications against excellence criteria."""
    
    def __init__(
        self,
        name: str,
        client: AzureOpenAI,
        model: str,
        training_examples: List[Dict[str, Any]] = None
    ):
        """
        Initialize the evaluator agent.
        
        Args:
            name: Agent name
            client: Azure OpenAI client
            model: Model deployment name
            training_examples: List of excellent application examples
        """
        super().__init__(name, client)
        self.model = model
        self.training_examples = training_examples or []
    
    def set_training_examples(self, examples: List[Dict[str, Any]]):
        """Update the training examples."""
        self.training_examples = examples
    
    def _build_evaluation_prompt(self, application: Dict[str, Any]) -> str:
        """Build the evaluation prompt with context."""
        prompt_parts = [
            "You are an expert hiring manager evaluating internship/job applications.",
            "",
            "# EVALUATION CRITERIA",
            "Evaluate the application on these dimensions (0-100 scale):",
            "1. **Technical Skills** - Relevant technical knowledge and abilities",
            "2. **Communication** - Clarity, professionalism, and articulation",
            "3. **Experience** - Relevant work, projects, or academic experience",
            "4. **Cultural Fit** - Alignment with company values and team dynamics",
            ""
        ]
        
        # Add training examples if available
        if self.training_examples:
            prompt_parts.append("# EXCELLENT APPLICATION EXAMPLES")
            prompt_parts.append("Here are examples of previously selected excellent applications:")
            prompt_parts.append("")
            
            for idx, example in enumerate(self.training_examples[:3], 1):  # Show top 3
                prompt_parts.append(f"## Example {idx}: {example.get('ApplicantName', 'Anonymous')}")
                prompt_parts.append(f"{example.get('ApplicationText', '')[:500]}...")
                prompt_parts.append(f"**Why selected:** {example.get('Notes', 'Exceptional candidate')}")
                prompt_parts.append("")
        
        # Add the application to evaluate
        prompt_parts.extend([
            "# APPLICATION TO EVALUATE",
            f"**Applicant:** {application.get('ApplicantName', 'Unknown')}",
            f"**Email:** {application.get('Email', 'N/A')}",
            f"**Position:** {application.get('Position', 'N/A')}",
            "",
            "**Application Content:**",
            application.get('ApplicationText', ''),
            "",
            "# YOUR TASK",
            "Provide a comprehensive evaluation in JSON format with these fields:",
            "```json",
            "{",
            '  "technical_skills_score": <0-100>,',
            '  "communication_score": <0-100>,',
            '  "experience_score": <0-100>,',
            '  "cultural_fit_score": <0-100>,',
            '  "overall_score": <0-100>,',
            '  "strengths": "<bullet points of key strengths>",',
            '  "weaknesses": "<bullet points of areas for improvement>",',
            '  "recommendation": "<Strongly Recommend|Recommend|Consider|Reject>",',
            '  "detailed_analysis": "<2-3 paragraph detailed analysis>",',
            '  "comparison_to_excellence": "<how this compares to excellent examples>"',
            "}",
            "```",
            "",
            "Provide ONLY the JSON response, no additional text."
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert hiring manager. Respond ONLY with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_completion_tokens=2000,
                response_format={"type": "json_object"}  # Ensure JSON response
            )
            
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            # Parse the JSON response
            evaluation = json.loads(response.choices[0].message.content)
            
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
