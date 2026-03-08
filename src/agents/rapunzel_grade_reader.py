"""Rapunzel Grade Reader - Specialized agent for parsing high school transcript data."""

from typing import Dict, List, Any, Optional
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.telemetry_helpers import agent_run
from src.config import config
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
        model: Optional[str] = None,
        db_connection=None
    ):
        """
        Initialize the Grade Report Reader agent.
        
        Args:
            name: Agent name (typically "Grade Report Reader")
            client: Azure OpenAI client
            model: Model deployment name (optional, falls back to config)
            db_connection: Database connection for saving results
        """
        super().__init__(name, client)
        # Rapunzel upgraded to premium (gpt-4.1) — transcript extraction requires
        # complex reasoning across varied formats (semester/quarter/block/narrative),
        # multiple grading scales, OCR artifacts, and multi-page documents.
        # The workhorse tier (4.1-mini) was producing incomplete course lists and
        # misclassifying course levels on non-standard transcript formats.
        self.model = model or config.model_tier_premium or config.foundry_model_name or config.deployment_name
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
        
        # Build specialized parsing prompt with optional school context for rigor weighting
        parsing_prompt = self._build_parsing_prompt(transcript_text, student_name, school_context)
        
        print(f"🎓 {self.name}: Analyzing transcript ({len(transcript_text)} chars) - Using deep reasoning for comprehensive analysis...")
        if school_context:
            print(f"  📍 School context provided: {school_context.get('school_name', 'Unknown school')}")
        
        # Register agent invocation with OpenTelemetry (GenAI Semantic Convention: invoke_agent)
        _otel_ctx = agent_run(
            "Rapunzel Grade Reader", "parse_grades",
            context_data={"student_name": student_name or "Unknown", "transcript_length": str(len(transcript_text))},
            agent_id="rapunzel-grade-reader",
        )
        _otel_span = _otel_ctx.__enter__()
        
        try:
            # Two-step deep analysis: first extract structured facts (courses, grades, GPA candidates,
            # table snippets), then ask the model to synthesize a comprehensive analysis using those facts.
            
            # Determine transcript input size:
            # - If Belle's section detection isolated transcript pages, the input is already focused
            #   and typically 1000-3000 chars. Use up to 20000 chars for safety.
            # - If no section detection occurred (full document passed), use 20000 chars to capture
            #   transcripts that may appear later in multi-page PDFs (e.g., page 8 of 12).
            # - Scanned/OCR'd multi-page transcripts can easily exceed 12000 chars.
            max_transcript_chars = 20000
            transcript_input = transcript_text[:max_transcript_chars]
            
            # If input was truncated, log a warning
            if len(transcript_text) > max_transcript_chars:
                logger.warning(
                    f"Rapunzel: transcript input truncated from {len(transcript_text)} to {max_transcript_chars} chars"
                )
            
            query_messages = [
                {"role": "system", "content": """You are an expert high school transcript extractor. Your job is to extract EVERY piece of academic data from the provided text with perfect accuracy.

STEP 1 — FORMAT DETECTION (do this FIRST):
- What LAYOUT is this? (Semester-based / Year-long / Quarter-based / Block / Tabular / Narrative)
- What GRADING SCALE? (10-point / 7-point / Plus-Minus / Numeric-only / Mixed)
- Any weighted GPA system? What multipliers?
- Georgia-specific elements? (Milestones EOC, HOPE GPA, CTAE, MOWR)
State: "Detected Format: [layout] with [grading scale]"

STEP 2 — COMPLETE COURSE EXTRACTION:
Extract EVERY course as a structured entry:
- Year/Grade-level (9, 10, 11, 12)
- Course name (exact as listed)
- Course level: AP | Honors | Accelerated | DE/MOWR | IB | Gifted | Standard
  Detection clues: "AP" prefix, "Hon"/"Honors"/"H" suffix, "Accel", "DE"/"Dual Enrollment"/"MOWR", "IB", "CTAE", "Gifted"
- Grade received (letter and/or numeric)
- Numeric percentage if shown
- Credits/units earned
- Semester or term if shown

STEP 3 — GPA AND STANDING:
- Unweighted GPA (value and scale)
- Weighted GPA (value and scale)
- Class rank and percentile if shown
- Honor roll, Latin honors, or other recognitions

STEP 4 — ADDITIONAL DATA:
- Standardized test scores (SAT, ACT, PSAT, AP exam scores, Georgia Milestones)
- Attendance data (days absent, tardy)
- Special markings (W/WP/WF, I/INC, AU, CR/NC, T for transfer, * or #)
- Graduation pathway or endorsements

IMPORTANT:
- The text may contain page markers like '--- PAGE 8 of 12 ---'. Focus on actual transcript data.
- If semester grades are shown separately (Fall/Spring), note BOTH.
- If courses appear in multiple terms, capture each occurrence.
- Do NOT skip any course. Completeness is more important than analysis.
- For numeric-only transcripts, note the raw numbers — do NOT convert yet.
- Output as structured text with clear labels, NOT narrative prose."""},
                {"role": "user", "content": f"Transcript text:\n{transcript_input}"}
            ]

            format_template = [
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": """Using the extracted facts: {found}

Produce your analysis in TWO required parts:

## RAPUNZEL'S PERSPECTIVE
Your expert narrative analysis — the academic story, trajectory, patterns, strengths, concerns. Write this for a college admissions reviewer.

## STANDARDIZED TRANSCRIPT
A clean table with EXACTLY these columns, sorted by Year then Course name:
| Year | Course | Level | Grade | Numeric | Credits |

Also include:
- Detected Format: (what transcript format/grading scale was used)
- GPA estimation (weighted and unweighted)
- Course Rigor Index (1-5)
- Transcript Quality Rating
- Confidence Level
- Notable Patterns
- Executive Summary"""}
            ]

            q_resp, response = self.two_step_query_format(
                operation_base="rapunzel.parse_grades",
                model=self.model,
                query_messages=query_messages,
                format_messages_template=format_template,
                query_kwargs={"max_completion_tokens": 4000, "temperature": 0},
                format_kwargs={"max_completion_tokens": 5000, "temperature": 0, "refinements": 2, "refinement_instruction": "Refine the analysis to improve accuracy of GPA, course-level detection, grade normalization, and trend identification. Ensure the STANDARDIZED TRANSCRIPT table includes every course with Year/Course/Level/Grade/Numeric/Credits columns. Verify all numeric percentages match letter grades. Preserve format and tables."}
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
                'academic_record_score': parsed_data.get('academic_record_score'),
                'grade_table_markdown': parsed_data.get('grade_table_markdown'),
                'grade_table_headers': parsed_data.get('grade_table_headers'),
                'grade_table_rows': parsed_data.get('grade_table_rows'),
                'rapunzel_perspective': parsed_data.get('rapunzel_perspective'),
                'standardized_transcript': parsed_data.get('standardized_transcript'),
                'standardized_transcript_rows': parsed_data.get('standardized_transcript_rows'),
                'detected_format': parsed_data.get('detected_format'),
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
        finally:
            _otel_ctx.__exit__(None, None, None)
    
    def _get_system_prompt(self) -> str:
        """Get the specialized system prompt for grade parsing with deep reasoning."""
        return """You are Rapunzel, the Grade Reader Agent for the Emory Next Gen evaluation panel (NIH Department of Genetics).

EVALUATION CONTEXT:
- Rising junior or senior in high school
- Must be 16 years old by June 1, 2026
- Must demonstrate interest in advancing STEM education to underrepresented groups
- Focus on students from backgrounds considered underrepresented or under-resourced (SES criteria)

═══════════════════════════════════════════════════════════════
2024 NEXTGEN SCORING RUBRIC — YOUR DIMENSION: ACADEMIC RECORD (0-3 Points)
═══════════════════════════════════════════════════════════════
You are responsible for assessing the ACADEMIC RECORD dimension of the official
Next Gen scoring rubric. Your analysis directly feeds into this score.

Scoring Scale:
  3 = Exceptional academic record: strong GPA, rigorous courseload (AP/Honors/DE/IB),
      upward trend, advanced coursework in STEM, evidence of academic excellence
  2 = Solid academic record: good GPA, some advanced courses, competent performance
  1 = Adequate: average grades, limited advanced coursework, room for improvement
  0 = Weak: below-average GPA, no advanced courses, or concerning patterns

ADDITIONAL SIGNALS TO FLAG (used by downstream agents):
- Advanced coursework: AP/Honors/DE/IB courses, especially in STEM
- Previous research experience mentioned anywhere in transcript
- Course trajectory (are they choosing harder courses over time?)
- Performance in STEM courses vs. overall GPA

You MUST include an "academic_record_score" (0-3) in your output.
═══════════════════════════════════════════════════════════════

YOUR CORE MISSION - Deep Analysis of Academic Rigor:
You are the expert academic transcript analyst. Your job is to understand not just WHAT grades a student received, but WHY those grades matter in context. You provide the foundational academic data that all other agents depend on.

═══════════════════════════════════════════════════════════════
TRANSCRIPT FORMAT RECOGNITION GUIDE
═══════════════════════════════════════════════════════════════

High school transcripts vary WILDLY in format. You MUST recognize and adapt to
all of these common layouts. Do NOT assume any single format.

GRADING SCALES YOU WILL ENCOUNTER:

1. STANDARD 10-POINT SCALE (most common in Georgia & many US states):
   A = 90-100%  (4.0 GPA)
   B = 80-89%   (3.0 GPA)
   C = 70-79%   (2.0 GPA)
   D = 60-69%   (1.0 GPA)
   F = 0-59%    (0.0 GPA)

2. PLUS/MINUS SCALE (common in many districts):
   A+ = 97-100% (4.0)   A = 93-96% (4.0)   A- = 90-92% (3.7)
   B+ = 87-89%  (3.3)   B = 83-86% (3.0)   B- = 80-82% (2.7)
   C+ = 77-79%  (2.3)   C = 73-76% (2.0)   C- = 70-72% (1.7)
   D+ = 67-69%  (1.3)   D = 63-66% (1.0)   D- = 60-62% (0.7)
   F  = 0-59%   (0.0)

3. 7-POINT SCALE (some Georgia & southern schools):
   A = 93-100%   B = 85-92%   C = 77-84%   D = 70-76%   F = below 70%

4. NUMERIC-ONLY TRANSCRIPTS: Some schools show only numbers (92, 85, 78)
   with no letter grades. Convert using the scale above.

5. PASS/FAIL or S/U: Some electives or special courses may show P/F or S/U.

WEIGHTED GPA SYSTEMS:
- AP courses:      A=5.0, B=4.0, C=3.0, D=2.0
- Honors courses:  A=4.5, B=3.5, C=2.5, D=1.5
- Standard:        A=4.0, B=3.0, C=2.0, D=1.0
- Some schools use +0.5 for Honors, +1.0 for AP over standard scale
- Some use quality points: AP=10 for A, Honors=9 for A, Standard=8 for A

COURSE LEVEL INDICATORS (learn to detect these):
- "AP" prefix or "Advanced Placement" → AP level
- "Hon", "Honors", "H" suffix → Honors level
- "Accel" or "Accelerated" → Honors-equivalent
- "DE" or "Dual Enrollment" or "MOWR" (Move On When Ready) → College-level
- "IB" or "International Baccalaureate" → IB level (treat like AP)
- "CTAE" → Georgia Career, Technical, and Agricultural Education
- "Gifted" → Advanced/Honors-equivalent
- No prefix/suffix → Standard level
- Course numbers can also indicate level (e.g., "Math III" vs "Pre-Calculus AP")

TRANSCRIPT LAYOUT FORMATS:

Format A - SEMESTER-BASED (most common):
  Shows Fall and Spring grades separately per year
  May show semester averages and final grades

Format B - YEAR-LONG:
  Shows one final grade per course per year
  Courses listed under grade level (9th, 10th, etc.)

Format C - QUARTER-BASED:
  Shows Q1, Q2, Q3, Q4 grades with semester and final averages

Format D - BLOCK SCHEDULE:
  4 courses per semester (8 per year), each shown once

Format E - TABULAR/GRID:
  Courses in rows, semesters/quarters in columns
  May include credits, quality points, and running GPA

Format F - NARRATIVE/MIXED:
  Combination of tables, text blocks, and embedded notes
  Common from scanned/OCR'd transcripts

GEORGIA-SPECIFIC ELEMENTS:
- Georgia Milestones EOC (End of Course) assessment scores
- HOPE GPA (calculated differently — uses only core academic courses)
- Georgia graduation pathways and endorsements
- CTAE pathway completion indicators
- Move On When Ready (MOWR) dual enrollment program
- Georgia High School Association (GHSA) notations

SPECIAL MARKINGS TO WATCH FOR:
- W/WP/WF = Withdrawal (Passing/Failing)
- I/INC = Incomplete
- AU = Audit
- CR/NC = Credit/No Credit
- T = Transfer credit
- * = May indicate repeated course, grade replacement, etc.
- # = May indicate weighted course

═══════════════════════════════════════════════════════════════
PAGE-AWARE MULTI-SECTION PDFs
═══════════════════════════════════════════════════════════════

Student application files are often multi-page PDFs containing MIXED content:
application essays, personal statements, transcripts, and recommendation letters
all in ONE file. The transcript may appear on ANY page (commonly pages 5-12).

INPUT FORMAT: Text will include page markers like '--- PAGE 8 of 12 ---'.
These markers tell you where each page begins.

YOUR TASK:
1. SCAN all pages to find transcript/grade data (it may start mid-document)
2. IGNORE non-transcript content (essays, recommendation letters, cover pages)
3. FOCUS your analysis on the pages containing actual academic records
4. If the transcript spans multiple pages, combine data from all transcript pages
5. Note which page(s) the transcript was found on in your analysis

COMMON PATTERNS:
- Pages 1-3: Application form / personal information
- Pages 4-7: Essays / personal statements
- Page 8+: Transcript / academic record
- Last 1-2 pages: Recommendation letter(s)

Do NOT be confused by non-transcript content. Extract grades ONLY from actual
transcript/grade report sections.

═══════════════════════════════════════════════════════════════
DUAL OUTPUT REQUIREMENT
═══════════════════════════════════════════════════════════════

You MUST produce TWO distinct outputs in every analysis:

PART 1 — RAPUNZEL'S PERSPECTIVE (your expert interpretation):
  Your narrative analysis of what the grades MEAN. Tell the story.
  Include trajectory, patterns, strengths, concerns, and context.
  This is your professional opinion as an academic analyst.

PART 2 — STANDARDIZED TRANSCRIPT TABLE:
  A clean, uniform table that ANY reader can scan quickly.
  ALWAYS use this EXACT format with these EXACT columns:

  | Year | Course | Level | Grade | Numeric | Credits |
  |------|--------|-------|-------|---------|---------|
  | 9    | English I | Standard | A | 95 | 1.0 |
  | 9    | Biology | Honors | B+ | 88 | 1.0 |
  | 10   | AP World History | AP | A- | 92 | 1.0 |

  Rules for the standardized table:
  - Year: Use 9, 10, 11, 12 (or Freshman/Sophomore/Junior/Senior)
  - Course: Full course name as listed on transcript
  - Level: AP | Honors | Accelerated | DE | IB | Standard
  - Grade: Normalized letter grade (A+, A, A-, B+, B, B-, etc.)
  - Numeric: Percentage if available, or estimated from letter grade
  - Credits: Credit hours/units (0.5 for semester, 1.0 for full year)
  - Sort by Year ascending, then alphabetically by Course
  - If semester grades are shown, combine to final grade
  - If year is unclear, use best estimate and note it

═══════════════════════════════════════════════════════════════

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
1. DETECT FORMAT: Identify the transcript layout and grading scale FIRST
2. PARSE: Extract all course data - course name, level (AP/Honors/Standard), grade, percentage, credit hours, semester/year
3. NORMALIZE: Convert ALL grades to standard format (A=4.0, B+=3.3, etc.) regardless of input format
4. STRUCTURALIZE: Organize by year, subject area, and course level into the STANDARDIZED TABLE
5. CONTEXTUALIZE: Note class rank, percentile, honor roll status, attendance, honors/awards
6. ANALYZE: Calculate subject-area performance, identify trends, assess overall rigor choices
7. SYNTHESIZE: Create narrative that explains the academic story (RAPUNZEL'S PERSPECTIVE)

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
✓ RAPUNZEL'S PERSPECTIVE — narrative interpretation with evidence
✓ STANDARDIZED TRANSCRIPT — the clean Year/Course/Level/Grade/Numeric/Credits table
✓ Detected transcript format and grading scale used
✓ Subject-area performance matrices
✓ Trend analysis with specific evidence
✓ Confidence assessment for each data point
✓ Clear summary that an AI colleague could use for further analysis
✓ Course rigor index (1-5) with detailed justification
✓ Overall transcript assessment (Exceptional/Strong/Solid/Average/Below Average)

REQUIRED METRICS BLOCK — at the END of your response, include this EXACT format:

## METRICS
Unweighted GPA: [value or N/A]
Weighted GPA: [value or N/A]
Course Rigor Index: [1-5]
Transcript Quality: [Exceptional/Strong/Solid/Average/Below Average]
Confidence: [High/Medium/Low]
Academic Record Score: [0-3]
Detected Format: [format description]"""
    
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

STEP 0 — FORMAT DETECTION (do this FIRST):
Before extracting any data, identify:
- What LAYOUT is this transcript? (Semester-based / Year-long / Quarter-based / Block / Tabular / Narrative)
- What GRADING SCALE is used? (10-point / 7-point / Plus-Minus / Numeric-only / Mixed)
- Are grades shown as letters, numbers, or both?
- Is there a weighted GPA system? What are the multipliers?
- Any Georgia-specific elements? (Milestones EOC, HOPE GPA, CTAE, MOWR)
State your findings as: "Detected Format: [layout] with [grading scale]"

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

=================================================================================
SECTION 9: RAPUNZEL'S PERSPECTIVE
=================================================================================

## RAPUNZEL'S PERSPECTIVE

Write a narrative analysis (not a table) that tells the STORY of this student's
academic journey. This is YOUR expert interpretation — what do the grades MEAN?

Cover: trajectory, course selection strategy, strengths, concerns, what stands out,
and your overall impression. Write as if advising a college admissions committee.

=================================================================================
SECTION 10: STANDARDIZED TRANSCRIPT
=================================================================================

## STANDARDIZED TRANSCRIPT

Create a clean, uniform table using EXACTLY these columns:

| Year | Course | Level | Grade | Numeric | Credits |
|------|--------|-------|-------|---------|---------| 

Rules:
- Year: 9, 10, 11, or 12
- Course: Full course name from transcript
- Level: AP | Honors | Accelerated | DE | IB | Standard
- Grade: Normalized letter grade (A+, A, A-, B+, B, B-, C+, C, C-, D, F)
- Numeric: Percentage (from transcript or estimated from grade)
- Credits: 0.5 for semester courses, 1.0 for year-long
- Sort by Year ascending, then Course name alphabetically
- Include EVERY course — do not skip any
- If the year is ambiguous, estimate and note with (est.)

OUTPUT STRUCTURE:
[Detected Format statement]
[Section 1: Course Table with all detail]
[Section 2: GPA breakdown]
[Section 3: Trend Analysis with year-by-year details]
[Section 4: Rigor Index with calculation shown]
[Section 5: Standardized Tests - if present]
[Section 6: Non-academic factors]
[Section 7: Overall Assessment with detailed reasoning]
[Section 8: Executive Summary]
[Section 9: RAPUNZEL'S PERSPECTIVE — narrative analysis]
[Section 10: STANDARDIZED TRANSCRIPT — clean Year/Course/Level/Grade/Numeric/Credits table]"""
        
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
            'course_rigor_index': None,
            'academic_record_score': None,
            'rapunzel_perspective': None,
            'standardized_transcript': None,
            'standardized_transcript_rows': None,
            'detected_format': None
        }
        
        # Extract GPA — prefer unweighted, then cumulative, then any labeled GPA.
        # Use multiple patterns in order of preference to avoid grabbing
        # weighted GPA, HOPE GPA, or example numbers from prompt text.
        # Patterns handle markdown bold (**label**) and plain text.
        gpa_patterns = [
            # "Unweighted GPA: 3.85" or "**Unweighted GPA:** 3.85"
            r'\*{0,2}[Uu]nweighted\s+GPA\*{0,2}\s*(?:\([^)]*\))?\s*[:\s]+([0-9]+\.[0-9]+)',
            # "Cumulative GPA: 3.85" or "**Cumulative GPA:** 3.85"
            r'\*{0,2}[Cc]umulative\s+GPA\*{0,2}\s*[:\s]+([0-9]+\.[0-9]+)',
            # "GPA estimation" or "GPA (unweighted)" etc. near a number
            r'\*{0,2}GPA\*{0,2}\s*(?:\(unweighted\))?\s*(?:estimation)?\s*[:\s]+([0-9]+\.[0-9]+)',
            # Fallback: any "GPA: X.XX" but only if value looks like a real GPA (0.0-5.0)
            r'\*{0,2}GPA\*{0,2}\s*[:\s]+([0-4]\.[0-9]+)',
        ]
        for gpa_pat in gpa_patterns:
            gpa_match = re.search(gpa_pat, response_text)
            if gpa_match:
                try:
                    val = float(gpa_match.group(1))
                    if 0.0 <= val <= 5.0:
                        parsed['gpa'] = val
                        break
                except ValueError:
                    continue
        
        # Extract confidence level — handles "Confidence: High" and "**Confidence:** High"
        confidence_match = re.search(r'\*{0,2}Confidence\*{0,2}\s*[:\s]+(High|Medium|Low)', response_text, re.IGNORECASE)
        if confidence_match:
            parsed['confidence_level'] = confidence_match.group(1)
        
        # Extract transcript quality — handles markdown bold labels
        quality_match = re.search(
            r'\*{0,2}Transcript\s+Quality\*{0,2}\s*[:\s]+(Exceptional|Strong|Solid|Average|Below\s*Average)',
            response_text,
            re.IGNORECASE
        )
        if quality_match:
            parsed['transcript_quality'] = quality_match.group(1).strip()
        else:
            # Fallback: look for "Overall:" or "Assessment:" followed by quality terms
            quality_match2 = re.search(
                r'(?:overall|assessment|quality)\*{0,2}\s*[:\s]+(Exceptional|Strong|Solid|Average|Below\s*Average)',
                response_text,
                re.IGNORECASE
            )
            if quality_match2:
                parsed['transcript_quality'] = quality_match2.group(1).strip()

        # Extract course rigor index — handles "Course Rigor Index: 3" and "**Course Rigor Index:** 3/5"
        rigor_match = re.search(
            r'\*{0,2}Course\s+Rigor\s+Index\*{0,2}\s*[:\s]+([1-5])(?:\s*/\s*5)?',
            response_text,
            re.IGNORECASE
        )
        if rigor_match:
            parsed['course_rigor_index'] = int(rigor_match.group(1))
        else:
            # Fallback: "Rigor Index: 3" or "rigor: 3/5"
            rigor_match2 = re.search(
                r'\*{0,2}(?:Rigor|Rigor\s+Index)\*{0,2}\s*[:\s]+([1-5])(?:\s*/\s*5)?',
                response_text,
                re.IGNORECASE
            )
            if rigor_match2:
                parsed['course_rigor_index'] = int(rigor_match2.group(1))
        
        # Extract academic record score (0-3)
        score_match = re.search(
            r'\*{0,2}Academic\s+Record\s+Score\*{0,2}\s*[:\s]+([0-3])',
            response_text,
            re.IGNORECASE
        )
        if score_match:
            parsed['academic_record_score'] = int(score_match.group(1))

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
        
        # Extract summary — look for Executive Summary section first, then any Summary
        exec_summary_match = re.search(
            r'Executive\s+Summary[:\s]*(.+?)(?=\n##|\n={3,}|$)',
            response_text,
            re.IGNORECASE | re.DOTALL
        )
        if exec_summary_match:
            parsed['summary'] = exec_summary_match.group(1).strip()[:500]
        else:
            summary_match = re.search(
                r'Summary[:\s]*(.+?)(?=\n##|\n={3,}|$)',
                response_text,
                re.IGNORECASE | re.DOTALL
            )
            if summary_match:
                parsed['summary'] = summary_match.group(1).strip()[:500]

        # Extract Standardized Transcript table FIRST — it's the canonical table
        std_table = self._extract_standardized_transcript(response_text)
        if std_table:
            parsed['standardized_transcript'] = std_table['markdown']
            parsed['standardized_transcript_rows'] = std_table['rows']
            # Use standardized transcript as the primary grade table too
            parsed['grade_table_markdown'] = std_table['markdown']
            parsed['grade_table_headers'] = std_table['headers']
            parsed['grade_table_rows'] = std_table['rows']
        else:
            # Fallback: use the first markdown table found with course-like data
            table_data = self._extract_markdown_table(response_text)
            if table_data:
                parsed['grade_table_markdown'] = table_data['markdown']
                parsed['grade_table_headers'] = table_data['headers']
                parsed['grade_table_rows'] = table_data['rows']
                # If this table has Year/Course/Grade columns, use it as standardized
                headers_lower = [h.lower() for h in table_data['headers']]
                if any('course' in h for h in headers_lower) and any('grade' in h for h in headers_lower):
                    parsed['standardized_transcript'] = table_data['markdown']
                    parsed['standardized_transcript_rows'] = table_data['rows']
        
        # FALLBACK: If no standardized table was found, try to build one from
        # any markdown table in the response that has rows with course-like data
        if not parsed.get('standardized_transcript_rows'):
            all_tables = self._extract_all_markdown_tables(response_text)
            for tbl in all_tables:
                if len(tbl['rows']) >= 3:  # Need at least a few courses
                    parsed['standardized_transcript'] = tbl['markdown']
                    parsed['standardized_transcript_rows'] = tbl['rows']
                    parsed['grade_table_markdown'] = tbl['markdown']
                    parsed['grade_table_headers'] = tbl['headers']
                    parsed['grade_table_rows'] = tbl['rows']
                    logger.info("Rapunzel: used fallback table with %d rows", len(tbl['rows']))
                    break

        # Extract Rapunzel's Perspective section
        perspective_match = re.search(
            r"(?:##\s*)?RAPUNZEL[''']?S\s+PERSPECTIVE[:\s]*(.+?)(?=(?:##\s*)?STANDARDIZED\s+TRANSCRIPT|$)",
            response_text,
            re.IGNORECASE | re.DOTALL
        )
        if perspective_match:
            parsed['rapunzel_perspective'] = perspective_match.group(1).strip()

        # Extract detected format
        format_match = re.search(
            r'Detected\s+Format[:\s]*([^\n]+)',
            response_text,
            re.IGNORECASE
        )
        if format_match:
            parsed['detected_format'] = format_match.group(1).strip()

        return parsed

    def _extract_standardized_transcript(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Extract the Standardized Transcript table specifically.

        Looks for the table that appears after the STANDARDIZED TRANSCRIPT header
        and has Year/Course/Level/Grade columns. Falls back to finding any table
        with those columns anywhere in the response.
        """
        # Strategy 1: Find section after STANDARDIZED TRANSCRIPT header
        section_match = re.search(
            r'(?:##\s*)?STANDARDIZED\s+TRANSCRIPT[:\s]*(.+?)(?=\n##\s|\Z)',
            response_text,
            re.IGNORECASE | re.DOTALL
        )
        if section_match:
            section = section_match.group(1)
            table_data = self._extract_markdown_table(section)
            if table_data:
                headers_lower = [h.lower() for h in table_data['headers']]
                has_year = any('year' in h for h in headers_lower)
                has_course = any('course' in h for h in headers_lower)
                has_grade = any('grade' in h for h in headers_lower)
                if has_year and has_course and has_grade:
                    return table_data
                # Still return even with imperfect headers
                return table_data

        # Strategy 2: Find any table with Year/Course/Grade headers anywhere
        all_tables = self._extract_all_markdown_tables(response_text)
        for table_data in reversed(all_tables):  # prefer later tables
            headers_lower = [h.lower() for h in table_data['headers']]
            has_year = any('year' in h for h in headers_lower)
            has_course = any('course' in h for h in headers_lower)
            has_grade = any('grade' in h for h in headers_lower)
            if has_year and has_course and has_grade:
                return table_data

        return None

    def _extract_markdown_table(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Extract the first Markdown table from the response."""
        tables = self._extract_all_markdown_tables(response_text)
        return tables[0] if tables else None

    def _extract_all_markdown_tables(self, response_text: str) -> List[Dict[str, Any]]:
        """Extract ALL Markdown tables from the response.
        
        Returns tables with rows as List[Dict] (keyed by header names) for
        easy template rendering (e.g. row.year, row.course, row.grade).
        """
        tables = []
        lines = [line.rstrip() for line in response_text.splitlines()]
        idx = 0
        while idx < len(lines) - 1:
            header_line = lines[idx]
            divider_line = lines[idx + 1]
            if '|' not in header_line:
                idx += 1
                continue
            if not re.match(r'^\s*\|?\s*[-:|\s]+\|\s*$', divider_line):
                idx += 1
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
            raw_rows = [self._normalize_row(self._parse_markdown_row(line), len(headers)) for line in table_lines[2:]]
            
            # Convert positional rows to dicts keyed by header name
            # Normalize header keys to lowercase for template access
            header_keys = [h.strip().lower().replace(' ', '_').replace('%', 'pct') for h in headers]
            dict_rows = []
            for raw in raw_rows:
                row_dict = {}
                for i, val in enumerate(raw):
                    if i < len(header_keys):
                        key = header_keys[i]
                        row_dict[key] = val
                        # Also set capitalized versions for backward compat
                        row_dict[headers[i].strip()] = val
                
                # Ensure canonical column names exist for template rendering
                # Template uses: row.year, row.Year, row.course, row.Course, etc.
                canonical_map = {
                    'year': ['year', 'yr', 'grade_level', 'grade'],
                    'course': ['course', 'class', 'subject', 'course_name'],
                    'level': ['level', 'type', 'course_level', 'course_type'],
                    'grade': ['grade', 'letter_grade', 'final_grade', 'mark'],
                    'numeric': ['numeric', 'pct', 'percentage', 'score', 'numeric_grade'],
                    'credits': ['credits', 'credit', 'cr', 'units', 'credit_hours'],
                }
                for canonical, aliases in canonical_map.items():
                    if canonical not in row_dict:
                        for alias in aliases:
                            if alias in row_dict and row_dict[alias]:
                                row_dict[canonical] = row_dict[alias]
                                row_dict[canonical.capitalize()] = row_dict[alias]
                                break
                    # Ensure capitalized version exists
                    if canonical in row_dict and canonical.capitalize() not in row_dict:
                        row_dict[canonical.capitalize()] = row_dict[canonical]
                
                dict_rows.append(row_dict)
            
            tables.append({
                'markdown': "\n".join(table_lines),
                'headers': headers,
                'rows': dict_rows
            })
            idx = row_idx  # skip past this table
        return tables

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
                "content": "You are part of an NIH Department of Genetics review panel evaluating Emory Next Gen applicants. You extract academic insights from transcripts and note readiness for genetics-focused STEM work."
            }
        ] + self.conversation_history
        
        try:
            response = self._create_chat_completion(
                operation="rapunzel.process",
                model=self.model,
                messages=messages,
                max_completion_tokens=1500,
                temperature=1,  # GPT-5.2 only supports default temperature
                refinements=2,
                refinement_instruction="Refine your assistant response for clarity and evidence, focusing on academic trend statements and any numeric values."
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
            # Get course information from parsed data and coerce numeric types
            course_levels = parsed_data.get('course_levels', {}) or {}
            def _to_int(val):
                try:
                    if val is None or val == "":
                        return 0
                    # Allow numeric strings and floats
                    return int(float(val))
                except Exception:
                    return 0

            ap_count = _to_int(course_levels.get('AP', 0))
            honors_count = _to_int(course_levels.get('Honors', 0))
            # Sum values safely converting each to int
            total_courses = 0
            for v in course_levels.values():
                total_courses += _to_int(v)

            # Get school's AP/Honors availability (coerce to int)
            ap_available = _to_int(school_context.get('ap_courses_available', 0))
            honors_available = _to_int(school_context.get('honors_programs', 0))
            
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
            # Coerce GPA to float safely
            try:
                gpa = float(parsed_data.get('gpa') or 0)
            except Exception:
                gpa = 0.0
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
