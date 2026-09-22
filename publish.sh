#!/usr/bin/env bash
set -euo pipefail

OWNER="${GH_OWNER:-TW1XSS}"
REPO="${GH_REPO:-minecraft-server-guardian}"
FULL_NAME="${OWNER}/${REPO}"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) is required: https://cli.github.com/" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "Run: gh auth login" >&2
  exit 1
fi

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Already inside a git repository. Reusing it."
else
  git init
fi

git branch -M main
git add .
if ! git diff --cached --quiet; then
  git commit -m "Initial release: Minecraft Server Guardian"
fi

if gh repo view "$FULL_NAME" >/dev/null 2>&1; then
  echo "Repository $FULL_NAME already exists; pushing to it."
else
  gh repo create "$FULL_NAME" --public --description "Self-hosted Minecraft server monitoring, crash recovery, backups and Discord alerts" --source . --remote origin --push
  gh repo edit "$FULL_NAME" \
    --add-topic minecraft \
    --add-topic minecraft-server \
    --add-topic monitoring \
    --add-topic discord-bot \
    --add-topic docker \
    --add-topic self-hosted
  echo "Published: https://github.com/$FULL_NAME"
  exit 0
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "https://github.com/$FULL_NAME.git"
fi

git push -u origin main

gh repo edit "$FULL_NAME" \
  --visibility public \
  --add-topic minecraft \
  --add-topic minecraft-server \
  --add-topic monitoring \
  --add-topic discord-bot \
  --add-topic docker \
  --add-topic self-hosted

echo "Published: https://github.com/$FULL_NAME"
