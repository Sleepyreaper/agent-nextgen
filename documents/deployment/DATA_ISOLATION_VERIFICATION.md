# DATA ISOLATION VERIFICATION CHECKLIST

## ✓ Deployment Status
- [x] Code changes committed to GitHub (commit: 9be69e2)
- [x] Deployed to Azure (nextgen-agents-web)
- [x] Deployment package accepted (status: BuildInProgress)
- [ ] Verify build completed successfully on Azure

## ✓ Pre-Deployment Fixes Applied
- [x] **src/database.py**
  - [x] Auto-migration creates is_test_data column if missing
  - [x] Auto-migration creates is_test_data index
  - [x] get_formatted_student_list includes is_test_data in SELECT
  - [x] get_formatted_student_list includes is_training_example in SELECT
  - [x] Formatted output includes both flags as booleans

- [x] **app.py /students Route (2026 Production)**
  - [x] Defensive loop through returned records
  - [x] Filters out records where is_test_data=TRUE
  - [x] Filters out records where is_training_example=TRUE
  - [x] Logs security warnings for filtered records
  - [x] Only returns records with both flags FALSE/NULL

- [x] **app.py /training Route (Training Data)**
  - [x] Defensive loop through returned records
  - [x] Filters out records where is_test_data=TRUE  
  - [x] Logs security warnings for filtered records
  - [x] Only returns records with is_training_example=TRUE

- [x] **app.py /test-data Route (Test Data)**
  - [x] Enhanced WHERE clause with AND condition on is_training_example
  - [x] Defensive validation that is_test_data=TRUE
  - [x] Defensive validation that is_training_example=FALSE
  - [x] Logs warnings for invalid records
  - [x] Only returns pure test records

## 📋 Manual Verification Tests

After deployment completes, perform these checks:

### Test 1: View 2026 Production Dashboard
```
URL: https://nextgen-agents-web.azurewebsites.net/students
Expected: Only 2026 applications (no test data, no training data)
```
- [ ] Page loads without errors
- [ ] Applications list displayed
- [ ] No test applications visible
- [ ] Count matches expected 2026 applications
- [ ] Check browser console for errors

### Test 2: View Training Data Dashboard
```
URL: https://nextgen-agents-web.azurewebsites.net/training
Expected: Only training applications (no test data)
```
- [ ] Page loads without errors
- [ ] Training applications displayed
- [ ] No test applications visible
- [ ] Count matches expected training applications

### Test 3: View Test Data Dashboard
```
URL: https://nextgen-agents-web.azurewebsites.net/test-data
Expected: Only test applications (no training, no 2026 data)
```
- [ ] Page loads without errors
- [ ] Test applications displayed
- [ ] Matches test records created

### Test 4: Create New Test Application
```
URL: https://nextgen-agents-web.azurewebsites.net/test
Action: Create a test application
```
- [ ] Test application created successfully
- [ ] Appears in /test-data view
- [ ] Does NOT appear in /students view
- [ ] Does NOT appear in /training view

### Test 5: Check Application Logs
```
Check Azure App Service Logs for security warnings
Pattern: "Filtered out test data from /students"
```
- [ ] No security warnings = good (no contamination)
- [ ] If warnings appear = investigate which records are contaminated

## 🔍 Database Verification

Run these queries to verify column setup:

### Query 1: Check is_test_data Column
```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'applications' AND column_name = 'is_test_data';
```
Expected: One row, type BOOLEAN, is_nullable=YES

### Query 2: Check is_training_example Column
```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'applications' AND column_name = 'is_training_example';
```
Expected: One row, type BOOLEAN, is_nullable=YES

### Query 3: Count Records by Type
```sql
SELECT
  SUM(CASE WHEN is_test_data = TRUE THEN 1 ELSE 0 END) as test_count,
  SUM(CASE WHEN is_training_example = TRUE THEN 1 ELSE 0 END) as training_count,
  SUM(CASE WHEN (is_test_data = FALSE OR is_test_data IS NULL) 
       AND (is_training_example = FALSE OR is_training_example IS NULL) THEN 1 ELSE 0 END) as production_2026_count
FROM applications;
```

### Query 4: Check for Data Type Anomalies
```sql
SELECT DISTINCT is_test_data, is_training_example, COUNT(*)
FROM applications
GROUP BY is_test_data, is_training_example;
```
Expected: Maximum 6 combinations (NULL/TRUE/FALSE x NULL/TRUE/FALSE)

## 📊 Expected Results

After successful deployment and verification:

| Route | Expected Data Type | Records | Notes |
|-------|-------------------|---------|-------|
| /students | 2026 Production | X records | Both flags FALSE/NULL |
| /training | Training Data | Y records | is_training_example=TRUE |
| /test-data | Test Data | Z records | is_test_data=TRUE, is_training_example=FALSE |

Where:
- X = number of 2026 applications
- Y = number of training examples
- Z = number of test records
- X + Y + Z should equal approximately total applications (assuming no overlaps)

## 🚨 If Issues Found

If security warnings appear or data isolation fails:

1. **Check Application Logs**
   - Which records are being filtered?
   - Are they marked correctly?

2. **Database Inspection**
   - Are the columns populated correctly?
   - Are there records with impossible combinations?

3. **Cleanup Script**
   - May need to run data cleanup to flag old test/training data
   - Contact engineering team for remediation

4. **Root Cause Analysis**
   - During test execution, was is_test_data set correctly?
   - Or is there legacy data from before this fix?

## ✅ Success Criteria

- [ ] /students shows ONLY 2026 applications
- [ ] /training shows ONLY training applications
- [ ] /test-data shows ONLY test applications
- [ ] No security warnings in application logs
- [ ] Database columns exist and are properly indexed
- [ ] New test applications stay isolated
- [ ] No cross-contamination between data types

## 📝 Sign-Off

Once all verification tests pass:

- [ ] User confirms data isolation is working
- [ ] No contamination between test/training/2026 data
- [ ] Application logs show no security warnings
- [ ] All routes display correct data types
- [ ] System is ready for continued use
