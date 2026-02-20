"""
Naveen School Data Scientist Agent
Analyzes schools to build enriched profiles with opportunity scores.
Character: Naveen (Disney character from "The Princess and the Frog")
Model: o4-mini (Azure AI Foundry)

Uses AI to analyze web data, academic programs, salary outcomes, and regional context.
Builds comprehensive school enrichment profiles for student opportunity assessment.
"""

import logging
import json
import re
import time
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import urlparse
from opentelemetry.trace import SpanKind

from src.agents.base_agent import BaseAgent
from src.observability import get_tracer

logger = logging.getLogger(__name__)


class NaveenSchoolDataScientist(BaseAgent):
    """
    Naveen - School Data Scientist Agent
    Analyzes and enriches school data using AI model.
    Uses web research and academic data to build comprehensive school profiles.
    Calculates opportunity scores based on capabilities, outcomes, and regional context.
    
    Inherits from BaseAgent to use Azure OpenAI for intelligent enrichment.
    """

    def __init__(self, name: str = "Naveen School Data Scientist", client: Any = None, model: str = "o4MiniAgent"):
        """Initialize Naveen with AI client."""
        super().__init__(name=name, client=client)
        self.model = model
        self.model_display = "gpt-4 mini"  # Display-friendly model name

    def analyze_school(
        self,
        school_name: str,
        school_district: Optional[str] = None,
        state_code: Optional[str] = None,
        web_sources: Optional[List[str]] = None,
        existing_data: Optional[Dict[str, Any]] = None,
        enrichment_focus: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze a school using AI and build enriched profile.
        
        Args:
            school_name: Name of the school
            school_district: District name
            state_code: State code (e.g., 'GA')
            web_sources: List of URLs to analyze
            existing_data: Pre-existing school data from other agents (Moana, etc)
            
        Returns:
            Enriched school data with AI-powered analysis results
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
            inferred_state = self._infer_state_code(state_code, existing_data)
            result["state_code"] = inferred_state

            search_query = self._build_search_query(
                school_name=school_name,
                school_district=school_district,
                state_code=inferred_state,
                existing_data=existing_data
            )
            result["search_query"] = search_query

            enriched_sources = self._build_web_sources(
                web_sources=web_sources,
                state_code=inferred_state,
                search_query=search_query
            )
            result["web_sources"] = enriched_sources

            # Build comprehensive school research prompt for AI
            research_prompt = self._build_research_prompt(
                school_name,
                school_district,
                inferred_state,
                enriched_sources,
                existing_data,
                enrichment_focus=enrichment_focus
            )
            
            # Use AI to analyze school comprehensively
            logger.info(f"Naveen analyzing {school_name} with AI model")
            # Wrap LLM call with telemetry helper so model usage is recorded
            from src.agents.telemetry_helpers import lm_call
            with lm_call(self.model, "school_analysis", system_prompt=research_prompt):
                ai_analysis = self._create_chat_completion(
                operation="school_analysis",
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are Naveen, a school data scientist expert. Analyze schools comprehensively to understand:
1. Academic capabilities and programs (AP, IB, STEM, etc)
2. Student outcomes (college placement, graduation rates, test scores)
3. School investment and resources (funding, facilities, teacher quality indicators)
4. Regional opportunity context (job market, economic indicators)
5. Overall opportunity score for students (0-100)

Provide structured analysis in JSON format."""
                    },
                    {
                        "role": "user",
                        "content": research_prompt
                    }
                ],
                temperature=0.7,
                max_completion_tokens=2000
                )
            
            # Parse AI response
            if ai_analysis and "content" in ai_analysis.choices[0].message:
                response_text = ai_analysis.choices[0].message.content
                
                # Try to extract JSON from response
                try:
                    # Look for JSON block in response
                    import re
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        ai_data = json.loads(json_match.group())
                    else:
                        ai_data = json.loads(response_text)
                    
                    result["enriched_data"] = ai_data
                    result["confidence_score"] = ai_data.get("confidence_score", 75)
                    result["opportunity_score"] = ai_data.get("opportunity_score", 50)
                    
                except json.JSONDecodeError:
                    # If JSON parsing fails, extract key fields from response
                    logger.warning(f"Could not parse JSON from Naveen response for {school_name}")
                    result["enriched_data"]["raw_analysis"] = response_text
                    result["confidence_score"] = 60
            
            # Use AI to refine and improve results if confidence is low
            if result["confidence_score"] < 70:
                refinement_result = self._refine_analysis(school_name, result, existing_data)
                result.update(refinement_result)
            
            result["analysis_status"] = "complete"
            result["status"] = "success"  # For compatibility with school_workflow
            result["analysis_summary"] = self._generate_analysis_summary(result)
            
            logger.info(f"Naveen enrichment complete for {school_name}: score={result['opportunity_score']}, confidence={result['confidence_score']}")

        except Exception as e:
            logger.error(f"Error analyzing school {school_name}: {str(e)}", exc_info=True)
            result["analysis_status"] = "error"
            result["status"] = "error"
            result["error"] = str(e)

        # Add model information to result
        result["agent_name"] = self.name
        result["model_used"] = self.model
        result["model_display"] = self.model_display

        return result

    def _build_web_sources(
        self,
        web_sources: Optional[List[str]],
        state_code: Optional[str],
        search_query: Optional[str]
    ) -> List[str]:
        """Build a focused list of sources for the model to reason over."""
        sources = list(web_sources or [])

        if search_query:
            sources.append(f"search:{search_query}")

        # State-specific sources
        if state_code == "GA":
            sources.append("https://gosa.georgia.gov/dashboards-data-report-card/data-dashboards")

        # Federal references
        sources.append("https://nces.ed.gov/fastfacts/")

        # De-duplicate while preserving order
        seen = set()
        unique_sources = []
        for source in sources:
            if source and source not in seen:
                seen.add(source)
                unique_sources.append(source)

        return unique_sources

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

    def _build_research_prompt(
        self,
        school_name: str,
        school_district: Optional[str],
        state_code: Optional[str],
        web_sources: Optional[List[str]],
        existing_data: Optional[Dict[str, Any]]
        , enrichment_focus: Optional[str] = None
    ) -> str:
        """Build comprehensive research prompt for AI to analyze school."""
        prompt = f"""Analyze the school '{school_name}' {'in ' + school_district if school_district else ''} {'(' + state_code + ')' if state_code else ''}.

Based on available sources and data, provide a comprehensive JSON analysis including:

1. Academic Capabilities
   - Number of AP courses offered
   - Number of IB programs available
   - STEM program availability and quality
   - Honors program availability
   - School type/grade levels

2. Student Outcomes
   - College acceptance/placement rate (estimate 0-100%)
   - Graduation rate (estimate 0-100%)
   - Average test scores (if available)
   - Notable achievements or recognitions

3. School Investment Level
   - Estimated funding level (low/medium/high)
   - Facility quality indicators
   - Teacher quality indicators
   - School improvement efforts

4. Enrollment & Demographics
   - Estimated total enrollment
   - Free/reduced lunch percentage (indicator of socioeconomic need)
   - Demographic diversity indicators
   - Community sentiment/satisfaction

5. Opportunity Score
   - Provide an overall opportunity score (0-100) reflecting how well this school positions students for college/career success
   - Consider academic rigor, resources, student outcomes, and addressing barriers

6. Confidence Score
   - How confident you are in this analysis (0-100) based on data availability

Available web sources to analyze (including a search query hint if provided): {json.dumps(web_sources) if web_sources else 'None provided'}

Existing data from other agents: {json.dumps(existing_data) if existing_data else 'None provided'}

Focus guidance: {enrichment_focus if enrichment_focus else 'General enrichment requested'}

Return your analysis as a single JSON object with keys: academic_courses, academic_programs, stem_programs, honors_programs, 
college_acceptance_rate, graduation_rate, test_scores, funding_level, facility_quality, teacher_quality_indicators, 
total_enrollment, free_lunch_percentage, diversity_indicators, community_sentiment, opportunity_score, confidence_score, key_insights."""
        
        return prompt

    def _infer_state_code(
        self,
        state_code: Optional[str],
        existing_data: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """Infer a two-letter state code from existing data if missing."""
        if state_code:
            return state_code.strip().upper()

        if not existing_data:
            return None

        candidates = [
            existing_data.get("state_code"),
            existing_data.get("state"),
            existing_data.get("school_state"),
            existing_data.get("student_state"),
            existing_data.get("address_state"),
            existing_data.get("region_state"),
        ]

        for value in candidates:
            if isinstance(value, str) and len(value.strip()) == 2:
                return value.strip().upper()

        return None

    def _build_search_query(
        self,
        school_name: str,
        school_district: Optional[str],
        state_code: Optional[str],
        existing_data: Optional[Dict[str, Any]]
    ) -> str:
        """Use the model to generate a focused search query for school data."""
        district_hint = f", {school_district}" if school_district else ""
        state_hint = f", {state_code}" if state_code else ""
        base_query = f"{school_name}{district_hint}{state_hint} high school profile graduation rate enrollment AP IB"

        try:
            query_prompt = f"""Create a concise web search query (max 18 words) to find official data for a high school.

School name: {school_name}
District: {school_district or 'Unknown'}
State: {state_code or 'Unknown'}
Existing data: {json.dumps(existing_data) if existing_data else 'None'}

Return only the search query text."""

            response = self._create_chat_completion(
                operation="school_search_query",
                model=self.model,
                messages=[
                    {"role": "system", "content": "You generate concise search queries for school data."},
                    {"role": "user", "content": query_prompt}
                ],
                temperature=0.2,
                max_completion_tokens=40
            )

            if response and "content" in response.choices[0].message:
                query_text = response.choices[0].message.content.strip()
                return query_text.strip("\"' ") or base_query
        except Exception as e:
            logger.warning(f"Search query generation failed: {e}")

        return base_query

    def _refine_analysis(
        self,
        school_name: str,
        initial_result: Dict[str, Any],
        existing_data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Refine analysis if initial confidence is low."""
        logger.info(f"Refining Naveen analysis for {school_name} (low confidence: {initial_result['confidence_score']})")
        
        refinement_prompt = f"""The initial analysis for '{school_name}' had low confidence ({initial_result['confidence_score']}%).
        
Initial findings: {json.dumps(initial_result['enriched_data'])}

Please refine this analysis by:
1. Identifying what data is missing or uncertain
2. Making educated inferences based on school district/region patterns
3. Providing a more confidence assessment

Return refined analysis as JSON with improved confidence_score."""
        
        refined_response = self._create_chat_completion(
            operation="school_analysis_refinement",
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are Naveen refining school analysis. Improve confidence in results where possible."
                },
                {
                    "role": "user",
                    "content": refinement_prompt
                }
            ],
            temperature=0.5,
            max_completion_tokens=1500
        )
        
        refined_data = {}
        try:
            if refined_response and "content" in refined_response.choices[0].message:
                response_text = refined_response.choices[0].message.content
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    refined_data = json.loads(json_match.group())
                    
        except Exception as e:
            logger.warning(f"Could not parse refined analysis: {e}")
        
        return {
            "enriched_data": refined_data or initial_result["enriched_data"],
            "confidence_score": refined_data.get("confidence_score", initial_result["confidence_score"] + 10)
        }

    async def process(self, message: str) -> str:
        """Process a message - not used for Naveen's school analysis pipeline."""
        return "Naveen processes schools via analyze_school() method"
