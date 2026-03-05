# Azure Internal Routing Audit — March 5, 2026

## Summary

Reviewed all service-to-service communication patterns in the codebase.
Front Door should only sit in front of the **web app** (user-facing HTTP).
All backend Azure services should use direct/internal routing.

## Current State ✅

| Service | Connection Method | Front Door? | Status |
|---------|------------------|-------------|--------|
| **Azure Blob Storage** | Direct via `{account}.blob.core.windows.net` using `DefaultAzureCredential` | ❌ No | ✅ Correct |
| **PostgreSQL** | Direct connection string from Key Vault (`DATABASE_URL`) | ❌ No | ✅ Correct |
| **Azure OpenAI** | Direct via `cognitiveservices.azure.com` endpoint | ❌ No | ✅ Correct |
| **Azure AI Foundry** | Direct via `services.ai.azure.com` (rewritten to `cognitiveservices.azure.com`) | ❌ No | ✅ Correct |
| **Key Vault** | Direct via Azure SDK + Managed Identity | ❌ No | ✅ Correct |

## Recommendations

### 1. Enable VNet Integration (if not already done)
- Web App → VNet → Private Endpoints for Blob, Postgres, OpenAI
- This keeps all backend traffic on the Azure backbone

### 2. Private Endpoints for Backend Services
```
Azure Front Door → Web App (public)
Web App (VNet) → Blob Storage (Private Endpoint)
Web App (VNet) → PostgreSQL Flexible Server (Private Endpoint)
Web App (VNet) → Azure OpenAI (Private Endpoint)
```

### 3. Front Door WAF Rules
- Exclude `/api/file/upload-chunk` from body inspection (supports 4MB chunks now)
- Or set custom body size limit for upload routes

### 4. Restrict Web App Direct Access
- Configure App Service to only accept traffic from Front Door
- Use `X-Azure-FDID` header validation or IP restrictions

### 5. Service Tags / NSG Rules
If using VNet, lock down NSGs so only:
- Front Door → Web App on port 443
- Web App → backend services via Private Endpoints

## No Code Changes Required

The codebase already routes all internal services directly.
Infrastructure changes should be done in Azure Portal / CLI / Bicep.
