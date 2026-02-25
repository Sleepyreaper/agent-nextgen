-- =====================================================================
-- Historical Scores Table
-- Stores human-assigned rubric scores from prior cohort years (e.g. 2024)
-- Used by Milo Data Scientist for calibration against real selection outcomes
-- =====================================================================

CREATE TABLE IF NOT EXISTS historical_scores (
    score_id SERIAL PRIMARY KEY,
    cohort_year INTEGER NOT NULL DEFAULT 2024,

    -- Student identification
    applicant_name VARCHAR(255) NOT NULL,
    applicant_name_normalized VARCHAR(255),  -- lowercase, stripped for fuzzy matching

    -- Reviewer / Status
    status VARCHAR(50),                      -- Eligible status: Accepted = met requirements (files, age, deadline). NOT who was chosen.
    was_selected BOOLEAN DEFAULT NULL,       -- Actually chosen for the program (set when 2024 apps uploaded with selection flag)
    preliminary_score VARCHAR(50),           -- High, Medium, Low
    quick_notes TEXT,
    reviewer_name VARCHAR(255),
    was_scored BOOLEAN DEFAULT FALSE,        -- Did the reviewer actually score? (Y/N)

    -- Rubric dimension scores (2024 NextGen rubric)
    academic_record NUMERIC(3,1),            -- 0-3
    stem_interest NUMERIC(3,1),              -- 0-3
    essay_video NUMERIC(3,1),                -- 0-3
    recommendation NUMERIC(3,1),             -- 0-2
    bonus NUMERIC(3,1),                      -- 0-1
    total_rating NUMERIC(4,1),               -- 0-12 (computed sum)

    -- Additional evaluation fields
    eligibility_notes TEXT,
    previous_research_experience TEXT,       -- Column N from spreadsheet
    advanced_coursework TEXT,                -- Column O from spreadsheet
    overall_rating VARCHAR(255),             -- yes/no/maybe for advancing candidate (Column P)
    column_q TEXT,                           -- Column Q (unknown header, captured as-is)

    -- Linkage to application record (populated when training upload matches)
    application_id INTEGER REFERENCES Applications(application_id) ON DELETE SET NULL,

    -- Metadata
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    import_source VARCHAR(500),              -- original filename
    row_number INTEGER,                      -- row in the source spreadsheet

    CONSTRAINT chk_academic_record CHECK (academic_record IS NULL OR (academic_record >= 0 AND academic_record <= 3)),
    CONSTRAINT chk_stem_interest CHECK (stem_interest IS NULL OR (stem_interest >= 0 AND stem_interest <= 3)),
    CONSTRAINT chk_essay_video CHECK (essay_video IS NULL OR (essay_video >= 0 AND essay_video <= 3)),
    CONSTRAINT chk_recommendation CHECK (recommendation IS NULL OR (recommendation >= 0 AND recommendation <= 2)),
    CONSTRAINT chk_bonus CHECK (bonus IS NULL OR (bonus >= 0 AND bonus <= 1))
);

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_historical_scores_year ON historical_scores(cohort_year);
CREATE INDEX IF NOT EXISTS idx_historical_scores_name ON historical_scores(applicant_name_normalized);
CREATE INDEX IF NOT EXISTS idx_historical_scores_status ON historical_scores(status);
CREATE INDEX IF NOT EXISTS idx_historical_scores_app_id ON historical_scores(application_id);
CREATE INDEX IF NOT EXISTS idx_historical_scores_total ON historical_scores(total_rating);
CREATE INDEX IF NOT EXISTS idx_historical_scores_was_scored ON historical_scores(was_scored);
CREATE INDEX IF NOT EXISTS idx_historical_scores_selected ON historical_scores(was_selected);
