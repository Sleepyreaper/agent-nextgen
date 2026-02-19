"""Rapunzel Grade Reader - Specialized agent for parsing high school transcript data."""

from typing import Dict, List, Any, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
import re
import json
import logging

logger = logging.getLogger(__name__)


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
        model: str,
        db_connection=None
    ):
        """
        Initialize the Grade Report Reader agent.
        
        Args:
            name: Agent name (typically "Grade Report Reader")
            client: Azure OpenAI client
            model: Model deployment name
            db_connection: Database connection for saving results
        """
        super().__init__(name, client)
        self.model = model
        self.db = db_connection
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
        student_name: Optional[str] = None,
        school_context: Optional[Dict[str, Any]] = None,
        application_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Parse grade report and extract structured academic data using deep reasoning.
        
        PHASE 4: Enhanced with school context for rigor weighting
        
        Args:
            transcript_text: The raw transcript text (should be detailed with course listings)
            student_name: Name of the student (optional)
            school_context: School enrichment data including AP/Honors availability for rigor weighting
            application_id: Application ID for storing results in database (optional)
            
        Returns:
            Dictionary with extracted grade data and analysis, including contextual_rigor_index
        """
        self.add_to_history("user", f"Parse comprehensive grade report for {student_name or 'candidate'}")
        
        # Log to Application Insights
        try:
            from src.telemetry import telemetry
            telemetry.track_event(
                "RapunzelTranscriptAnalysis",
                {
                    "student_name": student_name or "Unknown",
                    "transcript_length": len(transcript_text),
                    "agent": "Rapunzel Grade Reader",
                    "model": self.model
                }
            )
        except:
            pass  # Telemetry not available
        
        # Build specialized parsing prompt with optional school context for rigor weighting
        parsing_prompt = self._build_parsing_prompt(transcript_text, student_name, school_context)
        
        print(f"🎓 {self.name}: Analyzing transcript ({len(transcript_text)} chars) - Using deep reasoning for comprehensive analysis...")
        if school_context:
            print(f"  📍 School context provided: {school_context.get('school_name', 'Unknown school')}")
        
        try:
            # Use extended tokens for deep analysis
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
                max_completion_tokens=3500,  # Increased for detailed analysis
                temperature=1  # GPT-5.2 only supports default temperature
            )
            
            response_text = response.choices[0].message.content
            self.add_to_history("assistant", response_text)
            
            # Parse the structured response
            parsed_data = self._parse_response(response_text)
            
            result = {
                'status': 'success',
                'student_name': student_name,
                'agent_name': self.name,
                'model_used': self.model,
                'model_display': 'gpt-4',
                'grades': parsed_data.get('grades', {}),
                'gpa': parsed_data.get('gpa'),
                'academic_strength': parsed_data.get('academic_strength'),
                'course_levels': parsed_data.get('course_levels'),
                'transcript_quality': parsed_data.get('transcript_quality'),
                'notable_patterns': parsed_data.get('notable_patterns', []),
                'confidence_level': parsed_data.get('confidence_level'),
                'summary': parsed_data.get('summary'),
                'course_rigor_index': parsed_data.get('course_rigor_index'),
                'grade_table_markdown': parsed_data.get('grade_table_markdown'),
                'grade_table_headers': parsed_data.get('grade_table_headers'),
                'grade_table_rows': parsed_data.get('grade_table_rows'),
                'full_analysis': response_text,
                'school_context_used': bool(school_context)
            }
            
            # PHASE 4: Calculate contextual rigor index if school context provided
            if school_context:
                contextual_rigor = self._calculate_contextual_rigor_index(
                    parsed_data,
                    school_context
                )
                result['contextual_rigor_index'] = contextual_rigor
                result['school_name'] = school_context.get('school_name')
            else:
                result['contextual_rigor_index'] = None
            
            
            # Log success to Application Insights
            try:
                from src.telemetry import telemetry
                telemetry.track_event(
                    "RapunzelAnalysisComplete",
                    {
                        "student_name": student_name or "Unknown",
                        "status": "success",
                        "gpa": str(parsed_data.get('gpa', 'N/A')),
                        "rigor_index": str(parsed_data.get('course_rigor_index', 'N/A')),
                        "confidence": parsed_data.get('confidence_level', 'Unknown'),
                        "transcript_quality": parsed_data.get('transcript_quality', 'Unknown')
                    }
                )
            except:
                pass
            
            # Save to database if connection available and application_id provided
            if self.db and application_id:
                try:
                    self.db.save_rapunzel_grades(
                        application_id=application_id,
                        agent_name=self.name,
                        gpa=result.get('gpa'),
                        academic_strength=result.get('academic_strength'),
                        course_levels=result.get('course_levels'),
                        transcript_quality=result.get('transcript_quality'),
                        notable_patterns=result.get('notable_patterns'),
                        confidence_level=result.get('confidence_level'),
                        summary=result.get('summary'),
                        contextual_rigor_index=result.get('contextual_rigor_index'),
                        school_context_used=bool(school_context),
                        parsed_json=json.dumps(result, ensure_ascii=True, default=str)
                    )
                except Exception as db_error:
                    print(f"⚠️  {self.name}: Could not save to database: {db_error}")
            
            return result
            
        except Exception as e:
            error_msg = f"Error parsing transcript: {str(e)}"
            print(f"❌ {self.name}: {error_msg}")
            
            # Log error to Application Insights
            try:
                from src.telemetry import telemetry
                telemetry.track_event(
                    "RapunzelAnalysisError",
                    {
                        "student_name": student_name or "Unknown",
                        "status": "error",
                        "error": str(e)
                    }
                )
            except:
                pass
            
            return {
                'status': 'error',
                'error': error_msg,
                'student_name': student_name,
                'agent_name': self.name,
                'model_used': self.model,
                'model_display': 'gpt-4'
            }
    
    def _get_system_prompt(self) -> str:
        """Get the specialized system prompt for grade parsing with deep reasoning."""
        return """You are Rapunzel, the Grade Reader Agent for the Emory NextGen evaluation panel (NIH Department of Genetics).

EVALUATION CONTEXT:
- Rising junior or senior in high school
- Must be 16 years old by June 1, 2026
- Must demonstrate interest in advancing STEM education to underrepresented groups

YOUR CORE MISSION - Deep Analysis of Academic Rigor:
You are the expert academic transcript analyst. Your job is to understand not just WHAT grades a student received, but WHY those grades matter in context. You provide the foundational academic data that all other agents depend on.

DEEP REASONING APPROACH:
Before responding, think through:
1. What is the OVERALL academic trajectory? (improving/declining/stable/erratic)
2. What does the COURSE SELECTION tell us? (Risk-taking? Defensive choices? Strategic sequencing?)
3. How do GRADES match COURSE RIGOR? (A's in AP courses vs A's in standard courses = completely different)
4. What PATTERNS emerge? (Grade inflation in particular subjects? Course avoidance? Strategic choices?)
5. What do NON-ACADEMIC markings reveal? (Attendance issues? Conduct concerns? Honor roll consistency?)
6. How does SCHOOL CONTEXT constrain interpretation? (4 AP classes available vs 25? Matters enormously)

KEY INSIGHT: A B in AP Chemistry from a well-resourced school where 80% take AP classes tells a very different story than a B in AP Chemistry from a school where only 5 students take AP courses. Context is everything.

EXTRACTION SPECIALIZATION:
1. PARSE: Extract all course data - course name, level (AP/Honors/Standard), grade, percentage, credit hours, semester/year
2. NORMALIZE: Convert to standard format (A=4.0, B+=3.3, etc.) and identify weighted multipliers
3. STRUCTURALIZE: Organize by year, subject area, and course level
4. CONTEXTUALIZE: Note class rank, percentile, honor roll status, attendance, honors/awards
5. ANALYZE: Calculate subject-area performance, identify trends, assess overall rigor choices
6. SYNTHESIZE: Create narrative that explains the academic story

FOCUS AREAS (all required for complete analysis):
- Cumulative GPA (both weighted and unweighted with scale noted)
- Class rank and percentile
- Course-by-course breakdown: Name, Level, Grade, Percentage, Credits, Semester/Year
- Subject-area performance breakdown (Math vs Science vs English vs Social Studies)
- AP/Honors course density and performance
- Grade trend analysis (freshman to senior progression)
- Standardized test scores (if present)
- Non-academic factors: Attendance, conduct, special notations
- Honors and awards
- Special circumstances or constraints

OUTPUT REQUIREMENTS:
Return DETAILED, STRUCTURED analysis with:
✓ Complete course roster with detailed specifications
✓ Subject-area performance matrices
✓ Trend analysis with specific evidence
✓ Confidence assessment for each data point
✓ Clear summary that an AI colleague could use for further analysis
✓ Course rigor index (1-5) with detailed justification
✓ Overall transcript assessment (Exceptional/Strong/Solid/Average/Below Average)"""
    
    def _build_parsing_prompt(
        self,
        transcript_text: str,
        student_name: Optional[str] = None,
        school_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build the prompt for parsing a transcript with deep reasoning requirements.
        
        PHASE 4: Enhanced with school context for rigor weighting
        
        Args:
            transcript_text: Raw transcript text
            student_name: Student name if available
            school_context: School enrichment data for contextual analysis
            
        Returns:
            Detailed parsing prompt
        """
        prompt = f"""DETAILED TRANSCRIPT ANALYSIS REQUEST

Student: {student_name or 'Unknown Student'}
Analysis Date: {__import__('datetime').datetime.now().strftime('%B %d, %Y')}
{'='*70}

"""
        # Add school context section if provided (PHASE 4)
        if school_context:
            school_section = f"""SCHOOL CONTEXT FOR RIGOR EVALUATION:
School: {school_context.get('school_name', 'Unknown')}
State: {school_context.get('state_code', 'Unknown')}
AP Courses Available: {school_context.get('ap_courses_available', 'Unknown')}
Honors Programs: {school_context.get('honors_programs', 'Unknown')}
Opportunity Score: {school_context.get('opportunity_score', 'N/A')}/100

RIGOR INTERPRETATION CONTEXT:
- An AP or Honors course at this school carries specific weight
- Heavy AP load is particularly impressive for this school
- Standard courses at this school need context about what's available
- Graduation rate at this school: {school_context.get('graduation_rate', 'Unknown')}%

{'='*70}

"""
            prompt += school_section
        
        prompt += f"""RAW TRANSCRIPT DATA:
{transcript_text}

{'='*70}

CRITICAL ANALYSIS REQUIREMENTS:

Use deep reasoning to understand the complete academic picture. Go beyond surface-level data extraction.
"""
        if school_context:
            prompt += f"\nSTUDENT'S ACADEMIC RIGOR IN SCHOOL CONTEXT:\n"
            prompt += f"- Assess course selection relative to school's offerings (see School Context above)\n"
            prompt += f"- High proportion of AP/Honors is impressive given availability\n"
            prompt += f"- Note when student takes limited AP/Honors despite high availability\n"
            prompt += f"- Consider enrollment patterns and course difficulty progression\n\n"
        
        prompt += f"""
=================================================================================
SECTION 1: COMPREHENSIVE GRADE DATA EXTRACTION
=================================================================================

Please extract and detail EVERY course with this information:
- Course Name (exact as listed)
- Level (AP / Honors / Standard / Other - specify)
- Grade (letter grade and percentage if available)
- Credit Hours
- Semester/Quarter/Year
- Subject Area (Math, Science, English, Social Studies, Language, Technology, Elective)

Format as a detailed table. If percentage isn't shown, estimate from letter grade using standard scale.

=================================================================================
SECTION 2: GPA AND ACADEMIC STANDING
=================================================================================

Extract and explain:
- Unweighted GPA (scale noted, e.g., 4.0)
- Weighted GPA (scale noted, e.g., 5.0, and multiplier system explained)
- Class Rank (e.g., 5 of 480) and Percentile
- Academic Status (excellent standing, honors, dean's list, etc.)
- Cumulative Average by Subject Area (Math avg, Science avg, etc.)

If class rank appears as weighted GPA calculation, explain the weighting system.

=================================================================================
SECTION 3: ACADEMIC TRAJECTORY AND TREND ANALYSIS
=================================================================================

Analyze grade progression year by year:
- Grade 9: Overall average and pattern
- Grade 10: Overall average and pattern
- Grade 11: Overall average and pattern
- Grade 12: Overall average and pattern (if available)

Identify trends:
- Is performance IMPROVING (grades trending up)?
- Is performance DECLINING (grades trending down)?
- Is performance STABLE (consistent)?
- Are there SUBJECT-SPECIFIC trends? (Improving in Math but declining in English?)

For each trend, provide SPECIFIC EVIDENCE (e.g., "Grade 9: 3.8 avg→ Grade 10: 3.9 avg → Grade 11: 4.0 avg = IMPROVING")

=================================================================================
SECTION 4: COURSE RIGOR ANALYSIS
=================================================================================

Calculate and explain Course Rigor Index (1-5 scale):

Count:
- Total AP/Advanced courses taken
- Total Honors courses taken
- Total Standard courses taken
- Calculate AP/Honors percentage of total coursework

Rate on 1-5 Scale:
- Level 5 (Exceptional): 60%+ AP/Honors courses, consistent AP/Honors across all years
- Level 4 (Strong): 40-60% AP/Honors, good progression into advanced courses
- Level 3 (Solid): 20-40% AP/Honors, some advanced course taking
- Level 2 (Limited): <20% AP/Honors, mostly standard courses
- Level 1 (Minimal): No AP/Honors courses, all standard courses

Provide ONE SENTENCE JUSTIFICATION for your rating.

IMPORTANT: Also assess COURSE SELECTION STRATEGY:
- Did the student take AP/Honors in core subjects (Math, Science, English)?
- Or only in peripheral areas?
- Does the choice suggest strength-building or strength-showcasing?
- Any evident course avoidance patterns?

=================================================================================
SECTION 5: STANDARDIZED TEST SCORES
=================================================================================

If present, extract and note:
- SAT score(s) and percentile
- ACT score(s) and percentile
- PSAT score
- AP Exam scores (specific by exam with date)
- Any National Merit recognition

Compare standardized test performance to GPA (aligned or misaligned?).

=================================================================================
SECTION 6: NON-ACADEMIC FACTORS
=================================================================================

Extract and note:
- Attendance: Days absent and tardy
- Disciplinary record: Any infractions or conduct issues noted
- Honor roll status: Semesters made honor roll
- Honors and awards: All listed honors, awards, and special recognitions
- Leadership: Any indicators of leadership roles or responsibilities

=================================================================================
SECTION 7: OVERALL ASSESSMENT
=================================================================================

Transcript Quality Rating: Exceptional | Strong | Solid | Average | Below Average
Justification: 2-3 sentences explaining this rating with specific evidence.

Confidence Level: High | Medium | Low
If Medium or Low: What data is missing or unclear?

Depth of Analysis:
Show your reasoning for each major conclusion. For example:
- "Transcript Quality = Strong because: (1) 3.9 GPA in weighted system, (2) 50% of courses AP/Honors,
  (3) Consistent upward trend from 9-12, (4) AP scores of 4-5 on all exams"

=================================================================================
SECTION 8: EXECUTIVE SUMMARY
=================================================================================

Write a 6-8 sentence paragraph synthesizing this student's academic profile for a college admissions officer.

Include:
- Overall academic performance and trajectory
- Notable strengths and any areas of concern
- Most impressive achievements or unusual factors
- How rigor of coursework compares to typical high school offerings
- Overall readiness for advanced STEM work

Make this summary actionable for downstream AI agents.

=================================================================================

CRITICAL FORMAT REQUIREMENTS:
✓ Use clear section headers as shown above
✓ Present all course data in a detailed Markdown table (not abbreviated)
✓ Show all calculations and reasoning
✓ Highlight key numbers that other agents need to see
✓ Provide both summary AND detailed data
✓ Explain any inferences you make ("Estimated percentage as X% based on B+ grade typical = 87%")

OUTPUT STRUCTURE:
[Section 1: Course Table with all detail]
[Section 2: GPA breakdown]
[Section 3: Trend Analysis with year-by-year details]
[Section 4: Rigor Index with calculation shown]
[Section 5: Standardized Tests - if present]
[Section 6: Non-academic factors]
[Section 7: Overall Assessment with detailed reasoning]
[Section 8: Executive Summary]"""
        
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
            'summary': None,
            'grade_table_markdown': None,
            'grade_table_headers': None,
            'grade_table_rows': None,
            'course_rigor_index': None
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

        # Extract course rigor index
        rigor_match = re.search(
            r'Course Rigor Index[:\s]+([1-5])',
            response_text,
            re.IGNORECASE
        )
        if rigor_match:
            parsed['course_rigor_index'] = int(rigor_match.group(1))
        
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

        table_data = self._extract_markdown_table(response_text)
        if table_data:
            parsed['grade_table_markdown'] = table_data['markdown']
            parsed['grade_table_headers'] = table_data['headers']
            parsed['grade_table_rows'] = table_data['rows']
        
        return parsed

    def _extract_markdown_table(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Extract the first Markdown table from the response."""
        lines = [line.rstrip() for line in response_text.splitlines()]
        for idx in range(len(lines) - 1):
            header_line = lines[idx]
            divider_line = lines[idx + 1]
            if '|' not in header_line:
                continue
            if not re.match(r'^\s*\|?\s*[-:|\s]+\|\s*$', divider_line):
                continue

            table_lines = [header_line, divider_line]
            row_idx = idx + 2
            while row_idx < len(lines):
                row_line = lines[row_idx]
                if not row_line.strip() or '|' not in row_line:
                    break
                table_lines.append(row_line)
                row_idx += 1

            headers = self._parse_markdown_row(table_lines[0])
            rows = [self._normalize_row(self._parse_markdown_row(line), len(headers)) for line in table_lines[2:]]
            return {
                'markdown': "\n".join(table_lines),
                'headers': headers,
                'rows': rows
            }
        return None

    def _parse_markdown_row(self, row_line: str) -> List[str]:
        """Parse a Markdown table row into cells."""
        cleaned = row_line.strip().strip('|')
        return [cell.strip() for cell in cleaned.split('|')]

    def _normalize_row(self, row: List[str], target_len: int) -> List[str]:
        """Ensure table rows align with headers for rendering."""
        if len(row) > target_len:
            return row[:target_len]
        if len(row) < target_len:
            return row + [""] * (target_len - len(row))
        return row
    
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
    
    def _calculate_contextual_rigor_index(
        self,
        parsed_data: Dict[str, Any],
        school_context: Dict[str, Any]
    ) -> float:
        """
        PHASE 4: Calculate contextual rigor index based on school's AP/Honors availability.
        
        The rigor index accounts for what was AVAILABLE to the student.
        High AP/Honors load is more impressive if the school has few such courses.
        High rigor is less impressive if the student avoided abundant AP/Honors options.
        
        Index Range: 0.0 - 5.0 (5.0 = exceptional rigor within school's context)
        
        Args:
            parsed_data: Parsed transcript data from analysis
            school_context: School enrichment data with AP/Honors availability
            
        Returns:
            Float between 0.0 and 5.0 representing contextual rigor
        """
        try:
            # Get course information from parsed data
            course_levels = parsed_data.get('course_levels', {})
            ap_count = course_levels.get('AP', 0) or 0
            honors_count = course_levels.get('Honors', 0) or 0
            total_courses = sum(course_levels.values()) if course_levels else 0
            
            # Get school's AP/Honors availability
            ap_available = school_context.get('ap_courses_available', 0) or 0
            honors_available = school_context.get('honors_programs', 0) or 0
            
            if total_courses == 0:
                return 0.0
            
            # Calculate proportion of student's load in AP/Honors
            ap_honors_proportion = (ap_count + honors_count) / total_courses if total_courses > 0 else 0
            
            # Calculate relative AP/Honors availability at school
            # If school offers many AP courses, high AP load is expected
            # If school offers few AP courses, high AP load is impressive
            ap_availability_factor = 1.0
            if ap_available > 0:
                # If student took AP courses, evaluate relative to availability
                if ap_count > 0:
                    ap_availability_factor = min(2.0, 0.5 + (ap_count / ap_available))
                else:
                    # Student didn't take AP despite availability
                    ap_availability_factor = 0.5
            
            # Base rigor score from course selection
            base_rigor = ap_honors_proportion * 4.0  # 0-4.0 scale
            
            # Apply school context multiplier
            contextual_rigor = base_rigor * ap_availability_factor
            
            # Cap at 5.0
            contextual_rigor = min(5.0, contextual_rigor)
            
            # Adjust for GPA - high rigor is more impressive with high GPA
            gpa = parsed_data.get('gpa') or 0
            if gpa >= 3.9:
                contextual_rigor = min(5.0, contextual_rigor + 0.3)
            elif gpa < 3.0:
                contextual_rigor = max(0.0, contextual_rigor - 0.2)
            
            logger.info(
                f"Contextual Rigor Index Calculated",
                extra={
                    'school': school_context.get('school_name'),
                    'ap_count': ap_count,
                    'honors_count': honors_count,
                    'total_courses': total_courses,
                    'ap_available': ap_available,
                    'ap_honors_proportion': ap_honors_proportion,
                    'contextual_rigor': round(contextual_rigor, 2)
                }
            )
            
            return round(contextual_rigor, 2)
            
        except Exception as e:
            logger.warning(f"Error calculating contextual rigor index: {e}")
            return 0.0
    
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
