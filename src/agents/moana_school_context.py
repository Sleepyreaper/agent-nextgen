"""Moana School Context Analyzer — Contextualizes student achievements within
their school environment using NCES database data and AI-powered narrative analysis.

Workflow:
    NCES database → school_enriched_data → Naveen evaluation →
    Moana contextual narrative → Merlin final evaluation
"""

from typing import Dict, List, Any, Optional, Tuple
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.telemetry_helpers import agent_run

import re
import json


class MoanaSchoolContext(BaseAgent):
    """
    Moana — Student School Context Analyzer

    Uses NCES database data and AI to produce a rich contextual narrative about
    each student's school environment. Key outputs:

    * What did this school offer? (programs, resources, demographics)
    * What did the student do with what was available? (course selection, rigor)
    * How should their achievements be interpreted in context?
    * Are there equity factors that make their record more impressive?

    The contextual narrative is the key deliverable — a nuanced, data-grounded
    assessment that helps Merlin and reviewers understand what the student's
    academic record means given their school's capabilities and constraints.

    Key insight: A 4.0 GPA from a school with 2 AP classes and 70% free lunch
    is categorically different from the same GPA at a school with 20 APs and
    15% free lunch. Context defines opportunity.
    """
    
    def __init__(
        self,
        name: str,
        client: AzureOpenAI,
        model: Optional[str] = None,
        db_connection=None
    ):
        """
        Initialize Moana School Context Analyzer.
        
        Args:
            name: Agent name (typically "Moana School Context")
            client: Azure OpenAI client
            model: Model deployment name (if None falls back to config)
            db_connection: Database connection for storing/retrieving school data
        """
        super().__init__(name, client)
        # use configured model if none specified
        self.model = model or config.model_tier_workhorse or config.foundry_model_name or config.deployment_name
        self.db = db_connection
        
        # Cache for school lookups to avoid redundant API calls
        self.school_cache: Dict[str, Dict[str, Any]] = {}
    
    async def analyze_student_school_context(
        self,
        application: Dict[str, Any],
        transcript_text: Optional[str] = None,
        rapunzel_grades_data: Optional[Dict[str, Any]] = None,
        school_enrichment: Optional[Dict[str, Any]] = None,
        application_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Analyze student's school context using cached/enriched school data.
        
        Workflow:
        1. If school_enrichment provided (from Aurora via workflow): Use it directly
        2. Otherwise: Perform legacy analysis (backwards compatible)
        
        Args:
            application: Application data
            transcript_text: Grade report text (optional if using enriched school data)
            rapunzel_grades_data: Data from Rapunzel Grade Reader (contains school hints)
            school_enrichment: Pre-enriched school data from Aurora (via school_workflow)
                              If provided, skips school analysis and uses cached results
            application_id: Application ID for storing results in database (optional)
            
        Returns:
            Comprehensive school context analysis
        """
        student_name = self._resolve_student_name(application)
        self.add_to_history("user", f"Analyze school context for {student_name}")
        print(f"\n🌊 {self.name}: Discovering educational context for {student_name}...")
        
        with agent_run("Moana", "analyze_student_school_context", {"student": student_name, "application_id": str(application_id or "")}) as span:
            try:
                # CHECK: If school enrichment provided by workflow, use it directly
                if school_enrichment and school_enrichment.get('school_name'):
                    print(f"  ✓ Using cached/enriched school data from database")
                    return await self._analyze_with_enriched_school_data(
                        student_name=student_name,
                        application=application,
                        transcript_text=transcript_text,
                        rapunzel_grades_data=rapunzel_grades_data,
                        school_enrichment=school_enrichment,
                        application_id=application_id
                    )
                
                # FALLBACK: Legacy path for backwards compatibility
                print(f"  → No pre-enriched school data, performing analysis...")

                # Step 1: Extract school name and location
                school_info = await self._extract_school_info(transcript_text, application)
                
                if not school_info.get('school_name') or school_info.get('school_name') == 'High School':
                    print(f"⚠ Could not identify school from available data")
                    return {
                        'status': 'incomplete',
                        'student_name': student_name,
                        'error': 'School identification failed',
                        'confidence': 0
                    }
                
                print(f"  School Identified: {school_info['school_name']}")
                
                # Determine state and data availability
                school_state = school_info.get('state', '').upper()
                is_georgia_school = school_state in ['GA', 'GEORGIA']
                
                # Identify available data sources for this state
                available_data_sources = await self._identify_data_sources(school_state, school_info)
                
                if is_georgia_school:
                    print(f"  ✓ Georgia school detected - using local trained dataset")
                    school_info['georgia_data_available'] = True
                else:
                    print(f"  🔍 {school_state} school - checking local trained dataset...")
                
                # Step 2: Extract programs from transcript
                program_participation = await self._extract_program_participation(
                    transcript_text,
                    student_name,
                    rapunzel_grades_data=rapunzel_grades_data
                )
                
                # Step 3: Look up school in database or create profile
                school_profile = await self._get_or_create_school_profile(school_info)
                
                # Step 4: Analyze SES context
                ses_context = await self._analyze_socioeconomic_context(school_profile)
                
                # Step 4b: Analyze school resources and comparisons
                school_resources = self._analyze_school_resources(
                    school_profile,
                    school_info,
                    ses_context
                )
                
                # Step 5: Score student's access and participation
                scores = self._calculate_opportunity_scores(
                    school_profile,
                    program_participation,
                    ses_context
                )
                
                # Compile comprehensive analysis
                analysis = {
                    'status': 'success',
                    'student_name': student_name,
                    'school': {
                        'name': school_info['school_name'],
                        'city': school_info.get('city'),
                        'state': school_info.get('state'),
                        'identification_confidence': school_info.get('confidence', 0.7)
                    },
                    'school_profile': school_profile,
                    'ses_context': ses_context,
                    'program_participation': program_participation,
                    'school_resources': school_resources,
                    'opportunity_scores': scores,
                    'contextual_summary': self._build_summary(
                        student_name,
                        school_info,
                        program_participation,
                        scores,
                        ses_context,
                        school_resources,
                        rapunzel_grades_data
                    ),
                    'model_used': self.model
                }
                
                self.add_to_history("assistant", json.dumps(analysis, default=str)[:1000])
                return analysis
            
            except Exception as e:
                import traceback
                error_detail = traceback.format_exc()
                print(f"⚠ Exception in analyze_student_school_context: {e}")
                print(f"  Traceback: {error_detail[:200]}")
                return {
                    'status': 'error',
                    'student_name': student_name,
                    'error': str(e),
                    'error_type': type(e).__name__
                }
    
    async def _analyze_with_enriched_school_data(
        self,
        student_name: str,
        application: Dict[str, Any],
        transcript_text: str,
        rapunzel_grades_data: Optional[Dict[str, Any]],
        school_enrichment: Dict[str, Any],
        application_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Enriched path: Use NCES database school data + Naveen's evaluation to
        build a deep contextual understanding of the student's school environment.

        Workflow:
        1. Extract student's program participation from transcript (regex)
        2. Build school profile from enrichment data (database + Naveen eval)
        3. Calculate opportunity scores with real data
        4. Use AI to produce a rich contextual narrative about this student
           at THIS school — how should their achievements be interpreted?

        Args:
            student_name: Student's name
            application: Application data
            transcript_text: Grade report text
            rapunzel_grades_data: Grade analysis from Rapunzel
            school_enrichment: Pre-enriched school data from database

        Returns:
            School context analysis with AI-powered contextual narrative
        """
        try:
            print(f"  ✓ Using enriched school data: {school_enrichment.get('school_name')}")

            # Extract what student participated in
            program_participation = await self._extract_program_participation(
                transcript_text,
                student_name,
                rapunzel_grades_data=rapunzel_grades_data
            )

            # Build school profile from enrichment — use all available DB fields
            school_profile = {
                'school_name': school_enrichment.get('school_name'),
                'school_district': school_enrichment.get('school_district'),
                'state_code': school_enrichment.get('state_code'),
                'county': school_enrichment.get('county_name'),
                'enrollment_size': school_enrichment.get('total_students') or school_enrichment.get('enrollment_size'),
                'student_teacher_ratio': school_enrichment.get('student_teacher_ratio'),
                'socioeconomic_level': school_enrichment.get('socioeconomic_level'),
                'ap_count': self._safe_count(school_enrichment.get('ap_classes_count') or school_enrichment.get('ap_course_count', 0)),
                'ib_offerings': school_enrichment.get('ib_program_available') or school_enrichment.get('ib_offerings', 0),
                'honors_programs': school_enrichment.get('honors_course_count') or school_enrichment.get('honors_programs', 0),
                'stem_programs': school_enrichment.get('stem_program_available') or school_enrichment.get('stem_programs', 0),
                'dual_enrollment': school_enrichment.get('dual_enrollment_available', False),
                'graduation_rate': school_enrichment.get('graduation_rate'),
                'college_placement_rate': school_enrichment.get('college_acceptance_rate') or school_enrichment.get('college_placement_rate'),
                'free_lunch_pct': school_enrichment.get('free_lunch_percentage'),
                'is_title_i': school_enrichment.get('is_title_i'),
                'is_charter': school_enrichment.get('is_charter'),
                'is_magnet': school_enrichment.get('is_magnet'),
                'locale_code': school_enrichment.get('locale_code'),
                'district_exp_per_pupil': school_enrichment.get('district_exp_per_pupil'),
                'school_investment_level': school_enrichment.get('school_investment_level'),
                'opportunity_score': school_enrichment.get('opportunity_score'),
                'diversity_index': school_enrichment.get('diversity_index'),
                'analysis_date': school_enrichment.get('analysis_date'),
                'enrichment_source': 'nces_database',
                # Naveen's evaluation insights (if present)
                'school_summary': school_enrichment.get('school_profile', {}).get('school_summary', '') if isinstance(school_enrichment.get('school_profile'), dict) else '',
                'context_for_student': school_enrichment.get('school_profile', {}).get('context_for_student', '') if isinstance(school_enrichment.get('school_profile'), dict) else '',
            }

            # SES context from real data
            free_lunch = school_enrichment.get('free_lunch_percentage')
            ses_level = self._infer_ses_level(free_lunch)
            ses_context = {
                'socioeconomic_level': ses_level,
                'free_lunch_pct': free_lunch,
                'is_title_i': school_enrichment.get('is_title_i'),
                'district_exp_per_pupil': school_enrichment.get('district_exp_per_pupil'),
                'district_poverty_pct': school_enrichment.get('district_poverty_pct'),
                'diversity_index': school_enrichment.get('diversity_index'),
                'regional_context': f"{school_enrichment.get('state_code', 'US')} school",
                'based_on_enrichment': True,
            }

            # Calculate scores with enriched data
            scores = self._calculate_opportunity_scores_from_enrichment(
                school_profile,
                program_participation,
                school_enrichment
            )

            # Build resources summary
            school_resources = {
                'ap_programs_available': school_profile.get('ap_count', 0),
                'ib_available': bool(school_profile.get('ib_offerings')),
                'stem_available': bool(school_profile.get('stem_programs')),
                'dual_enrollment_available': bool(school_profile.get('dual_enrollment')),
                'enrollment_size_category': self._categorize_size(school_profile.get('enrollment_size')),
                'investment_level': school_enrichment.get('school_investment_level', 'unknown'),
                'opportunity_score': school_enrichment.get('opportunity_score', 0),
                'student_teacher_ratio': school_profile.get('student_teacher_ratio'),
                'is_title_i': school_profile.get('is_title_i'),
            }

            # Build AI-powered contextual narrative
            contextual_summary = await self._build_contextual_narrative(
                student_name,
                school_profile,
                program_participation,
                scores,
                rapunzel_grades_data,
                ses_context,
                school_resources,
            )

            # Final analysis
            analysis = {
                'status': 'success',
                'student_name': student_name,
                'school': {
                    'name': school_enrichment.get('school_name'),
                    'state': school_enrichment.get('state_code'),
                    'district': school_enrichment.get('school_district'),
                    'identification_confidence': 0.99,
                },
                'school_profile': school_profile,
                'ses_context': ses_context,
                'program_participation': program_participation,
                'school_resources': school_resources,
                'opportunity_scores': scores,
                'contextual_summary': contextual_summary,
                'model_used': self.model,
                'data_source': 'nces_database',
            }
            
            self.add_to_history("assistant", json.dumps(analysis, default=str)[:1000])
            
            # Save to database if connection available and application_id provided
            if self.db and application_id:
                try:
                    self.db.save_moana_school_context(
                        application_id=application_id,
                        agent_name=self.name,
                        school_name=analysis.get('school', {}).get('name'),
                        program_access_score=analysis.get('opportunity_scores', {}).get('program_access_score'),
                        program_participation_score=analysis.get('opportunity_scores', {}).get('program_participation_score'),
                        relative_advantage_score=analysis.get('opportunity_scores', {}).get('relative_advantage_score'),
                        ap_courses_available=school_profile.get('ap_count'),
                        ap_courses_taken=program_participation.get('ap_courses_taken'),
                        contextual_summary=analysis.get('contextual_summary'),
                        parsed_json=json.dumps(analysis, ensure_ascii=True, default=str)
                    )
                except Exception as db_error:
                    print(f"⚠️  {self.name}: Could not save to database: {db_error}")
            
            return analysis
            
        except Exception as e:
            import traceback
            print(f"⚠ Error in enriched school analysis: {e}")
            print(traceback.format_exc()[:200])
            # Fall back to legacy analysis
            return await self._legacy_school_analysis(
                student_name=student_name,
                application=application,
                transcript_text=transcript_text,
                rapunzel_grades_data=rapunzel_grades_data
            )
    
    def _categorize_size(self, enrollment: Optional[int]) -> str:
        """Categorize school size by enrollment."""
        enrollment_count = self._safe_count(enrollment)
        if not enrollment_count:
            return "unknown"
        if enrollment_count < 500:
            return "small"
        if enrollment_count < 1500:
            return "medium"
        if enrollment_count < 3000:
            return "large"
        return "very_large"

    @staticmethod
    def _safe_count(value: Any) -> int:
        """Normalize counts that might come in as lists, strings, or numbers."""
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, (list, tuple, set)):
            return len(value)
        if isinstance(value, dict):
            return len(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
            try:
                return int(float(stripped))
            except ValueError:
                return 0
        return 0
    
    def _calculate_opportunity_scores_from_enrichment(
        self,
        school_profile: Dict[str, Any],
        program_participation: Dict[str, Any],
        school_enrichment: Dict[str, Any]
    ) -> Dict[str, float]:
        """Calculate scores using real NCES database data and student activity."""
        # ── Program Access Score (0-100): What's available at this school ──
        ap_available = self._safe_count(school_profile.get('ap_count', 0))
        honors_available = self._safe_count(school_profile.get('honors_programs', 0))
        has_ib = bool(school_profile.get('ib_offerings'))
        has_stem = bool(school_profile.get('stem_programs'))
        has_dual = bool(school_profile.get('dual_enrollment'))

        program_access = min(100, (
            (min(ap_available, 20) / 20) * 30 +     # AP breadth (0-30)
            (min(honors_available, 30) / 30) * 20 +  # Honors breadth (0-20)
            (15 if has_ib else 0) +                   # IB availability (0-15)
            (15 if has_stem else 0) +                 # STEM programs (0-15)
            (10 if has_dual else 0) +                 # Dual enrollment (0-10)
            10                                        # Base for any school
        ))

        # ── Program Participation Score (0-100): What the student used ──
        ap_taken = self._safe_count(program_participation.get('ap_courses_taken', 0))
        honors_taken = self._safe_count(program_participation.get('honors_courses_taken', 0))
        stem_taken = len(program_participation.get('stem_courses', []))
        total_advanced = program_participation.get('total_advanced_courses', ap_taken + honors_taken + stem_taken)

        participation = min(100, (
            (min(ap_taken, 8) / 8) * 40 +            # AP participation (0-40)
            (min(honors_taken, 10) / 10) * 35 +      # Honors participation (0-35)
            (min(stem_taken, 5) / 5) * 15 +           # STEM participation (0-15)
            (10 if total_advanced >= 3 else 0)         # Rigor bonus (0-10)
        ))

        # ── Relative Advantage Score (0-100): Student vs school capacity ──
        if ap_available > 0:
            ap_utilization = min(ap_taken / ap_available, 1.0) * 100
        else:
            # No AP courses available — student can't be faulted
            ap_utilization = 70 if ap_taken == 0 else 90

        relative_advantage = min(100, (
            ap_utilization * 0.50 +
            participation * 0.30 +
            (20 if program_participation.get('gt_program') else 0)
        ))

        # ── Context-Adjusted Score: Factor in NCES benchmark comparisons ──
        # A student who maximizes limited resources deserves extra credit
        context_bonus = 0
        free_lunch_pct = school_enrichment.get('free_lunch_percentage')
        if free_lunch_pct is not None:
            try:
                fl = float(free_lunch_pct)
                if fl > 60 and total_advanced >= 2:
                    context_bonus += 10  # High-need school, student still took advanced
                elif fl > 40 and total_advanced >= 3:
                    context_bonus += 5
            except (ValueError, TypeError):
                pass

        overall = min(100, (
            program_access * 0.25 +
            participation * 0.30 +
            relative_advantage * 0.30 +
            context_bonus +
            15  # Base
        ))

        # Use Naveen's opportunity score if available (weighted blend)
        naveen_score = school_enrichment.get('opportunity_score')
        if naveen_score:
            try:
                overall = overall * 0.6 + float(naveen_score) * 0.4
            except (ValueError, TypeError):
                pass

        return {
            'program_access_score': round(program_access, 1),
            'program_participation_score': round(participation, 1),
            'relative_advantage_score': round(relative_advantage, 1),
            'overall_opportunity_score': round(overall, 1),
            'context_bonus': context_bonus,
            'interpretation': self._interpret_scores(program_access, participation, {
                'ses_level': self._infer_ses_level(free_lunch_pct),
            }),
        }
    
    @staticmethod
    def _infer_ses_level(free_lunch_pct) -> str:
        """Infer SES level from free/reduced lunch percentage."""
        if free_lunch_pct is None:
            return 'unknown'
        try:
            fl = float(free_lunch_pct)
        except (ValueError, TypeError):
            return 'unknown'
        if fl < 20:
            return 'High'
        if fl < 40:
            return 'Medium-High'
        if fl < 60:
            return 'Medium'
        return 'Low'

    async def _build_contextual_narrative(
        self,
        student_name: str,
        school_profile: Dict[str, Any],
        program_participation: Dict[str, Any],
        scores: Dict[str, float],
        rapunzel_grades_data: Optional[Dict[str, Any]] = None,
        ses_context: Optional[Dict[str, Any]] = None,
        school_resources: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Use AI to produce a rich contextual narrative about this student's
        school environment and how their achievements should be interpreted.

        This is the KEY output of Moana — a nuanced, fact-grounded analysis
        that helps Merlin and reviewers understand what the student's record
        means in the context of their school's capabilities and constraints.
        """
        school_name = school_profile.get('school_name', 'their school')

        # Build the context data for AI
        school_facts = []
        for label, key in [
            ("Enrollment", "enrollment_size"),
            ("Student-Teacher Ratio", "student_teacher_ratio"),
            ("Graduation Rate", "graduation_rate"),
            ("College Placement Rate", "college_placement_rate"),
            ("Free/Reduced Lunch %", "free_lunch_pct"),
            ("AP Courses Offered", "ap_count"),
            ("Honors Courses", "honors_programs"),
            ("Title I School", "is_title_i"),
            ("Charter School", "is_charter"),
            ("Magnet School", "is_magnet"),
            ("Dual Enrollment", "dual_enrollment"),
            ("STEM Programs", "stem_programs"),
            ("IB Program", "ib_offerings"),
            ("Investment Level", "school_investment_level"),
            ("Locale", "locale_code"),
            ("District Per-Pupil Expenditure", "district_exp_per_pupil"),
            ("Opportunity Score", "opportunity_score"),
        ]:
            val = school_profile.get(key)
            if val is not None and val != '' and val != 0 and val is not False:
                school_facts.append(f"  {label}: {val}")

        # Student's coursework
        ap_taken = program_participation.get('ap_courses_taken', [])
        honors_taken_raw = program_participation.get('honors_courses_taken', [])
        honors_taken = self._safe_count(honors_taken_raw)
        de_taken = program_participation.get('de_courses_taken', [])
        stem_courses = program_participation.get('stem_courses', [])
        total_advanced = program_participation.get('total_advanced_courses', 0)

        student_facts = [
            f"  AP Courses Taken: {len(ap_taken) if isinstance(ap_taken, list) else ap_taken}",
        ]
        if isinstance(ap_taken, list) and ap_taken:
            student_facts.append(f"  AP Subjects: {', '.join(ap_taken[:10])}")
        student_facts.append(f"  Honors Courses Taken: {honors_taken}")
        if isinstance(honors_taken_raw, list) and honors_taken_raw:
            student_facts.append(f"  Honors Subjects: {', '.join(honors_taken_raw[:10])}")
        if isinstance(de_taken, list) and de_taken:
            student_facts.append(f"  Dual Enrollment Courses: {len(de_taken)}")
            student_facts.append(f"  DE Subjects: {', '.join(de_taken[:10])}")
        if stem_courses:
            student_facts.append(f"  STEM Courses: {', '.join(stem_courses[:8])}")
        student_facts.append(f"  Total Advanced Courses: {total_advanced}")
        if program_participation.get('gt_program'):
            student_facts.append("  Gifted/Accelerated Program: Yes")

        # Grade data
        grade_facts = []
        if rapunzel_grades_data:
            if rapunzel_grades_data.get('gpa') is not None:
                grade_facts.append(f"  GPA: {rapunzel_grades_data['gpa']}")
            if rapunzel_grades_data.get('gpa_scale'):
                grade_facts.append(f"  GPA Scale: {rapunzel_grades_data['gpa_scale']}")
            if rapunzel_grades_data.get('class_rank'):
                grade_facts.append(f"  Class Rank: {rapunzel_grades_data['class_rank']}")
            if rapunzel_grades_data.get('weighted_gpa') is not None:
                grade_facts.append(f"  Weighted GPA: {rapunzel_grades_data['weighted_gpa']}")

        # Scores
        score_facts = [
            f"  Program Access Score: {scores.get('program_access_score', 'N/A')}/100",
            f"  Program Participation Score: {scores.get('program_participation_score', 'N/A')}/100",
            f"  Relative Advantage Score: {scores.get('relative_advantage_score', 'N/A')}/100",
            f"  Overall Opportunity Score: {scores.get('overall_opportunity_score', 'N/A')}/100",
        ]
        if scores.get('context_bonus', 0) > 0:
            score_facts.append(f"  Context Bonus: +{scores['context_bonus']} (high-need school, student pursued rigor)")

        # Naveen's insights if available
        naveen_summary = school_profile.get('school_summary', '')
        naveen_context = school_profile.get('context_for_student', '')

        prompt = f"""You are Moana, an education equity expert analyzing a scholarship applicant's school context.

STUDENT: {student_name}
SCHOOL: {school_name}

SCHOOL DATA (from NCES database):
{chr(10).join(school_facts) if school_facts else '  Limited data available'}

{"SCHOOL EVALUATION (from Naveen):" + chr(10) + "  " + naveen_summary if naveen_summary else ""}
{"STUDENT CONTEXT NOTE:" + chr(10) + "  " + naveen_context if naveen_context else ""}

STUDENT'S COURSEWORK:
{chr(10).join(student_facts)}

{"GRADES:" + chr(10) + chr(10).join(grade_facts) if grade_facts else "GRADES: Not yet available"}

OPPORTUNITY SCORES:
{chr(10).join(score_facts)}

NCES BENCHMARKS:
- National graduation rate: 87% | GA: 84%
- Free/reduced lunch national avg: 52%
- AP participation national avg: ~35% take at least 1 AP
- Student-teacher ratio national avg: ~16:1
- Per-pupil spending national avg: ~$14,000

Write a 6-10 sentence contextual assessment of {student_name}'s school environment and how their
academic record should be interpreted. Address:
1. What kind of school is this? (resources, demographics, opportunities available)
2. How did the student use what was available? (Did they maximize opportunities?)
3. How should their GPA/grades be interpreted given this school context?
4. What does their course selection reveal about their motivation and initiative?
5. Are there equity factors (high-need school, limited AP access, Title I) that make
   their achievements more impressive?

Be specific and grounded in the data. Avoid generic praise. This assessment will be used by
the final evaluator (Merlin) to make scholarship decisions."""

        try:
            response = self._create_chat_completion(
                operation="moana.contextual_narrative",
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "You are Moana, an education equity and school context expert. "
                        "You produce concise, data-grounded contextual assessments that help "
                        "scholarship evaluators understand what a student's achievements mean "
                        "given their school environment. Be specific, cite the data, and avoid "
                        "generic statements. A 4.0 GPA from a school with 2 AP courses and 75% "
                        "free lunch is categorically different from the same GPA at a school "
                        "with 20 APs and 15% free lunch. Context defines opportunity."
                    )},
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=800,
                temperature=0.5,
            )

            if (response and hasattr(response, 'choices')
                    and response.choices
                    and getattr(response.choices[0].message, 'content', None)):
                narrative = response.choices[0].message.content.strip()
                print(f"  ✓ AI contextual narrative generated ({len(narrative)} chars)")
                return narrative

        except Exception as e:
            print(f"  ⚠ AI narrative failed ({e}), falling back to template")

        # Fallback: template-based summary
        return self._build_template_summary(
            student_name, school_profile, program_participation,
            scores, rapunzel_grades_data
        )

    def _build_template_summary(
        self,
        student_name: str,
        school_profile: Dict[str, Any],
        program_participation: Dict[str, Any],
        scores: Dict[str, float],
        rapunzel_grades_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Fallback template-based summary when AI call fails."""
        school_name = school_profile.get('school_name', 'their school')
        ap_available = self._safe_count(school_profile.get('ap_count', 0))
        ap_taken = self._safe_count(program_participation.get('ap_courses_taken', 0))
        investment_level = school_profile.get('school_investment_level', 'moderate')

        parts = [
            f"{student_name} attends {school_name}, a {investment_level}-investment school "
            f"with an opportunity score of {school_profile.get('opportunity_score', 'N/A')}/100."
        ]

        if ap_available > 0:
            parts.append(
                f"The school offers {ap_available} AP course(s). "
                f"{student_name} took {ap_taken} AP course(s), "
                f"demonstrating {'strong' if ap_taken >= 3 else 'moderate'} engagement "
                f"with advanced curricula."
            )

        honors_taken = self._safe_count(program_participation.get('honors_courses_taken', 0))
        if honors_taken > 0:
            parts.append(
                f"{student_name} also participated in {honors_taken} "
                f"honors courses, showing consistent rigor seeking."
            )

        free_lunch = school_profile.get('free_lunch_pct')
        if free_lunch is not None:
            try:
                fl = float(free_lunch)
                if fl > 52:
                    parts.append(
                        f"The school's free/reduced lunch rate of {fl:.0f}% exceeds "
                        f"the national average (52%), indicating a higher-need environment."
                    )
            except (ValueError, TypeError):
                pass

        if rapunzel_grades_data and rapunzel_grades_data.get('gpa'):
            parts.append(
                f"Combined with a GPA of {rapunzel_grades_data['gpa']}, "
                f"{student_name} shows strong academic performance within their school context."
            )

        return " ".join(parts)
    
    async def _legacy_school_analysis(
        self,
        student_name: str,
        application: Dict[str, Any],
        transcript_text: str,
        rapunzel_grades_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Fallback to original school analysis logic for backwards compatibility.
        Called when enriched data is not available.
        """
        # Extract school name and location (original logic)
        school_info = await self._extract_school_info(transcript_text, application)
        
        if not school_info.get('school_name') or school_info.get('school_name') == 'High School':
            print(f"⚠ Could not identify school from available data")
            return {
                'status': 'incomplete',
                'student_name': student_name,
                'error': 'School identification failed',
                'confidence': 0
            }
        
        print(f"  School Identified: {school_info['school_name']}")
        
        # Determine state and data availability
        school_state = school_info.get('state', '').upper()
        is_georgia_school = school_state in ['GA', 'GEORGIA']
        
        # Identify available data sources for this state
        available_data_sources = await self._identify_data_sources(school_state, school_info)
        
        if is_georgia_school:
            print(f"  ✓ Georgia school detected - using local trained dataset")
            school_info['georgia_data_available'] = True
        else:
            print(f"  🔍 {school_state} school - checking local trained dataset...")
        
        # Extract programs from transcript
        program_participation = await self._extract_program_participation(
            transcript_text,
            student_name,
            rapunzel_grades_data=rapunzel_grades_data
        )
        
        # Look up school in database or create profile
        school_profile = await self._get_or_create_school_profile(school_info)
        
        # Analyze SES context
        ses_context = await self._analyze_socioeconomic_context(school_profile)
        
        # Analyze school resources and comparisons
        school_resources = self._analyze_school_resources(
            school_profile,
            school_info,
            ses_context
        )
        
        # Score student's access and participation
        scores = self._calculate_opportunity_scores(
            school_profile,
            program_participation,
            ses_context
        )
        
        # Compile comprehensive analysis
        analysis = {
            'status': 'success',
            'student_name': student_name,
            'school': {
                'name': school_info['school_name'],
                'city': school_info.get('city'),
                'state': school_info.get('state'),
                'identification_confidence': school_info.get('confidence', 0.7)
            },
            'school_profile': school_profile,
            'ses_context': ses_context,
            'program_participation': program_participation,
            'school_resources': school_resources,
            'opportunity_scores': scores,
            'contextual_summary': self._build_summary(
                student_name,
                school_info,
                program_participation,
                scores,
                ses_context,
                school_resources,
                rapunzel_grades_data
            ),
            'model_used': self.model
        }
        
        return analysis
    
    async def _extract_school_info(
        self,
        transcript_text: str,
        application: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract school name and location from transcript and application."""
        school_name = None
        confidence = 0.4

        application_school = self._extract_school_from_application(application)
        if application_school.get('school_name'):
            school_name = application_school['school_name']
            confidence = 0.85

        transcript_school = self._extract_school_from_transcript(transcript_text)
        if transcript_school:
            if not school_name or self._is_better_school_name(transcript_school, school_name):
                school_name = transcript_school
                confidence = 0.9

        city, state = self._extract_location_from_transcript(transcript_text)
        if not city and application_school.get('city'):
            city = application_school.get('city')
        if not state and application_school.get('state'):
            state = application_school.get('state')

        if not city:
            city = "Unknown City"
        if not state:
            state = "Unknown"

        if not school_name:
            school_name = 'High School'
            confidence = 0.4

        return {
            'school_name': school_name,
            'city': city,
            'state': state,
            'confidence': confidence,
            'extraction_method': 'application+transcript_parsing'
        }

    def _resolve_student_name(self, application: Dict[str, Any]) -> str:
        applicant_name = application.get('applicant_name') or application.get('ApplicantName')
        if applicant_name:
            return applicant_name
        student_id = application.get('student_id') or application.get('StudentID')
        if student_id:
            return str(student_id)
        application_id = application.get('application_id') or application.get('ApplicationID')
        if application_id:
            return f"Application {application_id}"
        return "Unknown"

    def _extract_school_from_application(self, application: Dict[str, Any]) -> Dict[str, Optional[str]]:
        school_data = application.get('school_data') if isinstance(application.get('school_data'), dict) else {}
        candidates = [
            school_data.get('name'),
            application.get('school_name'),
            application.get('SchoolName'),
            application.get('high_school'),
            application.get('HighSchool'),
            application.get('school')
        ]
        school_name = next((self._clean_school_name(name) for name in candidates if name), None)
        return {
            'school_name': school_name,
            'city': school_data.get('city') or application.get('school_city'),
            'state': school_data.get('state') or application.get('school_state')
        }

    def _extract_school_from_transcript(self, transcript_text: str) -> Optional[str]:
        if not transcript_text:
            return None

        labeled_match = re.search(
            r'(?:SCHOOL NAME|SCHOOL|HIGH SCHOOL)\s*[:\-]\s*([A-Za-z0-9\s&\-\'\.,]{3,100})',
            transcript_text,
            re.IGNORECASE
        )
        if labeled_match:
            candidate = self._clean_school_name(labeled_match.group(1))
            if candidate:
                return candidate

        header_lines = [line.strip() for line in transcript_text.splitlines()[:40] if line.strip()]
        candidates = []
        for line in header_lines:
            upper_line = line.upper()
            if any(bad in upper_line for bad in ['TRANSCRIPT', 'REPORT CARD', 'STUDENT ID', 'STUDENT NUMBER']):
                continue
            if any(bad in upper_line for bad in ['COUNTY', 'DISTRICT', 'PUBLIC SCHOOLS', 'BOARD OF EDUCATION']):
                continue
            if any(bad in upper_line for bad in ['LOCATION', 'ADDRESS']):
                continue
            if 'HIGH SCHOOL' in upper_line or upper_line.endswith('ACADEMY') or upper_line.endswith('SCHOOL'):
                candidates.append(line)

        best_candidate = None
        best_score = 0
        for candidate in candidates:
            score = 0
            upper_candidate = candidate.upper()
            if 'HIGH SCHOOL' in upper_candidate:
                score += 3
            if upper_candidate.endswith('HIGH SCHOOL'):
                score += 2
            if upper_candidate.isupper():
                score += 1
            if len(candidate) > 8:
                score += 1
            if score > best_score:
                best_score = score
                best_candidate = candidate

        return self._clean_school_name(best_candidate) if best_candidate else None

    def _extract_location_from_transcript(self, transcript_text: str) -> Tuple[Optional[str], Optional[str]]:
        location_patterns = [
            r'(?:CITY|LOCATION|ADDRESS)[:\s]+([A-Z][a-z\s]+),?\s*([A-Z]{2})',
            r'([A-Z][a-z\s]+),\s*([A-Z]{2})\s*\d{5}',
            r'([A-Z][a-z\s]+),\s*([A-Z]{2})(?:\s|$)'
        ]

        for pattern in location_patterns:
            match = re.search(pattern, transcript_text)
            if match:
                return match.group(1).strip(), match.group(2).strip()

        return None, None

    def _clean_school_name(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        cleaned = re.sub(r'\s+', ' ', str(name)).strip()
        cleaned = cleaned.strip('-:,')
        cleaned = re.sub(r'\b(Location|Campus|Site)\b$', '', cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r'\bSchool\s+School\b', 'School', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\bHigh School\s+School\b', 'High School', cleaned, flags=re.IGNORECASE)
        if len(cleaned) < 3:
            return None
        if any(bad in cleaned.upper() for bad in ['TRANSCRIPT', 'RECORD OF', 'STUDENT ID']):
            return None
        return cleaned

    def _is_better_school_name(self, candidate: str, current: str) -> bool:
        if not candidate:
            return False
        if not current:
            return True
        candidate_lower = candidate.lower()
        current_lower = current.lower()
        if 'location' in candidate_lower or 'address' in candidate_lower:
            return False
        if re.search(r'\bschool\s+school\b', candidate_lower):
            return False
        if 'high school' in candidate_lower and 'high school' not in current_lower:
            return True
        if len(candidate) > len(current) + 3:
            return True
        return False
    
    async def _extract_program_participation(
        self,
        transcript_text: str,
        student_name: str,
        rapunzel_grades_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Extract which advanced programs the student participated in.
        
        Primary source: Rapunzel's standardized_transcript_rows (per-course Level column).
        Fallback: Broad regex patterns on raw transcript text.
        """
        
        participation = {
            'ap_courses_taken': [],
            'ib_courses_taken': [],
            'honors_courses_taken': [],
            'de_courses_taken': [],
            'stem_courses': [],
            'gt_program': False,
            'other_programs': []
        }
        
        used_rapunzel = False
        
        # ── PRIMARY: Use Rapunzel's parsed transcript rows if available ──
        if rapunzel_grades_data and isinstance(rapunzel_grades_data, dict):
            # Rapunzel returns standardized_transcript_rows as list of lists:
            # [Year, Course, Level, Grade, Numeric, Credits]
            rows = (rapunzel_grades_data.get('standardized_transcript_rows')
                    or rapunzel_grades_data.get('grade_table_rows')
                    or [])
            headers = (rapunzel_grades_data.get('grade_table_headers') or [])
            
            # Find the Level column index
            level_idx = None
            course_idx = None
            headers_lower = [h.lower().strip() for h in headers] if headers else []
            for i, h in enumerate(headers_lower):
                if 'level' in h:
                    level_idx = i
                elif 'course' in h:
                    course_idx = i
            
            # Default positions if headers weren't parsed: Year=0, Course=1, Level=2
            if level_idx is None and rows and len(rows[0]) >= 3:
                level_idx = 2
            if course_idx is None and rows and len(rows[0]) >= 2:
                course_idx = 1
            
            if rows and level_idx is not None:
                for row in rows:
                    if not row or level_idx >= len(row):
                        continue
                    level = str(row[level_idx]).strip().upper()
                    course_name = str(row[course_idx]).strip() if course_idx is not None and course_idx < len(row) else ''
                    
                    if level in ('AP', 'ADVANCED PLACEMENT'):
                        participation['ap_courses_taken'].append(course_name)
                    elif level in ('HONORS', 'HNR', 'H', 'HON', 'HONOR'):
                        participation['honors_courses_taken'].append(course_name)
                    elif level in ('IB', 'INTERNATIONAL BACCALAUREATE'):
                        participation['ib_courses_taken'].append(course_name)
                    elif level in ('DE', 'DUAL ENROLLMENT', 'DUAL', 'COLLEGE'):
                        participation['de_courses_taken'].append(course_name)
                
                if (participation['ap_courses_taken'] or participation['honors_courses_taken']
                        or participation['ib_courses_taken'] or participation['de_courses_taken']):
                    used_rapunzel = True
                    print(f"    ✓ Program participation from Rapunzel: "
                          f"{len(participation['ap_courses_taken'])} AP, "
                          f"{len(participation['honors_courses_taken'])} Honors, "
                          f"{len(participation['ib_courses_taken'])} IB, "
                          f"{len(participation['de_courses_taken'])} DE")
        
        # ── FALLBACK: Broad regex extraction from transcript text ──
        if not used_rapunzel and transcript_text:
            text_lower = transcript_text.lower()
            
            # AP courses — multiple patterns
            ap_patterns = [
                r'AP\s+([A-Za-z\s&/]+?)(?:\s*[-:]\s*[A-F\+\-]|\s*\d|\s*$|\s*\|)',
                r'Advanced\s+Placement\s+([A-Za-z\s&/]+?)(?:\s*[-:]\s*[A-F\+\-]|\s*\d|\s*$|\s*\|)',
            ]
            for pat in ap_patterns:
                for m in re.finditer(pat, transcript_text, re.IGNORECASE | re.MULTILINE):
                    course = m.group(1).strip().rstrip('- :')
                    if course and course not in participation['ap_courses_taken']:
                        participation['ap_courses_taken'].append(course)
            
            # Honors courses — multiple patterns
            honors_patterns = [
                r'Honors\s+([A-Za-z\s&/]+?)(?:\s*[-:]\s*[A-F\+\-]|\s*\d|\s*$|\s*\|)',
                r'([A-Za-z\s&/]+?)\s+\(Honors\)',
                r'([A-Za-z\s&/]+?)\s+Honors(?:\s*[-:]\s*[A-F\+\-]|\s*\d|\s*$|\s*\|)',
                r'([A-Za-z\s&/]+?)\s+-\s*Honors',
                r'HNR\s+([A-Za-z\s&/]+?)(?:\s*[-:]\s*[A-F\+\-]|\s*\d|\s*$|\s*\|)',
                r'H\s+([A-Za-z\s&/]+?)(?:\s*[-:]\s*[A-F\+\-]|\s*\d|\s*$|\s*\|)',
            ]
            for pat in honors_patterns:
                for m in re.finditer(pat, transcript_text, re.IGNORECASE | re.MULTILINE):
                    course = m.group(1).strip().rstrip('- :')
                    if course and len(course) > 2 and course not in participation['honors_courses_taken']:
                        participation['honors_courses_taken'].append(course)
            
            # IB courses
            ib_patterns = [
                r'IB\s+([A-Za-z\s&/]+?)(?:\s*[-:]\s*[A-F\+\-]|\s*\d|\s*$|\s*\|)',
            ]
            for pat in ib_patterns:
                for m in re.finditer(pat, transcript_text, re.IGNORECASE | re.MULTILINE):
                    course = m.group(1).strip().rstrip('- :')
                    if course and course not in participation['ib_courses_taken']:
                        participation['ib_courses_taken'].append(course)
            
            # Dual Enrollment
            de_patterns = [
                r'(?:Dual\s+Enrollment|DE)\s+([A-Za-z\s&/]+?)(?:\s*[-:]\s*[A-F\+\-]|\s*\d|\s*$|\s*\|)',
            ]
            for pat in de_patterns:
                for m in re.finditer(pat, transcript_text, re.IGNORECASE | re.MULTILINE):
                    course = m.group(1).strip().rstrip('- :')
                    if course and course not in participation['de_courses_taken']:
                        participation['de_courses_taken'].append(course)
            
            if (participation['ap_courses_taken'] or participation['honors_courses_taken']
                    or participation['ib_courses_taken'] or participation['de_courses_taken']):
                print(f"    ✓ Program participation from regex: "
                      f"{len(participation['ap_courses_taken'])} AP, "
                      f"{len(participation['honors_courses_taken'])} Honors, "
                      f"{len(participation['ib_courses_taken'])} IB, "
                      f"{len(participation['de_courses_taken'])} DE")
        
        # ── STEM detection (always runs, supplements either source) ──
        stem_keywords = ['STEM', 'Computer Science', 'Physics', 'Chemistry', 'Biology', 'Mathematics', 'Engineering']
        for keyword in stem_keywords:
            if keyword.lower() in (transcript_text or '').lower():
                if keyword not in participation['stem_courses']:
                    participation['stem_courses'].append(keyword)
        
        # Check for gifted program
        if re.search(r'gifted|accelerated|advanced placement', transcript_text or '', re.IGNORECASE):
            participation['gt_program'] = True
        
        # Count total advanced courses (honors_courses_taken is now a list, not int)
        honors_count = len(participation['honors_courses_taken']) if isinstance(participation['honors_courses_taken'], list) else participation['honors_courses_taken']
        participation['total_advanced_courses'] = (
            len(participation['ap_courses_taken']) +
            honors_count +
            len(participation['ib_courses_taken']) +
            len(participation['de_courses_taken']) +
            len(participation['stem_courses'])
        )
        
        return participation
    
    async def _identify_data_sources(
        self,
        state: str,
        school_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Identify available data sources for a school's state.

        Now uses only the local trained dataset (school_enriched_data table)
        instead of external web sources.
        """
        state_code = state.upper()[:2] if state else ''

        return {
            'state': state,
            'sources': {'local_db': 'school_enriched_data'},
            'ai_search_enabled': False,
            'note': f"Using local trained dataset for {school_info.get('school_name', 'school')}",
        }

    async def _get_or_create_school_profile(
        self,
        school_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get school profile from the local trained dataset (database).
        
        Priority order:
        1. Check for human-approved enriched data in school_enriched_data table
        2. Check for CSV-imported government data
        3. Check for AI-analyzed enriched data (if confidence is high)
        4. Fall back to generic estimation
        """
        
        school_name = school_info['school_name']
        state = school_info.get('state', '').upper()
        is_georgia = state in ['GA', 'GEORGIA']
        
        # === NEW: Check enriched school database first ===
        try:
            from src.database import db
            enriched_school = db.get_school_enriched_data(school_name=school_name, state_code=state)
            
            if enriched_school:
                print(f"    ✓ Found enriched school data in database")
                
                # Prefer human-approved data
                if enriched_school.get('human_review_status') == 'approved':
                    print(f"    ✓ Using human-approved enriched data (opportunity score: {enriched_school.get('opportunity_score')})")
                    self.school_cache[school_name] = self._format_enriched_to_profile(enriched_school, approved=True)
                    return self.school_cache[school_name]
                
                # Accept CSV-imported government data (high-quality SES data)
                elif enriched_school.get('analysis_status') == 'csv_imported':
                    print(f"    ✓ Using CSV-imported government data (enrollment: {enriched_school.get('total_students')}, FRPL: {enriched_school.get('free_lunch_percentage')}%)")
                    self.school_cache[school_name] = self._format_enriched_to_profile(enriched_school, approved=False)
                    return self.school_cache[school_name]
                
                # Use AI-analyzed data if confidence is high
                elif enriched_school.get('analysis_status') == 'complete' and enriched_school.get('data_confidence_score', 0) >= 75:
                    print(f"    ✓ Using AI-analyzed enriched data (confidence: {enriched_school.get('data_confidence_score')}, score: {enriched_school.get('opportunity_score')})")
                    self.school_cache[school_name] = self._format_enriched_to_profile(enriched_school, approved=False)
                    return self.school_cache[school_name]
        except Exception as e:
            # If database lookup fails, continue with normal flow
            print(f"    ℹ Enriched data lookup unavailable: {str(e)}")
            pass
        
        # Check general cache
        if school_name in self.school_cache:
            return self.school_cache[school_name]

        # Try fuzzy match against database if exact match failed
        try:
            from src.database import db
            fuzzy_match = db.get_school_enriched_data_fuzzy(school_name=school_name, state_code=state if len(state) == 2 else None)
            if fuzzy_match:
                print(f"    ✓ Found school via fuzzy match: {fuzzy_match.get('school_name')}")
                self.school_cache[school_name] = self._format_enriched_to_profile(fuzzy_match, approved=False)
                return self.school_cache[school_name]
        except Exception as e:
            print(f"    ℹ Fuzzy lookup unavailable: {str(e)}")

        # No match in local trained dataset — use generic estimation
        print(f"    ℹ School '{school_name}' not found in local trained dataset — using generic estimates")
        profile = await self._create_generic_school_profile(school_info)
        self.school_cache[school_name] = profile
        return profile

    async def _create_generic_school_profile(
        self,
        school_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a generic school profile when school is not in the local trained dataset."""
        school_name = school_info['school_name']
        
        # Fallback to safe defaults
        return {
            'school_name': school_name,
            'school_type': 'Public',
            'ap_courses_available': 10,
            'ib_courses_available': 0,
            'honors_courses_available': 20,
            'stem_programs': ['Computer Science', 'Engineering', 'Robotics'],
            'total_students': 2000,
            'advanced_program_students': 300,
            'data_source': 'profile_estimation_fallback',
            'state': school_info.get('state', 'Unknown'),
            'error': 'School not found in local trained dataset - using conservative estimates'
        }
    
    async def _analyze_socioeconomic_context(
        self,
        school_profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze the SES context of the school area."""
        
        school_name = school_profile.get('school_name', '')
        
        # SES indicators based on school characteristics
        ses_analysis = {
            'analysis_method': 'school_characteristics',
            'median_household_income': None,
            'free_lunch_percentage': school_profile.get('free_reduced_lunch_pct'),  # From AI search if available
            'ses_level': 'Medium',  # Default
            'opportunity_level': 'Moderate',
            'data_reliability': 'Estimated',
            'data_source': school_profile.get('data_source', 'unknown')
        }
        
        # If AI search provided free lunch percentage, use it to infer SES
        if school_profile.get('free_reduced_lunch_pct'):
            free_lunch_pct = school_profile.get('free_reduced_lunch_pct', 0)
            if free_lunch_pct < 20:
                ses_analysis['ses_level'] = 'High'
                ses_analysis['opportunity_level'] = 'Extensive'
                ses_analysis['median_household_income'] = 95000
                ses_analysis['data_reliability'] = 'Public data'
            elif free_lunch_pct < 40:
                ses_analysis['ses_level'] = 'Medium-High'
                ses_analysis['opportunity_level'] = 'Moderate-High'
                ses_analysis['median_household_income'] = 75000
                ses_analysis['data_reliability'] = 'Public data'
            elif free_lunch_pct < 60:
                ses_analysis['ses_level'] = 'Medium'
                ses_analysis['opportunity_level'] = 'Moderate'
                ses_analysis['median_household_income'] = 55000
                ses_analysis['data_reliability'] = 'Public data'
            else:
                ses_analysis['ses_level'] = 'Low'
                ses_analysis['opportunity_level'] = 'Limited'
                ses_analysis['median_household_income'] = 35000
                ses_analysis['data_reliability'] = 'Public data'
        else:
            # Fallback: heuristics based on school name
            if any(word in school_name.lower() for word in ['academy', 'prep', 'international']):
                ses_analysis['ses_level'] = 'High'
                ses_analysis['opportunity_level'] = 'Extensive'
                ses_analysis['median_household_income'] = 95000
                ses_analysis['free_lunch_percentage'] = 15
            elif any(word in school_name.lower() for word in ['central', 'north', 'south', 'east', 'west']):
                ses_analysis['ses_level'] = 'Medium'
                ses_analysis['opportunity_level'] = 'Moderate'
                ses_analysis['median_household_income'] = 65000
                ses_analysis['free_lunch_percentage'] = 35
        
        return ses_analysis
    
    def _analyze_school_resources(
        self,
        school_profile: Dict[str, Any],
        school_info: Dict[str, Any],
        ses_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze the school's academic resources and compare to typical peers."""
        ap_available = school_profile.get('ap_courses_available', 0)
        ib_available = school_profile.get('ib_courses_available', 0)
        honors_available = school_profile.get('honors_courses_available', 0)
        stem_count = len(school_profile.get('stem_programs', []))
        is_georgia = school_profile.get('georgia_data_available', False)
        
        locale = self._infer_locale(school_info)
        ses_level = ses_context.get('ses_level', 'Medium')
        
        resource_score = (
            (ap_available / 20) * 35 +
            (ib_available / 8) * 15 +
            (min(honors_available, 30) / 30) * 25 +
            (stem_count / 5) * 15 +
            10
        )
        
        if ses_level == 'High':
            resource_score += 5
        elif ses_level == 'Low':
            resource_score -= 5
        
        resource_score = max(0, min(100, resource_score))
        
        if resource_score >= 80:
            resource_tier = 'High-resource'
        elif resource_score >= 55:
            resource_tier = 'Moderate-resource'
        else:
            resource_tier = 'Limited-resource'
        
        comparison_notes = (
            f"{resource_tier} school with {ap_available} AP courses and {honors_available} honors courses. "
            f"Locale: {locale}. SES: {ses_level}."
        )
        
        if is_georgia:
            comparison_notes += " [Georgia school - local trained dataset]"
        
        return {
            'ap_courses_available': ap_available,
            'ib_courses_available': ib_available,
            'honors_courses_available': honors_available,
            'stem_programs_count': stem_count,
            'locale': locale,
            'resource_score': round(resource_score, 1),
            'resource_tier': resource_tier,
            'comparison_notes': comparison_notes,
            'georgia_data_available': is_georgia,
            'data_source_url': None
        }
    
    def _calculate_opportunity_scores(
        self,
        school_profile: Dict[str, Any],
        program_participation: Dict[str, Any],
        ses_context: Dict[str, Any]
    ) -> Dict[str, float]:
        """Calculate comprehensive opportunity and access scores."""
        
        # Program Access Score (0-100): What programs are available
        ap_available = school_profile.get('ap_courses_available', 0)
        ib_available = school_profile.get('ib_courses_available', 0)
        honors_available = school_profile.get('honors_courses_available', 0)
        stem_count = len(school_profile.get('stem_programs', []))
        
        program_access = min(100, (
            (ap_available / 20) * 30 +  # AP courses (out of 20 possible)
            (ib_available / 8) * 15 +   # IB (out of 8)
            (min(honors_available, 30) / 30) * 20 +  # Honors
            (stem_count / 5) * 15 +     # STEM programs
            20  # Base for any access
        ))
        
        # Program Participation Score (0-100): How many programs student used
        ap_taken = len(program_participation.get('ap_courses_taken', []))
        honors_taken = program_participation.get('honors_courses_taken', 0)
        stem_taken = len(program_participation.get('stem_courses', []))
        
        program_participation_score = min(100, (
            (ap_taken / 8) * 40 +       # AP participation (out of 8 typical max)
            (min(honors_taken, 10) / 10) * 40 +  # Honors participation
            (stem_taken / 5) * 20       # STEM participation
        ))
        
        # Relative Advantage Score (0-100): Student usage vs peer opportunities
        # If student used 70% of what's available, they're ahead of peers
        program_availability = ap_available + ib_available
        programs_used = ap_taken + (ib_available if program_participation.get('ib_courses_taken') else 0)
        
        if program_availability > 0:
            utilization_rate = (programs_used / program_availability) * 100
            relative_advantage = min(100, utilization_rate * 1.2)  # Score higher if using proportionally more
        else:
            relative_advantage = 50  # Default if no programs available
        
        result = {
            'program_access_score': round(program_access, 1),
            'program_participation_score': round(program_participation_score, 1),
            'relative_advantage_score': round(relative_advantage, 1),
            'overall_opportunity_score': round(
                (program_access + program_participation_score + relative_advantage) / 3,
                1
            ),
            'interpretation': self._interpret_scores(program_access, program_participation_score, ses_context)
        }
        
        return result
    
    def _interpret_scores(
        self,
        access_score: float,
        participation_score: float,
        ses_context: Dict[str, Any]
    ) -> str:
        """Generate interpretation of opportunity scores."""
        
        if access_score < 30:
            access_level = "Limited access to advanced programs"
        elif access_score < 60:
            access_level = "Moderate access to advanced programs"
        elif access_score < 85:
            access_level = "Extensive access to advanced programs"
        else:
            access_level = "Exceptional access to advanced programs"
        
        if participation_score < 30:
            participation_level = "took few advanced courses"
        elif participation_score < 60:
            participation_level = "took several advanced courses"
        elif participation_score < 85:
            participation_level = "actively pursued advanced coursework"
        else:
            participation_level = "maximized available advanced opportunities"
        
        return f"Student had {access_level.lower()} and {participation_level}."
    
    def _build_summary(
        self,
        student_name: str,
        school_info: Dict[str, Any],
        participation: Dict[str, Any],
        scores: Dict[str, Any],
        ses_context: Dict[str, Any],
        school_resources: Dict[str, Any],
        rapunzel_grades_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build a comprehensive summary of school context."""
        
        summary_parts = [
            f"{student_name} attended {school_info['school_name']}",
            f"in an area with {ses_context.get('ses_level', 'medium-income')} socioeconomic indicators.",
            "",
            f"Program Participation:",
            f"• AP Courses: {len(participation.get('ap_courses_taken', []))} courses",
            f"• Honors Courses: {participation.get('honors_courses_taken', 0)} courses",
            f"• STEM Programs: {len(participation.get('stem_courses', []))} areas",
        ]
        
        summary_parts.extend([
            "",
            f"School Resources:",
            f"• AP Courses Available: {school_resources.get('ap_courses_available', 0)}",
            f"• IB Courses Available: {school_resources.get('ib_courses_available', 0)}",
            f"• Honors Courses Available: {school_resources.get('honors_courses_available', 0)}",
            f"• STEM Programs Available: {school_resources.get('stem_programs_count', 0)}",
            f"• School Resource Tier: {school_resources.get('resource_tier', 'Unknown')}",
            f"• Locale: {school_resources.get('locale', 'Unknown')}",
        ])
        
        summary_parts.extend([
            "",
            f"Opportunity Analysis:",
            f"• School Program Access: {scores.get('program_access_score', 0)}/100",
            f"• Student Participation: {scores.get('program_participation_score', 0)}/100",
            f"• Relative Advantage: {scores.get('relative_advantage_score', 0)}/100",
            f"• OVERALL OPPORTUNITY SCORE: {scores.get('overall_opportunity_score', 0)}/100",
            "",
            f"Context: {scores.get('interpretation', 'Analysis complete')}"
        ])

        if rapunzel_grades_data:
            resource_tier = school_resources.get('resource_tier', 'Unknown')
            ses_level = ses_context.get('ses_level', 'Unknown')
            gpa_value = rapunzel_grades_data.get('gpa')
            gpa_note = f"GPA: {gpa_value}." if gpa_value is not None else "GPA: not extracted."
            summary_parts.extend([
                "",
                "Grade Context:",
                f"• {gpa_note}",
                "• Interpretation note: Grades should be weighed against opportunity. A B from a high-rigor school can be as meaningful as an A from a low-rigor setting.",
                f"• SES context: {ses_level} socioeconomic indicators with {resource_tier} academic resources."
            ])

        return "\n".join(summary_parts)

    def _infer_locale(self, school_info: Dict[str, Any]) -> str:
        """Infer school locale (rural/urban/suburban) from available clues."""
        city = (school_info.get('city') or '').lower()
        name = (school_info.get('school_name') or '').lower()
        
        if any(keyword in city for keyword in ['rural', 'county', 'valley', 'mount', 'mountain']):
            return 'Rural'
        if any(keyword in name for keyword in ['county', 'regional', 'valley']):
            return 'Rural'
        if any(keyword in city for keyword in ['downtown', 'city', 'metro']):
            return 'Urban'
        if any(keyword in name for keyword in ['central', 'east', 'west', 'north', 'south']):
            return 'Suburban'
        
        return 'Unknown'
    
    def _extract_field(self, text: str, field: str, default: str) -> str:
        """Extract a single field from AI response."""
        pattern = rf'{field}[:\s]+([^\n]+)'
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else default
    
    def _extract_number(self, text: str, field: str, default: int) -> int:
        """Extract a number from AI response."""
        pattern = rf'{field}[:\s]+(\d+)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return default
        return default
    
    def _extract_programs(self, text: str, category: str) -> List[str]:
        """Extract programs from AI response."""
        pattern = rf'{category}[:\s]+([A-Za-z\s,&\-]+)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            programs = [p.strip() for p in match.group(1).split(',')]
            return [p for p in programs if p]
        return []
    
    def get_georgia_school_data_instructions(self, school_name: str) -> Dict[str, str]:
        """
        Get instructions for looking up Georgia school data from the local trained dataset.
        
        Args:
            school_name: Name of the Georgia high school
            
        Returns:
            Dictionary with lookup instructions and data points to collect
        """
        return {
            'data_source': 'school_enriched_data (local trained dataset)',
            'school_name': school_name,
            'lookup_instructions': f"""
Data for {school_name} is available in the local trained dataset (school_enriched_data table).
Search by school name to retrieve all metrics.
            """.strip(),
            'data_points': [
                'ap_courses_offered',
                'ib_courses_offered',
                'total_enrollment',
                'graduation_rate',
                'college_readiness_score',
                'free_reduced_lunch_pct',
                'student_teacher_ratio',
                'ap_pass_rate'
            ]
        }
    
    def get_national_school_data_instructions(self, school_name: str, state: str) -> Dict[str, str]:
        """
        Get instructions for looking up school data from the local trained dataset.
        
        Args:
            school_name: Name of the high school
            state: State code (e.g., 'CA', 'TX', 'NY')
            
        Returns:
            Dictionary with lookup instructions and data sources
        """
        return {
            'school_name': school_name,
            'state': state,
            'data_sources': {
                'local_db': 'school_enriched_data (local trained dataset)',
            },
            'lookup_instructions': f"""
Data for {school_name} in {state} is available in the local trained dataset (school_enriched_data table).
Search by school name and state to retrieve all metrics.
            """.strip(),
            'data_points': [
                'ap_courses_offered',
                'ib_program_available',
                'honors_courses_available',
                'stem_programs',
                'total_enrollment',
                'graduation_rate',
                'college_readiness_rate',
                'free_reduced_lunch_pct',
                'student_teacher_ratio',
                'per_pupil_spending',
                'school_type'
            ]
        }
    
    
    def _format_enriched_to_profile(self, enriched_school: Dict[str, Any], approved: bool = False) -> Dict[str, Any]:
        """
        Convert enriched school database record to Moana's expected profile format.
        
        Handles both AI-analyzed records (from Naveen) and CSV-imported
        government SES records.  The DB alias layer in ``database.py``
        ensures that legacy field names like ``enrollment_size`` and
        ``college_placement_rate`` are also present.
        
        Args:
            enriched_school: School record from school_enriched_data table
            approved: Whether this is human-approved data
            
        Returns:
            Profile dict in Moana's expected format
        """
        analysis_status = enriched_school.get('analysis_status', 'pending')
        is_csv = analysis_status == 'csv_imported'

        # Determine data_quality label
        if approved:
            quality = 'human_approved'
        elif is_csv:
            quality = 'government_ses_data'
        else:
            quality = 'ai_analyzed'

        # Use school_type from CSV if available, else default
        school_type = enriched_school.get('school_type') or 'Public'

        profile = {
            'school_name': enriched_school.get('school_name', 'Unknown'),
            'school_type': school_type,
            'ap_courses_offered': enriched_school.get('ap_course_count', 0),
            'ap_exam_pass_rate_pct': enriched_school.get('ap_exam_pass_rate', 0),
            'ib_offered': enriched_school.get('ib_program_available', False),
            'honors_courses_available': enriched_school.get('honors_course_count', 0) or 10,
            'stem_programs': enriched_school.get('stem_program_available', False),
            'dual_enrollment': enriched_school.get('dual_enrollment_available', False),
            'total_enrollment': enriched_school.get('total_students', 1500),
            'graduation_rate_pct': enriched_school.get('graduation_rate', 0),
            'college_acceptance_rate_pct': enriched_school.get('college_acceptance_rate', 0),
            'free_reduced_lunch_pct': enriched_school.get('free_lunch_percentage', 0),
            'opportunity_score': enriched_school.get('opportunity_score', 0),
            'data_source': 'csv_government' if is_csv else 'enriched_database',
            'data_quality': quality,
            'data_confidence': enriched_school.get('data_confidence_score', 0),
            'state_code': enriched_school.get('state_code'),
            'school_district': enriched_school.get('school_district'),
            'county': enriched_school.get('county_name'),
            'analysis_summary': f"School enriched profile from {analysis_status} analysis. "
                              f"Opportunity score: {enriched_school.get('opportunity_score', 0)}/100. "
                              f"Status: {enriched_school.get('human_review_status', 'pending')}. "
                              f"Data confidence: {enriched_school.get('data_confidence_score', 0)}%.",
        }

        # ---- CSV-sourced SES fields (enrich Moana's context) ----
        ses_keys = [
            'is_title_i', 'is_charter', 'is_magnet', 'is_virtual',
            'student_teacher_ratio', 'reduced_lunch_percentage',
            'direct_certification_pct', 'district_poverty_pct',
            'district_exp_per_pupil', 'district_rev_per_pupil',
            'locale_code', 'nces_id', 'enrollment_trend_json',
            'frpl_trend_json', 'years_of_data', 'latest_school_year',
        ]
        for key in ses_keys:
            val = enriched_school.get(key)
            if val is not None:
                profile[key] = val

        return profile
    
    async def process(self, message: str) -> str:
        """Process a general message."""
        self.add_to_history("user", message)
        
        messages = [
            {
                "role": "system",
                "content": "You are Moana, an expert in education systems and school contexts. You understand socioeconomic factors, advanced programs, and educational opportunities. Use broader knowledge and public sources beyond Georgia. Emphasize how opportunity constraints shape interpretation of performance.\n\nNCES CONDITION OF EDUCATION REFERENCE POINTS:\n- National graduation rate: 87% (varies by state and demographics)\n- GA graduation rate: 84%\n- AP access: ~35% of students take AP; 10+ AP courses = strong academic investment\n- Dual enrollment growing as equity bridge for under-resourced schools\n- Free/reduced lunch: 52% eligible nationally; schools above this face greater resource challenges\n- Immediate college enrollment: 62% nationally, lower for males (57%) vs females (66%)\n- College enrollment by race: Asian 74%, White 64%, Black 61%, Hispanic 58%\n- Status dropout rate: 5.3% nationally\n- Per-pupil spending and student-teacher ratio vary widely and are key capability indicators\n\nUse these benchmarks when evaluating any school's context. A 4.0 GPA from a school with 2 AP courses and 75% free lunch is categorically different from the same GPA at a school with 20 APs and 15% free lunch. Context defines opportunity."
            }
        ] + self.conversation_history
        
        try:
            response = self._create_chat_completion(
                operation="moana.process",
                model=self.model,
                messages=messages,
                max_completion_tokens=1500,
                temperature=1
            )
            
            assistant_message = response.choices[0].message.content
            self.add_to_history("assistant", assistant_message)
            return assistant_message
            
        except Exception as e:
            error_message = f"Moana encountered an error: {str(e)}"
            print(error_message)
            return error_message
