-- Add columns for transcript and recommendation text to Applications table
-- This allows Rapunzel and Mulan agents to have separate data to parse

ALTER TABLE Applications 
ADD COLUMN IF NOT EXISTS TranscriptText TEXT,
ADD COLUMN IF NOT EXISTS RecommendationText TEXT;

-- Add comments for documentation
COMMENT ON COLUMN Applications.TranscriptText IS 'High school transcript/grade report for Rapunzel Grade Reader agent';
COMMENT ON COLUMN Applications.RecommendationText IS 'Teacher/counselor recommendation letter for Mulan Recommendation Reader agent';
