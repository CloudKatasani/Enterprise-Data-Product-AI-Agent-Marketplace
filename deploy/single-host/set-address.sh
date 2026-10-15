#!/usr/bin/env bash
# Without an Elastic IP, EC2 gives the server a new public IP after every
# stop/start. When the site uses the free <ip>.sslip.io name, move it to the
# current IP. Runs at boot from cron; does nothing for a custom domain.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
SITE="$(sed -n 's/^SITE_ADDRESS=//p' .env)"
# <prefix.>a-b-c-d.sslip.io — keep any prefix (e.g. "marketplace.").
[[ "$SITE" =~ ^(.*\.)?[0-9]+-[0-9]+-[0-9]+-[0-9]+\.sslip\.io$ ]] || exit 0
PREFIX="${BASH_REMATCH[1]}"
IP="$(curl -fsS --retry 10 --retry-connrefused https://checkip.amazonaws.com | tr -d '[:space:]')"
NEW="$PREFIX${IP//./-}.sslip.io"
if [ "$SITE" = "$NEW" ]; then exit 0; fi
sed -i "s#^SITE_ADDRESS=.*#SITE_ADDRESS=$NEW#; s#^PORTAL_BASE_URL=.*#PORTAL_BASE_URL=https://$NEW#" .env
sed -i "s#^URL: .*#URL:      https://$NEW#" /root/marketplace-credentials.txt 2>/dev/null || true
if grep -q '^HOST_CADDY=1' .env; then
  docker compose up -d --force-recreate portal
  ./host-caddy.sh
else
  docker compose up -d --force-recreate caddy portal
fi
echo "$(date -u +%FT%TZ) site address is now https://$NEW"
