"""Belle Document Analyzer - Intelligently analyzes uploaded documents and extracts structured data.

Belle loves to read and understand complex information. Like Belle analyzing books in her library,
this agent analyzes student documents to extract structured data (grades, recommendations, 
applications, transcripts, etc.) and categorizes the information with deep understanding.
"""

import json
import re
from typing import Dict, List, Any, Optional, Tuple
from openai import AzureOpenAI
from src.agents.base_agent import BaseAgent
from src.agents.system_prompts import BELLE_ANALYZER_PROMPT
from src.agents.telemetry_helpers import agent_run, tool_call
from src.config import config
from src.services.content_processing_client import ContentProcessingClient


class BelleDocumentAnalyzer(BaseAgent):
    """Belle - Analyzes documents to identify type and extract structured data.
    
    Capabilities:
    - Identify document type (application, transcript, recommendation, grades, etc.)
    - Extract student information (name, email, ID, etc.)
    - Extract academic data (GPA, courses, grades, test scores)
    - Extract recommendations and evaluations
    - Extract achievements and activities
    - Categorize and structure extracted data
    """
    
    def __init__(self, name: str = "Belle Document Analyzer", client: AzureOpenAI = None, model: str = None, db_connection=None):
        """
        Initialize Belle Document Analyzer.
        
        Args:
            name: Agent name
            client: Azure OpenAI client
            model: Model deployment name
            db_connection: Database connection (optional)
        """
        super().__init__(name=name, client=client)
        self.model = model
        self.db_connection = db_connection
        self.emoji = "📖"
        self.description = "Analyzes documents and extracts structured data"
        self.content_processing_client: Optional[ContentProcessingClient] = None

        if config.content_processing_enabled and config.content_processing_endpoint:
            self.content_processing_client = ContentProcessingClient(
                endpoint=config.content_processing_endpoint,
                api_key=config.content_processing_api_key,
                api_key_header=config.content_processing_api_key_header
            )
        
        # Define document type detection patterns
        self.document_types = {
            "transcript": ["transcript", "grade report", "academic record", "gpa", "course", "grades", "mark", "semester", "major"],
            "letter_of_recommendation": ["letter of recommendation", "recommendation", "character reference", "endorsed", "recommends", "dear admissions", "to whom"],
            "application": ["application", "apply for", "student application", "job application", "cover letter", "statement of purpose"],
            "personal_statement": ["personal statement", "essay", "written response", "reflection", "why i want", "my background"],
            "grades": ["grades", "mark", "score", "test result", "exam", "final grade", "assignment grade", "gpa", "honors"],
            "test_scores": ["sat", "act", "gre", "gmat", "test score", "standardized test", "scores"],
            "resume": ["resume", "cv", "curriculum vitae", "experience", "employment history", "skills", "certifications"],
            "essay": ["essay", "personal statement", "written response", "reflection", "about me"],
            "achievement": ["award", "scholarship", "honor", "recognition", "achievement", "accomplishment", "dean's list"],
            "school_info": ["school district", "high school", "school name", "institution", "university", "college", "campus"]
        }
    
    def analyze_document(self, text_content: str, original_filename: str) -> Dict[str, Any]:
        """
        Analyze a document and extract structured information.
        
        Args:
            text_content: Extracted text from the document
            original_filename: Original filename of the document
            
        Returns:
            Dict containing:
            - document_type: Identified type of document
            - confidence: Confidence score for type identification (0-1)
            - extracted_data: Structured extracted data
            - summary: High-level summary of document content
            - raw_text: The original text
        """
        
        with agent_run(self.name, "analyze_document", {"filename": original_filename}):
            # Step 1: Identify document type
            doc_type, confidence = self._identify_document_type(text_content, original_filename)

            # Step 2: Extract type-specific data
            extracted_data = self._extract_data_by_type(text_content, doc_type)

            # Step 3: Extract common student info across all documents
            student_info = self._extract_student_info(text_content)

            # Step 4: Generate summary
        summary = self._generate_summary(text_content, doc_type, extracted_data)

        enhanced = self._run_content_processing(text_content, original_filename)
        raw_extraction = enhanced if isinstance(enhanced, dict) else None

        if raw_extraction:
            enhanced_text = raw_extraction.get("text") or raw_extraction.get("extracted_text")
            enhanced_doc_type = raw_extraction.get("document_type") or raw_extraction.get("doc_type")
            enhanced_confidence = raw_extraction.get("confidence")
            enhanced_extracted = raw_extraction.get("extracted_data") or raw_extraction.get("fields") or {}
            enhanced_student = raw_extraction.get("student_info") or {}
            enhanced_summary = raw_extraction.get("summary")

            if isinstance(enhanced_extracted, dict):
                extracted_data = self._merge_dicts(extracted_data, enhanced_extracted)
            if isinstance(enhanced_student, dict):
                student_info = self._merge_dicts(student_info, enhanced_student)
            if enhanced_doc_type:
                doc_type = enhanced_doc_type
            if isinstance(enhanced_confidence, (int, float)):
                confidence = float(enhanced_confidence)
            if enhanced_summary:
                summary = enhanced_summary
            if enhanced_text:
                text_content = enhanced_text
        
        # Map to agent-needed fields
        agent_fields = {}
        if doc_type in {"transcript", "grades", "academic_record"}:
            agent_fields["transcript_text"] = text_content
        if doc_type in {"letter_of_recommendation", "recommendation"}:
            agent_fields["recommendation_text"] = text_content
        if doc_type in {"application", "personal_statement", "essay"}:
            agent_fields["application_text"] = text_content
        if student_info.get("school_name"):
            agent_fields["school_name"] = student_info.get("school_name")
        if student_info.get("state_code"):
            agent_fields["state_code"] = student_info.get("state_code")

        if extracted_data.get("gpa") is not None:
            agent_fields["gpa"] = extracted_data.get("gpa")
        if extracted_data.get("ap_courses"):
            agent_fields["ap_courses"] = extracted_data.get("ap_courses")
        if extracted_data.get("activities"):
            agent_fields["activities"] = extracted_data.get("activities")
        if extracted_data.get("interest"):
            agent_fields["interest"] = extracted_data.get("interest")

        return {
            "document_type": doc_type,
            "confidence": confidence,
            "student_info": student_info,
            "extracted_data": extracted_data,
            "agent_fields": agent_fields,
            "summary": summary,
            "raw_extraction": raw_extraction,
            "original_filename": original_filename,
            "text_preview": text_content[:500] if len(text_content) > 500 else text_content
        }

    async def process(self, message: str) -> str:
        """Process text content and return a JSON summary string."""
        result = self.analyze_document(message, "")
        return json.dumps(result, ensure_ascii=True)

    def _run_content_processing(self, text: str, filename: str) -> Optional[Dict[str, Any]]:
        if not self.content_processing_client:
            return None
        return self.content_processing_client.analyze_text(text, filename)

    @staticmethod
    def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            if value is None:
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            merged[key] = value
        return merged
    
    def _identify_document_type(self, text: str, filename: str) -> Tuple[str, float]:
        """Identify the type of document based on content and filename."""
        
        text_lower = text.lower()
        filename_lower = filename.lower()
        combined = text_lower + " " + filename_lower
        
        scores = {}
        
        # Score each document type based on keyword matches
        for doc_type, keywords in self.document_types.items():
            match_count = sum(1 for keyword in keywords if keyword in combined)
            scores[doc_type] = match_count
        
        # Get best match
        if max(scores.values()) == 0:
            return "general_document", 0.3
        
        best_type = max(scores, key=scores.get)
        confidence = min(scores[best_type] / max(1, len(self.document_types[best_type])), 1.0)
        
        return best_type, confidence
    
    def _extract_student_info(self, text: str) -> Dict[str, Optional[str]]:
        """Extract student info using AI for name and school, always."""
        student_info = {
            "name": None,
            "first_name": None,
            "last_name": None,
            "email": None,
            "student_id": None,
            "phone": None,
            "major": None,
            "graduation_year": None,
            "school_name": None
        }

        # Always use AI for name and school extraction
        student_info["name"] = self._extract_name_with_ai(text)
        student_info["school_name"] = self._extract_school_name_with_ai(text)

        # Optionally, parse first/last from AI name
        if student_info["name"]:
            name_parts = [part for part in student_info["name"].split() if part]
            if len(name_parts) >= 2:
                student_info["first_name"] = name_parts[0]
                student_info["last_name"] = name_parts[-1]

        # Email pattern
        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        if email_match:
            student_info["email"] = email_match.group()

        # Student ID pattern
        student_id_match = re.search(r'(?:Student ID|ID|Student #|#)[\s:]*([A-Z]?\d{6,9})', text, re.IGNORECASE)
        if student_id_match:
            student_info["student_id"] = student_id_match.group(1)

        # Phone pattern
        phone_match = re.search(r'(?:\+1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})', text)
        if phone_match:
            student_info["phone"] = phone_match.group(0)

        # Graduation year pattern
        grad_match = re.search(r'(?:Class of|Graduating|Expected Graduation)[\s:]*([2-9]\d{3})', text, re.IGNORECASE)
        if grad_match:
            student_info["graduation_year"] = grad_match.group(1)

        # Major pattern
        major_match = re.search(r'Major[\s:]*([A-Za-z\s&]{3,50})(?:Minor|Concentration|GPA|$)', text, re.IGNORECASE)
        if major_match:
            student_info["major"] = major_match.group(1).strip()

        # State code extraction
        state_code = self._extract_state_code(text)
        if state_code:
            student_info["state_code"] = state_code

        # Debug logging for school/state extraction
        if student_info.get("school_name") or student_info.get("state_code"):
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"BELLE extracted school context: school={student_info.get('school_name')}, state={student_info.get('state_code')}")

        return {k: v for k, v in student_info.items() if v is not None}
    
    def _extract_state_code(self, text: str) -> Optional[str]:
        """Extract state code from text using pattern matching and state name lookup."""
        # List of US state codes
        state_codes = {
            'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
            'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
            'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
            'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
            'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
            'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire',
            'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina',
            'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania',
            'RI': 'Rhode Island', 'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee',
            'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington',
            'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming'
        }
        
        text_lower = text.lower()
        
        # First try direct state code pattern (e.g., "GA", "CA")
        # Look for patterns like "State: GA", "state code: NY", "Address: ..., GA 30301", etc.
        code_pattern = r'(?:state|state\s+code|located\s+in|from)\s*[:\-]?\s*([A-Z]{2})(?:\s|,|$)'
        code_match = re.search(code_pattern, text, re.IGNORECASE)
        if code_match:
            potential_code = code_match.group(1).upper()
            if potential_code in state_codes:
                return potential_code
        
        # Try zip code pattern (assumes last 5 digits of a zip code follows state)
        zip_pattern = r'([A-Z]{2})\s+(\d{5})'
        zip_match = re.search(zip_pattern, text)
        if zip_match:
            potential_code = zip_match.group(1).upper()
            if potential_code in state_codes:
                return potential_code
        
        # Then try matching state names (make sure we're matching full words)
        for code, state_name in state_codes.items():
            state_pattern = r'\b' + re.escape(state_name) + r'\b'
            if re.search(state_pattern, text, re.IGNORECASE):
                return code
        
        # If no state found and presence of GA-specific indicators, default to GA
        if any(indicator in text_lower for indicator in ['georgia', 'atlanta', 'savannah', 'emory', 'gwinnett']):
            return 'GA'
        
        return None

    
    def _extract_name_with_ai(self, text: str) -> Optional[str]:
        """Use AI to intelligently extract student name from document."""
        try:
            # First try pattern-based extraction for speed
            name = self._extract_name_pattern(text)
            if name:
                return name
            
            # Fallback to AI if pattern matching fails
            prompt = f"""Extract ONLY the student's full name from this document. 
Return just the name, nothing else. If no clear name found, return 'Unknown'.

Document excerpt:
{text[:500]}"""
            
            messages = [
                {"role": "system", "content": "You are an expert at extracting student names from documents. Be precise and return only the name."},
                {"role": "user", "content": prompt}
            ]
            
            response = self._create_chat_completion(
                operation="belle.extract_name",
                model=self.model,
                messages=messages,
                max_completion_tokens=50,
                temperature=0
            )
            
            name = response.choices[0].message.content.strip()
            if name and name != "Unknown" and len(name) > 2 and len(name) < 100:
                return name
            
            return None
        except Exception as e:
            # If AI fails, fall back to pattern matching
            return self._extract_name_pattern(text)
    
    def _extract_name_pattern(self, text: str) -> Optional[str]:
        """Extract name using pattern matching with multiple strategies."""
        lines = text.split('\n')

        def normalize_name_part(part: str) -> str:
            cleaned = part.strip()
            return cleaned.title() if cleaned.isupper() else cleaned

        # Strategy 0: Explicit First Name / Last Name fields
        first_match = re.search(r'First\s*Name\s*[:\-]?\s*([A-Za-z\'\-]+)', text, re.IGNORECASE)
        last_match = re.search(r'Last\s*Name\s*[:\-]?\s*([A-Za-z\'\-]+)', text, re.IGNORECASE)
        if first_match and last_match:
            first = normalize_name_part(first_match.group(1))
            last = normalize_name_part(last_match.group(1))
            return f"{first} {last}".strip()
        
        # Strategy 1: Look for explicit name patterns first (most reliable)
        name_patterns = [
            r"My name is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
            r"I am\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
            r"(?:my name|student name|applicant name)\s*:?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
            r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?:\s+from|\s+at|\s+studies|$)"
        ]
        
        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                candidate = match.group(1).strip()
                # Validate it looks like a name
                if len(candidate) > 2 and len(candidate) < 100:
                    return candidate
        
        # Strategy 2: Check first 20 lines for capitalized names
        for line in lines[:20]:
            line = line.strip()
            if len(line) > 4 and len(line) < 80:
                words = line.split()
                # Check if looks like a name (2-4 capitalized words, each word 2+ chars)
                if 2 <= len(words) <= 4 and all(len(w) > 1 for w in words):
                    # All major words capitalized
                    if all(w[0].isupper() for w in words):
                        # Avoid common false positives
                        text_lower = line.lower()
                        if not any(x in text_lower for x in ['high school', 'university', 'college', 'academy', 'institute', 'department']):
                            return line
        
        return None
    
    def _extract_school_name_with_ai(self, text: str) -> Optional[str]:
        """Use AI reasoning to intelligently extract school name from document."""
        try:
            # First try pattern-based extraction for speed
            school = self._extract_school_name_pattern(text)
            if school and school not in ['High School', 'School', 'High school']:
                return school
            
            # Fallback to AI if pattern matching fails or returns generic result
            # First attempt: short precise extraction (single value)
            short_prompt = (
                "You are an expert at extracting information from student documents.\n"
                "Extract ONLY the name of the student's HIGH SCHOOL or secondary school.\n"
                "Return just the school name, nothing else. If no clear school name found, return 'NONE'.\n\n"
                "Document excerpt:\n" + text[:800]
            )

            messages = [
                {"role": "system", "content": "You extract precise school names from student documents. Return only the school name, no explanations."},
                {"role": "user", "content": short_prompt}
            ]

            response = self._create_chat_completion(
                operation="belle.extract_school",
                model=self.model,
                messages=messages,
                max_completion_tokens=120,
                temperature=0
            )

            school = response.choices[0].message.content.strip() if response else None

            if school and school != "NONE" and len(school) > 3 and len(school) < 200 and not any(x in school.lower() for x in ['sorry', "i don't", 'unclear', 'not found', 'unable', 'cannot']):
                return school

            # Candidate generation: collect possible school name mentions from the document
            candidates = self._gather_school_name_candidates(text)
            if candidates:
                try:
                    ranked = self._rank_school_candidates(text, candidates)
                    if ranked and self._is_valid_school_name(ranked):
                        return ranked
                    # If ranked result isn't a clear school name (e.g., the model returned a city), ask the model to clarify
                    if ranked and not self._is_valid_school_name(ranked):
                        try:
                            clarify_prompt = (
                                f"The value '{ranked}' looks like it may be a city or incomplete.\n"
                                "Using the document below, identify the student's full HIGH SCHOOL name (full official name).\n"
                                "Return ONLY the school name or NONE.\n\nDocument excerpt:\n" + text[:1200]
                            )
                            clarify_messages = [
                                {"role": "system", "content": "You are an expert at extracting and validating school names. Return only the final school name or NONE."},
                                {"role": "user", "content": clarify_prompt}
                            ]
                            clar_resp = self._create_chat_completion(
                                operation="belle.clarify_school",
                                model=self.model,
                                messages=clarify_messages,
                                max_completion_tokens=120,
                                temperature=0
                            )
                            clar_choice = clar_resp.choices[0].message.content.strip() if clar_resp else None
                            if clar_choice and self._is_valid_school_name(clar_choice):
                                return clar_choice
                        except Exception:
                            pass
                except Exception:
                    # If ranking fails, continue to deep pass
                    pass

            # Deep reasoning pass (JSON) as a last resort
            deep_prompt = (
                "You are a careful document analyst.\n"
                "Using the document below, identify the student's HIGH SCHOOL (full name), the city it is located in (if present), and the state (full name or 2-letter code).\n"
                "Return a JSON object with the fields: {\"school_name\": string or null, \"city\": string or null, \"state\": string or null, \"confidence\": 0-100}.\n"
                "If you are not sure, set fields to null and confidence to a low number.\n\nDocument:\n" + text[:1800]
            )

            deep_messages = [
                {"role": "system", "content": "You are an expert annotator. Return ONLY JSON with the requested fields."},
                {"role": "user", "content": deep_prompt}
            ]

            deep_resp = self._create_chat_completion(
                operation="belle.extract_school_deep",
                model=self.model,
                messages=deep_messages,
                max_completion_tokens=400,
                temperature=0
            )

            try:
                deep_text = deep_resp.choices[0].message.content if deep_resp else ""
                # Try to extract JSON block
                json_match = re.search(r'\{[\s\S]*\}', deep_text)
                if json_match:
                    payload = json.loads(json_match.group())
                else:
                    payload = json.loads(deep_text)

                school_name = payload.get("school_name")
                if school_name and school_name != "NONE":
                    return school_name
            except Exception:
                # Fall through to return None
                pass

            return None
        except Exception as e:
            # If AI fails, fall back to pattern matching
            return self._extract_school_name_pattern(text)

    def _map_state_name_to_code(self, state_name: str) -> Optional[str]:
        """Map full state name to 2-letter code (best-effort)."""
        mapping = {
            'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA',
            'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA',
            'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA',
            'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
            'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO',
            'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ',
            'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH',
            'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
            'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT', 'vermont': 'VT',
            'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY'
        }
        if not state_name:
            return None
        key = state_name.strip().lower()
        return mapping.get(key)
    
    def _extract_school_name_pattern(self, text: str) -> Optional[str]:
        """Extract school name using pattern matching."""
        # Strategy 1: Explicit school name patterns
        patterns = [
            r'(?:High School|School Name|School)\s*[:\-]?\s*([A-Za-z0-9\s&\'\-\.]+?)(?:\n|$|,)',
            r'(?:Graduated from|From|Attended)\s+([A-Za-z0-9\s&\'\-\.]+?)\s+(?:High School|School)',
            r'([A-Za-z0-9\s&\'\-\.]+?)\s+(?:High School|School)',
            r'School\s*[:\-]?\s*([A-Za-z0-9\s&\'\-\.]+?)(?:\n|,|$)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                school = match.group(1).strip()
                if school and len(school) > 3 and len(school) < 200:
                    # Filter out noise
                    if not any(x in school.lower() for x in ['activities', 'i think', 'i would', 'want', 'continue', 'well at']):
                        return school
        
        return None

    def _gather_school_name_candidates(self, text: str) -> List[str]:
        """Gather candidate school names using heuristics and pattern matches."""
        candidates = []

        # Include the pattern-based primary candidate if present
        primary = self._extract_school_name_pattern(text)
        if primary:
            candidates.append(primary)

        # Regex patterns to catch 'X High School' and variations
        patterns = [
            r'([A-Z][A-Za-z0-9&\-\'\.]{{3,80}})\s+High School',
            r'([A-Z][A-Za-z0-9&\-\'\.]{{3,80}})\s+HS\b',
            r'Attended\s+([A-Z][A-Za-z0-9&\-\'\.]{{3,80}}(?:\s+High School)?)',
            r'Graduated from\s+([A-Z][A-Za-z0-9&\-\'\.]{{3,80}}(?:\s+High School)?)',
            r'([A-Z][A-Za-z0-9&\-\'\.]{{3,80}})\s+Secondary School'
        ]

        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                cand = m.group(1).strip()
                if cand and cand not in candidates and len(cand) > 3:
                    # Clean trailing punctuation
                    cand = cand.rstrip('.,;:')
                    candidates.append(cand)

        # Also inspect capitalized lines that end with 'High School' within first 60 lines
        for line in text.split('\n')[:60]:
            line = line.strip()
            if line.lower().endswith('high school') or ' high school ' in line.lower():
                # trim descriptors
                cand = re.sub(r'\s+High School.*$', ' High School', line, flags=re.IGNORECASE).strip()
                if cand and cand not in candidates:
                    candidates.append(cand)

        # Keep only unique, reasonable-length candidates
        final = []
        for c in candidates:
            if 3 < len(c) < 200 and c not in final:
                final.append(c)

        return final

    def _rank_school_candidates(self, text: str, candidates: List[str]) -> Optional[str]:
        """Ask the model to pick the best candidate from a short candidate list.

        Returns the selected candidate string or None.
        """
        if not candidates:
            return None

        # If only one candidate, trust it
        if len(candidates) == 1:
            return candidates[0]

        # Build a compact prompt listing candidates for the model to choose
        choices_text = '\n'.join([f"{i+1}. {c}" for i, c in enumerate(candidates)])
        prompt = (
            "Below are candidate school names found in a student document.\n"
            "Choose the single best candidate that is the student's HIGH SCHOOL (prefer candidates that include 'High School', 'HS', 'School', 'Academy', 'Charter', 'Magnet', or 'Institute').\n"
            "Do NOT return a city or state name — return NONE if the choices are cities or ambiguous.\n"
            "Return ONLY the chosen candidate text exactly as it appears in the list, or return 'NONE' if none match.\n\n"
            "Candidates:\n" + choices_text + "\n\n"
            "Document excerpt:\n" + text[:800]
        )

        messages = [
            {"role": "system", "content": "You are an expert at precise extraction and selection. Return only the selected candidate text or NONE."},
            {"role": "user", "content": prompt}
        ]

        resp = self._create_chat_completion(
            operation="belle.rank_school_candidates",
            model=self.model,
            messages=messages,
            max_completion_tokens=80,
            temperature=0
        )

        try:
            choice = resp.choices[0].message.content.strip() if resp else None
            if not choice:
                return None
            # If model returned a numbered choice (e.g., '1' or '1. School Name'), normalize
            m = re.match(r'^(\d+)\.?\s*(.*)$', choice)
            if m:
                idx = int(m.group(1)) - 1
                if 0 <= idx < len(candidates):
                    return candidates[idx]
                else:
                    # fallback to text portion
                    text_choice = m.group(2).strip()
                    if text_choice in candidates:
                        return text_choice

            # If returned exact candidate text
            if choice in candidates:
                return choice

            # Sometimes model returns a cleaned variant; pick best fuzzy match by substring
            for c in candidates:
                if c.lower() in choice.lower() or choice.lower() in c.lower():
                    return c

        except Exception:
            return None

        return None

    def _is_valid_school_name(self, name: Optional[str]) -> bool:
        """Return True if the extracted name looks like a real school name (not a city)."""
        if not name or not isinstance(name, str):
            return False
        s = name.strip()
        if len(s) < 3 or len(s) > 200:
            return False

        keywords = ['high school', 'hs', 'school', 'academy', 'charter', 'magnet', 'institute', 'secondary']
        lowered = s.lower()
        if any(k in lowered for k in keywords):
            return True

        # Accept multi-word names that look like proper nouns (e.g., "Central Catholic")
        parts = [p for p in s.split() if p]
        if len(parts) >= 2 and all(p[0].isupper() for p in parts if p[0].isalpha()):
            # But reject obvious city-only answers like single-word cities
            return True

        return False
    def _extract_data_by_type(self, text: str, doc_type: str) -> Dict[str, Any]:
        """Extract type-specific data from the document."""

        extractors = {
            "transcript": self._extract_transcript_data,
            "letter_of_recommendation": self._extract_recommendation_data,
            "application": self._extract_application_data,
            "grades": self._extract_grades_data,
            "test_scores": self._extract_test_scores_data,
            "resume": self._extract_resume_data,
            "essay": self._extract_essay_data,
            "achievement": self._extract_achievement_data
        }
        
        extractor = extractors.get(doc_type, self._extract_generic_data)
        return extractor(text)
    
    def _extract_transcript_data(self, text: str) -> Dict[str, Any]:
        """Extract academic transcript data."""
        data = {}
        
        # GPA pattern
        gpa_match = re.search(r'(?:GPA|Grade Point Average)[\s:]*([0-4]\.[0-9]{2})', text, re.IGNORECASE)
        if gpa_match:
            data["gpa"] = float(gpa_match.group(1))
        
        # Extract course entries (Pattern: CODE TITLE GRADE)
        course_pattern = r'([A-Z]{2,4}\s*\d{3,4})\s+([A-Za-z0-9\s&-]{10,60})\s+([A-F][+-]?|\d\.\d)'
        courses = re.findall(course_pattern, text)
        if courses:
            data["courses"] = [
                {"code": c[0].strip(), "title": c[1].strip(), "grade": c[2].strip()}
                for c in courses
            ]
        
        return data
    
    def _extract_recommendation_data(self, text: str) -> Dict[str, Any]:
        """Extract letter of recommendation data."""
        data = {}
        
        # Find recommender details
        lines = text.split('\n')
        for i, line in enumerate(lines[:20]):
            if 'dear' in line.lower() or 'to whom it may concern' in line.lower():
                data["salutation"] = line.strip()
                break
        
        # Extract strength keywords
        strength_keywords = ["excellent", "outstanding", "exceptional", "strong", "demonstrates", "skilled", "capable"]
        strengths = []
        for keyword in strength_keywords:
            if keyword in text.lower():
                # Find sentence containing keyword
                sentences = text.split('.')
                for sent in sentences:
                    if keyword in sent.lower() and len(sent.strip()) > 20:
                        strengths.append(sent.strip())
                        break
        
        if strengths:
            data["identified_strengths"] = strengths[:3]  # Top 3
        
        return data
    
    def _extract_application_data(self, text: str) -> Dict[str, Any]:
        """Extract application form data."""
        data = {}
        
        # Look for key fields
        fields = {
            "motivation": ["motivation", "why", "interest"],
            "experience": ["experience", "background", "history"],
            "goals": ["goals", "objectives", "future plans"],
            "achievements": ["achievement", "accomplishment", "award"]
        }
        
        sentences = text.split('.')
        for field_name, keywords in fields.items():
            for sent in sentences:
                if any(kw in sent.lower() for kw in keywords) and len(sent.strip()) > 30:
                    data[field_name] = sent.strip()
                    break
        
        return data
    
    def _extract_grades_data(self, text: str) -> Dict[str, Any]:
        """Extract grade/score data."""
        data = {}
        
        # Find all letter grades with potential scores
        grade_pattern = r'([A-F][+-]?|[1-5]|[0-9]{1,3}%)'
        grades = re.findall(grade_pattern, text)
        if grades:
            data["grades_found"] = list(set(grades))
        
        # Look for numerical scores
        score_pattern = r'(\d{1,3})(?:%|/100|points)'
        scores = re.findall(score_pattern, text)
        if scores:
            data["scores"] = [int(s) for s in scores]
        
        return data
    
    def _extract_test_scores_data(self, text: str) -> Dict[str, Any]:
        """Extract standardized test score data."""
        data = {}
        
        # SAT
        sat_match = re.search(r'SAT[\s:]*(\d{3,4})', text, re.IGNORECASE)
        if sat_match:
            data["sat_score"] = int(sat_match.group(1))
        
        # ACT
        act_match = re.search(r'ACT[\s:]*(\d{2})', text, re.IGNORECASE)
        if act_match:
            data["act_score"] = int(act_match.group(1))
        
        # GRE
        gre_match = re.search(r'GRE[\s:]*(\d{3})', text, re.IGNORECASE)
        if gre_match:
            data["gre_score"] = int(gre_match.group(1))
        
        return data
    
    def _extract_resume_data(self, text: str) -> Dict[str, Any]:
        """Extract resume/CV data."""
        data = {}
        
        # Find sections
        sections = ["education", "experience", "skills", "projects"]
        for section in sections:
            pattern = rf'{section}[\s\S]*?(?={"|".join(sections)}|$)'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data[f"{section}_section"] = match.group(0)[:200]  # First 200 chars
        
        return data
    
    def _extract_essay_data(self, text: str) -> Dict[str, Any]:
        """Extract essay/personal statement data."""
        data = {}
        
        word_count = len(text.split())
        data["word_count"] = word_count
        
        # Estimate reading time
        data["estimated_read_time_minutes"] = max(1, word_count // 200)
        
        # Extract opening statement
        sentences = text.split('.')
        if sentences:
            data["opening_statement"] = sentences[0].strip()[:100]
        
        return data
    
    def _extract_achievement_data(self, text: str) -> Dict[str, Any]:
        """Extract achievement/award data."""
        data = {}
        
        # Look for specific achievements
        keywords = ["award", "scholarship", "recognize", "honor", "received", "winner"]
        achievements = []
        
        sentences = text.split('.')
        for sent in sentences:
            if any(kw in sent.lower() for kw in keywords):
                achievements.append(sent.strip())
        
        if achievements:
            data["achievements"] = achievements
        
        return data
    
    def _extract_generic_data(self, text: str) -> Dict[str, Any]:
        """Extract generic data when document type is unknown."""
        return {
            "word_count": len(text.split()),
            "paragraph_count": len(text.split('\n\n')),
            "contains_numbers": bool(re.search(r'\d', text))
        }
    
    def _generate_summary(self, text: str, doc_type: str, extracted_data: Dict) -> str:
        """Generate a high-level summary of the document."""
        
        summary_parts = []
        summary_parts.append(f"Document Type: {doc_type.replace('_', ' ').title()}")
        
        if extracted_data:
            data_items = list(extracted_data.keys())[:3]
            summary_parts.append(f"Key Data: {', '.join(data_items)}")
        
        word_count = len(text.split())
        summary_parts.append(f"Length: ~{word_count} words")
        
        return " | ".join(summary_parts)
