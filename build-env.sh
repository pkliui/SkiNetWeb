#!/usr/bin/env bash
# Regenerates .env (gitignored, what docker compose actually reads) from
# .env.config (tracked in git — non-secret deployment config) and
# .env.secrets (gitignored — real credentials: KAGGLE_USERNAME, KAGGLE_KEY,
# OPENROUTER_API_KEY, MISTRAL_API_KEY).
#
# Both Studio and CI call this same script, so the merge logic lives in one
# place instead of being duplicated (and drifting) between a local .env and
# the GitHub Actions workflow. CI writes .env.secrets from GitHub Secrets
# before calling this script; locally, create .env.secrets by hand once.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f .env.secrets ]; then
  echo "build-env.sh: .env.secrets not found. Create it with:" >&2
  echo "  KAGGLE_USERNAME=... / KAGGLE_KEY=... / OPENROUTER_API_KEY=... / MISTRAL_API_KEY=..." >&2
  exit 1
fi

cat .env.config .env.secrets > .env
