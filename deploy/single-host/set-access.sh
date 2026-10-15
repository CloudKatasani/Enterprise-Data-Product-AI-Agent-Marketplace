#!/usr/bin/env bash
# Switch who can open the site, on a running install:
#   sudo ./set-access.sh public     anyone with the URL, no sign-in
#   sudo ./set-access.sh password   user name + password (BASIC_AUTH_* in .env)
# There is no per-user sign-in in the application (docs/DEPLOY_AWS.md, F2), so
# with "public" every visitor acts as the one demo identity, admin pages included.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
MODE="${1:-}"
case "$MODE" in
  public)   CONFIG=Caddyfile.public ;;
  password) CONFIG=Caddyfile ;;
  *) echo "usage: sudo $0 public|password" >&2; exit 2 ;;
esac
set_key() {
  if grep -q "^$1=" .env; then sed -i "s#^$1=.*#$1=$2#" .env; else echo "$1=$2" >> .env; fi
}
set_key ACCESS "$MODE"
set_key CADDY_CONFIG "$CONFIG"
if grep -q '^HOST_CADDY=1' .env; then
  ./host-caddy.sh
else
  docker compose up -d --force-recreate caddy
fi
SITE="$(sed -n 's/^SITE_ADDRESS=//p' .env)"
if [ "$MODE" = public ]; then
  echo "https://$SITE is now open to anyone with the link (no password)."
else
  echo "https://$SITE now asks for the user name and password in /root/marketplace-credentials.txt."
fi
