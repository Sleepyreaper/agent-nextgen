#!/bin/bash
# Script to configure Azure Storage for the web app
# Uses Entra ID (RBAC) authentication — shared-key access is DISABLED on the account.

set -euo pipefail

# Set these variables
RESOURCE_GROUP="${RESOURCE_GROUP:-your-resource-group}"
APP_NAME="${APP_NAME:-your-webapp-name}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-your-storage-account}"

# Container names must match StorageManager.CONTAINERS in src/storage.py
CONTAINERS=("applications-2026" "applications-test" "applications-training")

echo "🔧 Configuring Azure Storage for $APP_NAME (Entra ID / RBAC)..."

# Retrieve the Web App's managed-identity principal ID
PRINCIPAL_ID=$(az webapp identity show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --query "principalId" -o tsv 2>/dev/null || true)

if [ -z "$PRINCIPAL_ID" ]; then
  echo "  Enabling system-assigned managed identity on $APP_NAME..."
  PRINCIPAL_ID=$(az webapp identity assign \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --query "principalId" -o tsv)
fi

echo "✓ Managed identity principal: $PRINCIPAL_ID"

# Grant "Storage Blob Data Contributor" on the storage account
STORAGE_ID=$(az storage account show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$STORAGE_ACCOUNT" \
  --query "id" -o tsv)

echo "  Assigning Storage Blob Data Contributor role..."
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "$STORAGE_ID" \
  --output none 2>/dev/null || echo "  (role assignment already exists)"

echo "✓ RBAC role assigned"

# Ensure containers exist (uses Entra ID login)
az storage container list \
  --account-name "$STORAGE_ACCOUNT" \
  --auth-mode login -o none 2>/dev/null

for CONTAINER in "${CONTAINERS[@]}"; do
  az storage container create \
    --account-name "$STORAGE_ACCOUNT" \
    --name "$CONTAINER" \
    --auth-mode login \
    --public-access off \
    --output none 2>/dev/null || echo "  Container $CONTAINER already exists"
  echo "✓ Container ready: $CONTAINER"
done

# Set app setting — only the account name is needed at runtime
echo "📝 Setting App Service environment variable..."
az webapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --settings AZURE_STORAGE_ACCOUNT_NAME="$STORAGE_ACCOUNT" \
  --output none

echo ""
echo "✅ Azure Storage configured (Entra ID / RBAC)!"
echo "   Storage Account: $STORAGE_ACCOUNT"
echo "   Containers: ${CONTAINERS[*]}"
echo "   Auth: DefaultAzureCredential (managed identity)"
echo ""
echo "Try uploading a document now."
