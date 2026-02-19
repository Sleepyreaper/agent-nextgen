# COMPREHENSIVE DATABASE MIGRATIONS FOR AGENTS

## Problem Statement
Rapunzel and other agents were failing to persist data to the database because required columns were missing from their result tables. Example error:

```
⚠️  Rapunzel Grade Reader: Could not save to database: column "contextual_rigor_index" of relation "rapunzel_grades" does not exist
```

This happened because:
1. The schema_postgresql.sql file defined all required columns
2. But the actual Azure PostgreSQL database was created before these schemas were added
3. New columns weren't being created at runtime automatically for agent tables

## Solution: One-Time Comprehensive Migrations

Instead of handling missing columns at runtime, we now run a comprehensive migration **once at startup** that ensures all agent tables have their required fields.

### Migrations Implemented

#### 1. **Rapunzel Grades Table** (`rapunzel_grades`)
**Missing Columns Added:**
- `contextual_rigor_index NUMERIC(5,2)` - Academic rigor score weighted by school context
- `school_context_used BOOLEAN DEFAULT FALSE` - Flag indicating if school data was used in rigor calculation

**Impact:** Rapunzel can now save all grade analysis results including contextual rigor scoring

#### 2. **Tiana Applications Table** (`tiana_applications`)
**Verified/Added:**
- `parsed_json JSONB` - Full NLP output from essay analysis

**Impact:** Tiana essay analysis results are fully persisted

#### 3. **Mulan Recommendations Table** (`mulan_recommendations`)
**Verified/Added:**
- `parsed_json JSONB` - AI parsing of recommendation letter
- `raw_text TEXT` - Original recommendation text extracted from PDF

**Impact:** Mulan recommendation analysis is fully tracked

#### 4. **Merlin Evaluations Table** (`merlin_evaluations`)
**Verified/Added:**
- `parsed_json JSONB` - Complete evaluation reasoning and scores

**Impact:** Merlin final evaluations are properly persisted

#### 5. **Aurora Evaluations Table** (`aurora_evaluations`)
**Verified/Added:**
- `parsed_json JSONB` - Formatted output structure
- `agents_completed VARCHAR(500)` - List of agents that completed for this application

**Impact:** Aurora final formatting and agent tracking works correctly

#### 6. **Student School Context Table** (`student_school_context`)
**Verified/Added:**
- `agent_name VARCHAR(255)` - Track which agent provided the enrichment
- `parsed_json JSONB` - Full AI analysis from Moana/Naveen
- `updated_at TIMESTAMP` - Track when context was last updated

**Impact:** Moana school enrichment results are properly versioned and trackable

### Implementation Details

**File Modified:** `src/database.py` - `_run_migrations()` method

**Execution Timing:**
- Runs once per database connection during application startup
- Only adds missing columns (idempotent - won't fail if columns exist)
- Creates indexes for performance

**Database Checks:**
```python
# For each table and column:
# 1. Query information_schema.columns
# 2. Check if column_name exists
# 3. If missing: ALTER TABLE ADD COLUMN
# 4. If successful: log ✓ message
# 5. On error: log warning but continue (non-blocking)
```

### Affected Agents & Their Output

| Agent | Table | Required Fields | Status |
|-------|-------|-----------------|--------|
| **Rapunzel** | rapunzel_grades | contextual_rigor_index, school_context_used | ✅ FIXED |
| **Tiana** | tiana_applications | essay_summary, recommendation_texts, readiness_score, confidence, parsed_json | ✅ OK |
| **Mulan** | mulan_recommendations | recommender_name, endorsement_strength, specificity_score, summary, raw_text, parsed_json | ✅ FIXED |
| **Merlin** | merlin_evaluations | overall_score, recommendation, rationale, confidence, parsed_json | ✅ OK |
| **Aurora** | aurora_evaluations | formatted_evaluation, merlin_score, merlin_recommendation, agents_completed, parsed_json | ✅ FIXED |
| **Moana** | student_school_context | school_name, program scores, ap courses, resource access, agent_name, parsed_json, updated_at | ✅ FIXED |

### Deployment Status

- ✅ Code committed: `abe00fd` "CRITICAL: Comprehensive agent table migrations for all required fields"
- ✅ Pushed to GitHub  
- ✅ Deployed to Azure: Successful (Build: 0s, Start: 31s)
- ✅ Status: RuntimeSuccessful

### Verification Instructions

To verify the migrations ran successfully:

**Option 1: Check Application Logs**
```
Look for: "⭐ COMPREHENSIVE DATABASE MIGRATIONS COMPLETED"
```

**Option 2: Database Query**
```sql
-- Verify Rapunzel columns exist
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'rapunzel_grades' 
AND column_name IN ('contextual_rigor_index', 'school_context_used');

-- Should return 2 rows if migrations successful
```

**Option 3: Run an Application**
```
1. Upload a student application
2. Check grade transcript → should not see "column does not exist" error
3. Verify results appear in database with all fields populated
```

### Key Improvements

1. **Eliminates Runtime Errors** - All required columns exist before agents start processing
2. **One-Time Execution** - Migrations run once at startup, not on every request
3. **Non-Blocking** - If migrations fail, app continues (column checking prevents errors)
4. **Comprehensive** - All 6 agent types covered in a single migration batch
5. **Index Performance** - Indexes created on key query columns (e.g., contextual_rigor_index)

### Next Steps If Issues Occur

If an agent still reports "column does not exist":

1. Check application logs for full error message
2. Query the table in Azure PostgreSQL
3. Manually add the column if migration was missed:
   ```sql
   ALTER TABLE [table_name] ADD COLUMN [column_name] [type];
   ```
4. Restart the application to trigger migrations again

### Rollback Notes

The migrations are additive-only (adding columns, not removing or modifying). They cannot break existing functionality.

To verify previous migrations are still in place:
- first_name, last_name, high_school, state_code columns on applications table
- is_test_data column and index on applications table
- All student matching indexes

All of these are preserved and continue to work alongside new agent table columns.
