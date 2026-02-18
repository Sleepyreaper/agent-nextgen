#!/bin/sh

set -e

HOOKS_DIR=".git/hooks"
SOURCE_HOOK="scripts/git-hooks/pre-push"

if [ ! -d "$HOOKS_DIR" ]; then
  echo "No .git/hooks directory found."
  exit 1
fi

if [ ! -f "$SOURCE_HOOK" ]; then
  echo "Missing $SOURCE_HOOK"
  exit 1
fi

cp "$SOURCE_HOOK" "$HOOKS_DIR/pre-push"
chmod +x "$HOOKS_DIR/pre-push"

echo "Installed pre-push hook."
