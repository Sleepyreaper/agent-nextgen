-- =====================================================================
-- PostgreSQL Schema for AI-powered Student Evaluation System
-- Azure Flexible Server - Production Ready
-- =====================================================================
-- This schema defines all tables needed for the multi-agent evaluation system
-- Using snake_case for column names (PostgreSQL convention)
-- =====================================================================

-- Drop tables if they exist (for development/reset)
-- DROP TABLE IF EXISTS agent_audit_logs CASCADE;
-- DROP TABLE IF EXISTS aurora_evaluations CASCADE;
-- DROP TABLE IF EXISTS merlin_evaluations CASCADE;
-- DROP TABLE IF EXISTS mulan_recommendations CASCADE;
-- DROP TABLE IF EXISTS tiana_applications CASCADE;
-- DROP TABLE IF EXISTS ai_evaluations CASCADE;
-- DROP TABLE IF EXISTS student_school_context CASCADE;
-- DROP TABLE IF EXISTS schools CASCADE;
-- DROP TABLE IF EXISTS school_programs CASCADE;
-- DROP TABLE IF EXISTS school_socioeconomic_data CASCADE;
-- DROP TABLE IF EXISTS test_submissions CASCADE;
-- DROP TABLE IF EXISTS training_feedback CASCADE;
-- DROP TABLE IF EXISTS grade_records CASCADE;
-- DROP TABLE IF EXISTS Applications CASCADE;

-- =====================================================================
-- Core Tables
-- =====================================================================

-- Applications - Main table for student applications
CREATE TABLE IF NOT EXISTS Applications (
    application_id SERIAL PRIMARY KEY,
    applicant_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone_number VARCHAR(50),
    position VARCHAR(255),
    uploaded_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    application_text TEXT,
    original_file_name VARCHAR(500),
    file_type VARCHAR(50),
    blob_storage_path VARCHAR(1000),
    is_training_example BOOLEAN DEFAULT FALSE,
    was_selected BOOLEAN,
    status VARCHAR(50) DEFAULT 'Pending',
    created_by VARCHAR(255),
    updated_date TIMESTAMP,
    notes TEXT,
    recommendation_text TEXT,
    transcript_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_applications_is_training ON Applications(is_training_example);
CREATE INDEX IF NOT EXISTS idx_applications_status ON Applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_uploaded_date ON Applications(uploaded_date);
CREATE INDEX IF NOT EXISTS idx_applications_email ON Applications(email);

-- =====================================================================
-- Schools and Context Tables
-- =====================================================================

-- Schools - Reference data for schools
CREATE TABLE IF NOT EXISTS schools (
    school_id SERIAL PRIMARY KEY,
    school_name VARCHAR(500),
    school_district VARCHAR(255),
    state_code VARCHAR(2),
    county_name VARCHAR(100),
    is_title_i BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_schools_name ON schools(school_name);

-- School Socioeconomic Data
CREATE TABLE IF NOT EXISTS school_socioeconomic_data (
    ses_data_id SERIAL PRIMARY KEY,
    school_id INTEGER REFERENCES schools(school_id),
    median_household_income NUMERIC(12,2),
    free_lunch_percentage NUMERIC(5,2),
    school_ses_level VARCHAR(50),
    data_year INTEGER
);

-- School Programs - AP, IB, STEM, etc.
CREATE TABLE IF NOT EXISTS school_programs (
    program_id SERIAL PRIMARY KEY,
    school_id INTEGER REFERENCES schools(school_id),
    program_type VARCHAR(100),
    program_name VARCHAR(255),
    is_available BOOLEAN,
    student_enrollment INTEGER
);

-- Student School Context
CREATE TABLE IF NOT EXISTS student_school_context (
    context_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    school_id INTEGER REFERENCES schools(school_id),
    school_name VARCHAR(500),
    program_access_score NUMERIC(5,2),
    program_participation_score NUMERIC(5,2),
    relative_advantage_score NUMERIC(5,2),
    ap_courses_available INTEGER,
    ap_courses_taken INTEGER,
    ib_courses_available INTEGER,
    ib_courses_taken INTEGER,
    honors_courses_taken INTEGER,
    stem_programs_available INTEGER,
    stem_programs_accessed INTEGER,
    school_ses_level VARCHAR(50),
    median_household_income NUMERIC(12,2),
    free_lunch_pct NUMERIC(5,2),
    percentage_of_peers_using_programs NUMERIC(5,2),
    comparison_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_student_school_context_app_id ON student_school_context(application_id);
CREATE INDEX IF NOT EXISTS idx_student_school_context_school_id ON student_school_context(school_id);

-- =====================================================================
-- Grade Records
-- =====================================================================

CREATE TABLE IF NOT EXISTS grade_records (
    grade_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    grade_type VARCHAR(100),
    grade_value VARCHAR(50),
    max_value VARCHAR(50),
    subject VARCHAR(255),
    date TIMESTAMP,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_grade_records_app_id ON grade_records(application_id);

-- =====================================================================
-- AI Evaluation Tables
-- =====================================================================

-- AI Evaluations (generic agent evaluations)
CREATE TABLE IF NOT EXISTS ai_evaluations (
    evaluation_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    agent_name VARCHAR(255),
    evaluation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    overall_score NUMERIC(5,2),
    technical_skills_score NUMERIC(5,2),
    communication_score NUMERIC(5,2),
    experience_score NUMERIC(5,2),
    cultural_fit_score NUMERIC(5,2),
    strengths TEXT,
    weaknesses TEXT,
    recommendation VARCHAR(50),
    detailed_analysis TEXT,
    comparison_to_excellence TEXT,
    model_used VARCHAR(100),
    processing_time_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_ai_evaluations_app_id ON ai_evaluations(application_id);
CREATE INDEX IF NOT EXISTS idx_ai_evaluations_agent_name ON ai_evaluations(agent_name);

-- =====================================================================
-- Specialized Agent Tables
-- =====================================================================

-- Tiana Applications - Application parsing and summary
CREATE TABLE IF NOT EXISTS tiana_applications (
    tiana_application_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    agent_name VARCHAR(255) DEFAULT 'Tiana',
    essay_summary TEXT,
    recommendation_texts TEXT,
    readiness_score NUMERIC(5,2),
    confidence VARCHAR(50),
    parsed_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tiana_applications_app_id ON tiana_applications(application_id);

-- Mulan Recommendations - Recommendation letter analysis
CREATE TABLE IF NOT EXISTS mulan_recommendations (
    mulan_recommendation_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    agent_name VARCHAR(255) DEFAULT 'Mulan',
    recommender_name VARCHAR(255),
    recommender_role VARCHAR(255),
    endorsement_strength NUMERIC(5,2),
    specificity_score NUMERIC(5,2),
    summary TEXT,
    raw_text TEXT,
    parsed_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mulan_recommendations_app_id ON mulan_recommendations(application_id);

-- Merlin Evaluations - Final consolidated evaluation
CREATE TABLE IF NOT EXISTS merlin_evaluations (
    merlin_evaluation_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    agent_name VARCHAR(255) DEFAULT 'Merlin',
    overall_score NUMERIC(5,2),
    recommendation VARCHAR(100),
    rationale TEXT,
    confidence VARCHAR(50),
    parsed_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_merlin_evaluations_app_id ON merlin_evaluations(application_id);

-- Aurora Evaluations - Formatted final output
CREATE TABLE IF NOT EXISTS aurora_evaluations (
    aurora_evaluation_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    agent_name VARCHAR(255) DEFAULT 'Aurora',
    formatted_evaluation JSONB,
    merlin_score NUMERIC(5,2),
    merlin_recommendation VARCHAR(100),
    agents_completed VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_aurora_evaluations_app_id ON aurora_evaluations(application_id);
CREATE INDEX IF NOT EXISTS idx_aurora_evaluations_created_at ON aurora_evaluations(created_at);

-- =====================================================================
-- Audit and Logging
-- =====================================================================

-- Agent Audit Logs
CREATE TABLE IF NOT EXISTS agent_audit_logs (
    audit_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    agent_name VARCHAR(255),
    source_file_name VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_audit_logs_app_id ON agent_audit_logs(application_id);
CREATE INDEX IF NOT EXISTS idx_agent_audit_logs_agent_name ON agent_audit_logs(agent_name);

-- =====================================================================
-- Test and Training Data
-- =====================================================================

-- Test Submissions - Test session tracking
CREATE TABLE IF NOT EXISTS test_submissions (
    session_id VARCHAR(100) PRIMARY KEY,
    student_count INTEGER,
    application_ids JSONB,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_test_submissions_created_at ON test_submissions(created_at);
CREATE INDEX IF NOT EXISTS idx_test_submissions_status ON test_submissions(status);

-- Training Feedback
CREATE TABLE IF NOT EXISTS training_feedback (
    feedback_id SERIAL PRIMARY KEY,
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    agent_name VARCHAR(255),
    feedback_type VARCHAR(100),
    feedback_content TEXT,
    is_positive BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_feedback_app_id ON training_feedback(application_id);
CREATE INDEX IF NOT EXISTS idx_training_feedback_agent_name ON training_feedback(agent_name);

-- =====================================================================
-- Views for Common Queries
-- =====================================================================

-- View: Completed Applications with Latest Evaluations
CREATE OR REPLACE VIEW application_summary AS
SELECT 
    a.application_id,
    a.applicant_name,
    a.email,
    a.status,
    a.uploaded_date,
    a.is_training_example,
    a.was_selected,
    s.school_name,
    m.overall_score as merlin_score,
    m.recommendation as merlin_recommendation,
    au.formatted_evaluation
FROM Applications a
LEFT JOIN student_school_context ctx ON a.application_id = ctx.application_id
LEFT JOIN schools s ON ctx.school_id = s.school_id
LEFT JOIN merlin_evaluations m ON a.application_id = m.application_id
LEFT JOIN aurora_evaluations au ON a.application_id = au.application_id
WHERE a.is_training_example = FALSE
ORDER BY a.uploaded_date DESC;

-- =====================================================================
-- End of Schema Definition
-- =====================================================================
