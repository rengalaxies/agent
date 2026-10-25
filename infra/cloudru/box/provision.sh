#!/bin/bash
# First install of the agent-service box on a fresh VM, with the same installer as batch 5A.
#
# cloud-init writes this file and release.env (URL, sha256, name; no secrets) and starts
# it once; agent-service-box-provision.path starts it again whenever the owner writes
# /etc/agent-service/secrets.env or box.yaml over SSH. Every step is idempotent:
#   1. fetch the pinned release archive (kept after a verified download) and check its sha256;
#   2. extract it (tar runs only on a verified archive);
#   3. stop with phase waiting_for_config / waiting_for_secrets until the owner delivers them;
#   4. ./box install --config /etc/agent-service/box.yaml, then ./box doctor.
# Secret values are never read or printed here; box reads secrets.env itself and prints names only.
# BOX_PROVISION_ROOT relocates every path (tests); production leaves it empty.
set -euo pipefail
umask 077

ROOT="${BOX_PROVISION_ROOT:-}"
ENV_FILE="$ROOT/etc/agent-service-box-provision/release.env"
WORK="$ROOT/var/lib/agent-service-box-provision"
CONFIG="$ROOT/etc/agent-service/box.yaml"
SECRETS="$ROOT/etc/agent-service/secrets.env"
mkdir -p "$WORK"

status() {  # phase, detail; one JSON object, replaced atomically
  printf '{"phase": "%s", "release": "%s", "detail": "%s", "at": "%s"}\n' \
    "$1" "${RELEASE_NAME:-}" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$WORK/status.json.tmp"
  mv "$WORK/status.json.tmp" "$WORK/status.json"
  echo "box-provision: $1 $2"
}

# release.env holds three KEY=value lines; parse them instead of sourcing a file.
RELEASE_URL="" RELEASE_SHA256="" RELEASE_NAME=""
while IFS='=' read -r key value; do
  case "$key" in
    RELEASE_URL) RELEASE_URL="$value" ;;
    RELEASE_SHA256) RELEASE_SHA256="$value" ;;
    RELEASE_NAME) RELEASE_NAME="$value" ;;
  esac
done < "$ENV_FILE"
if [[ ! "$RELEASE_URL" =~ ^https://github\.com/rengalaxies/agent/releases/download/[A-Za-z0-9._+/-]+\.tar\.gz$ ]] \
  || [[ ! "$RELEASE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || [[ ! "$RELEASE_NAME" =~ ^agent-service-[0-9A-Za-z.]+-g[0-9a-f]{12}-linux-x86_64-cp312$ ]]; then
  status release_env_invalid "release.env must hold a GitHub release URL, sha256 and release name"
  exit 1
fi

ARCHIVE="$WORK/$RELEASE_NAME.tar.gz"
verified() { echo "$RELEASE_SHA256  $ARCHIVE" | sha256sum -c --status - 2>/dev/null; }

if [ -f "$ARCHIVE" ] && ! verified; then
  rm -f "$ARCHIVE"
fi
if [ ! -f "$ARCHIVE" ]; then
  status downloading "$RELEASE_URL"
  rm -f "$ARCHIVE.part"
  if ! curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
      --retry 5 --retry-delay 10 --connect-timeout 20 --max-time 900 \
      --output "$ARCHIVE.part" "$RELEASE_URL"; then
    rm -f "$ARCHIVE.part"
    status download_failed "check outbound HTTPS to github.com"
    exit 1
  fi
  mv "$ARCHIVE.part" "$ARCHIVE"
fi
if ! verified; then
  rm -f "$ARCHIVE"
  status release_rejected "sha256 of the downloaded archive differs from the pinned value"
  exit 1
fi

RELEASES="$WORK/releases"
BOX="$RELEASES/$RELEASE_NAME/box"
if [ ! -x "$BOX" ]; then
  rm -rf "$RELEASES/.extract"
  mkdir -p "$RELEASES/.extract"
  tar -xzf "$ARCHIVE" -C "$RELEASES/.extract" --no-same-owner
  if [ "$(ls -A "$RELEASES/.extract")" != "$RELEASE_NAME" ] || [ ! -f "$RELEASES/.extract/$RELEASE_NAME/box" ]; then
    rm -rf "$RELEASES/.extract"
    status release_rejected "archive top directory is not $RELEASE_NAME"
    exit 1
  fi
  rm -rf "${RELEASES:?}/$RELEASE_NAME"
  mv "$RELEASES/.extract/$RELEASE_NAME" "$RELEASES/$RELEASE_NAME"
  rmdir "$RELEASES/.extract"
  chmod 0755 "$BOX"
fi

if [ ! -f "$CONFIG" ]; then
  status waiting_for_config "copy box.yaml to /etc/agent-service/box.yaml"
  exit 0
fi
if [ ! -f "$SECRETS" ]; then
  status waiting_for_secrets "copy secrets.env to /etc/agent-service/secrets.env (root, 600)"
  exit 0
fi
if [ "$(id -u)" = "0" ]; then
  chown 0:0 "$SECRETS"
  chmod 0600 "$SECRETS"
fi

status installing "./box install --config $CONFIG"
set +e
"$BOX" install --config "$CONFIG"
install_rc=$?
"$BOX" doctor
doctor_rc=$?
set -e
# box install: 0 scenario ready, 2 service up but scenario not ready, 1 not installed.
case "$install_rc" in
  0) phase=installed_ready ;;
  2) phase=installed_not_ready ;;
  *) phase=install_failed ;;
esac
status "$phase" "install_rc=$install_rc doctor_rc=$doctor_rc"
[ "$install_rc" = "1" ] && exit 1
exit 0
