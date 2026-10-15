#!/usr/bin/env bash
# Run one backend job in a throw-away container and log its exit code.
#   ./run-job.sh python scripts/harvest.py
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
echo "$(date -u +%FT%TZ) start: $*"
docker compose run --rm -T jobs "$@"
rc=$?
echo "$(date -u +%FT%TZ) end rc=$rc: $*"
exit $rc
