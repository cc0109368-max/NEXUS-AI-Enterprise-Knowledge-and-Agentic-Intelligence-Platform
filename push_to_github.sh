#!/usr/bin/env bash
set -euo pipefail
REMOTE_URL="https://github.com/cc0109368-max/NEXUS-AI-Enterprise-Knowledge-and-Agentic-Intelligence-Platform.git"

if [ ! -d ".git" ]; then
  git init
  git branch -M main
  git add .
  git commit -m "feat: initial release of NEXUS AI Enterprise Knowledge and Agentic Intelligence Platform"
fi

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

echo "Pushing main branch to $REMOTE_URL ..."
git push -u origin main
