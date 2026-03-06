# Front Door Premium — Upload Optimization (Issue #12)

**Date:** 2026-03-06

## Problem
Video uploads (200MB+) were extremely slow because chunks were 100 KB each,
resulting in 2,000+ HTTP round-trips through Front Door for a single file.

## Changes Made

### 1. Increased Chunk Size: 100 KB → 4 MB
- **Before:** 100 KB chunks → 2,000 chunks for 200MB file
- **After:** 4 MB chunks → 50 chunks for 200MB file (40× fewer round-trips)
- Files: `web/static/js/video-upload.js`, `web/templates/test.html`

### 2. Increased Parallel Uploads: 3 → 6
- More concurrent uploads saturate the connection better
- Azure Blob Storage handles parallel block staging natively

### 3. Expected Performance
| File Size | Before (100KB × 3) | After (4MB × 6) | Improvement |
|-----------|--------------------|--------------------|-------------|
| 200 MB | ~2,000 requests | ~50 requests | ~40× fewer |
| 500 MB | ~5,000 requests | ~125 requests | ~40× fewer |

## Required Azure Configuration

### Front Door Premium WAF Policy
The WAF body inspection limit must accommodate 4 MB chunks. Options:

**Option A: Exclude upload route from body inspection (recommended)**
```
az network front-door waf-policy managed-rule-set rule override add \
  --policy-name <WAF_POLICY> \
  --resource-group <RG> \
  --type Microsoft_DefaultRuleSet \
  --rule-group-id REQUEST-920-PROTOCOL-ENFORCEMENT \
  --rule-id 920341 \
  --action Allow
```

Or add a custom exclusion for the upload path:
- Match variable: RequestUri
- Operator: Contains  
- Selector: `/api/file/upload-chunk`

**Option B: Increase request body inspection limit**
Front Door Premium supports up to 128 MB body inspection limit:
```
az network front-door waf-policy update \
  --name <WAF_POLICY> \
  --resource-group <RG> \
  --request-body-check Enabled \
  --request-body-inspect-limit-in-kb 8192
```

### App Service
Ensure the App Service `maxRequestBodySize` allows 4+ MB:
- This is typically not an issue with Gunicorn/Flask (no default limit)
- Verify `gunicorn.conf.py` doesn't restrict request size

## Rollback
If the larger chunks cause Front Door WAF blocks (HTTP 403), revert
`CHUNK_SIZE` to `100 * 1024` and `PARALLEL_UPLOADS` to `3`.
