#!/bin/bash
# Script to configure Azure Storage for the web app

# Set these variables
RESOURCE_GROUP="nextgen-agents"
APP_NAME="nextgen-agents-web"
STORAGE_ACCOUNT="nextgenagentsstorage"  # Change if different
CONTAINER_NAME="student-uploads"

echo "🔧 Configuring Azure Storage for $APP_NAME..."

# Get storage account key
STORAGE_KEY=$(az storage account keys list \
  --resource-group "$RESOURCE_GROUP" \
  --account-name "$STORAGE_ACCOUNT" \
  --query "[0].value" -o tsv)

if [ -z "$STORAGE_KEY" ]; then
  echo "❌ Could not retrieve storage account key. Check STORAGE_ACCOUNT name and resource group."
  exit 1
fi

echo "✓ Retrieved storage account key"

# Create container if it doesn't exist
az storage container create \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY" \
  --name "$CONTAINER_NAME" \
  --public-access off 2>/dev/null || echo "Container already exists or is being used"

echo "✓ Storage container ready"

# Set app settings
echo "📝 Setting App Service environment variables..."

az webapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APP_NAME" \
  --settings \
    AZURE_STORAGE_ACCOUNT_NAME="$STORAGE_ACCOUNT" \
    AZURE_STORAGE_ACCOUNT_KEY="$STORAGE_KEY" \
    AZURE_STORAGE_CONTAINER_NAME="$CONTAINER_NAME"

echo "✅ Azure Storage configured!"
echo ""
echo "Storage Account: $STORAGE_ACCOUNT"
echo "Container: $CONTAINER_NAME"
echo ""
echo "Try uploading a document now."
