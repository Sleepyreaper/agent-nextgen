#!/bin/bash
# Automated GitHub repo creation and push script

set -e

echo "🚀 Agent NextGen - Automated GitHub Setup"
echo "=========================================="
echo ""

# Check for required tools
command -v git >/dev/null 2>&1 || { echo "❌ git is required but not installed."; exit 1; }

# Get user input
echo "📝 Please provide your GitHub credentials:"
echo ""
read -p "GitHub Username: " GITHUB_USERNAME
read -p "Repository Name (e.g., agent-nextgen): " REPO_NAME
read -sp "GitHub Personal Access Token (with repo scope): " GITHUB_TOKEN
echo ""
echo ""

# Validate input
if [ -z "$GITHUB_USERNAME" ] || [ -z "$REPO_NAME" ] || [ -z "$GITHUB_TOKEN" ]; then
    echo "❌ All fields are required"
    exit 1
fi

echo "🔍 Checking GitHub API..."
GITHUB_API_TEST=$(curl -s -w "%{http_code}" -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/user" -o /dev/null)
if [ "$GITHUB_API_TEST" != "200" ]; then
    echo "❌ Invalid GitHub token or API unreachable"
    exit 1
fi
echo "✅ GitHub API authenticated"

echo ""
echo "📦 Creating GitHub repository: $GITHUB_USERNAME/$REPO_NAME"
echo ""

# Create repository via GitHub API
CREATE_REPO_RESPONSE=$(curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/user/repos" \
  -d "{\"name\":\"$REPO_NAME\",\"description\":\"Agent NextGen - Multi-agent AI system for Azure\",\"private\":false,\"auto_init\":false}")

# Check if repo creation succeeded
if echo "$CREATE_REPO_RESPONSE" | grep -q '"id"'; then
    echo "✅ Repository created successfully!"
    REPO_URL="https://github.com/$GITHUB_USERNAME/$REPO_NAME.git"
else
    echo "❌ Failed to create repository"
    echo "Response: $CREATE_REPO_RESPONSE"
    exit 1
fi

echo ""
echo "🔗 Adding GitHub as remote..."
# Check if github remote already exists
if git remote get-url github >/dev/null 2>&1; then
    git remote remove github
fi

git remote add github "https://$GITHUB_USERNAME:$GITHUB_TOKEN@github.com/$GITHUB_USERNAME/$REPO_NAME.git"
echo "✅ Remote added"

echo ""
echo "📤 Pushing code to GitHub..."
git push -u github main
echo "✅ Code pushed successfully!"

echo ""
echo "=============================================="
echo "✨ GitHub Setup Complete!"
echo "=============================================="
echo ""
echo "📍 Repository: $REPO_URL"
echo ""
echo "🔑 NEXT STEP - Add GitHub Secrets:"
echo "   1. Go to: https://github.com/$GITHUB_USERNAME/$REPO_NAME/settings/secrets/actions"
echo ""
echo "   2. Add Secret #1:"
echo "      Name:  AZURE_WEBAPP_NAME"
echo "      Value: nextgen-agents-web"
echo ""
echo "   3. Add Secret #2:"
echo "      Name:  AZURE_WEBAPP_PUBLISH_PROFILE"
echo "      Value: [Download from Azure Portal - see instructions below]"
echo ""
echo "📋 To get the publish profile:"
echo "   - Go to Azure Portal"
echo "   - App Services → nextgen-agents-web"
echo "   - Click 'Get publish profile' (top right)"
echo "   - Copy entire XML file contents into GitHub secret"
echo ""
echo "✅ Once secrets are added, CI/CD will auto-deploy on next push!"
echo ""
