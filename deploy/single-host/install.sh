#!/usr/bin/env bash
# One-command install of the marketplace on a single Ubuntu server
# (an Amazon EC2 instance, or any Ubuntu machine). See docs/DEPLOY_AWS_SIMPLE.md.
#
#   sudo ./deploy/single-host/install.sh
#
# Optional settings, as environment variables:
#   BACKUP_S3_BUCKET  S3 bucket that also receives the nightly database backup
#                   (the instance needs an IAM role allowed to s3:PutObject).
#   SITE_ADDRESS    host name to serve, e.g. marketplace.example.com.
#                   Default: <public-ip>.sslip.io, which needs no DNS set-up.
#                   ":80" serves plain HTTP (testing only).
#   ADMIN_USER      sign-in user name (default: admin)
#   ADMIN_PASSWORD  sign-in password (default: generated and printed)
#   PRODUCT_NAME    display name (default: Enterprise Data & Agents Marketplace)
#
# Safe to re-run: an existing .env is kept, and the one-time seeding is skipped
# once it has succeeded.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }

# --- 1. Swap: the portal build needs more memory than a small server has. ---
if [ "$(swapon --show --noheadings | wc -l)" -eq 0 ]; then
  log "Adding a 4 GB swap file"
  if fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile; then
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  else
    rm -f /swapfile; echo "Could not enable swap; continuing without it."
  fi
fi

# --- 2. Docker, with bounded container logs so the disk does not fill. ---
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker"
  mkdir -p /etc/docker
  [ -f /etc/docker/daemon.json ] || cat > /etc/docker/daemon.json <<'JSON'
{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}
JSON
  # Ubuntu's own packages first: they exist for every release, including ones
  # Docker's convenience script does not support yet.
  if ! { apt-get update -y && apt-get install -y docker.io docker-compose-v2 docker-buildx; }; then
    curl -fsSL https://get.docker.com | sh
  fi
fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is missing: apt-get install docker-compose-v2" >&2; exit 1; }

# --- Ports 80 and 443 must be free for the HTTPS proxy. ---
if ! docker compose ps --status running caddy 2>/dev/null | grep -q caddy; then
  BUSY="$(ss -Hltnp '( sport = :80 or sport = :443 )' 2>/dev/null || true)"
  if [ -n "$BUSY" ]; then
    echo "Ports 80/443 are already in use on this server:" >&2
    echo "$BUSY" >&2
    echo "Stop that program (e.g. 'sudo systemctl disable --now nginx'), or see" >&2
    echo "'Sharing the server with another app' in docs/DEPLOY_AWS_SIMPLE.md." >&2
    exit 1
  fi
fi

# --- 3. Configuration (.env), written once. ---
if [ ! -f .env ]; then
  log "Writing configuration"
  rand() { openssl rand -hex 16; }
  if [ -z "${SITE_ADDRESS:-}" ]; then
    IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
    SITE_ADDRESS="${IP//./-}.sslip.io"
  fi
  ADMIN_USER="${ADMIN_USER:-admin}"
  ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(rand)}"
  OWNER_PW="$(rand)"
  APP_PW="$(rand)"
  HASH="$(docker run --rm caddy:2.8 caddy hash-password --plaintext "$ADMIN_PASSWORD")"
  case "$SITE_ADDRESS" in :*) BASE_URL="http://localhost${SITE_ADDRESS}" ;; *) BASE_URL="https://$SITE_ADDRESS" ;; esac

  umask 077
  cat > .env <<EOF
# Written by install.sh. Values containing \$ are single-quoted so Docker
# Compose does not expand them.
SITE_ADDRESS=$SITE_ADDRESS
BASIC_AUTH_USER=$ADMIN_USER
BASIC_AUTH_HASH='$HASH'

PRODUCT_NAME=${PRODUCT_NAME:-Enterprise Data & Agents Marketplace}
TENANT_ID=TEN-DEMO

OWNER_PW=$OWNER_PW
DATABASE_URL=postgresql://marketplace:$OWNER_PW@postgres:5432/marketplace
APP_DATABASE_URL=postgresql://marketplace_app:$APP_PW@postgres:5432/marketplace
# Required to be present; nothing connects to it.
REDIS_URL=redis://unused:6379/0

# Must keep a local marker until per-user sign-in exists (DEPLOY_AWS.md F2).
OIDC_ISSUER=https://oidc.local/realms/marketplace
OIDC_CLIENT_ID=marketplace-portal
OIDC_CLIENT_SECRET=unused-until-oidc-is-implemented

SNOWFLAKE_ACCOUNT=placeholder
SNOWFLAKE_USER=SVC_MARKETPLACE_HARVEST
SNOWFLAKE_ROLE=MKT_READONLY
SNOWFLAKE_PRIVATE_KEY=

AGENT_RUNTIME=analytic
MODEL_PROVIDER=anthropic
MODEL_ID=claude-sonnet-5
MODEL_MAX_TOKENS=2000

DEMO_TIER_SCHEMA=MARKETPLACE_DEMO
DEMO_TIER_SCALE=0.1
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
FEATURE_FLAG_SOURCE=env
WORKER_POLL_SECONDS=5

API_BASE_URL=http://api:8000/api/v1
PORTAL_BASE_URL=$BASE_URL
PORTAL_LOCALE=en
PORTAL_DEV_SUBJECT=PTY-0061

# Optional: nightly backups are also copied here (see backup.sh).
BACKUP_S3_BUCKET=${BACKUP_S3_BUCKET:-}
EOF
  printf 'URL:      %s\nUser:     %s\nPassword: %s\n' "$BASE_URL" "$ADMIN_USER" "$ADMIN_PASSWORD" \
    > /root/marketplace-credentials.txt
  chmod 600 /root/marketplace-credentials.txt
  umask 022
fi

# The AWS CLI is needed only to copy backups to S3.
if grep -q '^BACKUP_S3_BUCKET=.' .env && ! command -v aws >/dev/null 2>&1; then
  log "Installing the AWS CLI (for S3 backups)"
  snap install aws-cli --classic
fi

# --- 4. Build the images on this server (no registry needed). ---
log "Building images (first time: 5-15 minutes)"
docker compose build

# --- 5. Database, then the one-time schema and seed sequence. ---
log "Starting the database"
docker compose up -d --wait postgres

log "Applying migrations"
./run-job.sh python scripts/migrate.py

if [ ! -f .seeded ]; then
  log "Seeding the catalog and demo data (first time only)"
  for step in \
      "python scripts/seed.py" \
      "python scripts/seed_platform.py" \
      "python scripts/harvest.py" \
      "python scripts/score.py" \
      "python scripts/seed_demo_tier.py" \
      "python scripts/demo_runner.py --verify" \
      "python scripts/evaluate.py" \
      "python scripts/publish_agents.py"; do
    # shellcheck disable=SC2086
    ./run-job.sh $step
  done
  # mesh and observe report findings through their exit code; a finding here
  # is information, not a failed install.
  ./run-job.sh python scripts/mesh.py || echo "mesh reported findings (see above)"
  ./run-job.sh python scripts/observe.py || echo "observe reported findings (see above)"
  touch .seeded
fi

# --- 6. Everything else. ---
log "Starting API, worker, portal and HTTPS proxy"
docker compose up -d --wait

# --- 7. Recurring jobs and nightly database backup. ---
log "Scheduling recurring jobs"
cat > /etc/cron.d/marketplace <<EOF
# Times are UTC. Output: /var/log/marketplace-jobs.log
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin
@reboot     root sleep 30; $HERE/set-address.sh >> /var/log/marketplace-jobs.log 2>&1
*/5 * * * * root $HERE/run-job.sh python scripts/observe.py >> /var/log/marketplace-jobs.log 2>&1
7 * * * *   root $HERE/run-job.sh python scripts/harvest.py >> /var/log/marketplace-jobs.log 2>&1
30 2 * * *  root $HERE/run-job.sh python scripts/score.py >> /var/log/marketplace-jobs.log 2>&1
0 3 * * *   root $HERE/run-job.sh python scripts/mesh.py >> /var/log/marketplace-jobs.log 2>&1
0 4 * * *   root $HERE/run-job.sh python scripts/demo_runner.py --nightly >> /var/log/marketplace-jobs.log 2>&1
0 5 * * 0   root $HERE/run-job.sh python scripts/rollback_drill.py >> /var/log/marketplace-jobs.log 2>&1
15 1 * * *  root $HERE/backup.sh >> /var/log/marketplace-jobs.log 2>&1
EOF
cat > /etc/logrotate.d/marketplace <<'EOF'
/var/log/marketplace-jobs.log {
  weekly
  rotate 8
  compress
  missingok
  notifempty
}
EOF

log "Done"
cat /root/marketplace-credentials.txt
echo
echo "The first HTTPS request can take ~30 s while the certificate is issued."
echo "Credentials are saved in /root/marketplace-credentials.txt"
