-- =====================================================================
-- School Enrichment Data Model
-- Comprehensive analysis of schools for contextual evaluation
-- =====================================================================

-- Main school enrichment table - stores all analyzed school data
CREATE TABLE IF NOT EXISTS school_enriched_data (
    school_enrichment_id SERIAL PRIMARY KEY,
    school_name VARCHAR(500) NOT NULL,
    school_district VARCHAR(255),
    state_code VARCHAR(2),
    county_name VARCHAR(100),
    school_url VARCHAR(1000),
    
    -- Opportunity Score (0-100) - composite metric
    opportunity_score NUMERIC(5,2),
    opportunity_score_last_updated TIMESTAMP,
    
    -- Demographic Data
    total_students INTEGER,
    graduation_rate NUMERIC(5,2),
    college_acceptance_rate NUMERIC(5,2),
    free_lunch_percentage NUMERIC(5,2),
    
    -- Academic Profile
    ap_course_count INTEGER,
    ap_exam_pass_rate NUMERIC(5,2),
    honors_course_count INTEGER,
    standard_course_count INTEGER,
    stem_program_available BOOLEAN,
    ib_program_available BOOLEAN,
    dual_enrollment_available BOOLEAN,
    
    -- School Capabilities
    avg_class_size NUMERIC(5,2),
    student_teacher_ratio NUMERIC(5,2),
    college_prep_focus BOOLEAN,
    career_technical_focus BOOLEAN,
    
    -- Salary Outcomes (Regional Context)
    median_graduate_salary NUMERIC(10,2),
    salary_data_source VARCHAR(255),
    salary_data_year INTEGER,
    
    -- Sentiment & Community Data
    community_sentiment_score NUMERIC(5,2),
    parent_satisfaction_score NUMERIC(5,2),
    school_investment_level VARCHAR(50), -- low, medium, high
    
    -- Analysis Tracking
    analysis_status VARCHAR(50) DEFAULT 'pending', -- pending, analyzing, complete, review_needed
    human_review_status VARCHAR(50) DEFAULT 'pending', -- pending, reviewed, approved, rejected
    reviewed_by VARCHAR(255),
    reviewed_date TIMESTAMP,
    human_notes TEXT,
    
    -- Data Quality
    data_confidence_score NUMERIC(5,2), -- 0-100, how confident are we in this data
    data_source_notes TEXT,
    web_sources_analyzed TEXT, -- JSON array of URLs analyzed
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    
    -- Historical Tracking
    is_active BOOLEAN DEFAULT TRUE,
    archived_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_school_enriched_name ON school_enriched_data(school_name);
CREATE INDEX IF NOT EXISTS idx_school_enriched_state ON school_enriched_data(state_code);
CREATE INDEX IF NOT EXISTS idx_school_enriched_opportunity ON school_enriched_data(opportunity_score);
CREATE INDEX IF NOT EXISTS idx_school_enriched_review_status ON school_enriched_data(human_review_status);
CREATE INDEX IF NOT EXISTS idx_school_enriched_active ON school_enriched_data(is_active);

-- Web sources and links for each school
CREATE TABLE IF NOT EXISTS school_web_sources (
    source_id SERIAL PRIMARY KEY,
    school_enrichment_id INTEGER NOT NULL REFERENCES school_enriched_data(school_enrichment_id) ON DELETE CASCADE,
    source_url VARCHAR(1000) NOT NULL,
    source_type VARCHAR(100), -- website, state_education, nces, greatschools, glassdoor, etc
    data_retrieved_at TIMESTAMP,
    content_summary TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_source_school_id ON school_web_sources(school_enrichment_id);

-- Academic capability breakdown
CREATE TABLE IF NOT EXISTS school_academic_profile (
    profile_id SERIAL PRIMARY KEY,
    school_enrichment_id INTEGER NOT NULL REFERENCES school_enriched_data(school_enrichment_id) ON DELETE CASCADE,
    
    -- AP Courses Detail
    ap_courses_list TEXT, -- JSON array of AP course names
    ap_exams_administered INTEGER,
    ap_students_tested INTEGER,
    ap_avg_score NUMERIC(3,1),
    
    -- Advanced Placement
    honors_courses_list TEXT,
    advanced_students_percentage NUMERIC(5,2),
    
    -- Standard Curriculum
    standard_courses_list TEXT,
    
    -- Special Programs
    stem_programs_detail TEXT,
    ib_programs_detail TEXT,
    dual_enrollment_detail TEXT,
    career_tech_detail TEXT,
    
    -- College Prep Indicators
    college_counselor_count INTEGER,
    college_applications_assisted INTEGER,
    college_acceptance_rate NUMERIC(5,2),
    top_colleges_attended TEXT, -- JSON array
    
    -- Academic Excellence Indicators
    national_merit_scholars_count INTEGER,
    advanced_placement_capacity_score NUMERIC(5,2), -- 0-100
    college_readiness_score NUMERIC(5,2), -- 0-100
    
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_profile_school_id ON school_academic_profile(school_enrichment_id);

-- Regional and salary outcome data
CREATE TABLE IF NOT EXISTS school_salary_outcomes (
    outcome_id SERIAL PRIMARY KEY,
    school_enrichment_id INTEGER NOT NULL REFERENCES school_enriched_data(school_enrichment_id) ON DELETE CASCADE,
    
    -- Salary Data by Field
    stem_field_median_salary NUMERIC(10,2),
    business_field_median_salary NUMERIC(10,2),
    humanities_field_median_salary NUMERIC(10,2),
    avg_all_fields_median_salary NUMERIC(10,2),
    
    -- Regional Context
    state_avg_salary NUMERIC(10,2),
    county_avg_salary NUMERIC(10,2),
    regional_cost_of_living NUMERIC(5,2),
    
    -- Post-Secondary Outcomes
    college_enrollment_rate NUMERIC(5,2),
    workforce_entry_rate NUMERIC(5,2),
    avg_starting_salary NUMERIC(10,2),
    avg_5yr_salary NUMERIC(10,2),
    
    -- Data Quality
    salary_data_source VARCHAR(255),
    salary_data_year INTEGER,
    data_confidence NUMERIC(5,2),
    
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_salary_school_id ON school_salary_outcomes(school_enrichment_id);

-- Analysis history and audit trail
CREATE TABLE IF NOT EXISTS school_analysis_history (
    history_id SERIAL PRIMARY KEY,
    school_enrichment_id INTEGER NOT NULL REFERENCES school_enriched_data(school_enrichment_id) ON DELETE CASCADE,
    
    analysis_type VARCHAR(100), -- initial_analysis, update, human_review, reprocessing
    agent_name VARCHAR(255),
    status VARCHAR(50),
    findings_summary TEXT,
    confidence_level NUMERIC(5,2),
    data_sources_used TEXT, -- JSON array of URLs
    
    -- Changes Made
    fields_updated TEXT, -- JSON array of field names
    old_values JSONB,
    new_values JSONB,
    
    -- Review Information
    reviewed_by VARCHAR(255),
    review_notes TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_history_school_id ON school_analysis_history(school_enrichment_id);
CREATE INDEX IF NOT EXISTS idx_history_created_at ON school_analysis_history(created_at);

-- School opportunity index - summary for quick lookup
CREATE TABLE IF NOT EXISTS school_opportunity_index (
    index_id SERIAL PRIMARY KEY,
    school_enrichment_id INTEGER NOT NULL REFERENCES school_enriched_data(school_enrichment_id) ON DELETE CASCADE,
    school_name VARCHAR(500),
    
    -- Composite Opportunity Score Components
    academic_opportunity_score NUMERIC(5,2),
    resource_opportunity_score NUMERIC(5,2),
    college_prep_opportunity_score NUMERIC(5,2),
    socioeconomic_opportunity_score NUMERIC(5,2),
    overall_opportunity_score NUMERIC(5,2),
    
    -- Ranking
    state_rank INTEGER,
    district_rank INTEGER,
    percentile_nationally NUMERIC(5,2),
    
    -- Insights
    key_strengths TEXT, -- JSON array
    areas_for_improvement TEXT, -- JSON array
    recommendations_for_students TEXT,
    
    last_calculated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_opportunity_school_id ON school_opportunity_index(school_enrichment_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_overall_score ON school_opportunity_index(overall_opportunity_score);
CREATE INDEX IF NOT EXISTS idx_opportunity_state_rank ON school_opportunity_index(state_rank);

-- Version history for data changes (for auditing human reviews)
CREATE TABLE IF NOT EXISTS school_data_versions (
    version_id SERIAL PRIMARY KEY,
    school_enrichment_id INTEGER NOT NULL REFERENCES school_enriched_data(school_enrichment_id) ON DELETE CASCADE,
    
    -- Full snapshot of the record at this version
    data_snapshot JSONB,
    change_summary TEXT,
    changed_by VARCHAR(255),
    change_reason VARCHAR(50), -- agent_analysis, human_adjustment, correction, etc
    
    version_number INTEGER,
    is_current BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_version_school_id ON school_data_versions(school_enrichment_id);
CREATE INDEX IF NOT EXISTS idx_version_is_current ON school_data_versions(is_current);
