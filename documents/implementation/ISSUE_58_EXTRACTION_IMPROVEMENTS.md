# Issue #58 — Grade Transcript Extraction Improvements

## Summary

Rapunzel (grade transcript reader) received two rounds of improvements that dramatically increased structured metric extraction rates. Tested on 30 real application PDFs from `~/Desktop/batch1/` using `scripts/diagnose_transcripts.py`.

---

## What Changed

### Round 1 — Core Extraction Upgrades (deployed as v1.0.79)

Six critical changes to `src/agents/rapunzel_grade_reader.py`:

| Change | Before | After | Why |
|--------|--------|-------|-----|
| **Model tier** | `model_tier_workhorse` (gpt-4.1-mini) | `model_tier_premium` (gpt-4.1) | Mini model produced incomplete course lists and misclassified course levels on non-standard formats |
| **Token limit** | 1,200 tokens | 4,000 tokens | Transcripts with 30+ courses were being truncated |
| **Temperature** | 1.0 | 0.0 | Deterministic extraction avoids hallucinated grades |
| **Input cap** | 12,000 chars | 20,000 chars | Many multi-page transcripts were being cut off |
| **Prompt** | Generic 8-line instruction | 4-step structured extraction (format detection → course extraction → GPA/standing → additional data) | Explicit phases reduce missed fields |
| **GPA regex** | Single greedy pattern | Multi-pattern cascade (unweighted → cumulative → general, validated 0.0-5.0) | Avoided grabbing weighted/HOPE GPAs |

Plus: `_extract_all_markdown_tables()` for standardized transcript as primary source, and `src/agents/smee_orchestrator.py` transcript fallback when Belle finds < 50 chars.

### Round 2 — Response Parsing & Metrics Block (this session)

1. **Config import bug fix**: `from src import config` → `from src.config import config`
   - `from src import config` returns the *module* object, not the Config instance
   - `config.model_tier_premium` → `AttributeError` because the module doesn't have that attribute
   - Production app was unaffected because `model=model_premium` is passed explicitly in `app.py`

2. **Markdown-aware regex patterns**: All `_parse_response` regex patterns updated to handle `**bold**` markdown formatting the model returns:
   - GPA: `r'\*{0,2}[Uu]nweighted\s+GPA\*{0,2}...'`
   - Confidence: `r'\*{0,2}Confidence\*{0,2}\s*[:\s]+(High|Medium|Low)'`
   - Transcript Quality: added fallback for `overall/assessment/quality` labels
   - Course Rigor Index: handles `3/5` suffix format
   - **New**: Academic Record Score (0-3) extraction

3. **METRICS BLOCK prompt requirement**: Added explicit instruction at the end of the system prompt requiring a structured metrics block:
   ```
   ## METRICS
   Unweighted GPA: [value or N/A]
   Weighted GPA: [value or N/A]
   Course Rigor Index: [1-5]
   Transcript Quality: [Exceptional/Strong/Solid/Average/Below Average]
   Confidence: [High/Medium/Low]
   Academic Record Score: [0-3]
   Detected Format: [format description]
   ```

---

## Batch Test Results (30 files, no OCR)

### Metric Extraction Rates

| Metric | Batch 1 (pre-fix) | Batch 2 (post-fix) | Batch 3 (post-fix) | Post-fix Total |
|--------|-------------------|---------------------|---------------------|----------------|
| **GPA** | 2/10 (20%) | 7/10 (70%) | 8/10 (80%) | **15/20 (75%)** |
| **Course Rigor Index** | 0/10 (0%) | 10/10 (100%) | 9/10 (90%) | **19/20 (95%)** |
| **Transcript Quality** | 0/10 (0%) | 10/10 (100%) | 9/10 (90%) | **19/20 (95%)** |
| **Confidence** | 0/10 (0%) | 10/10 (100%) | 9/10 (90%) | **19/20 (95%)** |

### Course Extraction

All 30 files extracted courses. Distribution:

- **Median**: 26 courses
- **Mean**: 27 courses
- **Range**: 1 to 58 courses
- **≥ 15 courses**: 27/30 (90%)
- **< 5 courses**: 2/30 — both legitimate edge cases (see below)

### Edge Cases Identified

| File | Courses | Issue | Root Cause |
|------|---------|-------|------------|
| **Aguilar Lopez, Jennifer** | 3 | No transcript in PDF | Application has no formal transcript — only essay mentions of coursework |
| **Annan, Naa Besa** | 1 | Scanned image transcript | Transcript pages are images, no extractable text without OCR |
| **Allen, Neil** | 8 | No transcript section found (0 chars) | Belle couldn't classify transcript pages; fell back to full doc text |
| **Ablante, Brooke** | 11 | Partial image pages | Pages 7-8 are images (detected by images=1 flag); only partial text extracted |

### GPA Misses (5/20 after fix)

The 5 remaining GPA=None cases fall into two categories:
- **Model outputs GPA in non-standard format** (e.g., `91.00/100` instead of `3.x`) — 2 files
- **Model outputs weighted GPA but labels it ambiguously** — 3 files (GPA regex is intentionally conservative to avoid grabbing HOPE/weighted GPAs)

---

## Files Modified

| File | Change Type | Description |
|------|-------------|-------------|
| `src/agents/rapunzel_grade_reader.py` | Modified (56 ins, 15 del) | Config import fix, markdown-aware regex, metrics block prompt, academic_record_score |
| `scripts/diagnose_transcripts.py` | New file | Batch PDF diagnostic tool with Belle → Rapunzel pipeline |
| `scripts/test_rapunzel_format.py` | New file (can be deleted) | Quick format test script |

---

## How to Prove the Improvements

### Option 1: Before/After Comparison (recommended, ~30 min)

1. **Rerun batch 1 with the old code** (already done — `batch1_report_01.txt` serves as the "before"):
   - Batch 1 used the pre-fix regex (all metrics = None)
   
2. **Rerun batch 1 files with the new code** to get a true before/after on the same files:
   ```bash
   .venv/bin/python3 scripts/diagnose_transcripts.py ~/Desktop/batch1/ --no-ocr -n 10 -o ~/Desktop/batch1_report_01_v2.txt
   ```

3. **Compare**: The same 10 files, same PDFs, but the v2 report should show GPA/rigor/quality/confidence populated where v1 showed all None.

### Option 2: Production A/B Test

1. Deploy the changes to the staging slot
2. Reprocess a cohort of training students through the staging app
3. Compare Rapunzel's output (structured metrics + course counts) between production and staging
4. Key metrics to compare: GPA capture rate, course rigor index populated, transcript quality populated

### Option 3: Manual Spot-Check

Open 5 random PDFs from the batch and manually verify:
- Does the extracted GPA match the actual transcript?
- Are course levels (AP/Honors/Standard) correctly classified?
- Is the course count reasonable for the number of transcript pages?

Good candidates for spot-checking (from batch 2-3):
- **Alavez, Jessica** (46 courses, GPA 3.37) — high course count, verify completeness
- **Barton, Kino** (58 courses, GPA 1.94, "Below Average") — unusual profile, verify accuracy
- **Benitez Parra, Cristian** (40 courses, GPA 3.98, "Exceptional") — verify AP classification
- **Allen, Alisha** (20 courses, GPA 3.4, "Solid") — mid-range, good baseline

### Option 4: Automated Regression Test

If you want a repeatable test:
1. Create a `testing/test_rapunzel_extraction.py` that embeds 5 known transcript texts
2. Assert that `parse_grades()` returns expected GPA, rigor index, and course count
3. Add to CI pipeline to catch future regressions

---

## Remaining Opportunities

1. **Enable OCR** for scanned transcripts: Would recover Annan, Allen, Ablante cases (~10% of files). Requires vision model access (gpt-4o) which costs more per page.
2. **GPA regex expansion**: Handle `91.00/100` format and weighted-only GPAs as fallback.
3. **Re-disable public network access** on `<your-foundry>` when done with local testing:
   ```bash
   az resource update --ids /subscriptions/<your-subscription-id>/resourceGroups/<your-resource-group>/providers/Microsoft.CognitiveServices/accounts/<your-foundry> --set properties.publicNetworkAccess=Disabled
   ```

---

## Report Files

All diagnostic reports are on the Desktop:
- `~/Desktop/batch1_report_01.txt` — Files 1-10 (pre-regex-fix baseline)
- `~/Desktop/batch1_report_02.txt` — Files 11-20 (post-fix)
- `~/Desktop/batch1_report_03.txt` — Files 21-30 (post-fix)
