# ARIEL Q&A Agent

## Overview

**ARIEL** (Articulate Response Intelligence Enhanced Learning) is a conversational Q&A agent that answers natural language questions about students based on data extracted by other evaluation agents.

**Agent Configuration:**
- 🧜‍♀️ **Name**: ARIEL
- **Role**: Student Q&A Assistant
- **Model**: Azure OpenAI GPT-4
- **Step**: 8.5 (between synthesis and reporting)
- **Input**: Student questions + evaluation context
- **Output**: Insightful, evidence-based responses

## Features

### 1. **Comprehensive Student Context**
ARIEL assembles complete student profiles including:
- Basic application info (name, school, GPA, test scores)
- School context (AP/Honors availability, opportunity score, SES level)
- Contextual rigor analysis (0-5 scale adjusted for school resources)
- Agent evaluations (scores and recommendations from all agents)
- Audit trail (recent interactions and decision points)

### 2. **Natural Language Understanding**
Ask questions in plain English about:
- Academic performance and grades
- School capabilities and resources
- Qualifications and achievements
- Contextual fairness factors
- Comparative analysis

### 3. **Evidence-Based Responses**
Every answer is:
- Based on actual student data from the database
- Cited with reference to specific data points
- Adjusted for school opportunity context
- Supported by agent evaluations

### 4. **Conversation Memory**
ARIEL maintains conversation history to:
- Provide context-aware follow-up answers
- Reference previous questions
- Build on prior discussions
- Enable natural dialogue flow

### 5. **Audit Trail Logging**
Every Q&A interaction is logged to the database with:
- Question text
- Answer text
- Student name and ID
- Timestamp
- Data sources used
- Entry point for future analysis

## Usage

### Web Interface

The ARIEL chat widget is available on every student's application detail page (`/application/<id>`):

1. **Scroll to ARIEL Q&A Section** - Bottom of the page
2. **Click in the input field** - "Ask a question about this student..."
3. **Type your question** - Natural language, any topic about the student
4. **Press Send or Shift+Enter** - Submit the question
5. **Read the response** - With references to data sources

### Sample Questions

```
"What is this student's GPA and how does it compare to their school?"
"What AP courses are available at this student's school?"
"What factors affect this student's contextual rigor score?"
"How does this student's opportunity score impact fairness assessment?"
"What were the key findings from TIANA and RAPUNZEL?"
"Is this student's performance exceptional given their school's resources?"
```

### API Endpoint

**POST** `/api/ask-question/<application_id>`

**Request:**
```json
{
    "question": "What is the student's academic performance?",
    "conversation_history": [
        {
            "question": "Previous question...",
            "answer": "Previous answer..."
        }
    ]
}
```

**Response:**
```json
{
    "success": true,
    "answer": "The student's academic performance is...",
    "reference_data": {
        "name": "Alice Smith",
        "school": "Lincoln High School",
        "gpa": 3.85,
        "data_sources": ["Application Data", "Grade Analysis", "Agent Evaluations"]
    }
}
```

**Error Response:**
```json
{
    "success": false,
    "error": "Student not found",
    "answer": null,
    "reference_data": {}
}
```

## Data Integration

### Data Sources

ARIEL assembles information from:

1. **applications** table
   - Student demographics
   - GPA and test scores
   - Application status

2. **student_school_context** table
   - AP course count
   - Honors course count
   - Community opportunity score
   - Free/reduced lunch percentage
   - School demographics

3. **rapunzel_grades** table
   - Contextual rigor index (0-5 scale)
   - Grade distribution
   - AP and Honors performance

4. **ai_evaluations** table
   - Scores from each agent
   - Recommendations
   - Key insights

5. **agent_interactions** table
   - Audit trail of all evaluations
   - Agent outputs
   - Decision points

### System Prompt Context

The system prompt automatically includes:
- Student name and school
- GPA and test scores
- Application status
- School context summary
- Rigor analysis
- Agent specializations
- Fairness weighting factors

This ensures GPT-4 has rich context for accurate, fair responses.

## Architecture

```
User Question
      ↓
[Web Interface or API]
      ↓
[ARIEL Q&A Agent]
      ├─→ Fetch Student Profile
      │   ├─ Application data
      │   ├─ School context
      │   ├─ Grade analysis
      │   ├─ Agent evaluations
      │   └─ Audit trail
      │
      ├─→ Build System Prompt
      │   ├─ Role and responsibilities
      │   ├─ Student data overview
      │   ├─ Analysis guidelines
      │   └─ Response guidelines
      │
      ├─→ Build User Message
      │   ├─ Current question
      │   ├─ Agent evaluations context
      │   └─ Conversation history
      │
      ├─→ Call GPT-4
      │   └─ Get response
      │
      ├─→ Log Interaction
      │   └─ Insert to database
      │
      └─→ Return Response with References
          ├─ Answer text
          ├─ Student metadata
          └─ Data sources used
```

## Implementation Details

### File Structure

```
src/agents/
├── ariel_qa_agent.py        # ARIEL Q&A agent implementation
└── ...

web/templates/
├── application.html          # Student detail page
└── components/
    └── ariel-qa-chat.html   # Chat widget UI

app.py
└── /api/ask-question/<id>   # Q&A endpoint
```

### Key Methods

#### `answer_question(application_id, question, conversation_history)`
Main entry point for answering questions.

**Parameters:**
- `application_id` (str): Student's application ID
- `question` (str): User's question
- `conversation_history` (list): Previous Q&A exchanges

**Returns:**
- `success` (bool): Whether the call succeeded
- `answer` (str): The response text
- `reference_data` (dict): Student info + data sources
- `error` (str): Error message if unsuccessful

#### `_build_student_profile(application_id)`
Assembles comprehensive student data from database.

**Returns:**
- Dictionary containing:
  - Basic info (name, school, GPA, status)
  - School context (AP/Honors, opportunity score, SES)
  - Rigor analysis (contextual weighting)
  - Agent evaluations (scores + recommendations)
  - Data sources used

#### `_build_system_prompt(student_profile)`
Creates system context for GPT-4.

Includes:
- ARIEL's role and responsibilities
- Student data overview
- Agent specializations
- Fairness guidelines
- Response requirements

#### `_build_user_message(question, student_profile)`
Formats the user question with context.

Includes:
- The actual question
- Agent evaluation summaries
- Structured format for clarity

#### `_log_qa_interaction(application_id, question, answer, student_profile)`
Records the interaction to the database.

Logged to `agent_interactions` table:
- application_id
- agent_name: "ARIEL"
- step: 8.5
- action: "qa_response"
- output_json: Question, answer, student, timestamp

## Fairness & Bias Considerations

### Context-Aware Responses

ARIEL is specifically designed to provide fair, context-aware assessment:

1. **School Opportunity Awareness**
   - Understands AP/Honors availability by school
   - Adjusts rigor expectations based on resources
   - Recognizes SES factors from free/reduced lunch data

2. **Fairness Weighting**
   - Aware of MOANA's fairness adjustments
   - Contexualizes academic performance
   - Explains school-based disparities

3. **Transparent References**
   - All responses include data sources
   - Cites specific data points
   - Enables human verification

### Bias Prevention

- Training data context prevents stereotyping
- School resource data prevents SES bias
- Demographic context prevents socioeconomic bias
- Transparent citations prevent unjustified claims

## Performance

### Response Times
- Database queries: ~100-300ms
- GPT-4 response: ~2-5 seconds
- Total response: ~2.5-5.5 seconds

### Database Queries
- Optimized SELECT statements
- Indexed on application_id
- Limited to necessary columns
- No N+1 query problems

### Limitations
- Max 1000 tokens in response (configurable)
- Conversation history limited to 10 exchanges (configurable)
- Timeout: 30 seconds per request

## Testing

Run the test suite:
```bash
python testing/test_ariel_qa.py
```

This will:
1. Test multiple Q&A interactions
2. Verify conversation history
3. Confirm reference data accuracy
4. Check database logging

## Integration with 9-Step Workflow

ARIEL fits into the overall evaluation workflow:

```
1️⃣ BELLE extraction
2️⃣ Student matching
2️⃣➕ School pre-enrichment
3️⃣ NAVEEN enrichment
3️⃣➕ MOANA validation loop
4️⃣ Core agents (TIANA, RAPUNZEL, MOANA, MULAN)
5️⃣ MILO pattern analysis
6️⃣ MERLIN evaluation
7️⃣ AURORA reporting
8️⃣➕ ARIEL Q&A ← Optional human inquiry
```

ARIEL can be accessed at any time after step 4, enabling:
- Exploration of evaluation details
- Verification of findings
- Follow-up questions about context
- Stakeholder communication

## Future Enhancements

### Planned Features
1. **Follow-up Intelligence**
   - Detect incomplete answers
   - Suggest relevant follow-up questions
   - Proactive clarifications

2. **Multi-Student Comparison**
   - Compare two students
   - Identify patterns across cohorts
   - Benchmark analysis

3. **Interactive Exploration**
   - "Show me" requests (visualizations)
   - Category suggestions
   - Guided discovery

4. **Document Generation**
   - Export Q&A as PDF
   - Create interview transcripts
   - Generate analysis summaries

5. **Specialized Agents**
   - ARIEL for general questions
   - Specialized sub-agents for deep dives
   - Domain-specific expertise

## Related Documentation

- [WORKFLOW_MAP.md](../WORKFLOW_MAP.md) - 9-step workflow overview
- [PHASE_5_SUMMARY.md](../PHASE_5_SUMMARY.md) - Audit logging and file upload
- [README.md](../README.md) - Main project documentation

---

**Built with Azure AI** 🚀
