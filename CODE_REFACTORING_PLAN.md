# Code Refactoring Plan - Agent Workflow Alignment

**Status**: Planning Phase  
**Date**: February 18, 2026

---

## 🎯 CRITICAL: BELLE is Reusable Data Extraction Service

**BELLE is NOT a single "Step 1" call. BELLE is a reusable utility that SMEE invokes throughout the workflow:**

| When | Why | What BELLE Does |
|------|-----|-----------------|
| Initial | Document just uploaded | Extract all fields: name, school, grades, recommendations, etc. |
| Validation fails | Agent needs data we don't have | Re-examine document for specific field (e.g., "find GPA", "find school") |
| School incomplete | NAVEEN can't enrich school fully | Re-examine document for school documents/details |
| New upload | User adds more files | Extract and merge with existing data |
| Pattern missing | Agent can't perform analysis | Re-examine document for specific patterns agent needs |

**SMEE's job**: Decide WHEN to call BELLE based on validation failures and data gaps.

---

## Summary

Refactor the agent orchestration system to match the correctly-defined workflow:

**BELLE = Reusable Data Extraction Utility**
- Called initially to extract from uploaded document
- Called reactively when agents need more data from document
- Called when user uploads new files
- SMEE determines WHEN to invoke BELLE based on needs

**Core Workflow Steps:**
```
Intake Phase:
  - BELLE extracts data (SMEE calls when needed)
  - Student record matching (first + last + school + state)
  - NAVEEN enriches school (if not cached)
  - School validation loop (NAVEEN ↔ MOANA feedback)
  - Core agent validation gates (per-agent readiness check)

Analysis Phase:
  - TIANA (application metadata)
  - RAPUNZEL (grades with school context weighting)
  - MOANA (school context)
  - MULAN (recommendations)

Synthesis Phase:
  - MILO (training pattern analysis)
  - MERLIN (executive synthesis & scoring)
  - AURORA (formatted report generation)
```

---

## Database Schema Changes

### 1. Add Student Metadata to `applications` Table
**File**: `database/schema_postgresql.sql` and `schema.sql`

**Add columns for accurate matching**:
```sql
ALTER TABLE applications ADD COLUMN IF NOT EXISTS first_name VARCHAR(255);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS last_name VARCHAR(255);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS high_school VARCHAR(500);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS state_code VARCHAR(2);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS school_name VARCHAR(500); -- redundant but safe
```

**Create index for fast matching**:
```sql
CREATE INDEX IF NOT EXISTS idx_app_student_match 
ON applications(first_name, last_name, high_school, state_code);
```

---

### 2. Create `rapunzel_grades` Table
**File**: `database/schema_postgresql.sql` and `schema.sql`

**For storing RAPUNZEL output** (currently saves to `ai_evaluations` - needs dedicated table):
```sql
CREATE TABLE IF NOT EXISTS rapunzel_grades (
    rapunzel_grade_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES applications(application_id) ON DELETE CASCADE,
    agent_name VARCHAR(255) DEFAULT 'Rapunzel',
    gpa NUMERIC(4,3),
    academic_strength VARCHAR(100),
    course_levels JSONB,
    transcript_quality VARCHAR(100),
    notable_patterns TEXT,
    contextual_rigor_index NUMERIC(5,2),
    confidence_level VARCHAR(50),
    summary TEXT,
    parsed_json JSONB,
    school_context_used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rapunzel_app_id ON rapunzel_grades(application_id);
```

---

### 3. Create `agent_interactions` Table (Audit Trail)
**File**: `database/schema_postgresql.sql` and `schema.sql`

**For tracking all agent questions, user responses, uploads, data extractions**:
```sql
CREATE TABLE IF NOT EXISTS agent_interactions (
    interaction_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES applications(application_id) ON DELETE CASCADE,
    agent_name VARCHAR(255),
    interaction_type VARCHAR(100), -- 'question', 'response', 'file_upload', 'data_extraction', 'pause'
    question_text TEXT,
    user_response TEXT,
    file_name VARCHAR(500),
    file_size INTEGER,
    file_type VARCHAR(50),
    extracted_data JSONB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sequence_number INTEGER
);

CREATE INDEX IF NOT EXISTS idx_interactions_app_id ON agent_interactions(application_id);
CREATE INDEX IF NOT EXISTS idx_interactions_agent ON agent_interactions(agent_name);
CREATE INDEX IF NOT EXISTS idx_interactions_type ON agent_interactions(interaction_type);
```

---

### 4. Create `naveen_enrichment_log` Table
**File**: `database/schema_postgresql.sql` and `schema.sql`

**For tracking when NAVEEN enriches schools and reuse**:
```sql
CREATE TABLE IF NOT EXISTS naveen_enrichment_log (
    enrichment_id SERIAL PRIMARY KEY,
    school_name VARCHAR(500),
    state_code VARCHAR(2),
    school_enrichment_id INTEGER REFERENCES school_enriched_data(school_enrichment_id),
    naveen_performed BOOLEAN DEFAULT FALSE,
    enrichment_timestamp TIMESTAMP,
    data_confidence NUMERIC(3,2),
    data_sources JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_naveen_school_match 
ON naveen_enrichment_log(school_name, state_code);
```

---

### 5. Add Columns to `school_enriched_data` Table
**File**: `database/schema_school_enrichment.sql`

**Add tracking for re-extraction**:
```sql
ALTER TABLE school_enriched_data ADD COLUMN IF NOT EXISTS 
  moana_requirements_met BOOLEAN DEFAULT FALSE;
ALTER TABLE school_enriched_data ADD COLUMN IF NOT EXISTS 
  last_moana_validation TIMESTAMP;
```

---

## Code Changes - Core Files

### 1. **smee_orchestrator.py** - Main Workflow Refactoring

#### Change 1.1: Add Student Matching Method
**Location**: After `__init__` method

```python
def _match_or_create_student_record(
    self, 
    first_name: str, 
    last_name: str, 
    high_school: str, 
    state_code: str,
    application: Dict[str, Any]
) -> str:
    """
    Match student to existing record OR create new one.
    Uses: first_name + last_name + high_school + state_code
    Returns: application_id (existing or newly created)
    """
    # 1. Normalize inputs for matching
    first_name_norm = first_name.strip().lower() if first_name else ""
    last_name_norm = last_name.strip().lower() if last_name else ""
    school_norm = high_school.strip().lower() if high_school else ""
    state_norm = state_code.strip().upper() if state_code else ""
    
    # 2. Query database for exact match
    if self.db:
        existing_app = self.db.find_student_by_match(
            first_name_norm, last_name_norm, school_norm, state_norm
        )
        if existing_app:
            logger.info(
                f"Found existing student record: {existing_app['application_id']} "
                f"for {first_name} {last_name} from {high_school}, {state_code}"
            )
            return existing_app['application_id']
    
    # 3. Create new record
    new_app_id = self.db.create_student_record(
        first_name=first_name,
        last_name=last_name,
        high_school=high_school,
        state_code=state_code,
        **application
    ) if self.db else None
    
    logger.info(
        f"Created new student record: {new_app_id} "
        f"for {first_name} {last_name} from {high_school}, {state_code}"
    )
    return new_app_id
```

#### Change 1.2: Refactor `coordinate_evaluation()` to Match Correct Workflow
**Location**: Lines 120-260 (complete rewrite of flow)

Replace with:
```python
async def coordinate_evaluation(
    self,
    application: Dict[str, Any],
    evaluation_steps: List[str],
    progress_callback: Optional[callable] = None
) -> Dict[str, Any]:
    """
    Orchestrate the complete evaluation pipeline:
    
    BELLE is a reusable extraction service called throughout the workflow:
    - Initial call: Extract from uploaded document
    - Reactive calls: Extract more data when agents need additional info
    - Upload calls: Re-extract when user uploads new files
    
    SMEE decides WHEN to invoke BELLE based on validation failures and data gaps.
    
    Core pipeline:
    1. Try to extract/gather data via BELLE (if needed)
    2. Match student to existing record or create new
    3. NAVEEN enriches school (if not cached)
    4. Validate school context meets all downstream needs
    5. Validate each core agent has required fields
    6. Run analysis agents (TIANA, RAPUNZEL, MOANA, MULAN)
    7. MILO training analysis
    8. MERLIN synthesis
    9. AURORA report
    """
    import uuid
    
    self.workflow_state = "evaluating"
    applicant_name = application.get('applicant_name') or application.get('ApplicantName', 'Unknown')
    
    self._progress_callback = progress_callback
    self._current_applicant_name = applicant_name
    
    # ===== INTAKE PHASE: DATA EXTRACTION & MATCHING =====
    
    # Try initial BELLE extraction from uploaded document
    logger.info(f"🎩 Smee requesting BELLE extraction for {applicant_name}...")
    belle_extracted = await self._extract_data_with_belle(
        document_text=application.get('application_text', ''),
        document_name=application.get('original_file_name', ''),
        context="initial extraction"
    )
    
    # ===== STEP 2: STUDENT RECORD MATCHING =====
    logger.info(f"🎩 Smee matching student record...")
    first_name = belle_extracted.get('first_name', '')
    last_name = belle_extracted.get('last_name', '')
    high_school = belle_extracted.get('school_name', '')
    state_code = belle_extracted.get('state_code', '')
    
    application_id = self._match_or_create_student_record(
        first_name, last_name, high_school, state_code, application
    )
    student_id = application.get('student_id') or f"student_{uuid.uuid4().hex[:16]}"
    
    self._current_application_id = application_id
    self._current_student_id = student_id
    
    # ===== STEP 3: NAVEEN SCHOOL ENRICHMENT =====
    logger.info(f"🎩 Smee routing to NAVEEN for school enrichment...")
    school_enrichment = await self._run_naveen_enrichment(
        high_school, state_code, application_id
    )
    
    # ===== STEP 3.5: SCHOOL VALIDATION LOOP =====
    # If NAVEEN couldn't enrich school, may need more documents
    logger.info(f"🎩 Smee validating school data for downstream agents...")
    school_validation = await self._validate_school_context(
        school_enrichment, high_school, state_code
    )
    
    if not school_validation['ready']:
        # Before pausing, try BELLE again with school-specific context
        logger.info(f"🎩 School context incomplete. Trying BELLE for school documents...")
        school_text = await self._extract_data_with_belle(
            document_text=application.get('application_text', ''),
            document_name=application.get('original_file_name', ''),
            context="school information"
        )
        # Check if BELLE found more school data
        if school_text.get('school_context'):
            school_enrichment.update(school_text.get('school_context', {}))
            school_validation = await self._validate_school_context(
                school_enrichment, high_school, state_code
            )
        
        if not school_validation['ready']:
            return self._pause_for_missing_fields(
                applicant_name=applicant_name,
                application_id=application_id,
                student_id=student_id,
                missing_fields=school_validation['missing'],
                agent_questions=school_validation['prompts'],
                application_snapshot=application
            )
    
    # ===== STEP 4 & 5: CORE AGENT VALIDATION & ANALYSIS =====
    logger.info(f"🎩 Smee validating core agent requirements...")
    core_agents = ['application_reader', 'grade_reader', 'school_context', 'recommendation_reader']
    
    for agent_id in core_agents:
        validation = await self._validate_agent_readiness(
            agent_id, application, application_id, belle_extracted
        )
        if not validation['ready']:
            # Try BELLE again with focused context
            logger.info(f"🎩 Agent {agent_id} missing data. Trying BELLE with focused context...")
            additional_data = await self._extract_data_with_belle(
                document_text=application.get('application_text', ''),
                document_name=application.get('original_file_name', ''),
                context=f"extract data for {agent_id}"
            )
            application.update(additional_data)
            
            # Re-validate
            validation = await self._validate_agent_readiness(
                agent_id, application, application_id, additional_data
            )
            
            if not validation['ready']:
                return self._pause_for_missing_fields(...)
    
    # All validation passed - run analysis agents
    evaluation_results = {}
    for agent_id in core_agents:
        result = await self._run_agent(
            agent_id, application, school_enrichment, evaluation_results
        )
        evaluation_results[agent_id] = result
    
    # ===== STEP 6: MILO TRAINING ANALYSIS =====
    milo_result = await self._run_milo(evaluation_results)
    evaluation_results['data_scientist'] = milo_result
    
    # ===== STEP 7: MERLIN SYNTHESIS =====
    merlin_result = await self._run_merlin(evaluation_results)
    evaluation_results['student_evaluator'] = merlin_result
    
    # ===== STEP 8: AURORA REPORT =====
    aurora_result = await self._run_aurora(evaluation_results)
    evaluation_results['output_formatter'] = aurora_result
    
    return {
        'application_id': application_id,
        'student_id': student_id,
        'applicant_name': applicant_name,
        'results': evaluation_results,
        'status': 'complete'
    }
```

---

#### Change 1.3: Add Helper Methods for Each Step

```python
async def _extract_data_with_belle(
    self, document_text: str, document_name: str = "", 
    context: str = ""
) -> Dict[str, Any]:
    """
    REUSABLE: Extract data from document via BELLE.
    
    Can be called:
    - Initially to extract from uploaded document
    - Reactively when agents need more data from document
    - When user uploads new/additional files
    - With context hint (e.g., "extract grades" vs "extract recommendations")
    
    Returns extracted fields that SMEE can use for matching, validation, etc.
    """
    belle = BelleDocumentAnalyzer(client=self.client, model=self.model)
    
    # If context provided, BELLE can focus extraction
    if context:
        logger.info(f"BELLE extracting {context} from {document_name}...")
    
    analysis = belle.analyze_document(document_text, document_name)
    
    # Log this extraction interaction
    if hasattr(self, '_current_application_id') and self._current_application_id:
        self.db.log_agent_interaction(
            application_id=self._current_application_id,
            agent_name='Belle',
            interaction_type='data_extraction',
            file_name=document_name,
            extracted_data=analysis
        )
    
    return analysis

async def _run_naveen_enrichment(
    self, school_name: str, state_code: str, application_id: int
) -> Dict[str, Any]:
    """STEP 3: Enrich school data via NAVEEN."""
    from src.school_workflow import ensure_school_context_in_pipeline
    naveen_agent = self.agents.get('naveen')
    school_enrichment = ensure_school_context_in_pipeline(
        school_name=school_name,
        state_code=state_code,
        db_connection=self.db,
        aurora_agent=naveen_agent
    )
    return school_enrichment

async def _validate_school_context(
    self, school_enrichment: Dict[str, Any], school_name: str, state_code: str
) -> Dict[str, Any]:
    """STEP 3.5: Validate NAVEEN provided all MOANA needs."""
    moana = self.agents.get('school_context')
    if not moana:
        return {'ready': True, 'missing': []}
    
    # Query moana's requirements
    required_fields = moana.get_required_school_fields()
    missing = [f for f in required_fields if f not in school_enrichment]
    
    if missing:
        return {
            'ready': False,
            'missing': missing,
            'prompts': f"Please provide school documents showing: {', '.join(missing)}"
        }
    
    return {'ready': True, 'missing': []}

async def _validate_agent_readiness(
    self, agent_id: str, application: Dict[str, Any], 
    application_id: int, belle_data: Dict[str, Any]
) -> Dict[str, Any]:
    """STEP 4.5: Validate individual agent has its required fields."""
    agent = self.agents.get(agent_id)
    if not agent:
        return {'ready': False}
    
    req = AgentRequirements.get_agent_requirements(agent_id)
    required_fields = req.get('required_fields', [])
    
    missing = []
    for field in required_fields:
        if not application.get(field) and not belle_data.get(field):
            missing.append(field)
    
    if missing:
        return {
            'ready': False,
            'missing': missing,
            'prompt': req.get('missing_prompt')
        }
    
    return {'ready': True}

async def _run_agent(
    self, agent_id: str, application: Dict[str, Any],
    school_enrichment: Dict[str, Any], prior_results: Dict[str, Any]
) -> Dict[str, Any]:
    """Run individual agent with appropriate context."""
    agent = self.agents.get(agent_id)
    if not agent:
        return {}
    
    # Route to correct agent method
    if agent_id == 'application_reader':
        return await agent.parse_application(application)
    elif agent_id == 'grade_reader':
        # Pass school context for rigor weighting
        transcript = application.get('transcript_text', '')
        return await agent.parse_grades(
            transcript,
            application.get('applicant_name', ''),
            school_context=school_enrichment
        )
    elif agent_id == 'school_context':
        return await agent.analyze_student_school_context(
            application=application,
            rapunzel_grades_data=prior_results.get('grade_reader'),
            school_enrichment=school_enrichment
        )
    elif agent_id == 'recommendation_reader':
        recommendation = application.get('recommendation_text', '')
        return await agent.parse_recommendation(
            recommendation,
            application.get('applicant_name', ''),
            application.get('application_id')
        )
    
    return {}

async def _run_milo(self, evaluation_results: Dict[str, Any]) -> Dict[str, Any]:
    """STEP 6: Run MILO training analysis."""
    milo = self.agents.get('data_scientist')
    if not milo:
        return {}
    return await milo.analyze_training_insights(evaluation_results)

async def _run_merlin(self, evaluation_results: Dict[str, Any]) -> Dict[str, Any]:
    """STEP 7: Run MERLIN synthesis."""
    merlin = self.agents.get('student_evaluator')
    if not merlin:
        return {}
    return await merlin.evaluate_student({}, evaluation_results)

async def _run_aurora(self, evaluation_results: Dict[str, Any]) -> Dict[str, Any]:
    """STEP 8: Generate AURORA report."""
    aurora = self.agents.get('output_formatter')
    if not aurora:
        return {}
    return await aurora.format_evaluation_report(evaluation_results)
```

---

### 2. **database.py** - Add Matching & Storage Methods

#### Change 2.1: Add Student Matching Method
**New method to add**:

```python
def find_student_by_match(
    self, 
    first_name: str, last_name: str, high_school: str, state_code: str
) -> Optional[Dict[str, Any]]:
    """
    Find existing student record by: first_name + last_name + high_school + state_code
    Returns application record if exact match found, else None.
    """
    try:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT application_id, first_name, last_name, high_school, state_code
            FROM applications
            WHERE LOWER(first_name) = %s
              AND LOWER(last_name) = %s
              AND LOWER(high_school) = %s
              AND UPPER(state_code) = %s
            LIMIT 1
        """, (first_name, last_name, high_school, state_code))
        row = cursor.fetchone()
        cursor.close()
        
        if row:
            return {
                'application_id': row[0],
                'first_name': row[1],
                'last_name': row[2],
                'high_school': row[3],
                'state_code': row[4]
            }
        return None
    except Exception as e:
        logger.error(f"Error matching student: {e}")
        return None

def create_student_record(
    self, first_name: str, last_name: str, high_school: str, 
    state_code: str, **kwargs
) -> int:
    """Create new student application record with metadata."""
    try:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO applications 
            (applicant_name, first_name, last_name, high_school, 
             state_code, school_name, application_text, uploaded_date, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING application_id
        """, (
            f"{first_name} {last_name}",
            first_name,
            last_name,
            high_school,
            state_code,
            high_school,
            kwargs.get('application_text', ''),
            datetime.now(),
            'Pending'
        ))
        app_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        return app_id
    except Exception as e:
        logger.error(f"Error creating student record: {e}")
        return None
```

#### Change 2.2: Add RAPUNZEL Grades Storage
**New method**:

```python
def save_rapunzel_grades(
    self, application_id: int, agent_name: str, gpa: float,
    academic_strength: str, course_levels: Dict, transcript_quality: str,
    notable_patterns: str, confidence_level: str, summary: str,
    contextual_rigor_index: float = None, school_context_used: bool = False,
    parsed_json: str = None
) -> bool:
    """Save RAPUNZEL grades analysis."""
    try:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO rapunzel_grades 
            (application_id, agent_name, gpa, academic_strength, course_levels,
             transcript_quality, notable_patterns, contextual_rigor_index,
             confidence_level, summary, school_context_used, parsed_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            application_id, agent_name, gpa, academic_strength,
            json.dumps(course_levels), transcript_quality,
            notable_patterns, contextual_rigor_index, confidence_level,
            summary, school_context_used, parsed_json, datetime.now()
        ))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Error saving rapunzel grades: {e}")
        return False
```

#### Change 2.3: Add Agent Interaction Logging
**New method**:

```python
def log_agent_interaction(
    self, application_id: int, agent_name: str, interaction_type: str,
    question_text: str = None, user_response: str = None,
    file_name: str = None, file_size: int = None, file_type: str = None,
    extracted_data: Dict = None, sequence_number: int = None
) -> bool:
    """Log all agent interactions for full audit trail."""
    try:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO agent_interactions
            (application_id, agent_name, interaction_type, question_text,
             user_response, file_name, file_size, file_type, extracted_data,
             timestamp, sequence_number)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            application_id, agent_name, interaction_type, question_text,
            user_response, file_name, file_size, file_type,
            json.dumps(extracted_data) if extracted_data else None,
            datetime.now(), sequence_number
        ))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f"Error logging interaction: {e}")
        return False
```

---

### 3. **rapunzel_grade_reader.py** - Accept School Context

#### Change 3.1: Update `parse_grades()` signature
**Current**:
```python
async def parse_grades(self, transcript_text: str, applicant_name: str) -> Dict[str, Any]:
```

**Change to**:
```python
async def parse_grades(
    self, transcript_text: str, applicant_name: str, 
    school_context: Dict[str, Any] = None
) -> Dict[str, Any]:
```

**In method, use school context for rigor weighting**:
```python
# After extracting base rigor_index, apply school context weighting
if school_context:
    ap_density = school_context.get('ap_density', 0)
    honors_density = school_context.get('honors_density', 0)
    # Weight rigor: if AP/Honors rare at school, boost significance
    if ap_density < 0.2:  # Few APs available
        rigor_index *= 1.15
    if honors_density < 0.3:
        rigor_index *= 1.10
    
    result['contextual_rigor_index'] = rigor_index
    result['school_context_applied'] = True

return result
```

---

### 4. **agent_requirements.py** - Add School & File Tracking

**Add fields to AGENT_NEEDS**:
```python
'school_context': {
    'required_fields': ['school_name', 'state_code', 'school_enrichment_data'],
    'questions': [...],
    'missing_prompt': "Please provide school data"
}
```

---

### 5. **Create new file: `workflow_file_handler.py`**

**For handling file uploads and restart logic**:

```python
async def handle_file_upload(
    self, application_id: int, file_path: str, smee: SmeeOrchestrator
) -> Dict[str, Any]:
    """
    Handle file upload (BELLE called reactively):
    1. Extract data from new file via BELLE
    2. Re-match student record (may be existing student or new)
    3. Log interaction in audit trail
    4. Restart full workflow with updated data
    
    NOTE: BELLE is reusable throughout the workflow. This is just one
    reactive invocation triggered by user file upload.
    """
    # Use SMEE's BELLE extraction utility
    extracted = await smee._extract_data_with_belle(
        document_text=open(file_path).read(),
        document_name=os.path.basename(file_path),
        context="user file upload"
    )
    
    # Re-match with potentially new data
    first_name = extracted.get('first_name')
    last_name = extracted.get('last_name')
    high_school = extracted.get('school_name')
    state = extracted.get('state_code')
    
    matched_id = smee._match_or_create_student_record(
        first_name, last_name, high_school, state, {}
    )
    
    # Log this upload interaction (BELLE auto-logs via _extract_data_with_belle)
    smee.db.log_agent_interaction(
        application_id=application_id,
        agent_name='Workflow',
        interaction_type='file_upload',
        file_name=os.path.basename(file_path),
        extracted_data=extracted
    )
    
    # If this is an EXISTING DIFFERENT record, mark that one for re-evaluation too
    if matched_id != application_id:
        smee.db.mark_for_re_evaluation(matched_id)
        logger.info(
            f"File upload matched to existing student {matched_id} "
            f"(original: {application_id}). Marking for re-evaluation."
        )
    
    # Restart workflow with updated data
    # BELLE will be called again as-needed during coordination
    return await smee.coordinate_evaluation(
        {**extracted, 'application_id': matched_id},
        evaluation_steps=['application_reader', 'grade_reader', 'school_context', 'recommendation_reader']
    )
```

---

### 6. **aurora_agent.py** - Implement Report Generation

**If not fully implemented, add**:

```python
async def format_evaluation_report(
    self, evaluation_results: Dict[str, Any]
) -> Dict[str, Any]:
    """Generate comprehensive formatted report."""
    merlin_result = evaluation_results.get('student_evaluator', {})
    
    report = {
        'header': {
            'merlin_score': merlin_result.get('overall_score'),
            'merlin_recommendation': merlin_result.get('recommendation'),
            'confidence': merlin_result.get('confidence')
        },
        'sections': {
            'application': evaluation_results.get('application_reader'),
            'academics': evaluation_results.get('grade_reader'),
            'school_context': evaluation_results.get('school_context'),
            'recommendations': evaluation_results.get('recommendation_reader'),
            'patterns': evaluation_results.get('data_scientist'),
            'synthesis': merlin_result
        },
        'timestamp': datetime.now().isoformat()
    }
    
    # Format as HTML or JSON for dashboard
    return self._render_report(report)
```

---

## Implementation Priority

1. **Phase 1 (Critical)**: Database schema changes + Student matching
2. **Phase 2 (Core)**: Refactor orchestrator workflow steps
3. **Phase 3 (Required)**: NAVEEN proactive call + School validation loop
4. **Phase 4 (Enhancement)**: RAPUNZEL school weighting + AURORA report
5. **Phase 5 (Audit)**: Agent interaction logging + File upload restart

---

## Testing Plan

- [ ] Unit test: Student matching logic (exact matches, no false positives)
- [ ] Integration test: NAVEEN called if school not cached
- [ ] Integration test: School validation loop
- [ ] Integration test: RAPUNZEL receives school context
- [ ] End-to-end test: Full pipeline for new student
- [ ] End-to-end test: Full pipeline for existing student (re-evaluation)
- [ ] End-to-end test: File upload restart logic

---

## Rollout Notes

- All changes are backward-compatible
- Tests must verify NO duplicate student records created
- School name matching must be case-insensitive and accent-insensitive
- Audit trail must capture every agent question, response, and upload

