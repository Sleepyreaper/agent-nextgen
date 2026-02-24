# 9-Step Agent Workflow Map

> Complete visual and textual map of the multi-agent evaluation system workflow with all decision points and data flows.

---

## 🎯 Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        STUDENT APPLICATION UPLOAD                           │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  STEP 1: BELLE - Document Extraction         │
        │  ├─ File type detection (PDF/DOCX/TXT)      │
        │  ├─ Extract: name, school, state, GPA       │
        │  └─ Parse document structure                │
        └──────────────────────────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  STEP 2: Student Record Matching             │
        │  ├─ Query by (first_name + last_name +      │
        │  │   high_school + state_code)             │
        │  ├─ If match found → use existing           │
        │  └─ If no match → create new record         │
        └──────────────────────────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  STEP 2.5: High School Pre-Enrichment (NEW)  │
        │  ├─ Look up school in database              │
        │  └─ If not found → call NAVEEN to enrich   │
        └──────────────────────────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  STEP 3: NAVEEN - School Data Enrichment     │
        │  ├─ NAVEEN calls with school context        │
        │  ├─ Enriches: AP courses, honors programs   │
        │  ├─ Calculates: opportunity score           │
        │  └─ Returns: full school enrichment data    │
        └──────────────────────────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  STEP 3.5: MOANA Validation Loop             │
        │  ├─ Validate school against 7 requirements  │
        │  ├─ Missing fields? → Call NAVEEN for       │
        │  │   remediation (up to 2 attempts)         │
        │  ├─ Success? → Continue to core agents      │
        │  └─ Failure? → PAUSE for user documents     │
        └──────────────────────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
              SUCCESS                  FAILURE
                    │                     │
                    ▼                     ▼
            CONTINUE              ┌─────────────┐
                                  │ PAUSE STATE │
                                  │ (Ask User)  │
                                  └─────────────┘
                    │
                    ▼
        ┌──────────────────────────────────────────────┐
        │  STEP 4: Core Agents (Validation Gates)      │
        │                                              │
        │  4.1: TIANA - Application Reader            │
        │    ├─ Gate: Extract application text        │
        │    ├─ Failed? → Reactive BELLE call         │
        │    └─ Still failed? → PAUSE for essay       │
        │                                              │
        │  4.2: RAPUNZEL - Grade Reader               │
        │    ├─ Gate: Extract transcript data         │
        │    ├─ Calculates: contextual_rigor_index    │
        │    │  (0-5 scale based on school context)  │
        │    ├─ Failed? → Reactive BELLE call         │
        │    └─ Still failed? → PAUSE for transcript  │
        │                                              │
        │  4.3: MOANA - School Context                │
        │    ├─ Gate: School data + demographics      │
        │    ├─ Analyzes: opportunity & access        │
        │    ├─ Failed? → Already validated in 3.5    │
        │    └─ (Used for fairness weighting)         │
        │                                              │
        │  4.4: MULAN - Recommendation Reader         │
        │    ├─ Gate: Recommendation letters exist    │
        │    ├─ Extracts: themes & themes            │
        │    ├─ Failed? → Reactive BELLE call         │
        │    └─ Still failed? → PAUSE for letters     │
        │                                              │
        │  ⚠️  STEP 4.5: Per-Agent Validation Gates   │
        │  Before each agent runs, verify inputs      │
        │  exist & are complete. If not, either:      │
        │  a) Reactively extract missing data         │
        │  b) Pause workflow asking user              │
        └──────────────────────────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  STEP 5: MILO - Training Insights Analysis   │
        │  ├─ Pattern detection across applications   │
        │  ├─ Identifies selection indicators         │
        │  ├─ Analyzes: outcomes vs. application      │
        │  └─ Provides: weighted scoring hints        │
        └──────────────────────────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  STEP 6: MERLIN - Comprehensive Synthesis    │
        │  ├─ Combines all agent outputs              │
        │  ├─ Calculates: overall recommendation      │
        │  ├─ Generates: decision rationale           │
        │  ├─ Weights scores by opportunity access    │
        │  └─ Returns: structured evaluation object   │
        └──────────────────────────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  STEP 7: AURORA - Report Generation          │
        │  ├─ Formats all results into report         │
        │  ├─ Sections:                                │
        │  │  • Applicant profile                      │
        │  │  • Document analysis (BELLE)             │
        │  │  • School context (MOANA)                │
        │  │  • Academic performance (RAPUNZEL)       │
        │  │  • Recommendations analysis (MULAN)      │
        │  │  • Training insights (MILO)              │
        │  │  • MERLIN assessment & rationale         │
        │  │  • Workflow status                        │
        │  └─ Returns: formatted evaluation report    │
        └──────────────────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ EVALUATION COMPLETE  │
                    │ Store in database    │
                    │ Return to user       │
                    └──────────────────────┘
```

---

## 📋 Data Flow by Step

### **Step 1: BELLE - Document Extraction**
```
INPUT:  Raw document (PDF/DOCX/TXT)
        ├─ document_text: full document content
        ├─ file_name: original filename
        ├─ file_type: mime type
        └─ file_size: bytes

PROCESS: Azure OpenAI extraction with system prompts
        ├─ Extract structured fields
        ├─ Identify document type
        └─ Parse content sections

OUTPUT: belle_extraction {
        ├─ first_name
        ├─ last_name
        ├─ high_school
        ├─ state_code
        ├─ gpa
        ├─ grades []
        ├─ essays {}
        ├─ experience []
        └─ extracted_text
        }

AUDIT:  step_1_extraction
        ├─ file_name, file_size, file_type
        ├─ extracted_data (full BELLE output)
        └─ timestamp
```

### **Step 2: Student Record Matching**
```
INPUT:  first_name, last_name, high_school, state_code
        (from BELLE extraction)

PROCESS: Database lookup
        ├─ COMPOSITE KEY: first_name + last_name + 
        │                 high_school + state_code
        ├─ If found: use existing application_id
        └─ If not found: create new record

OUTPUT: application_id (integer)
        applicant_record {
        ├─ application_id
        ├─ first_name, last_name
        ├─ high_school, state_code
        ├─ school_name
        └─ applicant_name
        }

AUDIT:  step_2_student_match
        ├─ first_name, last_name, high_school, state_code
        ├─ action: 'created' | 'matched'
        └─ application_id
```

### **Step 2.5: High School Pre-Enrichment**
```
INPUT:  high_school, state_code, application_id

PROCESS: Lookup school in database
        ├─ If found (cached): return cached data
        ├─ If not found: call NAVEEN for enrichment
        └─ Store enrichment for later use

OUTPUT: high_school_data {
        ├─ school_enrichment_id
        ├─ school_name
        ├─ state_code
        ├─ opportunity_score (0-100)
        ├─ ap_course_count
        ├─ honors_program_available
        └─ socioeconomic_indicators
        }

AUDIT:  step_2_5_school_check
        ├─ school_name, state_code
        ├─ status: 'success' | 'error'
        ├─ school_enrichment_id
        └─ opportunity_score
```

### **Step 3 & 3.5: NAVEEN Enrichment + Validation Loop**
```
INPUT:  high_school, state_code,
        school_district (optional),
        application_id

PROCESS - STEP 3 (NAVEEN Enrichment):
        ├─ Call NAVEEN agent with school context
        ├─ NAVEEN enriches: AP courses, honors, etc.
        ├─ NAVEEN scores: opportunity_score (0-100)
        └─ Store enrichment data

PROCESS - STEP 3.5 (MOANA Validation):
        ├─ Validate against 7 MOANA requirements:
        │  1. School type verification
        │  2. AP/Honors program presence
        │  3. Socioeconomic data
        │  4. Student demographics
        │  5. Academic context
        │  6. Opportunity metrics
        │  7. Reliability of data
        │
        ├─ ATTEMPT #1: Check schema completeness
        │  ├─ If all requirements met → SUCCESS
        │  └─ If missing → Continue to remediation
        │
        ├─ REMEDIATION #1: Re-enrich missing fields
        │  ├─ Call NAVEEN with specific context
        │  │  "Please provide: [missing fields]"
        │  ├─ ATTEMPT #2: Re-validate
        │  └─ If success → Continue
        │     If failed → Continue to remediation 2
        │
        └─ REMEDIATION #2: Final attempt
           ├─ Call NAVEEN again with all context
           ├─ ATTEMPT #3: Final validation
           ├─ If success → Continue to core agents
           └─ If failed → PAUSE (ask user for docs)

OUTPUT: school_enrichment {
        ├─ school_enrichment_id
        ├─ school_name, state_code
        ├─ ap_courses (count & list)
        ├─ honors_programs (count & list)
        ├─ opportunity_score
        ├─ moana_requirements_met (boolean)
        ├─ last_moana_validation (timestamp)
        └─ validation_log (all attempts)
        }

AUDIT:  step_3_naveen_enrichment
        ├─ school_name, state_code
        ├─ enrichment_data (full)
        ├─ opportunity_score
        └─ validation_status

        step_3_5_validation_attempt (per attempt)
        ├─ attempt_number (1, 2, 3)
        ├─ fields_checked []
        ├─ passed (boolean)
        └─ missing_fields []

        step_3_5_remediation (per remediation)
        ├─ remediation_number
        ├─ missing_fields_targeted []
        ├─ remediation_context (text)
        └─ result: 'passed' | 'incomplete'

        step_3_5_validation_passed
        ├─ validation_result: 'passed'
        ├─ total_attempts
        └─ school_name, state_code

        pause_for_documents (if fails)
        ├─ reason: 'school_validation_failed'
        ├─ missing_fields []
        ├─ validation_attempts (count)
        └─ remediation_attempts (count)
```

### **Step 4 & 4.5: Core Agents with Per-Agent Validation**
```
CORE AGENTS (4 agents on every student):
1. TIANA (Application Reader)
2. RAPUNZEL (Grade Reader)
3. MOANA (School Context)
4. MULAN (Recommendation Reader)

FOR EACH AGENT:

STEP 4.5 - Validation Gate #1:
  ├─ Check: Does required data exist?
  ├─ If YES → Continue to execution
  ├─ If NO → Attempt reactive BELLE extraction

REACTIVE BELLE EXTRACTION:
  ├─ Call BELLE with specific context
  │  "Extract data for: [agent_id requirements]"
  ├─ Retry validation gate

STEP 4.5 - Validation Gate #2:
  ├─ Check: Still missing data?
  ├─ If NO → Continue to execution
  ├─ If YES → PAUSE workflow
  │           Ask user for missing documents

STEP 4 - Execute Agent:
  ├─ TIANA:
  │ ├─ Parses: application essays, extracurriculars
  │ ├─ Analyzes: communication, articulation
  │ ├─ Input: application_text from BELLE
  │ └─ Output: tiana_result {essay_quality, clarity, ...}
  │
  ├─ RAPUNZEL:
  │ ├─ Parses: transcript, grades, test scores
  │ ├─ Analyzes: GPA, trend, rigor, consistency
  │ ├─ INPUT DATA:
  │ │  ├─ transcript_text (from BELLE)
  │ │  ├─ school_context (from school_enrichment)
  │ │  └─ school_name, state_code
  │ ├─ CALCULATES: contextual_rigor_index
  │ │  ├─ Base rigor (GPA-based)
  │ │  ├─ School rigor (AP/Honors availability)
  │ │  ├─ Opportunity score (from MOANA)
  │ │  └─ FINAL: 0-5 scale score
  │ ├─ Output: rapunzel_result {
  │ │  ├─ gpa, trend, rigor
  │ │  ├─ contextual_rigor_index (0-5)
  │ │  ├─ school_context_used (true)
  │ │  ├─ school_name
  │ │  └─ academic_assessment
  │ │  }
  │ └─ (stored in rapunzel_grades table)
  │
  ├─ MOANA:
  │ ├─ Uses: school_enrichment from Step 3
  │ ├─ Analyzes: school opportunity, access, context
  │ ├─ Calculates: fairness adjustments
  │ └─ Output: moana_result {school_analysis, context, ...}
  │
  └─ MULAN:
    ├─ Parses: recommendation letters
    ├─ Analyzes: themes, tone, recommendations
    ├─ Input: recommendation_text from BELLE
    └─ Output: mulan_result {themes, sentiment, assessment, ...}

AUDIT:  step_4_5_validation (per gate attempt)
        ├─ agent_id
        ├─ validation_status: 'failed_gate_1' | 'failed_gate_2' | 'passed'
        ├─ missing_fields []
        └─ gate_number

        pause_for_documents (if validation fails)
        ├─ agent_id
        ├─ reason: 'missing_required_documents'
        ├─ validation_status: 'failed_gate_2'
        ├─ missing_fields []
        └─ gate_number: 2

        step_4_agent_execution (per agent)
        ├─ agent_id
        ├─ agent_number (1-4)
        ├─ execution_status: 'completed'
        ├─ result_keys [] (what was produced)
        └─ execution_order: "1/4"
```

### **Step 5: MILO - Training Insights Analysis**
```
INPUT:  All evaluation_results from Steps 1-4
        ├─ BELLE extraction
        ├─ Student record
        ├─ School enrichment
        └─ Core agent results

PROCESS: Data scientist analysis
        ├─ Pattern detection
        ├─ Compare against historical data
        ├─ Identify selection indicators
        └─ Weight scoring suggestions

OUTPUT: milo_result {
        ├─ patterns_found []
        ├─ selection_indicators {}
        ├─ scoring_weights {}
        └─ insights []
        }

AUDIT:  step_5_milo_analysis
        ├─ analysis_status: 'completed' | 'failed'
        ├─ result_keys []
        ├─ insights_generated (boolean)
        └─ [error if failed]
```

### **Step 6: MERLIN - Comprehensive Synthesis**
```
INPUT:  All results from Steps 1-5
        ├─ belle_extraction
        ├─ naveen_enrichment
        ├─ school_enrichment
        ├─ rapunzel_result (with contextual_rigor_index)
        ├─ tiana_result
        ├─ moana_result
        ├─ mulan_result
        └─ milo_result

PROCESS: Advanced synthesis
        ├─ Aggregate scores with weights
        ├─ Apply fairness adjustments (from MOANA)
        ├─ Weight by opportunity (from RAPUNZEL context)
        ├─ Generate overall recommendation
        ├─ Create decision rationale
        └─ Structure for report

OUTPUT: merlin_result {
        ├─ overall_score (0-100)
        ├─ recommendation: 'Strong Accept' | 'Accept' | 'Reject' | ...
        ├─ decision_rationale: detailed text
        ├─ weighted_scores {
        │  ├─ academic_score (with rigor context)
        │  ├─ application_score
        │  ├─ recommendation_score
        │  ├─ opportunity_adjustment
        │  └─ final_score
        │  }
        └─ key_strengths [], areas_for_growth []
        }

AUDIT:  step_6_merlin_synthesis
        ├─ synthesis_status: 'completed' | 'failed'
        ├─ result_keys []
        ├─ has_overall_score (boolean)
        ├─ recommendations_generated (boolean)
        └─ [error if failed]
```

### **Step 7: AURORA - Report Generation**
```
INPUT:  merlin_result + all prior results

PROCESS: Report formatting
        ├─ Structure sections
        ├─ Format text
        ├─ Add context
        ├─ Create executive summary
        └─ Prepare for output

OUTPUT: formatted_report {
        ├─ executive_summary: string
        ├─ applicant_info: {name, school, gpa, ...}
        ├─ document_analysis: (from BELLE)
        ├─ school_context: (from MOANA)
        ├─ candidate_profile: {
        │  ├─ application_review (TIANA)
        │  ├─ academic_performance (RAPUNZEL with rigor)
        │  ├─ school_analysis (MOANA)
        │  └─ recommendation_analysis (MULAN)
        │  }
        ├─ training_insights: (from MILO)
        ├─ merlin_assessment: (from MERLIN)
        ├─ decision: recommendation_text
        ├─ rationale: decision_explanation
        └─ workflow_status: 'COMPLETE'
        }

AUDIT:  step_7_aurora_report
        ├─ report_status: 'generated' | 'failed'
        ├─ report_length (characters)
        ├─ sections_included []
        ├─ report_generated (boolean)
        └─ [error if failed]
```

---

## 🔄 Pause/Resume Flow

### **When Workflow Pauses:**
```
Pause Reasons:
├─ step_3_5_validation_failed
│  └─ Missing school documentation
├─ step_4_agent_missing_data
│  ├─ Missing essay (TIANA)
│  ├─ Missing transcript (RAPUNZEL)
│  ├─ Missing recommendations (MULAN)
│  └─ School data incomplete (MOANA)
│
└─ Logs pause_for_documents event with:
   ├─ reason
   ├─ missing_fields []
   └─ guide for user on what to provide

AUDIT:  pause_for_documents
        ├─ reason: documented above
        ├─ missing_fields []
        ├─ validation_attempts | validation_status | gate_number
        └─ timestamp
```

### **When User Resumes:**
```
User provides additional files →
FileUploadHandler matches to student →
Marks student for re-evaluation →
Workflow restarts from Step 1

AUDIT:  resume_from_pause
        ├─ previous_pause_reason
        ├─ new_files_added []
        ├─ match_confidence (if file matching)
        └─ timestamp
```

---

## 🎯 Key Decision Points

| Step | Decision | Outcome |
|------|----------|---------|
| 2 | Student exists? | Use existing \| Create new |
| 2.5 | School in cache? | Use cached \| Call NAVEEN |
| 3.5 | Validation passed? | Continue \| Remediate (up to 2x) |
| 3.5 | After remediation? | Continue \| PAUSE user |
| 4.5 | Data ready for agent? | Execute \| Retry BELLE |
| 4.5 | After BELLE retry? | Execute \| PAUSE user |
| 7 | All steps complete? | Return report \| Error handling |

---

## 📊 Database Tables Involved

```
applications
├─ application_id (PK)
├─ first_name, last_name (Step 2)
├─ high_school, state_code (Step 2)
├─ application_text (Step 1, 4)
├─ transcript_text (Step 4)
├─ recommendation_text (Step 4)
└─ status (Step 7)

student_school_context / school_enriched_data
├─ school_enrichment_id (PK)
├─ school_name, state_code (Steps 2.5, 3)
├─ opportunity_score (Step 3)
├─ moana_requirements_met (Step 3.5)
├─ last_moana_validation (Step 3.5)
└─ [7 required fields for MOANA]

rapunzel_grades
├─ grade_id (PK)
├─ application_id (FK)
├─ gpa, trend, rigor (Step 4)
├─ contextual_rigor_index (Step 4)
├─ school_context_used (Step 4)
└─ school_name (Step 4)

agent_interactions
├─ interaction_id (PK)
├─ application_id (FK)
├─ agent_name, interaction_type (AUDIT)
├─ question_text, extracted_data (AUDIT)
└─ timestamp

file_upload_audit
├─ audit_id (PK)
├─ matched_application_id (FK)
├─ extracted_first_name, extracted_last_name (AI)
├─ ai_match_confidence (AI)
├─ match_status: 'new_student' | 'matched_existing' (AI)
├─ human_reviewed, human_review_approved (REVIEW)
└─ timestamp
```

---

## 🔐 Error Handling & Logging

Every step logs to `agent_interactions` table:

```
Interaction Types (14 total):
├─ step_1_extraction
├─ step_2_student_match
├─ step_2_5_school_check
├─ step_3_naveen_enrichment
├─ step_3_5_validation_attempt
├─ step_3_5_validation_passed
├─ step_3_5_remediation
├─ step_4_agent_execution
├─ step_4_5_validation
├─ step_5_milo_analysis
├─ step_6_merlin_synthesis
├─ step_7_aurora_report
├─ pause_for_documents
├─ resume_from_pause
└─ file_upload

Each logs: timestamp, agent, question, results, errors
```

---

## 📈 Performance Characteristics

| Step | Typical Time | Dependencies |
|------|--------------|--------------|
| 1 (BELLE) | 5-10 sec | Document size |
| 2 (Matching) | <1 sec | DB query |
| 2.5 (School check) | 1-2 sec | Cache hit/miss |
| 3 (NAVEEN enrich) | 10-15 sec | NAVEEN complexity |
| 3.5 (Validation) | 5-30 sec | Remediation attempts |
| 4 (Core agents) | 20-40 sec | 4 agents sequential |
| 4.5 (Per-agent) | 2-5 sec | Validation complexity |
| 5 (MILO) | 5-10 sec | Dataset size |
| 6 (MERLIN) | 10-15 sec | Result aggregation |
| 7 (AURORA) | 2-5 sec | Formatting |
| **TOTAL** | **60-150 sec** | All factors |

---

## 🔄 Reusability Features

### **BELLE Reusability (Steps 1, 4.5)**
- Called initially to extract from document
- Called reactively when validation gates fail
- Called with context to focus on specific gaps
- Can be called multiple times per student

### **NAVEEN Reusability (Steps 2.5, 3, 3.5)**
- Pre-check at Step 2.5 for schools
- Full enrichment at Step 3
- Re-enrichment at Step 3.5 for missing fields
- Multiple remediation attempts (max 2)

### **MOANA Reusability (Steps 3.5, 4)**
- Validation at Step 3.5 of school data
- Analysis at Step 4 of student opportunity
- Data used throughout for fairness weighting

---

## ✅ Completeness Criteria

Workflow only proceeds when ALL criteria met at each gate:

**Step 2**: Student record created/matched
**Step 2.5**: School pre-enriched (not required)
**Step 3**: School fully enriched
**Step 3.5**: ✅ All 7 MOANA requirements met
**Step 4.5**: ✅ Per-agent validation gates passed
**Step 4**: ✅ All 4 core agents executed
**Step 5**: ✅ MILO analysis complete
**Step 6**: ✅ MERLIN synthesis complete
**Step 7**: ✅ AURORA report generated

Any ❌ at validation gates → reactive attempts → if still ❌ → PAUSE for user

