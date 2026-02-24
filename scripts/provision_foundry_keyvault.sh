#!/usr/bin/env bash
set -euo pipefail

# Provision Key Vault secrets for Foundry and grant App Service managed identity access.
# Usage:
#   VAULT_NAME="my-vault" \
#   RG="MyResourceGroup" \
#   WEBAPP_NAME="nextgen-agents-web" \
#   FOUNDARY_ENDPOINT="https://nextgenagentfoundry.cognitiveservices.azure.com" \
#   MODEL_NAME="gpt-4.1" \
#   API_VERSION="2024-05-01-preview" \
#   ./scripts/provision_foundry_keyvault.sh

VAULT_NAME=${VAULT_NAME:-}
RG=${RG:-}
WEBAPP_NAME=${WEBAPP_NAME:-}
FOUNDARY_ENDPOINT=${FOUNDARY_ENDPOINT:-}
MODEL_NAME=${MODEL_NAME:-gpt-4.1-2025-04-14}
API_VERSION=${API_VERSION:-2024-05-01-preview}

if [ -z "$VAULT_NAME" ]; then
  echo "ERROR: Please set VAULT_NAME environment variable to your Key Vault name."
  exit 2
fi

if [ -z "$RG" ]; then
  echo "ERROR: Please set RG environment variable to your Azure Resource Group name."
  exit 2
fi

if [ -z "$WEBAPP_NAME" ]; then
  echo "ERROR: Please set WEBAPP_NAME environment variable to your Azure Web App name."
  exit 2
fi

if [ -z "$FOUNDARY_ENDPOINT" ]; then
  echo "ERROR: Please set FOUNDARY_ENDPOINT environment variable to your AI Foundry endpoint URL."
  exit 2
fi

echo "Using:
  VAULT_NAME=$VAULT_NAME
  RG=$RG
  WEBAPP_NAME=$WEBAPP_NAME
  FOUNDARY_ENDPOINT=$FOUNDARY_ENDPOINT
  MODEL_NAME=$MODEL_NAME
  API_VERSION=$API_VERSION"

# Get caller public IP to add temporary access if vault has firewall rules
echo "Detecting public IP..."
MY_IP=$(curl -s https://ifconfig.me || true)
if [ -z "$MY_IP" ]; then
  echo "Could not detect public IP automatically; continuing without temporary firewall rule." 
else
  echo "Public IP detected: $MY_IP"
fi

# Add temporary network rule if we have an IP
if [ -n "$MY_IP" ]; then
  echo "Adding temporary Key Vault network rule for $MY_IP"
  az keyvault network-rule add --name "$VAULT_NAME" --ip-address "$MY_IP" || true
fi

# Set Foundry secrets in Key Vault
echo "Setting Key Vault secrets..."
az keyvault secret set --vault-name "$VAULT_NAME" --name "foundry-project-endpoint" --value "$FOUNDARY_ENDPOINT"
az keyvault secret set --vault-name "$VAULT_NAME" --name "foundry-model-name" --value "$MODEL_NAME"
az keyvault secret set --vault-name "$VAULT_NAME" --name "foundry-api-version" --value "$API_VERSION"

# Ensure App Service has a system-assigned managed identity
echo "Assigning system-managed identity to webapp (if missing)..."
az webapp identity assign --resource-group "$RG" --name "$WEBAPP_NAME" >/dev/null

# Get the principalId of the webapp identity
PRINCIPAL_ID=$(az webapp identity show --resource-group "$RG" --name "$WEBAPP_NAME" --query principalId -o tsv)
if [ -z "$PRINCIPAL_ID" ]; then
  echo "ERROR: Could not retrieve webapp principalId.";
  exit 3
fi
echo "Webapp principalId: $PRINCIPAL_ID"

# Grant Key Vault access policy for secrets to the webapp identity
echo "Granting Key Vault secret get/list permissions to webapp identity..."
az keyvault set-policy --name "$VAULT_NAME" --object-id "$PRINCIPAL_ID" --secret-permissions get list >/dev/null

# Set app settings so the app knows to use Key Vault and Foundry provider
echo "Updating App Service app settings..."
az webapp config appsettings set --resource-group "$RG" --name "$WEBAPP_NAME" --settings AZURE_KEY_VAULT_NAME="$VAULT_NAME" NEXTGEN_MODEL_PROVIDER=foundry FOUNDRY_MODEL_NAME="$MODEL_NAME" FOUNDRY_PROJECT_ENDPOINT="$FOUNDARY_ENDPOINT"

# Restart the webapp to pick up new settings
echo "Restarting webapp..."
az webapp restart --resource-group "$RG" --name "$WEBAPP_NAME"

# Remove temporary network rule if we added one
if [ -n "$MY_IP" ]; then
  echo "Removing temporary Key Vault network rule for $MY_IP"
  az keyvault network-rule remove --name "$VAULT_NAME" --ip-address "$MY_IP" || true
fi

echo "Done. Next steps:"
echo "  1) Run the smoke test:"
echo "     curl -i -s -X POST https://$(az webapp show -n $WEBAPP_NAME -g $RG --query defaultHostName -o tsv)/api/debug/model_test -H 'Content-Type: application/json' -d '{}' -w '\nHTTPSTATUS:%{http_code}\n'"
echo "  2) tail the webapp logs (stream): az webapp log tail --name $WEBAPP_NAME --resource-group $RG"

exit 0
