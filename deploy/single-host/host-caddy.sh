#!/usr/bin/env bash
# For a server that already runs Caddy (another site) on ports 80/443: add the
# marketplace to that Caddy as one more site, instead of starting a second
# proxy. Writes a marked block into /etc/caddy/Caddyfile from .env and reloads
# Caddy; if the reload is rejected, the previous file is restored.
# Re-running replaces the block, so it also applies a new address or password.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"
BEGIN="# >>> marketplace (managed by $(pwd)/host-caddy.sh; edits here are overwritten)"
END="# <<< marketplace"

env_value() { sed -n "s/^$1=//p" .env | sed "s/^'\(.*\)'$/\1/"; }
SITE="$(env_value SITE_ADDRESS)"
USER_NAME="$(env_value BASIC_AUTH_USER)"
HASH="$(env_value BASIC_AUTH_HASH)"
PORT="$(env_value PORTAL_HOST_PORT)"
PORT="${PORT:-3100}"
ACCESS="$(env_value ACCESS)"

# Password-protected unless ACCESS=public (set-access.sh).
AUTH="	basicauth {
		$USER_NAME $HASH
	}
"
[ "$ACCESS" = public ] && AUTH=""

BLOCK="$BEGIN
$SITE {
${AUTH}	encode gzip
	reverse_proxy 127.0.0.1:$PORT {
		flush_interval -1
	}
}
$END"

BACKUP="$CADDYFILE.before-marketplace"
[ -f "$BACKUP" ] || cp "$CADDYFILE" "$BACKUP"
PREVIOUS="$(mktemp)"
cp "$CADDYFILE" "$PREVIOUS"

# Drop an earlier copy of the block, then append the current one.
awk -v e="$END" '
  index($0, "# >>> marketplace") == 1 { skip = 1; next }
  skip && $0 == e { skip = 0; next }
  !skip { print }
' "$PREVIOUS" | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}' > "$CADDYFILE.tmp"   # no trailing blank lines
printf '\n%s\n' "$BLOCK" >> "$CADDYFILE.tmp"
cat "$CADDYFILE.tmp" > "$CADDYFILE"   # keep the file's owner and mode
rm -f "$CADDYFILE.tmp"

# A reload loads and checks the new file; if Caddy rejects it, the running
# configuration is left untouched and we put the old file back.
if systemctl reload caddy; then
  echo "Caddy now also serves https://$SITE (original file kept at $BACKUP)"
  rm -f "$PREVIOUS"
else
  cp "$CADDYFILE" "$CADDYFILE.marketplace-rejected"
  cat "$PREVIOUS" > "$CADDYFILE"
  rm -f "$PREVIOUS"
  echo "Caddy rejected the change, so $CADDYFILE was restored." >&2
  echo "The attempted file is $CADDYFILE.marketplace-rejected. Caddy's log:" >&2
  journalctl -u caddy -n 8 --no-pager >&2 || true
  exit 1
fi
