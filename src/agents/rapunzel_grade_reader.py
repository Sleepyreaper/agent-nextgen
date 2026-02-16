"""Rapunzel Grade Reader - Specialized agent for parsing high school transcript data."""

from typing import Dict, List, Any, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
import re
import json


class RapunzelGradeReader(BaseAgent):
    """
    Specialized agent (Rapunzel) for reading and parsing high school grade reports.
    
    This agent handles:
    - Various transcript formats (PDF, text, scanned documents)
    - Different grading scales (4.0, weighted, letter grades)
    - Non-standard formatting and inconsistent layouts
    - Extraction of key academic indicators
    - Identification of trends and patterns
    """
    
    def __init__(
        self,
        name: str,
        client: AzureOpenAI,
        model: str
    ):
        """
        Initialize the Grade Report Reader agent.
        
        Args:
            name: Agent name (typically "Grade Report Reader")
            client: Azure OpenAI client
            model: Model deployment name
        """
        super().__init__(name, client)
        self.model = model
        self.extraction_focus = [
            "GPA/Grade Point Average",
            "Letter Grades by Subject",
            "Course Names and Levels (AP, Honors, Standard)",
            "Attendance/Tardiness",
            "Graduation Status",
            "Class Rank/Percentile",
            "Standardized Test Scores",
            "Special Notations (Incomplete, Withdrawal, etc.)"
        ]
    
    async def parse_grades(
        self,
        transcript_text: str,
        student_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parse grade report and extract structured academic data.
        
        Args:
            transcript_text: The raw transcript text
            student_name: Name of the student (optional)
            
        Returns:
            Dictionary with extracted grade data and analysis
        """
        self.add_to_history("user", f"Parse grade report for {student_name or 'candidate'}")
        
        # Build specialized parsing prompt
        parsing_prompt = self._build_parsing_prompt(transcript_text, student_name)
        
        print(f"🎓 {self.name}: Analyzing {len(transcript_text)} characters of transcript data...")
        
        try:
            response = self._create_chat_completion(
                operation="rapunzel.parse_grades",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": parsing_prompt
                    }
                ],
                max_completion_tokens=2000,
                temperature=1  # GPT-5.2 only supports default temperature
            )
            
            response_text = response.choices[0].message.content
            self.add_to_history("assistant", response_text)
            
            # Parse the structured response
            parsed_data = self._parse_response(response_text)
            
            return {
                'status': 'success',
                'student_name': student_name,
                'grades': parsed_data.get('grades', {}),
                'gpa': parsed_data.get('gpa'),
                'academic_strength': parsed_data.get('academic_strength'),
                'course_levels': parsed_data.get('course_levels'),
                'transcript_quality': parsed_data.get('transcript_quality'),
                'notable_patterns': parsed_data.get('notable_patterns', []),
                'confidence_level': parsed_data.get('confidence_level'),
                'summary': parsed_data.get('summary'),
                'model_used': self.model
            }
            
        except Exception as e:
            error_msg = f"Error parsing transcript: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                'status': 'error',
                'error': error_msg,
                'student_name': student_name
            }
    
    def _get_system_prompt(self) -> str:
        """Get the specialized system prompt for grade parsing."""
        return """You are part of an NIH Department of Genetics review panel evaluating Emory NextGen applicants.

Apply the requirements:
- Rising junior or senior in high school
- Must be 16 years old by June 1, 2026
- Must demonstrate interest in advancing STEM education to groups from a variety of backgrounds

You are an expert academic transcript reader. Your specialization is:

1. EXTRACT: Pull out all relevant academic data from messy, poorly-formatted transcripts
2. NORMALIZE: Convert different grading scales to standard terminology
3. INTERPRET: Understand what different course levels mean (AP, Honors, Standard)
4. IDENTIFY: Spot academic trends, strengths, and areas of concern
5. ASSESS: Evaluate overall academic rigor and performance

Key focus areas:
- GPA/cumulative grade point average
- Subject-specific performance
- Course level distribution (honors, AP, standard courses)
- Trends over time (improving, declining, stable)
- Non-academic notations (incomplete, withdrawn, etc.)
- Special circumstances or patterns

Be thorough but precise. If information is unclear or missing, note it explicitly.
Return structured data that can be easily parsed, with clear categories.
Provide a verbose summary (4-6 sentences) grounded in transcript evidence."""
    
    def _build_parsing_prompt(
        self,
        transcript_text: str,
        student_name: Optional[str] = None
    ) -> str:
        """
        Build the prompt for parsing a transcript.
        
        Args:
            transcript_text: Raw transcript text
            student_name: Student name if available
            
        Returns:
            Detailed parsing prompt
        """
        prompt = f"""Please analyze this high school grade report thoroughly.

Student: {student_name or 'Unknown'}
{'='*60}

TRANSCRIPT TEXT:
{transcript_text}

{'='*60}

EXTRACTION REQUIREMENTS:
For each of these categories, extract and normalize the data:

1. **GPA Information**
   - Unweighted GPA
   - Weighted GPA (if applicable)
   - Grading scale (e.g., 4.0, 5.0)
   - Any caveats or special notes

2. **Course Performance by Grade Level**
   List courses by level:
   - AP/Advanced Placement courses (with grades)
   - Honors level courses (with grades)
   - Standard/Regular courses (with grades)
   - Other specialized programs
   
3. **Academic Trends**
   - Freshman to Senior progression (improving/declining/stable)
   - Strongest subject areas
   - Weakest subject areas
   - Performance consistency

4. **Transcript Quality Assessment**
   Rate: Exceptional | Strong | Solid | Average | Below Average
   Reasoning: [1-2 sentences]

5. **Notable Patterns**
   - Course load trends
   - Attendance issues (if noted)
   - Late grades or incomplete marks
   - Grade recovery or improvement patterns
   - Unusual notations

6. **Confidence in Parsing**
   Rate: High | Medium | Low
   If low, explain what was unclear or missing

7. **Summary Assessment**
    - 4-6 sentences with specific evidence from the transcript
   One paragraph synthesizing this student's academic profile as it would appear to a college admissions officer.

Return your analysis in clear, structured format (not JSON, but clearly organized sections)."""
        
        return prompt
    
    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse the AI response into structured data.
        
        Args:
            response_text: Raw response from the model
            
        Returns:
            Parsed and structured data
        """
        parsed = {
            'gpa': None,
            'grades': {},
            'academic_strength': None,
            'course_levels': {},
            'transcript_quality': None,
            'notable_patterns': [],
            'confidence_level': None,
            'summary': None
        }
        
        # Extract GPA with regex
        gpa_match = re.search(r'(?:unweighted\s+)?GPA[:\s]+([0-9.]+)', response_text, re.IGNORECASE)
        if gpa_match:
            try:
                parsed['gpa'] = float(gpa_match.group(1))
            except ValueError:
                pass
        
        # Extract confidence level
        confidence_match = re.search(r'Confidence[:\s]+(High|Medium|Low)', response_text, re.IGNORECASE)
        if confidence_match:
            parsed['confidence_level'] = confidence_match.group(1)
        
        # Extract transcript quality
        quality_match = re.search(
            r'Transcript Quality[:\s]+(Exceptional|Strong|Solid|Average|Below Average)',
            response_text,
            re.IGNORECASE
        )
        if quality_match:
            parsed['transcript_quality'] = quality_match.group(1)
        
        # Extract first mention of academic strength/weakness
        strength_section = re.search(
            r'(?:Strongest subject|Academic Strength)[:\s]*([^.]+\.[^.]*)',
            response_text,
            re.IGNORECASE
        )
        if strength_section:
            parsed['academic_strength'] = strength_section.group(1).strip()
        
        # Try to extract course levels
        for level in ['AP', 'Honors', 'Standard']:
            level_pattern = rf'{level}[^:]*courses[:\s]*([^.]+\.[^.]*)'
            level_match = re.search(level_pattern, response_text, re.IGNORECASE)
            if level_match:
                parsed['course_levels'][level] = level_match.group(1).strip()
        
        # Extract patterns
        patterns_section = re.search(
            r'Notable Patterns[:\s]*(.+?)(?=\n\n|\d\.|$)',
            response_text,
            re.IGNORECASE | re.DOTALL
        )
        if patterns_section:
            pattern_text = patterns_section.group(1).strip()
            # Split by dashes or bullets
            patterns = [p.strip() for p in re.split(r'[-•*]\s+', pattern_text) if p.strip()]
            parsed['notable_patterns'] = patterns[:5]  # Keep top 5
        
        # Extract summary (usually last paragraph)
        summary_match = re.search(
            r'Summary[:\s]*(.+?)$',
            response_text,
            re.IGNORECASE | re.DOTALL
        )
        if summary_match:
            parsed['summary'] = summary_match.group(1).strip()[:500]  # Limit to 500 chars
        
        return parsed
    
    async def process(self, message: str) -> str:
        """
        Process a general message (for conversation).
        
        Args:
            message: User input
            
        Returns:
            Agent response
        """
        self.add_to_history("user", message)
        
        messages = [
            {
                "role": "system",
                "content": "You are part of an NIH Department of Genetics review panel evaluating Emory NextGen applicants. You extract academic insights from transcripts and note readiness for genetics-focused STEM work."
            }
        ] + self.conversation_history
        
        try:
            response = self._create_chat_completion(
                operation="rapunzel.process",
                model=self.model,
                messages=messages,
                max_completion_tokens=1500,
                temperature=1  # GPT-5.2 only supports default temperature
            )
            
            assistant_message = response.choices[0].message.content
            self.add_to_history("assistant", assistant_message)
            return assistant_message
            
        except Exception as e:
            error_message = f"Grade Reader encountered an error: {str(e)}"
            print(error_message)
            return error_message
    
    def get_specialization_info(self) -> Dict[str, Any]:
        """Get information about this agent's specialization."""
        return {
            'agent': self.name,
            'specialization': 'High School Transcript Analysis',
            'focus_areas': self.extraction_focus,
            'handles': [
                'Various transcript formats',
                'Different grading scales',
                'Non-standard formatting',
                'Trend identification',
                'Academic pattern recognition'
            ]
        }
