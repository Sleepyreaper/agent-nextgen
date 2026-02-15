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
    
    def __init__(self, client: AzureOpenAI, model: str):
        """
        Initialize Belle Document Analyzer.
        
        Args:
            client: Azure OpenAI client
            model: Model deployment name
        """
        super().__init__(name="Belle", client=client)
        self.model = model
        self.emoji = "📖"
        self.description = "Analyzes documents and extracts structured data"
        
        # Define document type detection patterns
        self.document_types = {
            "transcript": ["transcript", "grade report", "academic record", "gpa", "course"],
            "letter_of_recommendation": ["letter of recommendation", "recommendation", "character reference", "endorsed", "recommends"],
            "application": ["application", "apply for", "student application", "job application", "cover letter"],
            "grades": ["grades", "mark", "score", "test result", "exam", "final grade", "assignment grade"],
            "test_scores": ["sat", "act", "gre", "gmat", "test score", "standardized test"],
            "resume": ["resume", "cv", "curriculum vitae", "experience", "employment history"],
            "essay": ["essay", "personal statement", "written response", "reflection"],
            "achievement": ["award", "scholarship", "honor", "recognition", "achievement", "accomplishment"]
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
        
        # Step 1: Identify document type
        doc_type, confidence = self._identify_document_type(text_content, original_filename)
        
        # Step 2: Extract type-specific data
        extracted_data = self._extract_data_by_type(text_content, doc_type)
        
        # Step 3: Extract common student info across all documents
        student_info = self._extract_student_info(text_content)
        
        # Step 4: Generate summary
        summary = self._generate_summary(text_content, doc_type, extracted_data)
        
        return {
            "document_type": doc_type,
            "confidence": confidence,
            "student_info": student_info,
            "extracted_data": extracted_data,
            "summary": summary,
            "original_filename": original_filename,
            "text_preview": text_content[:500] if len(text_content) > 500 else text_content
        }
    
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
        """Extract common student information from any document."""
        
        student_info = {
            "name": None,
            "email": None,
            "student_id": None,
            "phone": None,
            "major": None,
            "graduation_year": None
        }
        
        # Email pattern
        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        if email_match:
            student_info["email"] = email_match.group()
        
        # Student ID pattern (common formats: S12345, 123456789, A00123456)
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
        
        # Major pattern (common engineering patterns)
        major_match = re.search(r'Major[\s:]*([A-Za-z\s&]{3,50})(?:Minor|Concentration|GPA|$)', text, re.IGNORECASE)
        if major_match:
            student_info["major"] = major_match.group(1).strip()
        
        # Name extraction (heuristic: appears at top of document)
        lines = text.split('\n')
        for line in lines[:10]:  # Check first 10 lines
            if len(line.strip()) > 2 and len(line.strip()) < 60:
                words = line.strip().split()
                if len(words) <= 4 and all(w[0].isupper() for w in words if len(w) > 1):
                    student_info["name"] = line.strip()
                    break
        
        return {k: v for k, v in student_info.items() if v is not None}
    
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
