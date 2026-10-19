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
#   ACCESS          "password" (default) or "public": anyone with the URL can
#                   open the site. Change later with set-access.sh.
#   PRODUCT_NAME    display name (default: Enterprise Data & Agents Marketplace)
#
# Safe to re-run: an existing .env is kept, and the one-time seeding is skipped
# once it has succeeded.
set -euo pipefail

# Host name prefix used when sharing a Caddy with another site on the same IP:
# <prefix>.<ip>.sslip.io. Host names are case-insensitive, so it is lowercase.
SITE_PREFIX="enterprise-data-agents-marketplace"

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

# --- Who serves HTTPS: our own Caddy container, or a Caddy already here. ---
PROXY=container
if [ -f .env ] && grep -q '^HOST_CADDY=1' .env; then
  PROXY=host
elif ! docker compose ps --status running caddy 2>/dev/null | grep -q caddy; then
  BUSY="$(ss -Hltnp '( sport = :80 or sport = :443 )' 2>/dev/null || true)"
  if [ -n "$BUSY" ]; then
    if grep -q '"caddy"' <<<"$BUSY" && [ -f /etc/caddy/Caddyfile ] && systemctl is-active --quiet caddy; then
      PROXY=host
      log "Caddy already serves ports 80/443 here; the marketplace will be added to it as a second site"
    else
      echo "Ports 80/443 are already in use on this server:" >&2
      echo "$BUSY" >&2
      echo "Stop that program (e.g. 'sudo systemctl disable --now nginx'), or see" >&2
      echo "'Sharing the server with another app' in docs/DEPLOY_AWS_SIMPLE.md." >&2
      exit 1
    fi
  fi
fi

# --- 3. Configuration (.env), written once. ---
if [ ! -f .env ]; then
  log "Writing configuration"
  rand() { openssl rand -hex 16; }
  if [ -z "${SITE_ADDRESS:-}" ]; then
    IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
    SITE_ADDRESS="${IP//./-}.sslip.io"
    # Sharing a Caddy with another site: use a name of our own on the same IP.
    [ "$PROXY" = host ] && SITE_ADDRESS="$SITE_PREFIX.$SITE_ADDRESS"
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

# Proxy settings, also added to a .env written by an earlier version.
set_key() {
  if grep -q "^$1=" .env; then sed -i "s#^$1=.*#$1=$2#" .env; else echo "$1=$2" >> .env; fi
}
grep -q '^PORTAL_HOST_PORT=' .env || set_key PORTAL_HOST_PORT 3100
grep -q '^ACCESS=' .env || set_key ACCESS "${ACCESS:-password}"
if grep -q '^ACCESS=public' .env; then set_key CADDY_CONFIG Caddyfile.public; else set_key CADDY_CONFIG Caddyfile; fi
if [ "$PROXY" = host ]; then
  set_key HOST_CADDY 1
  set_key COMPOSE_PROFILES ""
  # A bare <ip>.sslip.io name may be the other site's; take <prefix>.<ip>.sslip.io.
  # An address from an earlier install (marketplace.<ip>.sslip.io) moves to the
  # current prefix too.
  SITE="$(sed -n 's/^SITE_ADDRESS=//p' .env)"
  if [[ "$SITE" =~ ^(marketplace\.)?([0-9]+-[0-9]+-[0-9]+-[0-9]+\.sslip\.io)$ ]]; then
    SITE="$SITE_PREFIX.${BASH_REMATCH[2]}"
    set_key SITE_ADDRESS "$SITE"
    set_key PORTAL_BASE_URL "https://$SITE"
    sed -i "s#^URL: .*#URL:      https://$SITE#" /root/marketplace-credentials.txt 2>/dev/null || true
  fi
else
  set_key HOST_CADDY 0
  set_key COMPOSE_PROFILES proxy
fi

PORT="$(sed -n 's/^PORTAL_HOST_PORT=//p' .env)"
if ! docker compose ps --status running portal 2>/dev/null | grep -q portal \
   && [ -n "$(ss -Hltn "sport = :$PORT" 2>/dev/null)" ]; then
  echo "Port $PORT is already in use; set PORTAL_HOST_PORT to a free port in $HERE/.env and re-run." >&2
  exit 1
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
  # Each finished step is recorded in .seed-progress, so a re-run after an
  # interruption or failure resumes instead of seeding twice.
  touch .seed-progress
  run_step() {  # run_step required|report <command...>
    local kind="$1"; shift
    if grep -qxF "$*" .seed-progress; then echo "already done: $*"; return 0; fi
    if ./run-job.sh "$@"; then
      echo "$*" >> .seed-progress
    elif [ "$kind" = report ]; then
      # These report findings through their exit code. A finding is information
      # about the demo estate, not a failed install.
      echo "$* reported findings (see above); continuing"
      echo "$*" >> .seed-progress
    else
      echo "Install stopped at: $*  (re-run install.sh to resume here)" >&2
      exit 1
    fi
  }
  run_step required python scripts/seed.py
  run_step required python scripts/seed_platform.py
  run_step required python scripts/harvest.py
  run_step required python scripts/score.py
  run_step required python scripts/seed_demo_tier.py
  # --nightly, not --verify: the stored golden answers were recorded on an
  # earlier date, and date-relative questions ("this quarter") drift. --nightly
  # hides a drifted answer from the front page instead of failing; --verify is
  # the strict CI gate.
  run_step report python scripts/demo_runner.py --nightly
  run_step report python scripts/evaluate.py
  run_step report python scripts/publish_agents.py
  run_step report python scripts/mesh.py
  run_step report python scripts/observe.py
  touch .seeded
fi

# --- 6. Everything else. ---
log "Starting API, worker, portal and HTTPS proxy"
docker compose up -d --wait
if [ "$PROXY" = host ]; then
  log "Adding the marketplace to this server's Caddy"
  ./host-caddy.sh
fi

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
if grep -q '^ACCESS=public' .env; then
  echo "URL: https://$(sed -n 's/^SITE_ADDRESS=//p' .env)  (public: no password needed)"
else
  cat /root/marketplace-credentials.txt
fi
echo
echo "The first HTTPS request can take ~30 s while the certificate is issued."
echo "Credentials are saved in /root/marketplace-credentials.txt"
