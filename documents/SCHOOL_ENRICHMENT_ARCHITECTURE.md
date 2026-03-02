# School Data Enrichment System Architecture

**Status**: Fully Implemented — Database-First with NCES CCD Data  
**Last Updated**: March 2, 2026 (v1.0.43)

> **Note**: This document was originally written when the system planned to use web scraping. The architecture has since evolved to a database-first approach using NCES Common Core of Data (CCD) imported via CSV. Naveen now evaluates database records with AI to produce component scores and school summaries. Moana uses Naveen's evaluation plus NCES data to build contextual narratives. No external web data is fetched at runtime.

---

## 🎯 Vision & Purpose

The School Data Enrichment system provides nuanced, data-driven analysis of student opportunities within their school context.

### Public Data, Locally Enriched

> **All school data is derived from publicly available U.S. government datasets.** We combine multiple public data sources from the NCES Common Core of Data (CCD), normalize them into a unified schema, and store them locally. Our AI agents then evaluate and enrich this data — no proprietary school data is used, and no external APIs are called at runtime.

**Public data sources used:**
| Source | Data Provided | Published By |
|--------|--------------|-------------|
| NCES CCD School Directory | School names, addresses, NCES IDs, locale codes, charter/magnet/Title I flags | U.S. Dept. of Education |
| NCES CCD Enrollment | Total enrollment, grade-level counts, student-teacher ratios | U.S. Dept. of Education |
| NCES CCD Free/Reduced Lunch | FRPL percentages, direct certification rates | U.S. Dept. of Education |
| NCES CCD Finance (District) | Per-pupil expenditure, revenue breakdowns (federal/state/local) | U.S. Dept. of Education |
| NCES CCD Staffing | Full-time equivalent teacher counts | U.S. Dept. of Education |

These separate CCD datasets are joined by NCES school ID, aggregated across multiple school years to capture trends, and uploaded as a combined CSV.

### Current Architecture (v1.0.43)
- **Data Pipeline**: Download public CCD datasets → combine/normalize offline → upload merged CSV → import into local database
- **Naveen**: Evaluates NCES database records to produce School Evaluation Reports with component scores (Academic Rigor, Resource Investment, Student Outcomes, Equity & Access)
- **Moana**: Uses Naveen's evaluation + NCES data + student coursework to build AI-powered contextual narratives
- **Matching**: GA schools matched via fuzzy matching (threshold 0.55) against CSV-imported records
- **No Runtime Web Calls**: All school data comes from the database; no NAEP, web scraping, or external APIs

---

## 📊 Data Model Overview

### Core Tables

#### `school_enriched_data` (Primary)
Main table storing all analyzed school information:

```sql
- school_name, school_district, state_code, county_name
- opportunity_score (0-100) - PRIMARY METRIC
- Academic profile (AP courses, exam pass rates, STEM/IB availability)
- Demographics (students, graduation rate, free lunch %)
- Outcomes (college acceptance, salary data)
- Analysis tracking (status, confidence, last updated)
- Human review status (pending, reviewed, approved)
- Web sources analyzed (JSON array of URLs)
- Data confidence score (0-100)
```

#### `school_web_sources`
Tracks URL sources for each school:
- source_url, source_type (website, state_edu, nces, glassdoor, etc)
- data_retrieved_at, content_summary
- is_active flag for managing data freshness

#### `school_academic_profile`
Detailed academic capabilities:
- AP courses list, exam pass rates, student participation
- Honors & advanced course offerings
- Special programs (STEM, IB, dual enrollment, career tech)
- College prep indicators (counselor count, application support)
- National Merit scholars, college acceptance rates

#### `school_salary_outcomes`
Regional salary and post-secondary outcomes:
- Median salary by field (STEM, business, humanities)
- College enrollment & workforce entry rates
- Regional context (state/county averages, cost of living)
- Starting salary vs 5-year outcomes
- Data source tracking and confidence scores

#### `school_analysis_history`
Audit trail for all school analyses:
- analysis_type (initial, update, human_review, reprocessing)
- agent_name, status, findings_summary
- fields_updated, old_values (JSONB), new_values (JSONB)
- review information and notes
- Timestamp tracking

#### `school_opportunity_index`
Summary metrics and rankings:
- Component scores (academic, resource, college prep, socioeconomic)
- State/district ranking, national percentile
- Key strengths & areas for improvement
- Recommendations for students
- Last calculated timestamp

#### `school_data_versions`
Version history for tracking human adjustments:
- Full data snapshot at each version
- Change summary and reason
- Version number and current flag
- Used for audit trail and rollback capability

---

## 🤖 School Detail Data Scientist Agent

### Agent Architecture

Located: `src/agents/school_detail_data_scientist.py`

#### Primary Methods

**`analyze_school()`**
```python
analyze_school(
    school_name: str,
    school_district: Optional[str],
    state_code: Optional[str],
    web_sources: Optional[List[str]],
    existing_data: Optional[Dict]
) -> Dict[str, Any]
```

Returns enriched profile with:
- Academic profile analysis
- Salary outcomes modeling
- Demographic profile
- Opportunity metrics (composite scoring)
- Analysis summary and confidence scores

**`_analyze_web_sources()`**
- Classifies source types (state education, federal, college data, salary, community)
- Extracts relevant data from each source
- Tracks scraping success rate
- Builds data source profile

**`_build_academic_profile()`**
- Extracts AP/IB/Advanced course counts
- College acceptance and readiness metrics
- STEM program availability
- Dual enrollment options
- College counseling capacity

**`_calculate_opportunity_score()`**
Composite scoring algorithm:

```
Academic Opportunity (35%):
  - AP availability (30%)
  - College acceptance rate (35%)
  - College counseling (20%)
  - College readiness (15%)

Resource Opportunity (25%):
  - Class size (25%)
  - Student/teacher ratio (25%)
  - School investment level (25%)
  - STEM programs (25%)

College Prep Opportunity (25%):
  - College acceptance rate (40%)
  - Dual enrollment (30%)
  - College prep focus (30%)

Socioeconomic Opportunity (15%):
  - Resource availability (50%)
  - Programs for disadvantaged (35%)
  - Community sentiment (15%)

OVERALL = (Academic × 0.35) + (Resource × 0.25) + 
          (CollegePrep × 0.25) + (Socioeconomic × 0.15)
```

### Integration Points

#### With Moana (School Context Agent)
```python
# Moana can query pre-analyzed school data:
school_data = db.get_school_enriched_data(school_name, state_code)

# Use for enhanced context:
- School capability assessment
- Comparative advantage analysis
- Regional opportunity evaluation
- Student program access quantification
```

#### With Application Processing
```python
# Schools are indexed during:
1. Application upload (if school mentioned)
2. Manual school addition via admin dashboard
3. Batch processing of new schools
4. Reprocessing with human-reviewed data
```

---

## 🎨 School Management Dashboard

**Location**: `web/templates/school_management.html`

### Features

#### 1. School List & Discovery
- **Search**: School name or district
- **Filters**: State, review status, opportunity score range
- **Quick Stats**:
  - AP courses offered
  - College acceptance rate
  - Graduation rate
  - Total students

#### 2. School Detail View
- **Overview Tab**: Opportunity score breakdown with progress bars
- **Academics Tab**: Programs, AP offerings, college prep indicators
- **Outcomes Tab**: Salary data, college enrollment rates, regional context
- **Review Tab**: Human adjustment and approval workflow

#### 3. Human Review Workflow
```
View School → Examine Data → Add Notes → Adjust Scores → Submit Review
                                                              ↓
                                    Trigger Reprocessing with Moana
```

#### 4. Dashboard Statistics
- Total schools indexed
- Pending human review
- Average opportunity score
- Last analysis date

### API Endpoints (to be implemented)

```javascript
// Get all schools with filters
GET /api/schools/list?state=GA&review=pending&score_min=75

// Get school details
GET /api/school/{id}

// Submit human review
POST /api/school/{id}/review
  { reviewNotes, opportunityScore, reviewStatus }

// Trigger reanalysis
POST /api/school/{id}/analyze

// Get analysis history
GET /api/school/{id}/history
```

---

## 🔄 Data Flow & Integration

### Current to Future State

```
CURRENT (Moana Limited):
Student Upload → Embedded URL → Moana Extracts → Basic Context

FUTURE (Enhanced with School Data Scientist):
Student Upload → School Name Detection
                    ↓
            Is School Indexed?
            ↙           ↘
          YES           NO
           ↓             ↓
      Use Cached    Trigger New Analysis
      Enriched      by School Data Scientist
      Data           ↓
           ←────── Save to school_enriched_data
           ↓
      Moana Uses Enhanced Context Data:
        - Academic capabilities
        - Regional opportunity score
        - Comparative advantages
        - Demographic context
        - College prep pathway clarity
           ↓
      Better Executive Summary & Recommendation
```

### Example: Moana's Enhanced Analysis

**Before**: "Student attends Lincoln High School with good AP offerings"

**After**: 
```
"Student attends Lincoln High School (Opportunity Score: 78/100)
- Above-average academic opportunity (82): 24 AP courses, 89% pass rate
- Strong resource allocation (75): 15:1 student/teacher ratio
- Excellent college prep focus (88): 96% college acceptance
- Serving 42% disadvantaged population with strong support

REGIONAL CONTEXT: Lincoln outperforms GA average salary ($58k) with 
$64k median graduate salary. Provides meaningful opportunity for 
upward mobility, particularly in STEM pathways (5 STEM programs).

COMPARATIVE ADVANTAGE: Student's school provides above-state-average 
foundation. Should be encouraged to leverage dual enrollment and 
AP course load to maximize opportunity."
```

---

## 📋 Implementation Roadmap

### Phase 1: Foundation (CURRENT)
- ✅ Database schema created
- ✅ Agent class structure built
- ✅ Management dashboard UI created
- ⏳ API endpoints (next)
- ⏳ Database integration code

### Phase 2: Integration
- [ ] API route handlers (/api/schools/*, /api/school/*/review)
- [ ] Database connection layer
- [ ] School data ingestion (seeding with known schools)
- [ ] Moana integration (accept school_enriched_data parameter)
- [ ] Web scraping/data collection (Phase 2B)

### Phase 3: Enhancement
- [ ] Real web data extraction (BeautifulSoup, Selenium)
- [ ] State education department API integration
- [ ] CollegeBoard & ACT data feeds
- [ ] Salary outcome database integration (BLS, GitHub Salary Survey)
- [ ] Machine learning for missing data inference

### Phase 4: Automation
- [ ] Scheduled reanalysis of schools (quarterly)
- [ ] New school detection and auto-analysis
- [ ] Confidence score auto-improvement
- [ ] Alert system for data quality issues
- [ ] Email digest of newest/best schools

---

## 🎓 How Moana Will Use School Data

### Enhanced Context Construction

```python
def build_school_context(school_name, state_code, student_data):
    # 1. Get pre-analyzed school data
    school = db.get_school_enriched_data(school_name, state_code)
    
    # 2. Extract key metrics
    opportunity_score = school.opportunity_score
    academic_profile = school.academic_profile
    salary_outcomes = school.salary_outcomes
    
    # 3. Build comparative analysis
    comparison = {
        'school_vs_state': opportunity_score - get_state_avg(),
        'ap_access': academic_profile.ap_course_count,
        'college_trajectory': salary_outcomes.college_enrollment_rate,
        'regional_salary': salary_outcomes.avg_all_fields_median_salary
    }
    
    # 4. Generate insight
    context = f"""
    School Opportunity Context:
    {school.school_name} provides {opportunity_score}/100 opportunity.
    
    Strengths: {school.key_strengths}
    Areas for Growth: {school.areas_for_improvement}
    
    For this student with {student_data.gpa} GPA:
    - Recommended programs: {get_recommendations(student_data, academic_profile)}
    - Realistic outcomes: {project_outcomes(student_data, salary_outcomes)}
    """
    
    return context
```

---

## ✅ Success Metrics

### Data Quality
- School profiles completeness: >90% of key fields populated
- Data confidence score: >80% average
- Human review approval rate: >85%

### Integration
- Moana's executive summaries reference school context: >75% of reports
- School opportunity score impacts final recommendation: Measurable
- False positive reduction in matching: <2%

### User Engagement
- School management dashboard usage: Regular reviews
- Human adjustment frequency: 2-3 per week
- Reanalysis requests: Tracked and trending

---

## 🔐 Data Governance

### Human Review Workflow
1. AI analyzes and populates `school_enriched_data`
2. Status: `analysis_status = 'complete'`, `human_review_status = 'pending'`
3. Human reviews in dashboard, adjusts if needed
4. Submits with adjusted scores and notes
5. Creates version in `school_data_versions`
6. Triggers reprocessing with updated data
7. Status: `human_review_status = 'approved'` or `'review_needed'`

### Audit Trail
- All changes recorded in `school_analysis_history`
- Version snapshots in `school_data_versions`
- Review notes tracked with reviewer ID
- Timestamp all modifications

### Data Validation
- Confidence scores on all data points
- Data source documentation
- Last-updated tracking
- Stale data detection (>6 months)

---

## 📈 Future Enhancements

### Real Web Scraping
- Integrate requests/BeautifulSoup for news sentiment
- Crawl state education dashboards
- Parse school.state.edu for official data
- Glassdoor/Indeed salary scraping for graduate outcomes

### Advanced Scoring
- Machine learning model for opportunity score
- Neural network: Learn what makes schools impactful for students
- Feedback loop: Track actual student outcomes vs predictions
- Dynamic weighting: Adjust algorithm based on results

### Comparative Analysis
- School ranking system (state-level, district-level, regional)
- Peer schools identification
- Benchmark comparisons
- "What if" scenarios for student decisions

### Predictive Integration
- Student success probability by school
- College acceptance likelihood given school profile
- Career outcome predictions by field
- Earnings trajectory modeling

---

## 🚀 Next Steps

1. **Immediate**: Implement API endpoints
2. **This week**: Database integration and school seeding
3. **Next week**: Moana integration testing
4. **Following week**: Real data collection and manual review
5. **Ongoing**: Refinement based on test results

Continue with comprehensive school data analysis supporting stronger context for Moana and better student evaluations.
