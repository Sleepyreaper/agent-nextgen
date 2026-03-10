# 🔒 Security Sweep — March 10, 2026

**Reviewer:** Sideshow Bob (automated cron)  
**Scope:** Full codebase scan — SQL injection, secrets, auth, dependencies, container

---

## 🔴 Critical

### 1. SQL Injection in `scripts/init/setup_db.py` (lines 44, 47)

Password is interpolated directly into SQL via f-string:
```python
cur.execute(f"CREATE USER {APP_USER} WITH PASSWORD '{pwd}'")
cur.execute(f"ALTER USER {APP_USER} WITH PASSWORD '{pwd}'")
```
Both `APP_USER` and `pwd` are string-formatted into DDL. A malicious `POSTGRES_APP_USER` env var could inject arbitrary SQL. The password contains special characters (`!@#$%^&*`) which could break quoting.

**Fix:** Use parameterized queries for the password and `psycopg.sql.Identifier` for the username:
```python
from psycopg import sql
cur.execute(sql.SQL("CREATE USER {} WITH PASSWORD %s").format(sql.Identifier(APP_USER)), (pwd,))
```

### 2. Unparameterized DDL in `_run_migrations()` (database.py, lines ~1103, 1165, 3593)

`col_name` and `col_type` from hardcoded dicts are f-string-interpolated into `ALTER TABLE` statements. While these values are currently developer-controlled, any future dynamic source would be exploitable. Lines ~794 and ~821 correctly use `psycopg.sql` — the rest should follow suit.

---

## 🟠 High

### 3. `innerHTML` XSS vectors in templates

Multiple templates set `innerHTML` from server responses without sanitization:
- `web/templates/upload.html:126-134` — static strings (low risk)
- `web/templates/school_enrichment_detail.html:1013` — `resultDiv.innerHTML = html` where `html` comes from a fetch response. If the API ever returns user-controlled content, this is XSS.
- `web/templates/data_management.html:303` — interpolates `data.count` into innerHTML.

**Fix:** Use `textContent` for data values; sanitize or use DOM APIs for structured HTML.

### 4. Overly broad `DELETE` in `clear_test_data()` (database.py ~2930)

```python
delete_query = f"DELETE FROM {table} WHERE {column} IN ({placeholders})"
```
`table` and `column` come from a hardcoded list, but the pattern is fragile. An accidental edit could delete from the wrong table. Use `psycopg.sql.Identifier`.

### 5. `f"DELETE FROM {table}"` with no WHERE clause (database.py ~3685)

This truncates entire tables. Should use `TRUNCATE` with explicit safeguards or at minimum log/confirm before execution.

---

## 🟡 Medium

### 6. No CORS configuration

No `flask-cors` or manual `Access-Control-Allow-Origin` headers found. If this API is consumed by any other origin (mobile app, separate frontend), CORS will silently block requests. If it's purely same-origin, this is fine — but worth documenting the intent.

### 7. `startup.sh` runs `apt-get install` at runtime

Line in startup.sh: `apt-get update -qq && apt-get install -y -qq ffmpeg`  
This downloads packages at container start, which:
- Slows cold starts
- Could pull compromised packages if the mirror is poisoned
- Breaks reproducibility

**Fix:** Install ffmpeg in the Dockerfile build stage.

### 8. Dependency pinning gaps in `requirements.txt`

Several packages use `>=` without upper bounds (`pypdf>=4.0`, `opencv-python-headless>=4.8.0`, `azure-ai-evaluation>=1.0.0`, `openpyxl>=3.1.0`, `pytest>=8.0`). A `pip install` could pull a future breaking or vulnerable version.

**Fix:** Pin exact versions or use compatible release (`~=`) operators.

### 9. Session secret fallback in development

```python
app.secret_key = os.urandom(32).hex()  # random per-start in dev only
```
This means dev sessions break on every restart and there's no warning if someone accidentally runs "dev mode" in a staging environment. Consider requiring an explicit secret in all non-test environments.

---

## 🟢 Low / Informational

### 10. Cookie settings look good ✅
`SESSION_COOKIE_SECURE=True`, `HTTPONLY=True`, `SAMESITE=Lax` — properly configured.

### 11. CSRF protection enabled ✅
Flask-WTF CSRF is initialized globally.

### 12. Rate limiting present ✅
Flask-Limiter is configured.

### 13. Dockerfile runs as non-root ✅
Container creates and switches to `appuser`.

### 14. Database connections use SSL ✅
`sslmode=require` enforced in connection params.

### 15. Production secret key enforced ✅
App raises `RuntimeError` if `FLASK_SECRET_KEY` missing in production.

---

## Summary

| Severity | Count | Action Required |
|----------|-------|-----------------|
| 🔴 Critical | 2 | SQL injection — fix immediately |
| 🟠 High | 3 | XSS vectors, unsafe DELETE patterns |
| 🟡 Medium | 4 | Deps, CORS, startup, sessions |
| 🟢 Good | 6 | No action needed |

**Recommended priority:** Fix #1 (setup_db.py SQL injection) first — it's the only one exploitable from environment variables today. Then address #2 and #3 in a follow-up.
