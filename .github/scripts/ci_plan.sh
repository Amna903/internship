#!/usr/bin/env bash
# Decides which CI jobs a push needs, to keep GitHub Actions minutes down while keeping the green gate for
# whatever changed. Prints three JSON arrays for GITHUB_OUTPUT: backend, frontend and ml weeks.
#
# FULL (every week, every job): manual runs (workflow_dispatch), pushes to main, and pull requests to main or
# week4 when they are opened, reopened or marked ready for review. Otherwise, only what this push changed:
#   weekN/backend/**            -> that week's backend tests (SQLite and PostgreSQL)
#   weekN/frontend/**           -> that week's frontend checks
#   weekN/backend/ml/** or weekN/backend/requirements*.txt -> that week's ML reproducibility (weeks 3-5)
#   .github/**                  -> the newest week's backend, frontend and ML jobs (tests the CI plumbing itself)
# Markdown files and docs/ folders never trigger jobs on their own. If the changed files can't be worked out
# (first push, force push), it falls back to FULL.
# Inputs (environment): EVENT, ACTION, BASE_REF, REF, BEFORE, AFTER, BASE_SHA, HEAD_SHA.
set -euo pipefail
WEEKS=(week1 week2 week3 week4 week5 week6)
ML_WEEKS=(week3 week4 week5 week6)
NEWEST=week6
json() { local out=""; for w in "$@"; do out+="\"$w\","; done; echo "[${out%,}]"; }
# Docker stack job (Week 6): only for pull requests and manual runs, never plain pushes (the user's rule).
docker_full() { [ "$EVENT" = "workflow_dispatch" ] || [ "$EVENT" = "pull_request" ] && echo true || echo false; }
full() { echo "backend=$(json "${WEEKS[@]}")"; echo "frontend=$(json "${WEEKS[@]}")"; echo "ml=$(json "${ML_WEEKS[@]}")"; echo "docker=$(docker_full)"; echo "mode=full"; exit 0; }

[ "$EVENT" = "workflow_dispatch" ] && full
[ "$EVENT" = "push" ] && [ "$REF" = "refs/heads/main" ] && full
if [ "$EVENT" = "pull_request" ] && [[ "$ACTION" =~ ^(opened|reopened|ready_for_review)$ ]] && [[ "$BASE_REF" =~ ^(main|week4|week5)$ ]]; then
  full
fi

if [ "$EVENT" = "pull_request" ] && [ "$ACTION" != "synchronize" ]; then
  range="$BASE_SHA...$HEAD_SHA"
else
  range="$BEFORE..$AFTER"
fi
if [[ "$BEFORE" =~ ^0+$ ]] && [ "$ACTION" = "synchronize" -o "$EVENT" = "push" ]; then full; fi
files=$(git diff --name-only "$range" 2>/dev/null) || full

code=$(printf '%s\n' "$files" | grep -Ev '(\.md$|(^|/)docs/)' || true)
backend=""; frontend=""; ml=""   # space-separated week lists (portable to old bash)
add() { case " $1 " in *" $2 "*) echo "$1" ;; *) echo "$1 $2" ;; esac; }
if printf '%s\n' "$code" | grep -q '^\.github/'; then backend=$NEWEST; frontend=$NEWEST; ml=$NEWEST; fi
for w in "${WEEKS[@]}"; do
  if printf '%s\n' "$code" | grep -q "^$w/backend/"; then backend=$(add "$backend" "$w"); fi
  if printf '%s\n' "$code" | grep -q "^$w/frontend/"; then frontend=$(add "$frontend" "$w"); fi
done
for w in "${ML_WEEKS[@]}"; do
  if printf '%s\n' "$code" | grep -Eq "^$w/backend/(ml/|requirements)"; then ml=$(add "$ml" "$w"); fi
done
# shellcheck disable=SC2086  (word splitting is intended)
echo "backend=$(json $backend)"
echo "frontend=$(json $frontend)"
echo "ml=$(json $ml)"
docker=false
if [ "$EVENT" = "pull_request" ] && printf '%s\n' "$code" | grep -Eq "^$NEWEST/(docker-compose[^/]*\.yml|Makefile|deploy/|e2e/|backend/(Dockerfile|docker-entrypoint\.sh|requirements[^/]*\.txt)|frontend/(Dockerfile|package(-lock)?\.json))"; then
  docker=true
fi
echo "docker=$docker"
echo "mode=changed"
