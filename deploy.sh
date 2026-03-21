#!/bin/bash
# NextGen Agents — Deploy Script
# Usage: ./deploy.sh [slot]
#   ./deploy.sh          → deploy to production
#   ./deploy.sh staging  → deploy to staging slot
#
# Requirements: az CLI logged in, in the agent-nextgen repo directory

set -e

SLOT="${1:-}"
APP_NAME="nextgen2-web"
RG="Nextgen_agents2"
ZIP_PATH="/tmp/nextgen-deploy.zip"

echo "╔══════════════════════════════════════════╗"
echo "║     NextGen Agents — Deploy Pipeline     ║"
echo "╚══════════════════════════════════════════╝"

# 1. Build zip (excluding dev/test artifacts and Oryx cache)
echo ""
echo "📦 Building deployment zip..."
rm -f "$ZIP_PATH"
zip -r "$ZIP_PATH" . \
  -x ".git/*" "__pycache__/*" "*/__pycache__/*" "*.pyc" ".env*" \
  "testing/*" "documents/*" "data/sample*" ".venv/*" "node_modules/*" \
  "oryx-manifest.toml" "output.tar.zst" \
  > /dev/null 2>&1
echo "   Zip: $(du -sh $ZIP_PATH | cut -f1) ($(unzip -l $ZIP_PATH | tail -1 | awk '{print $2}') files)"

# 2. Deploy
SLOT_ARGS=""
SLOT_LABEL="production"
if [ -n "$SLOT" ]; then
  SLOT_ARGS="--slot $SLOT"
  SLOT_LABEL="$SLOT"
fi

echo ""
echo "🚀 Deploying to $SLOT_LABEL..."
az webapp deploy \
  -n "$APP_NAME" -g "$RG" \
  $SLOT_ARGS \
  --src-path "$ZIP_PATH" \
  --type zip \
  --restart true \
  -o none 2>&1

echo "   Deploy submitted. Waiting for startup..."
sleep 45

# 3. Health check
HEALTH_URL="https://${APP_NAME}.azurewebsites.net/healthz"
if [ -n "$SLOT" ]; then
  HEALTH_URL="https://${APP_NAME}-${SLOT}.azurewebsites.net/healthz"
fi

echo ""
echo "🏥 Health check: $HEALTH_URL"
for i in $(seq 1 6); do
  STATUS=$(python3 -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('$HEALTH_URL', timeout=15)
    d = json.loads(r.read())
    print(f\"OK: {d}\")
except Exception as e:
    print(f'FAIL: {e}')
" 2>&1)
  echo "   Attempt $i: $STATUS"
  if echo "$STATUS" | grep -q "^OK:"; then
    echo ""
    echo "✅ Deploy to $SLOT_LABEL SUCCESSFUL"
    echo "   URL: https://${APP_NAME}.azurewebsites.net"
    exit 0
  fi
  sleep 15
done

echo ""
echo "❌ Health check failed after 6 attempts"
exit 1
