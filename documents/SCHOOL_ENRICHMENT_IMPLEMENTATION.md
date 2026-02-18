# School Data Enrichment - Implementation Guide

**Purpose**: Step-by-step guide for implementing API endpoints and database integration  
**Timeline**: 1-2 days  
**Owner**: Development Team

---

## Phase 2 Implementation Tasks

### 1. Database Layer Integration

**File**: `src/database.py`

Add these methods to the Database class:

```python
# ==================== SCHOOL ENRICHMENT METHODS ====================

def create_school_enriched_data(self, school_data: Dict[str, Any]) -> Optional[int]:
    """Create a new enriched school record."""
    query = """
        INSERT INTO school_enriched_data (
            school_name, school_district, state_code, county_name, school_url,
            opportunity_score, total_students, graduation_rate, college_acceptance_rate,
            free_lunch_percentage, ap_course_count, ap_exam_pass_rate, stem_program_available,
            ib_program_available, dual_enrollment_available, analysis_status, 
            human_review_status, web_sources_analyzed, data_confidence_score, created_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING school_enrichment_id
    """
    
    result = self.execute_query(
        query,
        (
            school_data.get('school_name'),
            school_data.get('school_district'),
            school_data.get('state_code'),
            school_data.get('county_name'),
            school_data.get('school_url'),
            school_data.get('opportunity_score', 0),
            school_data.get('total_students'),
            school_data.get('graduation_rate'),
            school_data.get('college_acceptance_rate'),
            school_data.get('free_lunch_percentage'),
            school_data.get('ap_course_count'),
            school_data.get('ap_exam_pass_rate'),
            school_data.get('stem_program_available', False),
            school_data.get('ib_program_available', False),
            school_data.get('dual_enrollment_available', False),
            school_data.get('analysis_status', 'pending'),
            school_data.get('human_review_status', 'pending'),
            json.dumps(school_data.get('web_sources', [])),
            school_data.get('data_confidence_score', 0),
            school_data.get('created_by', 'system')
        )
    )
    
    return result[0].get('school_enrichment_id') if result else None

def get_school_enriched_data(self, school_id: Optional[int] = None, school_name: Optional[str] = None, 
                             state_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve enriched school data by ID or name/state."""
    if school_id:
        query = "SELECT * FROM school_enriched_data WHERE school_enrichment_id = %s"
        result = self.execute_query(query, (school_id,))
    elif school_name and state_code:
        query = "SELECT * FROM school_enriched_data WHERE LOWER(school_name) = LOWER(%s) AND state_code = %s"
        result = self.execute_query(query, (school_name, state_code))
    else:
        return None
    
    return result[0] if result else None

def get_all_schools_enriched(self, filters: Optional[Dict[str, Any]] = None, 
                            limit: int = 100) -> List[Dict[str, Any]]:
    """Get all enriched schools with optional filters."""
    query = "SELECT * FROM school_enriched_data WHERE is_active = TRUE"
    params = []
    
    if filters:
        if filters.get('state_code'):
            query += " AND state_code = %s"
            params.append(filters['state_code'])
        if filters.get('human_review_status'):
            query += " AND human_review_status = %s"
            params.append(filters['human_review_status'])
        if filters.get('opportunity_score_min'):
            query += " AND opportunity_score >= %s"
            params.append(filters['opportunity_score_min'])
    
    query += " ORDER BY opportunity_score DESC LIMIT %s"
    params.append(limit)
    
    return self.execute_query(query, tuple(params))

def update_school_review(self, school_id: int, review_data: Dict[str, Any]) -> bool:
    """Update school record with human review."""
    query = """
        UPDATE school_enriched_data
        SET human_review_status = %s,
            opportunity_score = %s,
            reviewed_by = %s,
            reviewed_date = CURRENT_TIMESTAMP,
            human_notes = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE school_enrichment_id = %s
    """
    
    try:
        self.execute_non_query(
            query,
            (
                review_data.get('review_status', 'pending'),
                review_data.get('opportunity_score'),
                review_data.get('reviewed_by', 'system'),
                review_data.get('human_notes'),
                school_id
            )
        )
        
        # Save version for audit trail
        self._save_school_version(school_id, review_data, 'human_adjustment')
        
        # Save to analysis history
        self._save_analysis_history(school_id, 'human_review', review_data)
        
        return True
    except Exception as e:
        logger.error(f"Error updating school review: {e}")
        return False

def _save_school_version(self, school_id: int, data: Dict[str, Any], change_reason: str) -> None:
    """Save version snapshot for audit trail."""
    school = self.get_school_enriched_data(school_id)
    if not school:
        return
    
    query = """
        INSERT INTO school_data_versions (school_enrichment_id, data_snapshot, 
                                         change_summary, changed_by, change_reason)
        VALUES (%s, %s, %s, %s, %s)
    """
    
    self.execute_non_query(
        query,
        (
            school_id,
            json.dumps(school),
            data.get('human_notes', ''),
            data.get('reviewed_by', 'system'),
            change_reason
        )
    )

def _save_analysis_history(self, school_id: int, analysis_type: str, data: Dict[str, Any]) -> None:
    """Save to analysis history."""
    query = """
        INSERT INTO school_analysis_history (school_enrichment_id, analysis_type, 
                                            agent_name, status, findings_summary, 
                                            reviewed_by, review_notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    
    self.execute_non_query(
        query,
        (
            school_id,
            analysis_type,
            'human_review_system',
            'complete',
            data.get('human_notes', ''),
            data.get('reviewed_by', 'system'),
            json.dumps(data)
        )
    )
```

### 2. Flask Routes

**File**: `app.py`

Add these routes:

```python
# ==================== SCHOOL MANAGEMENT ROUTES ====================

@app.route('/schools', methods=['GET'])
def schools_dashboard():
    """School management and review dashboard."""
    return render_template('school_management.html')

@app.route('/api/schools/list', methods=['GET'])
def get_schools_list():
    """Get all schools with filters."""
    try:
        filters = {}
        if request.args.get('state'):
            filters['state_code'] = request.args.get('state')
        if request.args.get('review'):
            filters['human_review_status'] = request.args.get('review')
        if request.args.get('score_min'):
            filters['opportunity_score_min'] = float(request.args.get('score_min'))
        
        schools = db.get_all_schools_enriched(filters=filters, limit=200)
        
        return jsonify({
            'status': 'success',
            'schools': schools,
            'count': len(schools)
        })
    except Exception as e:
        logger.error(f"Error getting schools list: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/school/<int:school_id>/review', methods=['POST'])
def submit_school_review(school_id):
    """Submit human review for a school."""
    try:
        data = request.json or request.form.to_dict()
        
        # Add reviewer info
        data['reviewed_by'] = current_user.username if current_user else 'anonymous'
        
        success = db.update_school_review(school_id, data)
        
        if success:
            # Trigger Moana reprocessing with updated school data
            trigger_moana_reprocessing_with_school(school_id)
            
            return jsonify({'status': 'success', 'message': 'Review submitted'})
        else:
            return jsonify({'status': 'error', 'error': 'Failed to update'}), 400
            
    except Exception as e:
        logger.error(f"Error submitting school review: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/school/<int:school_id>/analyze', methods=['POST'])
def trigger_school_analysis(school_id):
    """Trigger re-analysis of a school."""
    try:
        school = db.get_school_enriched_data(school_id)
        if not school:
            return jsonify({'status': 'error', 'error': 'School not found'}), 404
        
        # Queue for re-analysis
        from src.agents.school_detail_data_scientist import SchoolDetailDataScientist
        scientist = SchoolDetailDataScientist()
        
        # Get web sources
        web_sources = json.loads(school.get('web_sources_analyzed', '[]'))
        
        # Run analysis in background
        def background_analysis():
            result = scientist.analyze_school(
                school_name=school['school_name'],
                school_district=school['school_district'],
                state_code=school['state_code'],
                web_sources=web_sources,
                existing_data=school
            )
            
            # Update database with results
            update_data = {
                'opportunity_score': result.get('opportunity_metrics', {}).get('overall_opportunity_score'),
                'analysis_status': result.get('analysis_status'),
                'data_confidence_score': result.get('confidence_score'),
                'human_notes': f"Re-analyzed: {result.get('analysis_summary')}"
            }
            
            db.execute_non_query(
                "UPDATE school_enriched_data SET opportunity_score = %s, analysis_status = %s, "
                "data_confidence_score = %s WHERE school_enrichment_id = %s",
                (update_data['opportunity_score'], update_data['analysis_status'], 
                 update_data['data_confidence_score'], school_id)
            )
        
        # Start background task
        import threading
        thread = threading.Thread(target=background_analysis)
        thread.daemon = True
        thread.start()
        
        return jsonify({'status': 'success', 'message': 'Analysis queued'})
        
    except Exception as e:
        logger.error(f"Error triggering school analysis: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

def trigger_moana_reprocessing_with_school(school_id):
    """After school review, trigger Moana reprocessing."""
    # Find all applications from this school
    school = db.get_school_enriched_data(school_id)
    if not school:
        return
    
    # Query applications with this school
    apps = db.execute_query(
        "SELECT DISTINCT application_id FROM Applications WHERE lower(school_name) = lower(%s) LIMIT 50",
        (school['school_name'],)
    )
    
    # Reprocess each application with updated school data
    for app in apps:
        app_id = app.get('application_id')
        # This would trigger: start_application_processing(app_id, force_reprocess=True)
        logger.info(f"Queuing reprocessing for application {app_id} with updated school data")
```

### 3. Database Schema Initialization

**File**: `src/database.py` - add to initialization:

```python
def initialize_school_enrichment_tables(self):
    """Create school enrichment tables if they don't exist."""
    try:
        # Read and execute schema file
        with open('database/schema_school_enrichment.sql', 'r') as f:
            schema_sql = f.read()
        
        # Execute schema
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(schema_sql)
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info("School enrichment tables initialized")
    except Exception as e:
        logger.error(f"Error initializing school enrichment tables: {e}")
```

### 4. Moana Integration

**File**: `src/agents/moana_school_context.py` - Enhanced:

```python
def get_school_context(self, school_name: str, state_code: Optional[str] = None) -> Dict[str, Any]:
    """
    Get enhanced school context with enriched data.
    Falls back to web analysis if enriched data not available.
    """
    from src.database import db
    
    # Try enriched data first
    enriched_school = db.get_school_enriched_data(school_name=school_name, state_code=state_code)
    
    if enriched_school and enriched_school.get('human_review_status') == 'approved':
        # Use trusted, human-reviewed data
        return self._format_enriched_context(enriched_school)
    
    elif enriched_school and enriched_school.get('analysis_status') == 'complete':
        # Use AI-analyzed data with caveat about confidence
        return self._format_enriched_context(enriched_school, confidence=enriched_school.get('data_confidence_score'))
    
    else:
        # Fall back to web analysis (original behavior)
        return self._analyze_school_web_sources(school_name, state_code)

def _format_enriched_context(self, school_data: Dict[str, Any], confidence: Optional[float] = None) -> Dict[str, Any]:
    """Format enriched school data for Moana's analysis."""
    return {
        'school_name': school_data.get('school_name'),
        'opportunity_score': school_data.get('opportunity_score'),
        'academic_profile': {
            'ap_courses': school_data.get('ap_course_count'),
            'stem_available': school_data.get('stem_program_available'),
            'college_acceptance': school_data.get('college_acceptance_rate')
        },
        'demographics': {
            'total_students': school_data.get('total_students'),
            'graduation_rate': school_data.get('graduation_rate'),
            'free_lunch_percentage': school_data.get('free_lunch_percentage')
        },
        'outcomes': {
            'median_salary': school_data.get('median_graduate_salary'),
            'college_enrollment': school_data.get('college_acceptance_rate')
        },
        'confidence': confidence or 100 if school_data.get('human_review_status') == 'approved' else 75,
        'data_source': 'enriched_database',
        'analysis_status': school_data.get('analysis_status')
    }
```

---

## Seed Data: Initial Schools

Add to a new file `scripts/seed_schools.py`:

```python
#!/usr/bin/env python3
"""
Seed database with initial schools.
Run this after schema is created.
"""

from src.database import Database

INITIAL_SCHOOLS = [
    {
        'school_name': 'Lincoln High School',
        'school_district': 'Fulton County Schools',
        'state_code': 'GA',
        'school_url': 'https://lincolnhs.fcschools.us',
        'total_students': 1950,
        'graduation_rate': 92.5,
        'college_acceptance_rate': 85.0,
        'free_lunch_percentage': 28.0,
        'ap_course_count': 24,
        'ap_exam_pass_rate': 78.5,
        'stem_program_available': True,
        'ib_program_available': False,
        'dual_enrollment_available': True,
        'opportunity_score': 81.5,
        'analysis_status': 'complete',
        'human_review_status': 'pending',
        'web_sources_analyzed': '[
            "https://lincolnhs.fcschools.us",
            "https://www.greatschools.org/georgia/atlanta/lincoln-high-school",
            "https://www.niche.com/k12/search/best-high-schools/s/georgia"
        ]'
    },
    # Add more schools...
]

def seed_schools():
    db = Database()
    
    for school in INITIAL_SCHOOLS:
        # Check if already exists
        existing = db.get_school_enriched_data(
            school_name=school['school_name'],
            state_code=school['state_code']
        )
        
        if not existing:
            school_id = db.create_school_enriched_data(school)
            print(f"✓ Created school {school['school_name']} (ID: {school_id})")
        else:
            print(f"- School {school['school_name']} already exists")

if __name__ == '__main__':
    seed_schools()
    print("Done!")
```

---

## Testing Checklist

- [ ] Database schema creates successfully
- [ ] /api/schools/list returns schools
- [ ] School detail modal loads data correctly
- [ ] Human review submission saves to database
- [ ] Review updates trigger Moana reprocessing
- [ ] School analysis re-trigger works
- [ ] Moana pulls and uses enriched data
- [ ] Version history tracks changes
- [ ] Analysis history records human reviews

---

## Deployment Steps

1. Run database schema: `psql -U user -d db < database/schema_school_enrichment.sql`
2. Add database methods to Database class
3. Add Flask routes to app.py
4. Deploy school_management.html template
5. Run seed script: `python scripts/seed_schools.py`
6. Test in staging environment
7. Deploy to production with database backup

