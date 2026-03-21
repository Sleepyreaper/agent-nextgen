#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
# Deploy new models into Azure AI Foundry (nextgenagentfoundry)
#
# These models were approved March 2026. Deploy them so the team
# can be upgraded via:  python -m core_team.cli upgrade --apply
#
# Prerequisites:
#   az login
#   az account set --subscription b1672fa6-8e52-45d0-bf79-ceccc352177d
#
# Usage:
#   chmod +x deploy_models.sh
#   ./deploy_models.sh              # deploy all needed models
#   ./deploy_models.sh --list       # just show what would be deployed
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

ACCOUNT="springfield-ai-eastus2"
SUB="b1672fa6-8e52-45d0-bf79-ceccc352177d"
RG="NextGen_Agents"
SKU="GlobalStandard"
CAPACITY=1

echo "Account: $ACCOUNT (eastus2)"
echo "Resource Group: $RG"
echo "Subscription: $SUB"
echo ""

# ── Models to deploy ──────────────────────────────────────────────
# Each line: deployment_name|model_name|model_version
# Using deployment_name = model_name for clean discovery matching.
MODELS=(
    "o3-pro|o3-pro|2025-06-01"
    "o3|o3|2025-06-01"
    "gpt-5.4|gpt-5.4|2026-02-01"
    "gpt-5.4-pro|gpt-5.4-pro|2026-02-01"
    "gpt-5.3-codex|gpt-5.3-codex|2026-01-01"
)

echo "Models to deploy:"
echo "─────────────────────────────────────────"
printf "  %-20s %-20s %s\n" "DEPLOYMENT" "MODEL" "VERSION"
echo "─────────────────────────────────────────"
for entry in "${MODELS[@]}"; do
    IFS='|' read -r deploy model version <<< "$entry"
    printf "  %-20s %-20s %s\n" "$deploy" "$model" "$version"
done
echo ""

if [[ "${1:-}" == "--list" ]]; then
    echo "Run without --list to deploy."
    exit 0
fi

# ── Check what's already deployed ─────────────────────────────────
echo "Checking existing deployments..."
EXISTING=$(az cognitiveservices account deployment list \
    --resource-group "$RG" --name "$ACCOUNT" \
    --query "[].name" -o tsv 2>/dev/null || echo "")

# ── Deploy each model ─────────────────────────────────────────────
for entry in "${MODELS[@]}"; do
    IFS='|' read -r deploy model version <<< "$entry"

    if echo "$EXISTING" | grep -qw "$deploy"; then
        echo "✓ $deploy — already deployed, skipping"
        continue
    fi

    echo "⟳ Deploying $deploy ($model @ $version, $SKU, capacity=$CAPACITY)..."
    az cognitiveservices account deployment create \
        --resource-group "$RG" \
        --name "$ACCOUNT" \
        --deployment-name "$deploy" \
        --model-name "$model" \
        --model-version "$version" \
        --model-format OpenAI \
        --sku-capacity "$CAPACITY" \
        --sku-name "$SKU" \
        --only-show-errors \
    && echo "  ✓ $deploy deployed successfully" \
    || echo "  ✗ $deploy FAILED — check region availability or model name"
done

echo ""
echo "Done. Now run:"
echo "  python -m core_team.cli models     # verify deployments"
echo "  python -m core_team.cli upgrade    # see upgrade plan"
echo "  python -m core_team.cli upgrade --apply  # apply upgrades"
