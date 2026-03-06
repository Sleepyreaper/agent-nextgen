#!/bin/sh

set -e

HOOKS_DIR=".git/hooks"

if [ ! -d "$HOOKS_DIR" ]; then
  echo "No .git/hooks directory found."
  exit 1
fi

# Install all hooks from scripts/git-hooks/
for hook in scripts/git-hooks/*; do
  hook_name=$(basename "$hook")
  if [ -f "$hook" ]; then
    cp "$hook" "$HOOKS_DIR/$hook_name"
    chmod +x "$HOOKS_DIR/$hook_name"
    echo "Installed $hook_name hook."
  fi
done

echo "All git hooks installed."
