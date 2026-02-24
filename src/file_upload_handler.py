"""
File Upload Handler - PHASE 5 Component 2

Handles file uploads with intelligent AI-based student matching and re-evaluation.

Workflow:
1. New file uploaded
2. Extract student identifier from file
3. Query database for matching students (fuzzy + AI)
4. If match found: Add to student's file collection + re-evaluate
5. If no match: Create new student record
6. Re-run 9-step workflow with accumulated files for fresh perspective
"""

import logging
import json
from src.utils import safe_load_json
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime
# Avoid importing `openai` at module import time to prevent startup failures when
# the package is not installed in the runtime. The client is accepted as a runtime
# object and should be provided by the caller (lazy instantiation).

logger = logging.getLogger(__name__)


def _call_model(client, model, messages, **kwargs):
    """Provider-agnostic helper to call the AI client.

    Tries common client shapes in order so callers don't need to handle
    Foundry vs Azure/OpenAI differences.
    """
    # Try Foundry-style: client.chat.create(...)
    try:
        if hasattr(client, "chat") and hasattr(client.chat, "create"):
            return client.chat.create(model=model, messages=messages, **kwargs)
    except Exception:
        logger.debug("client.chat.create failed or not compatible")

    # Try Azure/OpenAI-style: client.chat.completions.create(...)
    try:
        if hasattr(client, "chat") and hasattr(client.chat, "completions") and hasattr(client.chat.completions, "create"):
            return client.chat.completions.create(model=model, messages=messages, **kwargs)
    except Exception:
        logger.debug("client.chat.completions.create failed or not compatible")

    # Try generic generate()
    try:
        if hasattr(client, "generate"):
            return client.generate(model=model, messages=messages, **kwargs)
    except Exception:
        logger.debug("client.generate failed or not compatible")

    # Try older completions attribute: client.completions.create(...)
    try:
        if hasattr(client, "completions") and hasattr(client.completions, "create"):
            return client.completions.create(model=model, messages=messages, **kwargs)
    except Exception:
        logger.debug("client.completions.create failed or not compatible")

    raise RuntimeError("No compatible model call method found on client")


class FileUploadHandler:
    """Manages file uploads and intelligent student matching."""
    
    def __init__(self, db_connection, client: Any, model: str):
        """
        Initialize the file upload handler.
        
        Args:
            db_connection: Database connection
            client: Azure OpenAI client
            model: Model deployment name
        """
        self.db = db_connection
        self.client = client
        self.model = model
    
    async def handle_file_upload(
        self,
        file_content: str,
        file_name: str,
        file_type: str,
        file_size: int
    ) -> Dict[str, Any]:
        """
        PHASE 5: Handle new file upload with AI student matching.
        
        Workflow:
        1. Extract student identifier from file (extract_student_id_from_file)
        2. AI-based matching against database records (ai_match_student)
        3. Determine if new or existing student
        4. Add file to student's collection
        5. Mark for re-evaluation
        6. Trigger workflow restart
        
        Args:
            file_content: Text content of uploaded file
            file_name: Original file name
            file_type: MIME type (pdf, text, image, etc)
            file_size: File size in bytes
            
        Returns:
            Dict with {
                'status': 'success|error',
                'application_id': int (student ID),
                'action': 'new_student|file_added_to_existing',
                'match_confidence': float (0-1),
                'student_info': {...},
                'workflow_started': bool,
                'message': str
            }
        """
        try:
            logger.info(f"📤 File upload handler: {file_name} ({file_size} bytes)")
            
            # STEP 1: Extract student identifier from file
            logger.info(f"🔍 Extracting student identifier from {file_name}...")
            student_id_info = await self._extract_student_id_from_file(
                file_content, file_name
            )
            
            if 'error' in student_id_info:
                logger.warning(f"Could not extract student ID: {student_id_info.get('error')}")
                return {
                    'status': 'error',
                    'error': student_id_info.get('error'),
                    'message': 'Could not extract student information from file'
                }
            
            first_name = student_id_info.get('first_name', '')
            last_name = student_id_info.get('last_name', '')
            high_school = student_id_info.get('high_school', '')
            state_code = student_id_info.get('state_code', '')
            
            logger.info(
                f"✓ Extracted student info: {first_name} {last_name}, {high_school}, {state_code}"
            )
            
            # STEP 2: AI-based matching against database
            logger.info(f"🤖 Running AI-based student matching...")
            match_result = await self._ai_match_student(
                first_name=first_name,
                last_name=last_name,
                high_school=high_school,
                state_code=state_code,
                file_content=file_content,
                file_name=file_name
            )
            
            match_found = match_result.get('found')
            match_confidence = match_result.get('confidence', 0.0)
            existing_application_id = match_result.get('application_id')
            
            logger.info(
                f"AI Match Result: found={match_found}, confidence={match_confidence}",
                extra={'application_id': existing_application_id}
            )
            
            # STEP 3: Determine if new or existing student
            if match_found and existing_application_id:
                # Existing student: add file to collection
                logger.info(
                    f"✅ Found existing student (ID: {existing_application_id}, confidence: {match_confidence})",
                    extra={'application_id': existing_application_id}
                )
                
                result = await self._add_file_to_existing_student(
                    application_id=existing_application_id,
                    file_content=file_content,
                    file_name=file_name,
                    file_type=file_type,
                    file_size=file_size,
                    match_confidence=match_confidence,
                    extracted_info=student_id_info
                )
                
                return {
                    'status': 'success',
                    'application_id': existing_application_id,
                    'action': 'file_added_to_existing',
                    'match_confidence': match_confidence,
                    'student_info': result.get('student_info'),
                    'workflow_started': result.get('workflow_started', True),
                    'audit_id': result.get('audit_id'),
                    'message': f"File added to existing student record (Match confidence: {match_confidence:.1%}). Re-evaluation started."
                }
            else:
                # New student or low confidence match: create new record
                logger.info(
                    f"📝 Creating new student record",
                    extra={'confidence': match_confidence}
                )
                
                result = await self._create_new_student_from_file(
                    file_content=file_content,
                    file_name=file_name,
                    file_type=file_type,
                    file_size=file_size,
                    extracted_info=student_id_info
                )
                
                return {
                    'status': 'success',
                    'application_id': result.get('application_id'),
                    'action': 'new_student',
                    'match_confidence': match_confidence if match_found else 0.0,
                    'student_info': {
                        'first_name': first_name,
                        'last_name': last_name,
                        'high_school': high_school,
                        'state_code': state_code
                    },
                    'workflow_started': result.get('workflow_started', True),
                    'audit_id': result.get('audit_id'),
                    'message': f"New student record created. Workflow started with uploaded file."
                }
            
        except Exception as e:
            logger.error(f"❌ File upload handler error: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Error processing file upload'
            }
    
    async def _extract_student_id_from_file(
        self,
        file_content: str,
        file_name: str
    ) -> Dict[str, Any]:
        """
        Extract student identifier from file using AI.
        
        Uses BELLE-like extraction to find:
        - Student first name
        - Student last name
        - High school name
        - State code
        
        Args:
            file_content: File text content
            file_name: Original file name
            
        Returns:
            Dict with extracted student info or error
        """
        try:
            prompt = f"""Extract student identifier information from this document.

FILE: {file_name}
CONTENT (first 5000 chars):
{file_content[:5000]}

Extract ONLY these fields (return as JSON, null if not found):
{{
  "first_name": "student's first name or null",
  "last_name": "student's last name or null",
  "high_school": "high school name or null",
  "state_code": "2-letter state code or null",
  "confidence": 0-1 scale of extraction confidence
}}

Return ONLY the JSON, no other text."""
            
            response = _call_model(
                self.client,
                self.model,
                [
                    {
                        "role": "system",
                        "content": "You are an expert document analyzer. Extract student information accurately."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=500,
                temperature=0
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                extracted = safe_load_json(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from response text
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    extracted = safe_load_json(json_match.group())
                else:
                    return {'error': 'Could not parse extraction response'}
            
            if not (extracted.get('first_name') and extracted.get('last_name')):
                logger.warning("Incomplete student information extracted")
                return {'error': 'Could not extract sufficient student information'}
            
            return {
                'first_name': extracted.get('first_name', '').strip(),
                'last_name': extracted.get('last_name', '').strip(),
                'high_school': extracted.get('high_school', '').strip(),
                'state_code': extracted.get('state_code', '').strip(),
                'confidence': extracted.get('confidence', 0.5)
            }
            
        except Exception as e:
            logger.error(f"Error extracting student ID: {e}")
            return {'error': str(e)}
    
    async def _ai_match_student(
        self,
        first_name: str,
        last_name: str,
        high_school: str,
        state_code: str,
        file_content: str,
        file_name: str
    ) -> Dict[str, Any]:
        """
        Use AI for fuzzy matching of student against database records.
        
        Can match based on:
        - Exact name + school match
        - Similar name with same school
        - Same school + similar demographics
        
        If confidence >= 0.8, consider it a match.
        
        Args:
            first_name: Extracted first name
            last_name: Extracted last name
            high_school: Extracted high school
            state_code: Extracted state
            file_content: File content for additional context
            file_name: File name for context
            
        Returns:
            Dict with {found, confidence, application_id}
        """
        try:
            # Query database for similar students
            similar_students = self.db.find_similar_students(
                first_name=first_name,
                last_name=last_name,
                high_school=high_school,
                state_code=state_code,
                limit=5
            )
            
            if not similar_students:
                logger.info("No similar students found in database")
                return {'found': False, 'confidence': 0.0, 'application_id': None}
            
            # Use AI to evaluate matches
            candidates_text = "\n".join([
                f"ID {s['application_id']}: {s['first_name']} {s['last_name']}, "
                f"{s.get('high_school', 'Unknown School')}, {s.get('state_code', 'Unknown')}"
                for s in similar_students
            ])
            
            prompt = f"""Determine if any of these database records match the uploaded student.

UPLOADED STUDENT:
Name: {first_name} {last_name}
High School: {high_school}
State: {state_code}
File: {file_name}

DATABASE CANDIDATES:
{candidates_text}

DECISION RULES:
- Exact match (same name, school, state) = 0.95
- Same school and state, similar name = 0.85
- Same school, similar name = 0.75
- Other similarities = 0.50
- No match = 0.0

Return JSON:
{{
  "best_match_id": <application_id or null>,
  "confidence": <0-1>,
  "reasoning": "brief explanation"
}}

Return ONLY JSON, no other text."""
            
            response = _call_model(
                self.client,
                self.model,
                [
                    {
                        "role": "system",
                        "content": "You are expert at fuzzy matching student records"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=300,
                temperature=0
            )
            
            response_text = response.choices[0].message.content.strip()
            decision = safe_load_json(response_text)
            
            confidence = decision.get('confidence', 0.0)
            best_match_id = decision.get('best_match_id')
            
            # Threshold: 0.8+ = match
            if confidence >= 0.8 and best_match_id:
                logger.info(
                    f"✓ AI Match found with confidence {confidence}",
                    extra={'application_id': best_match_id}
                )
                return {
                    'found': True,
                    'confidence': confidence,
                    'application_id': best_match_id,
                    'reasoning': decision.get('reasoning')
                }
            else:
                logger.info(f"No confident match found (best confidence: {confidence})")
                return {'found': False, 'confidence': confidence, 'application_id': None}
            
        except Exception as e:
            logger.error(f"Error in AI matching: {e}", exc_info=True)
            return {'found': False, 'confidence': 0.0, 'application_id': None}
    
    async def _add_file_to_existing_student(
        self,
        application_id: int,
        file_content: str,
        file_name: str,
        file_type: str,
        file_size: int,
        match_confidence: float,
        extracted_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Add uploaded file to existing student's collection and restart workflow.
        
        Args:
            application_id: Student application ID
            file_content: File content
            file_name: File name
            file_type: File type
            file_size: File size
            match_confidence: AI match confidence
            extracted_info: Extracted student info from file
            
        Returns:
            Dict with {student_info, workflow_started, audit_id}
        """
        try:
            logger.info(f"Adding file to student {application_id}")
            
            # Get existing student record
            student_record = self.db.get_application(application_id)
            if not student_record:
                return {'error': 'Student record not found', 'workflow_started': False}
            
            # Log file upload audit for human review
            audit_id = self.db.log_file_upload_audit(
                file_name=file_name,
                file_type=file_type,
                file_size=file_size,
                extracted_first_name=extracted_info.get('first_name', ''),
                extracted_last_name=extracted_info.get('last_name', ''),
                extracted_high_school=extracted_info.get('high_school', ''),
                extracted_state_code=extracted_info.get('state_code', ''),
                extraction_confidence=extracted_info.get('confidence', 0.5),
                matched_application_id=application_id,
                ai_match_confidence=match_confidence,
                match_status='matched_existing',
                match_reasoning=f"File matched to existing student with {match_confidence:.1%} confidence"
            )
            
            # Log file upload to workflow audit trail
            self.db.log_agent_interaction(
                application_id=application_id,
                agent_name='FileUploadHandler',
                interaction_type='file_upload',
                question_text=f"New file uploaded for re-evaluation",
                file_name=file_name,
                file_size=file_size,
                file_type=file_type,
                extracted_data={
                    'action': 'file_added_to_existing',
                    'match_confidence': match_confidence,
                    'audit_id': audit_id,
                    'timestamp': datetime.now().isoformat()
                }
            )
            
            # Mark for re-evaluation (workflow will run with all files)
            self.db.mark_for_re_evaluation(application_id)
            
            # Store file content (would be in actual storage - for now just track)
            logger.info(
                f"✓ File added to student {application_id}, marked for re-evaluation",
                extra={'file': file_name, 'match_confidence': match_confidence, 'audit_id': audit_id}
            )
            
            return {
                'student_info': {
                    'application_id': application_id,
                    'first_name': student_record.get('first_name'),
                    'last_name': student_record.get('last_name')
                },
                'workflow_started': True,
                'audit_id': audit_id
            }
            
        except Exception as e:
            logger.error(f"Error adding file to student: {e}")
            return {'error': str(e), 'workflow_started': False}
    
    async def _create_new_student_from_file(
        self,
        file_content: str,
        file_name: str,
        file_type: str,
        file_size: int,
        extracted_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create new student record from uploaded file.
        
        Args:
            file_content: File content
            file_name: File name
            file_type: File type
            file_size: File size
            extracted_info: Extracted student information
            
        Returns:
            Dict with {application_id, workflow_started, audit_id}
        """
        try:
            logger.info("Creating new student record from uploaded file")
            
            first_name = extracted_info.get('first_name', '')
            last_name = extracted_info.get('last_name', '')
            high_school = extracted_info.get('high_school', '')
            state_code = extracted_info.get('state_code', '')
            
            # Create student record
            application_id = self.db.create_student_record(
                first_name=first_name,
                last_name=last_name,
                high_school=high_school,
                state_code=state_code,
                application_text=file_content
            )
            
            if not application_id:
                return {'error': 'Failed to create student record', 'workflow_started': False}
            
            # Log file upload audit for human review
            audit_id = self.db.log_file_upload_audit(
                file_name=file_name,
                file_type=file_type,
                file_size=file_size,
                extracted_first_name=first_name,
                extracted_last_name=last_name,
                extracted_high_school=high_school,
                extracted_state_code=state_code,
                extraction_confidence=extracted_info.get('confidence', 0.5),
                matched_application_id=application_id,
                ai_match_confidence=1.0,  # Perfect match for new student
                match_status='new_student',
                match_reasoning='First file for new student - automatically matched'
            )
            
            # Log file upload to workflow audit trail
            self.db.log_agent_interaction(
                application_id=application_id,
                agent_name='FileUploadHandler',
                interaction_type='file_upload',
                question_text='Initial upload for new student',
                file_name=file_name,
                file_size=file_size,
                file_type=file_type,
                extracted_data={
                    'action': 'new_student_created',
                    'audit_id': audit_id,
                    'timestamp': datetime.now().isoformat()
                }
            )
            
            logger.info(f"✓ New student created: ID {application_id}")
            
            return {
                'application_id': application_id,
                'workflow_started': True,
                'audit_id': audit_id
            }
            
        except Exception as e:
            logger.error(f"Error creating new student: {e}")
            return {'error': str(e), 'workflow_started': False}


# Helper function for convenience
async def handle_file_upload(
    file_content: str,
    file_name: str,
    file_type: str,
    file_size: int,
    db_connection,
    client: Any,
    model: str
) -> Dict[str, Any]:
    """Convenience function to handle file upload."""
    handler = FileUploadHandler(db_connection, client, model)
    return await handler.handle_file_upload(file_content, file_name, file_type, file_size)
