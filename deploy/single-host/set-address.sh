#!/usr/bin/env bash
# Without an Elastic IP, EC2 gives the server a new public IP after every
# stop/start. When the site uses the free <ip>.sslip.io name, move it to the
# current IP. Runs at boot from cron; does nothing for a custom domain.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
grep -q '^SITE_ADDRESS=.*\.sslip\.io$' .env || exit 0
IP="$(curl -fsS --retry 10 --retry-connrefused https://checkip.amazonaws.com | tr -d '[:space:]')"
NEW="${IP//./-}.sslip.io"
if grep -q "^SITE_ADDRESS=$NEW$" .env; then exit 0; fi
sed -i "s#^SITE_ADDRESS=.*#SITE_ADDRESS=$NEW#; s#^PORTAL_BASE_URL=.*#PORTAL_BASE_URL=https://$NEW#" .env
sed -i "s#^URL: .*#URL:      https://$NEW#" /root/marketplace-credentials.txt 2>/dev/null || true
docker compose up -d --force-recreate caddy portal
echo "$(date -u +%FT%TZ) site address is now https://$NEW"
