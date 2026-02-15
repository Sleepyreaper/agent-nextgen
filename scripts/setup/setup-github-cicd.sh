#!/bin/bash
# Quick setup script for GitHub & Azure CI/CD integration

echo "🚀 Agent NextGen - GitHub & Azure CI/CD Setup"
echo "=============================================="
echo ""

# Check if git is initialized
if [ ! -d .git ]; then
    echo "❌ Git not initialized. Please run: git init"
    exit 1
fi

echo "✅ Git repository found"

# Check git status
echo ""
echo "📋 Current Changes:"
git status --short

echo ""
echo "📦 Commits in repo:"
git log --oneline | head -5

echo ""
echo "🔗 Remote repositories:"
git remote -v || echo "   No remotes configured yet"

echo ""
echo "=============================================="
echo "📌 NEXT STEPS:"
echo "=============================================="
echo ""
echo "1️⃣  CREATE GITHUB REPOSITORY"
echo "   - Go to https://github.com/new"
echo "   - Create a new repo: 'agent-nextgen' (or your preferred name)"
echo "   - Do NOT initialize with README, .gitignore, or license (we have these)"
echo "   - Click 'Create repository'"
echo ""

echo "2️⃣  ADD GITHUB REMOTE (replace YOUR_USERNAME and YOUR_REPO)"
echo "   git remote add github https://github.com/YOUR_USERNAME/YOUR_REPO.git"
echo "   git branch -M main"
echo "   git push -u github main"
echo ""

echo "3️⃣  ADD GITHUB SECRETS (for Azure deployment)"
echo "   a) Go to: https://github.com/YOUR_USERNAME/YOUR_REPO/settings/secrets/actions"
echo ""
echo "   b) Add these secrets:"
echo "      Secret: AZURE_WEBAPP_NAME"
echo "      Value:  your-webapp-name"
echo ""
echo "      Secret: AZURE_WEBAPP_PUBLISH_PROFILE"
echo "      Value:  Download from Azure Portal:"
echo "              - App Services → your-webapp-name"
echo "              - Click 'Get publish profile' (top right)"
echo "              - Upload entire XML file contents"
echo ""

echo "4️⃣  VERIFY GITHUB ACTIONS"
echo "   - Go to: https://github.com/YOUR_USERNAME/YOUR_REPO/actions"
echo "   - Workflows should run automatically on next push"
echo "   - Watch 'Deploy to Azure Web App' workflow"
echo ""

echo "=============================================="
echo "✨ Once complete, every push to main will:"
echo "   ✅ Run security scans"
echo "   ✅ Validate code"
echo "   ✅ Deploy to Azure Web App"
echo "=============================================="
echo ""
