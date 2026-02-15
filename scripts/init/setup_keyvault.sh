#!/bin/bash
# Setup script to configure Azure Key Vault secrets for the application
# Run this script after deploying your Azure resources

set -e

VAULT_NAME="${AZURE_KEY_VAULT_NAME:-your-keyvault-name}"

echo "🔐 Azure Key Vault Secret Configuration"
echo "========================================"
echo ""
echo "This script will help you configure secrets in Azure Key Vault: $VAULT_NAME"
echo ""

# Check if user is logged in
if ! az account show &>/dev/null; then
    echo "❌ Not logged in to Azure. Please run: az login"
    exit 1
fi

echo "✓ Logged in to Azure"
echo ""

# Function to set secret with prompt
set_secret() {
    local secret_name=$1
    local prompt_text=$2
    local default_value=$3
    
    if [ -n "$default_value" ]; then
        read -p "$prompt_text [$default_value]: " value
        value=${value:-$default_value}
    else
        read -p "$prompt_text: " value
    fi
    
    if [ -n "$value" ]; then
        az keyvault secret set \
            --vault-name "$VAULT_NAME" \
            --name "$secret_name" \
            --value "$value" \
            --output none
        echo "  ✓ Set $secret_name"
    else
        echo "  ⚠ Skipped $secret_name"
    fi
}

# Function to set secret silently (for passwords)
set_secret_secure() {
    local secret_name=$1
    local prompt_text=$2
    
    read -s -p "$prompt_text: " value
    echo ""
    
    if [ -n "$value" ]; then
        az keyvault secret set \
            --vault-name "$VAULT_NAME" \
            --name "$secret_name" \
            --value "$value" \
            --output none
        echo "  ✓ Set $secret_name"
    else
        echo "  ⚠ Skipped $secret_name"
    fi
}

echo "📝 Azure OpenAI Configuration"
echo "------------------------------"
set_secret "azure-openai-endpoint" "Azure OpenAI Endpoint" "https://your-openai-resource.openai.azure.com/"
set_secret "azure-deployment-name" "Deployment Name" "your-deployment-name"
set_secret "azure-api-version" "API Version" "2024-12-01-preview"
echo ""

echo "📝 Azure Subscription Configuration"
echo "-----------------------------------"
set_secret "azure-subscription-id" "Azure Subscription ID" ""
set_secret "azure-resource-group" "Resource Group Name" "your-resource-group"
echo ""

echo "📝 PostgreSQL Database Configuration"
echo "------------------------------------"
set_secret "postgres-host" "PostgreSQL Host" ""
set_secret "postgres-port" "PostgreSQL Port" "5432"
set_secret "postgres-database" "PostgreSQL Database Name" "ApplicationsDB"
set_secret "postgres-username" "PostgreSQL Username" ""
set_secret_secure "postgres-password" "PostgreSQL Password"
echo ""

echo "📝 Flask Configuration"
echo "---------------------"
echo "Generating secure Flask secret key..."
FLASK_SECRET=$(openssl rand -hex 32)
az keyvault secret set \
    --vault-name "$VAULT_NAME" \
    --name "flask-secret-key" \
    --value "$FLASK_SECRET" \
    --output none
echo "  ✓ Set flask-secret-key (auto-generated)"
echo ""

echo "✅ Key Vault configuration complete!"
echo ""
echo "To verify your secrets, run:"
echo "  az keyvault secret list --vault-name $VAULT_NAME -o table"
echo ""
echo "To test the application:"
echo "  python -c 'from src.config import config; print(config.get_config_summary())'"
