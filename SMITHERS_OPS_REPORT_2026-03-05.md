# 👔 SMITHERS' INFRASTRUCTURE REPORT
**Date:** 2026-03-05

*"Good morning, sir. Here's what happened overnight."*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 💰 COST & SPEND

| Item | Status | Notes |
|------|--------|-------|
| **App Service SKU** | ⚠️ P0v3 (~$74/mo) | Competitive pricing, but verify VNet/auto-scale are actually used. If not, Standard S2 is comparable (#56) |
| **Log Analytics retention** | 🔴 7 days | Increasing to 30 days is **free** — Azure includes 31-day retention in ingestion cost. Currently paying same but keeping less data (#55) |
| **Model tier architecture** | ✅ Well-optimized | 4-tier system (Premium→Merlin→Workhorse→Lightweight) is sound. GPT-5-mini reserved only for Merlin final evaluator, GPT-4.1-mini for bulk work, Nano for classification |
| **AI token waste** | ✅ No obvious waste | Timeout at 120s is reasonable. No runaway retry loops found |
| **Storage** | ✅ Properly containerized | Staging/prod isolation via prefix. Azure AD auth (no shared keys) |
| **OpenAI SKU** | ✅ S0 (pay-as-you-go) | Appropriate for current usage patterns |

**Estimated quick savings:** ~$0/mo (Log Analytics retention increase is free but improves observability)

## 🏥 HEALTH STATUS

| Check | Status | Details |
|-------|--------|---------|
| **asyncio.run() blocking** | 🔴 Critical | **13 calls** to `asyncio.run()` inside sync Flask handlers. Creates/destroys event loops per request. With 2×4=8 thread slots, slow AI calls can starve all threads (#52) |
| **DB connection pooling** | 🟡 Known (#24) | Single connection reused, no pool. Adequate at low concurrency but will fail under load |
| **DB table growth** | 🟡 Known (#29) | No retention/archival. Telemetry + evaluation tables will grow unbounded |
| **Error handling** | ✅ Solid | Consistent try/except with logging across agents. Graceful agent import failures at startup |
| **Memory leaks** | ✅ No obvious issues | No unbounded caches or growing lists found |
| **Session security** | ✅ Hardened | Secure + HttpOnly + SameSite=Lax cookies. CSRF protection enabled |

## 📊 RESOURCE & CAPACITY

| Resource | Status | Notes |
|----------|--------|-------|
| **app.py** | 🔴 Known (#23) | 8,745 lines / 381KB. Growing each sweep. Critical maintainability risk |
| **Database schemas** | ✅ Well-structured | 7 schema files, 1,509 total lines. Separate migration scripts |
| **Container image** | ⚠️ Minor bloat | `database/` folder (1,509 lines SQL) ships in container unnecessarily (#53) |
| **File uploads** | ✅ 16MB limit enforced | `MAX_CONTENT_LENGTH` set. Nginx bumped to 100MB for chunked video |
| **Gunicorn config** | ✅ Clean | Environment-variable driven, single source of truth |

## 🔧 CI/CD & REPO

| Check | Status | Notes |
|-------|--------|-------|
| **GitHub Actions** | ✅ Efficient | pip caching enabled, two-environment (staging/prod) split |
| **Branch hygiene** | 🟡 Accumulating | 8 unmerged sweep branches piling up. No auto-cleanup (#54) |
| **Open PRs** | ⚠️ 4 Draft PRs | #50 (Smithers 03-04), #43 (Bob 03-04), #35 (Willie 03-04), #51 (Willie 03-05). Yesterday's PRs should be reviewed or closed |
| **.gitignore** | ✅ Comprehensive | Covers env files, PII, IDE, archives |
| **.dockerignore** | ⚠️ Missing `database/` | Schema files ship in container unnecessarily (#53) |
| **requirements.txt** | ✅ Clean | All packages appear used. Versions pinned. OpenTelemetry version note present |
| **Large files** | ✅ None | No binaries or data files in repo (beyond app.py itself) |

## 🧹 POST-SWEEP CHECK

### Willie's Sweep (willie/sweep-2025-03-05)
- **Status:** ✅ Changes look sane
- **Scope:** 7 files changed, 250 insertions, 21 deletions
- **Changes:** Video upload chunk size increase, telemetry dashboard enhancements, school fuzzy matching improvements, Azure routing audit docs, feedback display fixes
- **Risk:** Low — mostly UI and data pipeline improvements
- **Note:** Branch name has wrong year (`2025-03-05` instead of `2026-03-05`) — cosmetic issue

### Bob's Sweep (bob/security-sweep-2026-03-05)
- **Status:** ✅ Clean — report only
- **Scope:** 1 file changed (security sweep markdown report), 120 insertions
- **Risk:** Zero — no code changes, documentation only
- **Breaking changes:** None

### Main Branch
- **Status:** ✅ Clean at v1.0.73
- **Latest:** Telemetry persistence to DB for dashboard

## ⚠️ ACTION ITEMS (by urgency)

1. 🔴 **asyncio.run() thread starvation** (#52) — 13 blocking calls in Flask handlers. Increase `GUNICORN_THREADS` to 8 as immediate mitigation, then refactor to shared event loop
2. 🟡 **Log Analytics free retention boost** (#55) — Change `retentionInDays` from 7 to 30. Literally free. One line change
3. 🟡 **Review/close yesterday's Draft PRs** — #50, #43, #35 are from March 4th, getting stale
4. 🟡 **Branch cleanup automation** (#54) — Sweep branches accumulating daily

## 💡 OPTIMIZATION SUGGESTIONS

1. **Free win:** Bump Log Analytics retention to 30 days (same cost, better observability)
2. **Quick win:** Add `database/` to `.dockerignore` — smaller container image
3. **Medium effort:** Implement branch auto-cleanup GHA workflow for `willie/*`, `bob/*`, `smithers/*` branches older than 7 days
4. **Larger effort:** Refactor `asyncio.run()` calls to use a shared background event loop — eliminates thread starvation risk
5. **Ongoing:** The app.py monolith (#23) grows ~100+ lines per sweep. Each Willie sweep adds features inline. Consider blocking PRs that add to app.py without a decomposition plan

## 📋 ISSUES CREATED THIS SWEEP

| # | Title | Priority |
|---|-------|----------|
| #52 | 🏥 HEALTH: 13x asyncio.run() calls blocking Flask threads | High |
| #53 | 🔧 OPS: .dockerignore missing database/ exclusion | Low |
| #54 | 🔧 OPS: Stale sweep branches accumulating | Medium |
| #55 | 💰 COST: Log Analytics 7-day retention (30 days is free) | Medium |
| #56 | 💰 COST: App Service P0v3 — verify premium features in use | Low |

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*"Five new issues filed, sir. The asyncio blocking situation is the one that keeps me up at night — well, if I slept. Everything else is running smoothly. The overnight sweeps from Willie and Bob both look clean. Will that be all?"*

— Smithers, Infrastructure & Ops
