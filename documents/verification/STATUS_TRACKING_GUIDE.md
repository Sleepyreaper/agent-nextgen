📋 AGENT STATUS TRACKING SYSTEM - Implementation Guide
=======================================================

## Overview
The status tracking system tells you:
1. What agent is currently working on a student's application
2. What information each agent needs to function
3. What documents are missing and need to be uploaded
4. When the application is ready for processing

## How It Works

### 1. Smee Analyzes Requirements
When you upload a student application or view a student's detail page, Smee automatically:
- Analyzes the application text
- Checks the database for existing agent data
- Identifies what information is available
- Determines which agents can work with available data

### 2. Agent Status Indicators

**Agent Status Types:**
- ✅ **Ready** - Agent has all required information
- ⏳ **Waiting** - Agent is waiting for other agents' results (especially Merlin)  
- ⚠️ **Missing Info** - Agent lacks required information

**Agents & Their Requirements:**

1. 📖 **Belle - Document Analyzer**
  - Needs: Uploaded content
  - Analyzes: Document type + field extraction
  - Status: Runs on upload to enrich fields for other agents

2. 👸 **Tiana - Application Reader**
   - Needs: Application essay or personal statement
   - Analyzes: Applicant's motivation, goals, writing quality
   - Status: Ready if essay/statement detected in application text

3. 💇 **Rapunzel - Grade Reader**
   - Needs: Transcript with grades and GPA
   - Analyzes: Academic performance, grade trends, course difficulty
   - Status: Ready if grades/GPA/transcript detected

4. 🌊 **Moana - School Context**
   - Needs: School name and location
   - Analyzes: School reputation, challenges, student demographics
   - Status: Ready if school info or grades detected (usually on transcript)

5. 🗡️ **Mulan - Recommendation Reader**
   - Needs: Teacher/counselor recommendation letters
   - Analyzes: Endorsement strength, personal qualities
   - Status: Ready if recommendation text detected

6. 🧙 **Merlin - Final Evaluator**
   - Needs: Results from other agents
   - Analyzes: Overall fit, synthesis of all factors
   - Status: Waits for at least 2 other agents to complete

7. ✨ **Aurora - Results Formatter**
  - Needs: Merlin output and other agent results
  - Analyzes: Executive summary and presentation formatting
  - Status: Runs after Merlin

8. 🪄 **Fairy Godmother - Document Generator**
  - Needs: Completed agent results
  - Analyzes: Final evaluation document generation
  - Status: Runs last after Aurora

9. 🧪 **Milo - Data Scientist**
  - Needs: Training examples
  - Analyzes: Patterns in accepted vs not selected training data
  - Status: Optional insights used by Merlin

### 3. Overview Dashboard

**Readiness Percentage**
- Shows what % of agents have required information (0-100%)
- Green (✅): All information available - ready to process
- Yellow (⚠️): Partial information - some agents can work
- Red (❌): Missing critical information

**Missing Information Section**
Shows in priority order:
1. Transcripts (needed by Rapunzel & Moana)
2. Recommendations (needed by Mulan)
3. Essays (needed by Tiana)

### 4. Smart Recommendations
The system tells you exactly what to upload next:
- "Upload transcript file - Rapunzel needs grades and Moana needs the school"
- "Upload recommendation letters - Mulan can analyze endorsements"
- (etc.)

## API Endpoint

**GET /api/status/<application_id>**

Returns JSON with:
```json
{
  "success": true,
  "application_id": 123,
  "status": {
    "readiness": {
      "ready_count": 3,        // Agents ready to work
      "total_count": 5,
      "percentage": 60,
      "overall_status": "partial"
    },
    "agents": {
      "application_reader": {
        "agent_name": "👸 Tiana...",
        "status": "ready",
        "can_process": true,
        "missing": [],
        "data_source": "from_uploaded_file"
      },
      // ... other agents
    },
    "missing_information": [
      "Teacher/counselor recommendation letters"
    ],
    "can_proceed": true,
    "recommendation": "Upload recommendation letters..."
  }
}
```

## User Experience

### On Student Detail Page
1. **Requirements Card** appears at top (refreshes on page load)
2. Shows status for each agent
3. Lists what files can be uploaded
4. Provides next steps recommendation
5. "Refresh Status" button to check again

### Before Processing
- System checks all requirements
- If >50% ready, you can start processing
- Agents that are ready will run immediately
- Agents missing info will be skipped (gracefully)

### After Upload
- Upload file → System detects content
- Check status page → See updated requirements
- May need multiple uploads (grades, then recommendations, etc.)
- Recommendation updates to guide next upload

## Information Detection

The system detects information by looking for keywords:

**Essay/Statement Detection:**
- Keywords: 'essay', 'personal statement'
- OR: Application text > 500 characters

**Grades Detection:**
- Keywords: 'gpa', 'grade', 'transcript', 'course', 'a-', 'b+'

**School Info Detection:**
- Keywords: 'high school', 'school name', 'school district'

**Recommendations Detection:**
- Keywords: 'recommendation', 'recommender', 'letter of', 'reference'

## Example Workflows

### Scenario 1: Complete Package
Upload: Application essay + transcript + 2 recommendations
→ Status: 100% ready → All 5 agents can work → Process immediately

### Scenario 2: Minimal Start
Upload: Application essay only
→ Status: 20% ready (Tiana only) → Tiana runs → Get feedback
→ Then upload transcript → Status: 60% ready → Rapunzel & Moana run
→ Then upload recommendations → Status: 100% ready → Merlin runs

### Scenario 3: Training Data
Upload: Historical application + mark as "Selected"
→ Goes to Training page → Agents use as reference for new applications
→ Improves benchmarking for future evaluations

## Benefits

✅ **Transparency** - Users know exactly what information is needed
✅ **Guided Upload** - System tells you what to upload next
✅ **Efficient Processing** - Run agents only when they have data
✅ **Failure Prevention** - Avoid agent errors from missing info
✅ **Smart Prioritization** - Know which documents matter most

## Technical Implementation

**Files Changed:**
- `src/agents/smee_orchestrator.py` - Added `check_application_requirements()` method
- `app.py` - Added `/api/status/<id>` endpoint
- `web/templates/student_detail.html` - Added requirements card with JavaScript
- `web/templates/base.html` - Added spinner CSS

**Key Methods:**
- `Smee.check_application_requirements(application)` - Returns full status object
- `Smee._get_upload_recommendation(missing_items)` - Generates next step text

## Testing

Demo script: `testing/demo_status_tracking.py`

Creates test cases showing:
- Essay-only application
- Application with grades
- Minimal/empty application

Shows how system adapts recommendations based on available content.
