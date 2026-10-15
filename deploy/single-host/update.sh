#!/usr/bin/env bash
# Deploy the latest code: pull, rebuild, migrate, restart.
#   sudo ./deploy/single-host/update.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
git -C ../.. pull --ff-only
docker compose build
./run-job.sh python scripts/migrate.py
# Republish agents in case their manifests changed; a no-op otherwise.
./run-job.sh python scripts/evaluate.py
./run-job.sh python scripts/publish_agents.py
docker compose up -d --wait
docker image prune -f >/dev/null
echo "Updated to $(git -C ../.. rev-parse --short HEAD)"
