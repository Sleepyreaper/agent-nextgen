"""
Naveen School Data Scientist Agent
Analyzes schools to build enriched profiles with opportunity scores.
Character: Naveen (Disney character from "The Princess and the Frog")
Model: gpt-4.1 (deployed as o4miniagent in Azure AI Foundry)

Scrapes web data, analyzes academic programs, salary outcomes, and regional context.
"""

import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class NaveenSchoolDataScientist:
    """
    Naveen - School Data Scientist Agent
    Analyzes and enriches school data.
    Uses web sources to build comprehensive school profiles.
    Calculates opportunity scores based on academic capabilities, outcomes, and regional context.
    
    Model: gpt-4.1 (o4miniagent deployment in Azure AI Foundry)
    """

    def __init__(self, name: str = "Naveen School Data Scientist", model: str = "o4miniagent"):
        self.name = name
        self.model = model
        self.model_display = "gpt-4.1"  # Display-friendly model name

    def analyze_school(
        self,
        school_name: str,
        school_district: Optional[str] = None,
        state_code: Optional[str] = None,
        web_sources: Optional[List[str]] = None,
        existing_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze a school and build enriched profile.
        
        Args:
            school_name: Name of the school
            school_district: District name
            state_code: State code (e.g., 'GA')
            web_sources: List of URLs to analyze
            existing_data: Pre-existing school data from other agents (Moana, etc)
            
        Returns:
            Enriched school data with analysis results
        """
        result = {
            "school_name": school_name,
            "school_district": school_district,
            "state_code": state_code,
            "web_sources": web_sources or [],
            "analysis_status": "analyzing",
            "timestamp": datetime.now().isoformat(),
            "school_profile": {},
            "enriched_data": {},
            "opportunity_score": 0,
            "confidence_score": 0,
            "analysis_summary": "",
            "data_quality_notes": ""
        }

        try:
            # Step 1: Build web source profile
            if web_sources:
                result["web_sources_analyzed"] = self._analyze_web_sources(web_sources)

            # Step 2: Extract academic data
            result["academic_profile"] = self._build_academic_profile(
                school_name, 
                web_sources,
                existing_data
            )

            # Step 3: Extract salary outcomes and regional context
            result["salary_outcomes"] = self._build_salary_profile(
                school_name,
                state_code,
                web_sources
            )

            # Step 4: Build demographic and capability profile
            result["demographic_profile"] = self._build_demographic_profile(
                school_name,
                existing_data
            )

            # Step 5: Calculate opportunity score
            result["opportunity_metrics"] = self._calculate_opportunity_score(
                result["academic_profile"],
                result["salary_outcomes"],
                result["demographic_profile"]
            )

            result["analysis_status"] = "complete"
            result["analysis_summary"] = self._generate_analysis_summary(result)

        except Exception as e:
            logger.error(f"Error analyzing school {school_name}: {str(e)}", exc_info=True)
            result["analysis_status"] = "error"
            result["error"] = str(e)

        # Add model information to result
        result["agent_name"] = self.name
        result["model_used"] = self.model
        result["model_display"] = self.model_display

        return result

    def _analyze_web_sources(self, urls: List[str]) -> Dict[str, Any]:
        """Analyze web sources and extract relevant data."""
        sources = {
            "urls_analyzed": [],
            "data_sources_found": {
                "official_website": None,
                "state_education": None,
                "federal_data": None,
                "college_data": None,
                "salary_data": None,
                "community_ratings": None
            },
            "scraping_success_rate": 0
        }

        for url in urls:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                
                source_info = {
                    "url": url,
                    "domain": domain,
                    "data_type": self._classify_source(domain, url),
                    "is_accessible": True,  # In real implementation, test connectivity
                    "content_type": "text/html"
                }
                
                sources["urls_analyzed"].append(source_info)
                
                # Classify source
                if "state.us" in domain or "education" in domain.lower():
                    sources["data_sources_found"]["state_education"] = url
                elif "nces.ed.gov" in domain or "ced.gov" in domain:
                    sources["data_sources_found"]["federal_data"] = url
                elif "collegeboard" in domain or "act.org" in domain:
                    sources["data_sources_found"]["college_data"] = url
                elif "salary" in domain.lower() or "indeed" in domain or "glassdoor" in domain:
                    sources["data_sources_found"]["salary_data"] = url
                elif "greatschools" in domain or "niche" in domain:
                    sources["data_sources_found"]["community_ratings"] = url
                else:
                    sources["data_sources_found"]["official_website"] = url
                    
            except Exception as e:
                logger.debug(f"Error parsing URL {url}: {e}")

        sources["scraping_success_rate"] = len(sources["urls_analyzed"]) / len(urls) * 100 if urls else 0
        return sources

    def _classify_source(self, domain: str, url: str) -> str:
        """Classify the type of data source."""
        if "state" in domain or "education" in domain.lower():
            return "state_education"
        elif "nces" in domain or "census" in domain:
            return "federal_data"
        elif "college" in domain or "sat" in domain or "act" in domain:
            return "college_prep"
        elif "salary" in domain.lower() or "indeed" in domain:
            return "salary_outcomes"
        elif "rate" in domain or "great" in domain or "niche" in domain:
            return "community_sentiment"
        else:
            return "general_information"

    def _build_academic_profile(
        self,
        school_name: str,
        web_sources: Optional[List[str]],
        existing_data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build academic capabilities profile."""
        profile = {
            "ap_course_count": 0,
            "ap_exam_pass_rate": 0,
            "honors_course_count": 0,
            "standard_course_count": 0,
            "stem_program_available": False,
            "ib_program_available": False,
            "dual_enrollment_available": False,
            "ap_courses_list": [],
            "college_acceptance_rate": 0,
            "college_counselor_count": 0,
            "advanced_placement_capacity_score": 0,
            "college_readiness_score": 0
        }

        # In production, extract from web sources
        # This is a placeholder for the structure
        if existing_data:
            profile.update(existing_data.get("academic_info", {}))

        return profile

    def _build_salary_profile(
        self,
        school_name: str,
        state_code: Optional[str],
        web_sources: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Build regional salary and outcomes profile."""
        salary_data = {
            "stem_field_median_salary": 0,
            "business_field_median_salary": 0,
            "humanities_field_median_salary": 0,
            "avg_all_fields_median_salary": 0,
            "college_enrollment_rate": 0,
            "workforce_entry_rate": 0,
            "avg_starting_salary": 0,
            "avg_5yr_salary": 0,
            "state_avg_salary": self._get_state_avg_salary(state_code),
            "salary_data_source": "BLS, NCES, regional analysis",
            "salary_data_year": 2024,
            "data_confidence": 0
        }

        return salary_data

    def _build_demographic_profile(
        self,
        school_name: str,
        existing_data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build demographic and community profile."""
        demographics = {
            "total_students": 0,
            "graduation_rate": 0,
            "free_lunch_percentage": 0,
            "student_teacher_ratio": 0,
            "avg_class_size": 0,
            "community_sentiment_score": 0,
            "parent_satisfaction_score": 0,
            "school_investment_level": "medium",
            "college_prep_focus": False,
            "career_technical_focus": False
        }

        if existing_data:
            demographics.update(existing_data.get("demographic_info", {}))

        return demographics

    def _calculate_opportunity_score(
        self,
        academic_profile: Dict[str, Any],
        salary_outcomes: Dict[str, Any],
        demographics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate composite opportunity score and component scores."""
        
        # Academic Opportunity (0-100)
        # Weighted: AP availability (30%), college acceptance (35%), college counseling (20%), readiness (15%)
        academic_score = (
            (academic_profile.get("advanced_placement_capacity_score", 0) * 0.30) +
            (academic_profile.get("college_acceptance_rate", 0) * 0.35) +
            (min(academic_profile.get("college_counselor_count", 0) / 2 * 100, 100) * 0.20) +
            (academic_profile.get("college_readiness_score", 0) * 0.15)
        )

        # Resource Opportunity (0-100)
        # Weighted: class size (25%), teacher ratio (25%), investment level (25%), STEM programs (25%)
        investment_score = 100 if demographics.get("school_investment_level") == "high" else (
            75 if demographics.get("school_investment_level") == "medium" else 50
        )
        stem_score = 25 if academic_profile.get("stem_program_available") else 0
        
        resource_score = (
            (max(100 - (demographics.get("avg_class_size", 25) / 30 * 100), 0) * 0.25) +
            (max(100 - (demographics.get("student_teacher_ratio", 25) / 30 * 100), 0) * 0.25) +
            (investment_score * 0.25) +
            (stem_score * 0.25)
        )

        # College Prep Opportunity (0-100)
        college_prep_score = (
            (academic_profile.get("college_acceptance_rate", 0) * 0.40) +
            (min(academic_profile.get("dual_enrollment_available", False) * 50, 100) * 0.30) +
            (demographics.get("college_prep_focus", False) * 100 * 0.30)
        )

        # Socioeconomic Opportunity (0-100)
        # Schools with more disadvantaged students but good programs = higher opportunity
        free_lunch_adjustment = (demographics.get("free_lunch_percentage", 0) / 100) * 30  # More opportunity if more need
        socioeconomic_score = (
            (100 - demographics.get("free_lunch_percentage", 0) * 0.3) * 0.50 +  # Resources
            free_lunch_adjustment * 0.35 +  # Programs for disadvantaged
            (demographics.get("community_sentiment_score", 50) * 0.15)
        )

        # Overall Composite Score
        overall_score = (
            (academic_score * 0.35) +
            (resource_score * 0.25) +
            (college_prep_score * 0.25) +
            (socioeconomic_score * 0.15)
        )

        return {
            "academic_opportunity_score": round(academic_score, 2),
            "resource_opportunity_score": round(resource_score, 2),
            "college_prep_opportunity_score": round(college_prep_score, 2),
            "socioeconomic_opportunity_score": round(socioeconomic_score, 2),
            "overall_opportunity_score": round(overall_score, 2),
            "score_components": {
                "academic": academic_profile,
                "resources": demographics,
                "college_prep": {"rate": academic_profile.get("college_acceptance_rate", 0)},
                "socioeconomic": demographics
            }
        }

    def _get_state_avg_salary(self, state_code: Optional[str]) -> float:
        """Get average salary for state (mock data for now)."""
        # In production, would query actual BLS data
        state_salaries = {
            "GA": 58000,
            "CA": 72000,
            "NY": 68000,
            "TX": 56000,
            "FL": 54000
        }
        return state_salaries.get(state_code, 60000) if state_code else 60000

    def _generate_analysis_summary(self, result: Dict[str, Any]) -> str:
        """Generate natural language summary of analysis."""
        school = result.get("school_name", "School")
        score = result.get("opportunity_metrics", {}).get("overall_opportunity_score", 0)
        
        summary = f"""
School Profile Analysis: {school}
========================================

🔷 Agent: {self.name} ({self.model_display})
Overall Opportunity Score: {score}/100

Analysis Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Data Sources Analyzed: {len(result.get('web_sources', []))}

Key Metrics:
- Academic Opportunity: {result.get('opportunity_metrics', {}).get('academic_opportunity_score', 'N/A')}/100
- Resource Opportunity: {result.get('opportunity_metrics', {}).get('resource_opportunity_score', 'N/A')}/100
- College Prep Opportunity: {result.get('opportunity_metrics', {}).get('college_prep_opportunity_score', 'N/A')}/100

Academic Profile:
- AP Courses Available: {result.get('academic_profile', {}).get('ap_course_count', 'N/A')}
- College Acceptance Rate: {result.get('academic_profile', {}).get('college_acceptance_rate', 'N/A')}%
- STEM Programs: {'Yes' if result.get('academic_profile', {}).get('stem_program_available') else 'No'}

Demographics:
- Total Students: {result.get('demographic_profile', {}).get('total_students', 'N/A')}
- Graduation Rate: {result.get('demographic_profile', {}).get('graduation_rate', 'N/A')}%
- Free Lunch %: {result.get('demographic_profile', {}).get('free_lunch_percentage', 'N/A')}%
""".strip()

        return summary

    async def _create_chat_completion(self, system_prompt: str, user_message: str) -> str:
        """Create chat completion via OpenAI API."""
        # This would be implemented with actual OpenAI API calls in production
        # For now, returning structured data
        return "Analysis complete"
