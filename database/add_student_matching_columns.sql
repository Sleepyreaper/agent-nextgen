-- Migration: Add student matching columns to Applications table
-- Purpose: Enable matching students by first_name, last_name, high_school, state_code
-- This prevents creating duplicate records for the same student

ALTER TABLE IF EXISTS Applications
ADD COLUMN IF NOT EXISTS first_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS last_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS high_school VARCHAR(500),
ADD COLUMN IF NOT EXISTS state_code VARCHAR(10);

-- Create index for faster matching queries
CREATE INDEX IF NOT EXISTS idx_student_match 
ON Applications(
    LOWER(COALESCE(first_name, '')),
    LOWER(COALESCE(last_name, '')),
    LOWER(COALESCE(high_school, '')),
    UPPER(COALESCE(state_code, ''))
);

-- Create index on state_code for school enrichment lookups
CREATE INDEX IF NOT EXISTS idx_state_code ON Applications(state_code);
