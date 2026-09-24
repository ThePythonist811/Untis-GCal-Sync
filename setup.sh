#!/usr/bin/env bash
# Creates a PRIVATE GitHub repo, pushes the code and sets the Actions secrets.
# Requires: gh (GitHub CLI, logged in via `gh auth login`) and a filled .env
set -euo pipefail

REPO="${1:-untis-gcal-sync}"

[ -f .env ] || { echo "Missing .env (copy from .env.example)"; exit 1; }
set -a; source .env; set +a

for v in UNTIS_USERNAME UNTIS_PASSWORD UNTIS_CLASS GOOGLE_CALENDAR_ID GOOGLE_SERVICE_ACCOUNT_JSON; do
  [ -n "${!v:-}" ] || { echo "Empty: $v"; exit 1; }
done

[ -d .git ] || git init -b main
git add -A
git status --short | grep -E '\.env$|service-account' && { echo "Secret file staged, abort"; exit 1; } || true
git commit -m "Initial commit" || true

gh repo create "$REPO" --private --source=. --push

for v in UNTIS_USERNAME UNTIS_PASSWORD UNTIS_CLASS GOOGLE_CALENDAR_ID GOOGLE_SERVICE_ACCOUNT_JSON; do
  gh secret set "$v" --body "${!v}"
done

echo "Done. Start a first run: gh workflow run 'Untis Sync' && gh run watch"
