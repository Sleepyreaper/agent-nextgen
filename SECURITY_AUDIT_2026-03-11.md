# 🔒 Security Audit — March 11, 2026

**Auditor:** Sideshow Bob (automated sweep)
**Repo:** scholarship application processing platform
**Scope:** Python backend (`src/`), config, Dockerfile, dependencies

---

## 🔴 Critical Findings

### 1. SQL Injection via Dynamic Column/Table Names in `database.py`

The `update_application()` method accepts **arbitrary field names** from callers and interpolates them directly into ALTER TABLE and UPDATE statements without parameterization:

```python
# Line ~3010: user-supplied key becomes a column name via f-string
alter_sql = f'ALTER TABLE {applications_table} ADD COLUMN "{col_name}" TEXT'
```

If any caller passes unsanitized user input as a field key, this is a direct SQL injection vector. The `col_name` value is only loosely validated through `get_applications_column()` which falls back to the raw key.

**Similar patterns:**
- `csv_school_importer.py:727` — dynamic SET clause construction
- `school_workflow.py:390` — same pattern
- `database.py:2930` — dynamic DELETE with f-string table/column names

**Mitigation:** All table/column identifiers should use `psycopg.sql.Identifier()` (already used in some migration code but not consistently). Add an allowlist of valid column names before interpolation.

### 2. `update_application()` Auto-Creates Columns From Arbitrary Input

Any caller can pass arbitrary `**fields` and the method will **create new database columns** on the fly. This is a schema manipulation risk — a bug or malicious input upstream could pollute the DB schema with junk columns or exfiltrate data via crafted column names.

**Recommendation:** Remove auto-column-creation or restrict it to an explicit allowlist. Schema changes should not be driven by runtime input.

---

## 🟠 High Findings

### 3. `_run_migrations()` Uses f-String SQL for ALTER TABLE (Lines 1103, 1165, 3593)

Migration code constructs ALTER TABLE statements with `f"ALTER TABLE ... ADD COLUMN {col_name} {col_type}"`. While the values come from hardcoded dicts (lower risk), the pattern is fragile — if anyone adds a computed value to those dicts, it becomes injectable. Some paths already use `psycopg.sql.Identifier()` properly; the rest should follow suit.

### 4. No CORS Configuration Detected

No CORS headers or Flask-CORS usage found. If this serves a web frontend (implied by Flask references and UI mentions), either CORS is handled by a reverse proxy (acceptable) or the API is wide open. Verify.

### 5. Pinned but Outdated Dependencies (`requirements.txt`)

Dependencies should be checked against known CVEs. Key packages to audit:
- `psycopg` / `psycopg-pool`
- `azure-*` SDKs
- `flask` (if used as web server)

**Recommendation:** Run `pip-audit` or `safety check` against `requirements.txt`.

---

## 🟡 Medium Findings

### 6. `subprocess.run()` in `mirabel_video_analyzer.py` — Low Risk

Line 368 calls `ffmpeg` via `subprocess.run()` with a list (not `shell=True`), which is safe. The `video_path` comes from uploaded files. Verify that filenames are sanitized before being passed as arguments (path traversal risk).

### 7. SQLite Fallback Silently Degrades Security

`database.py` falls back to an in-memory SQLite database when `psycopg` is unavailable. This means:
- No data persistence
- No SSL enforcement
- Different SQL dialect (could mask bugs)

This should either fail hard or be explicitly flagged as dev-only.

### 8. Connection String Logged on Error

Exception messages from `psycopg.connect()` may contain connection strings with embedded credentials. These get passed to `ConnectionError` and could surface in logs/tracebacks.

### 9. `.env` Files Properly Gitignored ✅

`.env`, `.env.local`, `.env.production`, `.env.staging` are all in `.gitignore`. `.env.example` contains only placeholder values. Good.

### 10. `signal.SIGALRM` in Config Init

`config.py` uses `signal.alarm()` for Key Vault timeouts. This only works on Unix and will crash on Windows. Also, `SIGALRM` interferes with other alarm-based code in the process.

---

## 🟢 Positive Observations

- Parameterized queries (`%s`) used correctly for all data values in most methods
- `psycopg.sql.Identifier()` used in several migration paths (rapunzel, historical_scores)
- Secrets loaded from Azure Key Vault in production (not hardcoded)
- SSL required for PostgreSQL connections (`sslmode=require`)
- Statement timeout set (5000ms) to prevent long-running queries
- Connection pooling with reasonable limits (max=10)
- File content hashing for duplicate detection
- Audit logging for agent interactions

---

## Recommendations Summary

| Priority | Action |
|----------|--------|
| 🔴 P0 | Sanitize all dynamic column/table names with `sql.Identifier()` or strict allowlists |
| 🔴 P0 | Remove or restrict auto-column-creation in `update_application()` |
| 🟠 P1 | Run `pip-audit` on dependencies |
| 🟠 P1 | Verify CORS policy (reverse proxy or explicit config) |
| 🟡 P2 | Sanitize uploaded filenames before passing to subprocess |
| 🟡 P2 | Make SQLite fallback explicit opt-in or remove it |
| 🟡 P2 | Scrub credentials from error messages |
