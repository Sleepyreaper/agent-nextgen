# Data Persistence & Test Management Implementation

## Overview
Fixed the data persistence issue where test students were being created but not retrievable after navigation. Now all test data persists in the database and can be viewed/cleared from the test page.

## Changes Made

### 1. **New API Endpoints** (`app.py`)

#### GET `/api/test-data/list`
- Returns all test data currently stored in the database
- Pulls from TestSubmissions table to identify test applications
- Returns student name, email, status, upload date, and Merlin score

#### POST `/api/test-data/clear`
- Deletes all test data created during test sessions
- Uses TestSubmissions table to safely identify test applications
- Preserves historical training data (real examples)
- Cleans up all related tables (TianaApplications, MerlinEvaluations, etc.)

### 2. **Updated Test Page** (`web/templates/test.html`)

#### New Features:
- **🗑️ Clear Test Data Button**: Removes all synthetic test students
- **Persistent Data Loading**: Automatically loads and displays existing test data when page loads
- **Data Refresh**: Shows count of loaded test students from database

#### New JavaScript Functions:
```javascript
clearTestData()             // Clear all test students with confirmation
loadPersistentTestData()    // Load and display test data from database
```

Auto-runs on page load via `DOMContentLoaded` event

### 3. **Data Flow Architecture**

```
Test Submission
    ↓
Create Applications (marked with IsTrainingExample=TRUE)
    ↓
Save TestSubmissions record (tracks session + application IDs)
    ↓
Run Agent Pipeline (Smee orchestrates agents)
    ↓
Save Evaluation Results
    ↓
Database Persistence (survives navigation)

When visiting /test page:
    1. Check TestSubmissions table
    2. Load all test application IDs
    3. Fetch student details and display in table
    4. Show persistent test data from last session(s)
```

## Key Data Persistence Features

### Test Data vs Training Data
- **Test Data**: Synthetic students created during testing, tracked in TestSubmissions table
- **Training Data**: Real historical examples, uploaded separately with WasSelected flag
- **Safety**: Clear Test Data button only deletes test submissions, not training data

### Database Tables Used:
1. **Applications** - Student application records
2. **TestSubmissions** - Tracks test session IDs and their application IDs
3. **MerlinEvaluations** - Agent evaluation results
4. **AuroraEvaluations** - Formatted evaluations
5. Supporting agent tables (Tiana, Mulan, etc.)

## How to Use

### View Persistent Test Data
1. Go to `/test` page
2. Page automatically loads and displays any test students in database
3. View summary/results by clicking application links

### Create New Test Data
1. Click one of the test creation buttons:
   - 🚀 Random Students (3 random)
   - ⚡ Preset Students (Alice, Brian, Carol)
   - ⚡ Single Student (Alice only)
2. Watch real-time agent processing
3. Data automatically persists to database
4. Close tab/navigate away - data remains!

### Clear & Reset Test Data
1. Click 🗑️ Clear Test Data button
2. Confirm deletion (cannot be undone)
3. All synthetic test students deleted
4. Table clears, ready for fresh testing
5. Historical training data preserved

## Technical Details

### TestSubmissions Table Schema
```sql
CREATE TABLE TestSubmissions (
    SessionID UUID PRIMARY KEY,
    StudentCount INT,
    ApplicationIDs JSON,      -- Stores array of application IDs created in this session
    Status VARCHAR(50),
    CreatedAt TIMESTAMP
)
```

### Safe Deletion Logic
```
When clearing test data:
1. Query all TestSubmissions records
2. Extract ApplicationIDs from each (stored as JSON)
3. For each application:
   - Delete from all evaluation tables
   - Delete from agent result tables
   - Delete main Applications record
4. Delete TestSubmissions records
5. Result: Clean database, ready for fresh tests
```

## Benefits

✅ **Data Persistence**: Test students survive page navigation  
✅ **Easy Testing**: Create test data once, view repeatedly  
✅ **Clean Reset**: Clear test data for fresh test runs  
✅ **Safe Deletion**: Preserves historical training data  
✅ **Session Tracking**: Know which students belong to which test  
✅ **Real-time Updates**: SSE streaming during agent processing  

## Testing Checklist

- [ ] Start `/test` page - loads existing test data
- [ ] Create random students - displayed in table
- [ ] Click student links - view full evaluation
- [ ] Navigate away and return - data persists
- [ ] Click "Clear Test Data" - all test students removed
- [ ] Verify training page unaffected
- [ ] Create new test data - fresh session works

## Files Modified

1. **app.py**
   - Added `/api/test-data/list` endpoint
   - Added `/api/test-data/clear` endpoint (improved version)

2. **web/templates/test.html**
   - Added Clear Test Data button to UI
   - Added `clearTestData()` JavaScript function
   - Added `loadPersistentTestData()` JavaScript function
   - Added auto-load on page load

## Database Queries

### Get Test Data:
```sql
SELECT * FROM TestSubmissions ORDER BY CreatedAt DESC LIMIT 50
-- Then extract ApplicationIDs from JSON and fetch student details
```

### Clear Test Data:
```sql
DELETE FROM TestSubmissions
DELETE FROM Applications WHERE ApplicationID IN (selected test IDs)
-- Also delete from all related tables
```

## Notes

- Test data is identified via TestSubmissions table, not just IsTrainingExample flag
- This prevents accidental deletion of actual training/historical data
- Test submissions are timestamped for tracking
- Application IDs stored as JSON in TestSubmissions for flexible querying
