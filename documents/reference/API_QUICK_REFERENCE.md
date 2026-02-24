# School Enrichment System - API Quick Reference

## Ready-to-Use API Endpoints

All endpoints are now implemented and ready to test.

---

## Endpoint Summary

### 1. Dashboard Page
```
GET /schools
```
**Purpose**: Main school management and review interface  
**Returns**: HTML page with school_management.html template  
**Authentication**: None (currently - can be added)

---

### 2. Get Schools List
```
GET /api/schools/list
```

**Query Parameters**:
- `state` (optional): Filter by state code (e.g., "GA")
- `review` (optional): Filter by review status ("pending", "approved", "rejected")
- `score_min` (optional): Minimum opportunity score (0-100)
- `search` (optional): Search in school name or district

**Example Requests**:
```bash
# Get all schools
GET /api/schools/list

# Get GA schools pending review
GET /api/schools/list?state=GA&review=pending

# Get high-opportunity schools
GET /api/schools/list?score_min=80

# Search schools
GET /api/schools/list?search=Lincoln
```

**Response**:
```json
{
  "status": "success",
  "schools": [
    {
      "school_enrichment_id": 1,
      "school_name": "Lincoln High School",
      "school_district": "Fulton County Schools",
      "state_code": "GA",
      "opportunity_score": 81.5,
      "human_review_status": "approved",
      "analysis_status": "complete",
      "total_students": 1950,
      "ap_course_count": 24,
      "graduation_rate": 92.5,
      "college_acceptance_rate": 85.0,
      ...
    }
  ],
  "count": 1
}
```

---

### 3. Submit School Review
```
POST /api/school/<school_id>/review
```

**Request Body** (JSON):
```json
{
  "review_status": "approved",
  "opportunity_score": 82.0,
  "human_notes": "Excellent program offerings. Data verified against FCSchools website."
}
```

**Parameters**:
- `school_id` (path): ID from school_enriched_data table

**Response**:
```json
{
  "status": "success",
  "message": "Review submitted"
}
```

**What Happens**:
1. Updates `human_review_status` in database
2. Records `opportunity_score` adjustment
3. Saves human reviewer metadata
4. Creates version snapshot in `school_data_versions`
5. Records event in `school_analysis_history`
6. Logs all changes with timestamps

**Example cURL**:
```bash
curl -X POST http://localhost:5002/api/school/1/review \
  -H "Content-Type: application/json" \
  -d '{
    "review_status": "approved",
    "opportunity_score": 85.0,
    "human_notes": "Verified data quality is high"
  }'
```

---

### 4. Trigger School Re-analysis
```
POST /api/school/<school_id>/analyze
```

**Parameters**:
- `school_id` (path): ID from school_enriched_data table

**Response**:
```json
{
  "status": "success",
  "message": "Analysis queued"
}
```

**What Happens** (Background):
1. Fetches school record including web_sources
2. Calls SchoolDetailDataScientist agent
3. Runs full analysis pipeline
4. Updates fields:
   - `opportunity_score` - New composite score
   - `analysis_status` - "complete"
   - `data_confidence_score` - Confidence level
5. Updates `updated_at` timestamp
6. Non-blocking (returns immediately, processes in background)

**Example cURL**:
```bash
curl -X POST http://localhost:5002/api/school/1/analyze
```

---

## How Moana Uses Enriched Data

When Moana processes a student application:

1. **Extracts school name & state** from transcript/application
2. **Queries enriched database**:
   ```python
   enriched_school = db.get_school_enriched_data(
       school_name="Lincoln High School",
       state_code="GA"
   )
   ```
3. **Priority decision**:
   - If `human_review_status == "approved"` → Use data directly (100% trust)
   - Else if `analysis_status == "complete"` AND `data_confidence_score >= 75` → Use data with note
   - Else → Fall back to web search
4. **Uses data for context**:
   - AP courses offered (better context for student's course load)
   - STEM programs (evaluates student's STEM positioning)
   - College acceptance rate (frames student's achievements)
   - Opportunity scores (contextualizes difficulty/access)

---

## Testing Workflow

### Step 1: Start the app
```bash
python app.py
```

### Step 2: Seed initial data (first time only)
```bash
python scripts/seed_schools.py
```
Output:
```
🌱 Starting school database seeding...
✓ Created: Lincoln High School (ID: 1) - Score: 81.5
✓ Created: Westlake High School (ID: 2) - Score: 72.3
✓ Created: MLK Jr. High School (ID: 3) - Score: 79.7
✓ Created: Lakeside High School (ID: 4) - Score: 86.2
✓ Created: Northside High School (ID: 5) - Score: 68.4

==================================================
📊 Seeding Summary:
   Created: 5
   Skipped: 0
   Errors:  0
   Total:   5
==================================================

✅ Seeding complete!
```

### Step 3: Test dashboard
```
Browser: http://localhost:5002/schools
```
- Should see all 5 schools
- Filter by state, review status
- Click school to view details
- Try adjusting opportunity score and submitting review

### Step 4: Test API directly
```bash
# Get all GA schools
curl http://localhost:5002/api/schools/list?state=GA

# Get schools pending review
curl http://localhost:5002/api/schools/list?review=pending

# Submit a review
curl -X POST http://localhost:5002/api/school/1/review \
  -H "Content-Type: application/json" \
  -d '{"review_status":"approved","opportunity_score":85,"human_notes":"Verified"}'

# Trigger re-analysis
curl -X POST http://localhost:5002/api/school/1/analyze
```

### Step 5: Verify in database
```sql
-- Check school data
SELECT school_name, opportunity_score, human_review_status 
FROM school_enriched_data 
WHERE school_name = 'Lincoln High School';

-- Check review history
SELECT analysis_type, reviewed_by, review_notes, created_at
FROM school_analysis_history
WHERE school_enrichment_id = 1
ORDER BY created_at DESC;

-- Check versions
SELECT change_reason, changed_by, created_at
FROM school_data_versions
WHERE school_enrichment_id = 1
ORDER BY created_at DESC;
```

---

## Data Schema

### Main Table: school_enriched_data
```
school_enrichment_id (PRIMARY KEY)
school_name, school_district, state_code, county_name, school_url
opportunity_score (0-100 composite)
  ├─ Academic opportunity (35%)
  ├─ Resource opportunity (25%)
  ├─ College prep opportunity (25%)
  └─ Socioeconomic opportunity (15%)

total_students, graduation_rate, college_acceptance_rate
ap_course_count, ap_exam_pass_rate
stem_program_available, ib_program_available, dual_enrollment_available
free_lunch_percentage

human_review_status (pending/approved/rejected)
reviewed_by, reviewed_date, human_notes

analysis_status (pending/complete/error)
web_sources_analyzed (JSON), data_confidence_score
web_sources_analyzed, created_at, updated_at
```

### Supporting Tables:
- `school_analysis_history` - Full audit trail
- `school_data_versions` - Complete snapshots
- `school_opportunity_index` - Component scoring
- `school_academic_profile` - AP/IB/STEM detail
- `school_salary_outcomes` - Graduate data
- `school_web_sources` - URL tracking

---

## Error Handling

All endpoints include:
✅ Try-catch error blocks  
✅ JSON error responses  
✅ Logging with audit trail  
✅ Graceful degradation  

Example error response:
```json
{
  "status": "error",
  "error": "School not found"
}
```

---

## Security Notes

Current implementation:
- No authentication required (for testing)
- Can be enhanced with Flask-Login or similar
- Reviewer captured as "admin_user" (can be enhanced with session)
- All operations logged with timestamps

Recommendations for production:
1. Add authentication layer
2. Validate user roles (admin/reviewer/viewer)
3. Enable audit logging of who changed what
4. Rate limit API endpoints
5. Sanitize user input

---

## Performance

- ✅ Indexes on: school_id, opportunity_score, review_status
- ✅ Query limit: 200 schools per request
- ✅ Background tasks: Non-blocking re-analysis
- ✅ Caching: Moana caches school lookups

---

## Ready for Integration

When you're ready:
1. Create the database schema: `psql < database/schema_school_enrichment.sql`
2. Run seed script: `python scripts/seed_schools.py`
3. Test endpoints above
4. Start using with Moana

All code is ready - **waiting for git push signal**
