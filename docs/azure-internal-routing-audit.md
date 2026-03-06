# Azure Internal Routing Audit — Issue #11

**Date:** 2026-03-06  
**Auditor:** Willie (overnight sweep)

## Summary

Azure services currently route through public endpoints. Internal routing via
VNet/Private Endpoints would optimize latency and secure inter-service traffic.

## Current Architecture (from code audit)

| Service | Current Endpoint Pattern | File |
|---------|------------------------|------|
| Azure OpenAI | `*.openai.azure.com` (via env/KV) | `src/config.py:100` |
| Azure Blob Storage | `{account}.blob.core.windows.net` | `src/storage.py:50,158,224,340` |
| Azure Key Vault | `{name}.vault.azure.net` | `src/config.py:79` |
| PostgreSQL | Connection string (via env/KV) | `src/database.py` |
| Front Door | Routes external traffic to web app | (Azure config) |

## Recommendations

### 1. Private Endpoints (Priority: HIGH)
Set up Private Endpoints for all backend services so they communicate over the
Azure backbone VNet instead of public internet:

- **Azure OpenAI** → Private Endpoint in app's VNet
- **Blob Storage** → Private Endpoint + disable public access
- **Key Vault** → Private Endpoint + firewall rules
- **PostgreSQL** → Already likely on private endpoint or VNet integration; verify

### 2. Code Changes Needed

#### Storage (src/storage.py)
The `account_url` is hardcoded to `blob.core.windows.net`. With Private Endpoints,
the DNS auto-resolves to the private IP via Azure Private DNS Zone — **no code change
needed** as long as:
- Private DNS Zone `privatelink.blob.core.windows.net` is linked to the VNet
- App Service VNet Integration is enabled

#### Key Vault (src/config.py)
Same pattern — `vault.azure.net` resolves to private IP via
`privatelink.vaultcore.azure.net` DNS zone. **No code change needed.**

#### OpenAI (src/config.py)
Endpoint URL from env/Key Vault. With Private Endpoint, the `openai.azure.com`
hostname resolves to private IP. **No code change needed.**

### 3. Front Door Routing
The issue states: "all azure services except our web app should be able to route
internal without having to use FD at all."

**Action items:**
1. Front Door should ONLY be the entry point for external web traffic
2. Internal service-to-service calls (app → OpenAI, app → Storage, app → DB)
   should go through VNet/Private Endpoints, NOT through Front Door
3. Verify no service URLs are configured to go through the Front Door hostname
4. Add VNet Integration to the App Service if not already enabled

### 4. Network Security Groups (NSGs)
- Restrict inbound to App Service from Front Door only (use `AzureFrontDoor.Backend` service tag)
- Restrict storage/KV/OpenAI inbound to VNet only

### 5. Verification Checklist
- [ ] Enable VNet Integration on App Service
- [ ] Create Private Endpoints for: Storage, Key Vault, OpenAI, PostgreSQL
- [ ] Create Private DNS Zones and link to VNet
- [ ] Disable public network access on Storage, Key Vault (after testing)
- [ ] Verify OpenAI calls route internally (check latency drop)
- [ ] Verify Front Door → App Service uses the correct backend
- [ ] Add NSG rules restricting backend service access to VNet
- [ ] Test all agent workflows end-to-end after changes

## What Willie CAN'T Do

This is an infrastructure issue — the actual changes happen in Azure Portal,
Azure CLI, or IaC templates (Bicep/ARM). The Python code doesn't need modification
because Azure Private DNS Zones transparently redirect the existing hostnames.

**Human action required:** Execute the Azure infrastructure changes above.
