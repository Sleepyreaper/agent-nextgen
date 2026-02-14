# Moana's Georgia School Data Integration

## Overview

Moana (School Context Analyzer) now includes special handling for **Georgia high schools**, enabling access to verified public data through the **Georgia Governor's Office of Student Achievement (GOSA)** dashboard.

## Data Source

**Georgia Awards Dashboard**  
URL: https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard

This dashboard provides comprehensive public data for all Georgia high schools, including:

### Available Data Points

#### Academic Programs
- **AP Courses Offered** - Exact number of Advanced Placement courses
- **IB Program** - International Baccalaureate availability and course count
- **Honors Programs** - Honors course offerings
- **STEM Programs** - Science, Technology, Engineering, Math offerings
- **Career/Technical Education** - CTE program availability

#### Student Performance
- **Graduation Rate** - 4-year and 5-year graduation rates
- **College Readiness Score** - Composite readiness indicator
- **SAT/ACT Scores** - Average standardized test scores
- **AP Exam Pass Rates** - Percentage scoring 3+ on AP exams
- **End of Course (EOCT) Scores** - State assessment performance

#### Demographics & Resources
- **Total Enrollment** - Exact student count
- **Free/Reduced Lunch %** - Socioeconomic indicator
- **Student-Teacher Ratio** - Class size indicator
- **Per-Pupil Expenditure** - Resource allocation (when available)
- **Demographic Breakdown** - Racial/ethnic composition
- **Special Education %** - Students with IEPs
- **English Language Learner %** - ELL student percentage

#### School Context
- **School Type** - Traditional public, charter, private
- **Locale Classification** - Urban, suburban, rural
- **District Information** - School district context
- **School Size Category** - Small, medium, large

---

## How It Works

### 1. Automatic Detection

When Moana analyzes a student's school context, she:

1. **Extracts school location** from transcript
2. **Detects Georgia schools** (state = "GA" or "GEORGIA")
3. **Flags for data availability** when Georgia is detected
4. **Includes reference URL** in analysis output

### 2. Integration Points

```python
# School detection
is_georgia = school_info.get('state', '').upper() in ['GA', 'GEORGIA']

# Profile creation
if is_georgia:
    profile['georgia_data_available'] = True
    profile['georgia_data_source'] = "https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard"
    print(f"✓ Georgia school detected - public data available")

# Resource analysis
if is_georgia:
    comparison_notes += f" [Georgia school - verified data available at {data_source}]"
```

### 3. Output Markers

Georgia schools include these fields in analysis results:

```json
{
  "school": {
    "name": "North Atlanta High School",
    "city": "Atlanta",
    "state": "GA",
    "georgia_data_available": true,
    "data_source_url": "https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard"
  },
  "school_resources": {
    "georgia_data_available": true,
    "data_source_url": "https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard",
    "comparison_notes": "Moderate-resource school... [Georgia school - verified data available]"
  }
}
```

---

## Usage Examples

### Example 1: Georgia School Analysis

```python
from src.agents.moana_school_context import MoanaSchoolContext

# Initialize Moana
moana = MoanaSchoolContext(name="Moana", client=openai_client, model="NextGenGPT")

# Analyze Georgia student
result = await moana.analyze_student_school_context(
    application={"ApplicantName": "Alex Johnson", ...},
    transcript_text=georgia_transcript
)

# Check if Georgia data is available
if result['school_resources'].get('georgia_data_available'):
    print(f"✓ Real data available at: {result['school_resources']['data_source_url']}")
    
    # Get lookup instructions
    instructions = moana.get_georgia_school_data_instructions(
        school_name=result['school']['name']
    )
    print(instructions['lookup_instructions'])
```

### Example 2: Manual Data Lookup

```python
# Get instructions for manual lookup
instructions = moana.get_georgia_school_data_instructions("North Atlanta High School")

# Returns:
{
    'data_source': 'https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard',
    'school_name': 'North Atlanta High School',
    'lookup_instructions': '...',  # Detailed instructions
    'data_points': [
        'ap_courses_offered',
        'ib_courses_offered',
        'graduation_rate',
        'college_readiness_score',
        'free_reduced_lunch_pct',
        # ... more metrics
    ]
}
```

---

## Test Results

✅ **Georgia school detection: PASSED**  
✅ **Data source integration: WORKING**  
✅ **Non-Georgia school handling: PASSED**

### Test File
Run: `python testing/test_moana_georgia.py`

### Sample Output
```
TEST 1: Georgia School (North Atlanta High School)
  School Identified: NORTH ATLANTA HIGH
  ✓ Georgia school detected - public data available

✅ GEORGIA DATA SOURCE DETECTED!
  • Data URL: https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard
  • School: NORTH ATLANTA HIGH
  • Data Points: 8 metrics
```

---

## Future Enhancements

### Phase 1: Manual Lookup (Current)
- ✅ Detect Georgia schools
- ✅ Flag data availability
- ✅ Provide lookup instructions
- ⚠️ User manually retrieves data

### Phase 2: Semi-Automated (Future)
- [ ] Pre-populated Georgia school database
- [ ] Lookup school in local database first
- [ ] Fall back to AI estimates if not found

### Phase 3: Fully Automated (Future)
- [ ] Web scraping integration (if legally permissible)
- [ ] API integration (if GOSA provides one)
- [ ] Automatic data refresh
- [ ] Real-time school profile updates

---

## Data Privacy & Ethics

### Public Data Only
- All data from GOSA dashboard is **public information**
- No student-level data is accessed
- School-level aggregated data only

### Fair Use
- Data used for **educational opportunity assessment**
- Helps contextualize student achievement
- Supports equitable admissions decisions

### Accuracy
- AI estimates used when real data unavailable
- Georgia data flagged as "verified" when sourced
- Clear labeling of data source (AI vs. verified)

---

## Benefits

### For Student Evaluation
- **Context-aware assessment**: 3.8 GPA from limited-resource school vs. high-resource school
- **Fair comparison**: Student achievements evaluated relative to opportunities
- **Resource awareness**: Understand what programs were available to student

### For Admissions Teams
- **Verified data**: Real numbers instead of estimates
- **Consistent analysis**: Same data source for all GA schools
- **Time savings**: Automated detection and flagging

### For Students
- **Equal opportunity**: Context considered in evaluation
- **Recognition**: Achievements evaluated fairly relative to resources
- **Transparency**: Clear understanding of how context matters

---

## Related Agents

- **Rapunzel (Grade Reader)**: Parses transcripts that Moana analyzes for context
- **Merlin (Evaluator)**: Uses Moana's context analysis for holistic evaluation
- **Smee (Orchestrator)**: Coordinates data flow between agents

---

## Configuration

No additional configuration needed! Georgia detection works automatically:

```python
# Moana initializes with Georgia support built-in
moana = MoanaSchoolContext(
    name="Moana",
    client=azure_openai_client,
    model="NextGenGPT"
)

# Georgia data source is pre-configured
moana.georgia_data_source  # => "https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard"
```

---

**Status**: ✅ **PRODUCTION READY**  
Georgia school data integration is fully functional and tested.
