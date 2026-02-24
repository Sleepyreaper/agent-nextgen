"""Moana School Context Analyzer - Discovers school environment and program access context."""

from typing import Dict, List, Any, Optional, Tuple
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.telemetry_helpers import agent_run
import re
import json


class MoanaSchoolContext(BaseAgent):
    """
    Specialized agent (Moana) for deeply understanding a student's school context. Model is determined by configuration when not explicitly provided.
    
    This agent analyzes:
    - The high school itself: type, size, location (rural/urban/suburban)
    - What programs the school offers (AP classes, IB, Honors, STEM)
    - School resources compared to other schools
    - Socioeconomic factors affecting school quality
    - How much of the school's available resources the student utilized
    
    Key insight: A 4.0 GPA from a school with 2 AP classes is different 
    from a 4.0 GPA from a school with 20 AP classes. This agent provides that context.
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
        self.model = model or config.foundry_model_name or config.deployment_name
        self.db = db_connection
        
        # Cache for school lookups to avoid redundant API calls
        self.school_cache: Dict[str, Dict[str, Any]] = {}
        
        # Georgia School Data Source
        # Public data available at: https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard
        # Provides: enrollment, demographics, AP/IB offerings, graduation rates, test scores, etc.
        self.georgia_data_source = "https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard"
        self.georgia_schools_cache: Dict[str, Dict[str, Any]] = {}
        
        # National and state data sources for non-Georgia schools
        self.national_data_sources = {
            'nces': 'https://nces.ed.gov/ccd/',  # National Center for Education Statistics
            'great_schools': 'https://www.greatschools.org/',
            'school_digger': 'https://www.schooldigger.com/',
            'niche': 'https://www.niche.com/k12/search/best-schools/',
        }
        
        # State-specific education department dashboards
        self.state_data_sources = {
            'CA': 'https://www.cde.ca.gov/DataQuest/',
            'TX': 'https://tea.texas.gov/student-assessment/staar/',
            'NY': 'https://data1.nysed.gov/febrl/',
            'FL': 'https://www.fldoe.org/accountability/data-sys/',
            'IL': 'https://www.isbe.net/Pages/default.aspx',
            'OH': 'https://education.ohio.gov/Topics/Data-and-Accountability',
            'PA': 'https://www.education.pa.gov/DataAndReporting/Pages/default.aspx',
            'MI': 'https://www.michigan.gov/mde',
            'NC': 'https://www.dpi.nc.gov/accountability',
            'VA': 'https://www.doe.virginia.gov/data-and-analytics/research-and-reports',
        }
    
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
                    print(f"  ✓ Georgia school detected - using Georgia state data")
                    school_info['georgia_data_available'] = True
                    school_info['data_source_url'] = self.georgia_data_source
                else:
                    print(f"  🔍 {school_state} school - searching for public data sources...")
                    school_info['data_sources'] = available_data_sources['sources']
                    school_info['data_availability'] = available_data_sources
                
                # Step 2: Extract programs from transcript
                program_participation = await self._extract_program_participation(
                    transcript_text,
                    student_name
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
        Fast path: Use pre-enriched school data from Aurora (via school_workflow).
        
        Instead of analyzing the school from scratch, we:
        1. Use Aurora's enriched school profile
        2. Extract student's program participation from transcript
        3. Calculate opportunity scores with the pre-analyzed school data
        4. Build contextual summary
        
        This is much faster and more consistent than re-analyzing each school.
        
        Args:
            student_name: Student's name
            application: Application data
            transcript_text: Grade report text
            rapunzel_grades_data: Grade analysis from Rapunzel
            school_enrichment: Pre-enriched school data from Aurora
            
        Returns:
            School context analysis using enriched data
        """
        try:
            print(f"  ✓ Using enriched school data: {school_enrichment.get('school_name')}")
            
            # Extract what student participated in
            program_participation = await self._extract_program_participation(
                transcript_text,
                student_name
            )
            
            # Build school profile from enrichment
            school_profile = {
                'school_name': school_enrichment.get('school_name'),
                'enrollment_size': school_enrichment.get('enrollment_size'),
                'socioeconomic_level': school_enrichment.get('socioeconomic_level'),
                'ap_count': school_enrichment.get('ap_classes_count', 0),
                'ib_offerings': school_enrichment.get('ib_offerings', 0),
                'honors_programs': school_enrichment.get('honors_programs', 0),
                'stem_programs': school_enrichment.get('stem_programs', 0),
                'graduation_rate': school_enrichment.get('graduation_rate'),
                'college_placement_rate': school_enrichment.get('college_placement_rate'),
                'diversity_index': school_enrichment.get('diversity_index'),
                'data_sources': school_enrichment.get('web_sources_analyzed', []),
                'analysis_date': school_enrichment.get('analysis_date'),
                'enrichment_source': 'aurora_cached'
            }
            
            # Quick SES context from enrichment
            ses_context = {
                'socioeconomic_level': school_enrichment.get('socioeconomic_level', 'unknown'),
                'diversity_index': school_enrichment.get('diversity_index'),
                'regional_context': f"{school_enrichment.get('state_code', 'US')} school",
                'based_on_enrichment': True
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
                'ib_available': bool(school_profile.get('ib_offerings', 0)),
                'stem_available': bool(school_profile.get('stem_programs', 0)),
                'enrollment_size_category': self._categorize_size(school_profile.get('enrollment_size')),
                'investment_level': school_enrichment.get('school_investment_level', 'unknown'),
                'opportunity_score': school_enrichment.get('opportunity_score', 0)
            }
            
            # Final analysis
            analysis = {
                'status': 'success',
                'student_name': student_name,
                'school': {
                    'name': school_enrichment.get('school_name'),
                    'state': school_enrichment.get('state_code'),
                    'identification_confidence': 0.99  # High confidence from Aurora
                },
                'school_profile': school_profile,
                'ses_context': ses_context,
                'program_participation': program_participation,
                'school_resources': school_resources,
                'opportunity_scores': scores,
                'contextual_summary': self._build_summary_from_enrichment(
                    student_name,
                    school_enrichment,
                    program_participation,
                    scores,
                    rapunzel_grades_data
                ),
                'model_used': self.model,
                'data_source': 'enriched_aurora'  # Track that this used Aurora data
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
        """Calculate scores using pre-analyzed school data."""
        # Use Aurora's opportunity score as base
        base_score = float(school_enrichment.get('opportunity_score', 50))
        
        # Adjust based on what student actually participated in
        participation_adjustment = 0
        ap_taken = self._safe_count(program_participation.get('ap_courses_taken', 0))
        honors_taken = self._safe_count(program_participation.get('honors_courses_taken', 0))
        advanced_count = self._safe_count(
            program_participation.get('advanced_courses_count', program_participation.get('advanced_courses', []))
        )
        if ap_taken > 0:
            participation_adjustment += 10
        if honors_taken > 0:
            participation_adjustment += 5
        if advanced_count > 5:
            participation_adjustment += 10
        
        return {
            'opportunity_score': min(100, base_score + participation_adjustment),
            'program_access_score': school_profile.get('ap_count', 0) * 2,  # Roughly
            'program_participation_score': advanced_count * 5,
            'relative_advantage_score': base_score / 100 * 50  # Normalized
        }
    
    def _build_summary_from_enrichment(
        self,
        student_name: str,
        school_enrichment: Dict[str, Any],
        program_participation: Dict[str, Any],
        scores: Dict[str, float],
        rapunzel_grades_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build contextual summary using enriched school data."""
        school_name = school_enrichment.get('school_name', 'their school')
        ap_available = self._safe_count(school_enrichment.get('ap_classes_count', 0))
        ap_taken = self._safe_count(program_participation.get('ap_courses_taken', 0))
        opportunity = school_enrichment.get('opportunity_score', 50)
        investment_level = school_enrichment.get('school_investment_level', 'moderate')
        
        parts = [
            f"{student_name} attends {school_name}, a {investment_level}-investment school "
            f"with an opportunity score of {opportunity}/100."
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
        
        contextual_insight = (
            f"In the context of {school_name}'s resources and demographics, "
            f"{student_name}'s course selection demonstrates a relative advantage score of "
            f"{scores.get('relative_advantage_score', 0):.0f}/50."
        )
        parts.append(contextual_insight)
        
        if rapunzel_grades_data and rapunzel_grades_data.get('gpa'):
            parts.append(
                f"Combined with a GPA of {rapunzel_grades_data.get('gpa')}, "
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
            print(f"  ✓ Georgia school detected - using Georgia state data")
            school_info['georgia_data_available'] = True
            school_info['data_source_url'] = self.georgia_data_source
        else:
            print(f"  🔍 {school_state} school - searching for public data sources...")
            school_info['data_sources'] = available_data_sources['sources']
            school_info['data_availability'] = available_data_sources
        
        # Extract programs from transcript
        program_participation = await self._extract_program_participation(
            transcript_text,
            student_name
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
        student_name: str
    ) -> Dict[str, Any]:
        """Extract which advanced programs the student participated in."""
        
        participation = {
            'ap_courses_taken': [],
            'ib_courses_taken': [],
            'honors_courses_taken': [],
            'stem_courses': [],
            'gt_program': False,
            'other_programs': []
        }
        
        # Count AP courses
        ap_matches = re.findall(r'AP\s+([A-Za-z\s&]+):\s*([A-F\+\-])', transcript_text, re.IGNORECASE)
        participation['ap_courses_taken'] = [course for course, _ in ap_matches]
        
        # Count Honors courses
        honors_matches = re.findall(r'\(Honors\):\s*([A-F\+\-])', transcript_text)
        participation['honors_courses_taken'] = len(honors_matches)
        
        # Look for STEM indicators
        stem_keywords = ['STEM', 'Computer Science', 'Physics', 'Chemistry', 'Biology', 'Mathematics', 'Engineering']
        for keyword in stem_keywords:
            if keyword.lower() in transcript_text.lower():
                if keyword not in participation['stem_courses']:
                    participation['stem_courses'].append(keyword)
        
        # Check for gifted program
        if re.search(r'gifted|accelerated|advanced placement', transcript_text, re.IGNORECASE):
            participation['gt_program'] = True
        
        # Count total advanced courses
        participation['total_advanced_courses'] = (
            len(participation['ap_courses_taken']) +
            participation['honors_courses_taken'] +
            len(participation['stem_courses'])
        )
        
        return participation
    
    async def _identify_data_sources(
        self,
        state: str,
        school_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Identify publicly available data sources for a school's state.
        
        For non-Georgia schools, identifies state education department dashboards,
        NCES data, and other public sources that can provide school metrics.
        """
        state_code = state.upper()[:2] if state else ''
        
        sources = {
            'nces': self.national_data_sources['nces'],
            'state_dashboard': self.state_data_sources.get(state_code),
        }
        
        # Add common sources
        sources['great_schools'] = self.national_data_sources['great_schools']
        sources['niche'] = self.national_data_sources['niche']
        
        return {
            'state': state,
            'sources': {k: v for k, v in sources.items() if v},
            'ai_search_enabled': True,
            'note': f"Will use AI to synthesize data from public sources for {school_info.get('school_name', 'school')}",
            'recommended_search': f"{school_info.get('school_name', '')} {school_info.get('city', '')} {state} NCES school data"
        }
    
    async def _search_school_data_ai(
        self,
        school_name: str,
        city: str,
        state: str
    ) -> Dict[str, Any]:
        """
        Use AI to search for and synthesize publicly available school data.
        
        This method instructs the AI to:
        1. Identify the school in national databases (NCES)
        2. Find state-specific education metrics
        3. Look for public school ratings/rankings
        4. Extract key metrics about programs and resources
        
        Returns synthesized data similar to what we get from Georgia sources.
        """
        search_query = f"""You are an education data researcher. Find publicly available information about {school_name} in {city}, {state}.

Using public sources (NCES, {state} Department of Education, GreatSchools.org, Niche, School Digger, etc.), compile:

SCHOOL BASICS:
- School type (public/private/charter)
- Total enrollment
- Grades served
- School locale (urban/suburban/rural)

ACADEMIC PROGRAMS:
- Number of AP courses/offerings
- IB program (yes/no, how many courses)
- Honors program scope
- STEM program offerings (robotics, computer science, engineering, etc.)

STUDENT DEMOGRAPHICS & SES:
- Estimated free/reduced lunch percentage (poverty indicator)
- Racial/ethnic breakdown
- Student-teacher ratio
- Budget/per-pupil spending

PERFORMANCE METRICS:
- Graduation rate
- College readiness rate
- State test scores (proficiency %)
- AP pass rate (if available)

COLLEGE PREPARATION:
- Number of students going to 4-year colleges
- Dual enrollment/early college programs

Provide this as a structured analysis. Be honest about data availability. If exact numbers aren't publicly available, provide conservative estimates based on school size/type/location and clearly label them as estimates."""

        try:
            response = self._create_chat_completion(
                operation="moana.search_school_data",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are part of an NIH Department of Genetics review panel evaluating Emory NextGen applicants. You find and synthesize publicly available school data to contextualize opportunity and STEM access. Use national and state sources, not just Georgia data. Label estimates clearly and avoid overconfident claims."
                    },
                    {
                        "role": "user",
                        "content": search_query
                    }
                ],
                max_completion_tokens=2000,
                temperature=0.7,  # Lower temp for more factual output
                refinements=2,
                refinement_instruction="Refine the factual synthesis: correct inconsistencies, cite likely data sources, and clearly label estimates."
            )
            
            analysis_text = response.choices[0].message.content
            
            # Parse the AI response into structured data
            school_data = {
                'school_name': school_name,
                'city': city,
                'state': state,
                'data_source': 'AI_synthesized_public_data',
                'school_type': self._extract_field(analysis_text, 'school type', 'Public'),
                'ap_courses_available': self._extract_number(analysis_text, 'AP courses', 12),
                'ib_courses_available': self._extract_number(analysis_text, 'IB courses', 0),
                'honors_courses_available': self._extract_number(analysis_text, 'honors', 20),
                'stem_programs': self._extract_programs(analysis_text, 'STEM'),
                'total_students': self._extract_number(analysis_text, 'enrollment', 2000),
                'student_teacher_ratio': self._extract_field(analysis_text, 'student-teacher ratio', '16:1'),
                'free_reduced_lunch_pct': self._extract_number(analysis_text, 'free.*lunch', 35),
                'graduation_rate': self._extract_number(analysis_text, 'graduation', 85),
                'college_readiness_rate': self._extract_number(analysis_text, 'college readiness', 70),
                'locale': self._infer_locale({'school_name': school_name, 'city': city}),
                'raw_analysis': analysis_text[:800],
                'data_estimation_note': 'Data synthesized from public sources via AI analysis'
            }
            
            return school_data
            
        except Exception as e:
            print(f"Error searching school data with AI: {e}")
            return {
                'school_name': school_name,
                'error': str(e),
                'data_source': 'failed_ai_search'
            }
    
    async def _get_or_create_school_profile(
        self,
        school_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get school profile from database or create one with AI analysis.
        
        Priority order:
        1. Check for human-approved enriched data in school_enriched_data table
        2. Check for AI-analyzed enriched data (if confidence is high)
        3. Fall back to AI synthesis from web sources
        4. For Georgia schools, uses Georgia public data sources
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
                
                # Use AI-analyzed data if confidence is high
                elif enriched_school.get('analysis_status') == 'complete' and enriched_school.get('data_confidence_score', 0) >= 75:
                    print(f"    ✓ Using AI-analyzed enriched data (confidence: {enriched_school.get('data_confidence_score')}, score: {enriched_school.get('opportunity_score')})")
                    self.school_cache[school_name] = self._format_enriched_to_profile(enriched_school, approved=False)
                    return self.school_cache[school_name]
        except Exception as e:
            # If database lookup fails, continue with normal flow
            print(f"    ℹ Enriched data lookup unavailable: {str(e)}")
            pass
        
        # === END NEW: Fall back to existing logic ===
        
        # Check Georgia-specific cache first
        if is_georgia and school_name in self.georgia_schools_cache:
            return self.georgia_schools_cache[school_name]
        
        # Check general cache
        if school_name in self.school_cache:
            return self.school_cache[school_name]
        
        # For non-Georgia schools, use AI to search for public data
        if not is_georgia:
            print(f"    Using AI to search public data sources...")
            profile = await self._search_school_data_ai(
                school_name,
                school_info.get('city', 'Unknown'),
                state
            )
            
            if profile.get('error'):
                print(f"    AI search encountered error: {profile['error']}")
                # Fall back to generic estimation
                return await self._create_generic_school_profile(school_info)
            
            self.school_cache[school_name] = profile
            return profile
        
        # For Georgia schools, use the standard Georgia data note
        georgia_note = "\n\nNOTE: This is a Georgia school. Real public data is available at https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard including exact enrollment, AP/IB offerings, demographics, graduation rates, and college readiness scores. For now, provide best estimates."
        
        profile_prompt = f"""Based on the school name "{school_name}" {f'in {school_info.get("city")}, {school_info.get("state")}' if school_info.get('city') else ''},
provide a realistic assessment of:
1. School type (Public/Private/Charter)
2. Number of AP courses offered (estimate: 5-20 for typical schools)
3. Number of IB courses (if applicable): 0-8
4. Honors program scope (courses available)
5. STEM programs offered (robotics, engineering, computer science, etc)
6. Estimated number of students in advanced programs (estimate total enrollment ~1500-2500)
7. Typical SES level of the area (based on school name/location if identifiable){georgia_note}

Provide realistic, conservative estimates. Explicitly note where opportunity is constrained by limited programs or resources. Format as clear categories."""

        try:
            response = self._create_chat_completion(
                operation="moana.profile_school",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are part of an NIH Department of Genetics review panel evaluating Emory NextGen applicants. Provide realistic assessments of high schools based on common patterns. Be specific with numbers, label estimates, and call out opportunity constraints."
                    },
                    {
                        "role": "user",
                        "content": profile_prompt
                    }
                ],
                temperature=0.7
            )
            
            profile_text = response.choices[0].message.content
            
            # Parse AI response into structured data
            profile = {
                'school_name': school_name,
                'school_type': self._extract_field(profile_text, 'school type', 'Public'),
                'ap_courses_available': self._extract_number(profile_text, 'AP courses', 12),
                'ib_courses_available': self._extract_number(profile_text, 'IB courses', 0),
                'honors_courses_available': self._extract_number(profile_text, 'honors', 25),
                'stem_programs': self._extract_programs(profile_text, 'STEM'),
                'total_students': self._extract_number(profile_text, 'enrollment', 2000),
                'advanced_program_students': self._extract_number(profile_text, 'advanced', 400),
                'raw_analysis': profile_text[:500],
                'data_source': 'AI_estimated_georgia',
                'state': school_info.get('state', 'Unknown'),
                'georgia_data_available': True,
                'georgia_data_source': self.georgia_data_source,
                'note': f"Real data for {school_name} available at Georgia Governor's Office of Student Achievement dashboard"
            }
            
            self.georgia_schools_cache[school_name] = profile
            self.school_cache[school_name] = profile
            return profile
            
        except Exception as e:
            print(f"Error creating Georgia school profile: {e}")
            return await self._create_generic_school_profile(school_info)
    
    async def _create_generic_school_profile(
        self,
        school_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a generic school profile when AI search fails."""
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
            'error': 'Profile could not be fully determined - using conservative estimates'
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
            comparison_notes += f" [Georgia school - verified data available at {self.georgia_data_source}]"
        
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
            'data_source_url': self.georgia_data_source if is_georgia else None
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
        Get instructions for manually looking up Georgia school data.
        
        Args:
            school_name: Name of the Georgia high school
            
        Returns:
            Dictionary with lookup instructions and data points to collect
        """
        return {
            'data_source': self.georgia_data_source,
            'school_name': school_name,
            'lookup_instructions': f"""
To get verified data for {school_name}:

1. Visit: {self.georgia_data_source}
2. Search for: "{school_name}"
3. Collect the following data points:
   
   ACADEMIC PROGRAMS:
   - Number of AP courses offered
   - Number of IB courses offered
   - Honors program availability
   - STEM program offerings
   
   STUDENT BODY:
   - Total enrollment
   - Students in advanced programs
   - Demographics breakdown
   
   PERFORMANCE METRICS:
   - Graduation rate
   - College readiness score
   - SAT/ACT average scores
   - AP exam pass rates
   
   RESOURCES:
   - Free/reduced lunch percentage (SES indicator)
   - Student-teacher ratio
   - Per-pupil expenditure
   
   CONTEXT:
   - School locale (urban/suburban/rural)
   - District information
   - School type (public/charter/private)

This data will provide accurate context for evaluating student opportunity and achievement.
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
        Get instructions for looking up non-Georgia school data from national sources.
        
        Args:
            school_name: Name of the high school
            state: State code (e.g., 'CA', 'TX', 'NY')
            
        Returns:
            Dictionary with lookup instructions and data sources
        """
        state_source = self.state_data_sources.get(state, '')
        
        return {
            'school_name': school_name,
            'state': state,
            'data_sources': {
                'nces': self.national_data_sources['nces'],
                'great_schools': self.national_data_sources['great_schools'],
                'niche': self.national_data_sources['niche'],
                'state_dashboard': state_source
            },
            'lookup_instructions': f"""
To get verified data for {school_name} in {state}:

PRIMARY SOURCES:
1. NCES (National Center for Education Statistics): {self.national_data_sources['nces']}
   - Search by school name and district
   - Find NCES school ID for official records
   
2. {state} Department of Education Dashboard: {state_source if state_source else 'Check your state education website'}
   - Most states have official school performance dashboards
   - Contains verified AP/IB enrollments, graduation rates, test scores
   
3. GreatSchools.org: {self.national_data_sources['great_schools']}
   - Aggregate public data with school ratings
   - Parent reviews and performance trends
   
4. Niche.com: {self.national_data_sources['niche']}
   - Combines multiple data sources
   - Rankings and comparative analysis

DATA TO COLLECT:
   ACADEMIC PROGRAMS:
   - AP courses offered (course list)
   - IB program (yes/no, number of courses)
   - Honors/accelerated program enrollment
   - STEM program offerings
   
   SCHOOL SIZE & DEMOGRAPHICS:
   - Total enrollment
   - Grade configuration
   - Racial/ethnic demographics
   - Free/reduced lunch % (best SES indicator)
   
   ACHIEVEMENTS:
   - Graduation rate
   - College readiness rate
   - Average SAT/ACT scores
   - STEM graduates count
   
   RESOURCES:
   - Student-teacher ratio
   - Per-pupil spending
   - School type (public/charter/private)
   - AP exam pass rates (if available)

This data will provide accurate context for evaluating student opportunity and achievement.
            """.strip(),
            'api_endpoints': [
                f'NCES Common Core Data: https://nces.ed.gov/ccd/',
                f'{state} education data portal',
                'Public data.gov datasets for education'
            ],
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
        
        Args:
            enriched_school: School record from school_enriched_data table
            approved: Whether this is human-approved data
            
        Returns:
            Profile dict in Moana's expected format
        """
        return {
            'school_name': enriched_school.get('school_name', 'Unknown'),
            'school_type': 'Public',  # Will be enhanced with actual data later
            'ap_courses_offered': enriched_school.get('ap_course_count', 0),
            'ap_exam_pass_rate_pct': enriched_school.get('ap_exam_pass_rate', 0),
            'ib_offered': enriched_school.get('ib_program_available', False),
            'honors_courses_available': True,
            'stem_programs': enriched_school.get('stem_program_available', False),
            'dual_enrollment': enriched_school.get('dual_enrollment_available', False),
            'total_enrollment': enriched_school.get('total_students', 1500),
            'graduation_rate_pct': enriched_school.get('graduation_rate', 0),
            'college_acceptance_rate_pct': enriched_school.get('college_acceptance_rate', 0),
            'free_reduced_lunch_pct': enriched_school.get('free_lunch_percentage', 0),
            'opportunity_score': enriched_school.get('opportunity_score', 0),
            'data_source': 'enriched_database',
            'data_quality': 'human_approved' if approved else 'ai_analyzed',
            'data_confidence': enriched_school.get('data_confidence_score', 0),
            'state_code': enriched_school.get('state_code'),
            'school_district': enriched_school.get('school_district'),
            'county': enriched_school.get('county_name'),
            'analysis_summary': f"School enriched profile from {enriched_school.get('analysis_status', 'pending')} analysis. "
                              f"Opportunity score: {enriched_school.get('opportunity_score', 0)}/100. "
                              f"Status: {enriched_school.get('human_review_status', 'pending')}. "
                              f"Data confidence: {enriched_school.get('data_confidence_score', 0)}%."
        }
    
    async def process(self, message: str) -> str:
        """Process a general message."""
        self.add_to_history("user", message)
        
        messages = [
            {
                "role": "system",
                "content": "You are Moana, an expert in education systems and school contexts. You understand socioeconomic factors, advanced programs, and educational opportunities. Use broader knowledge and public sources beyond Georgia. Emphasize how opportunity constraints shape interpretation of performance."
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
