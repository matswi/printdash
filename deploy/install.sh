#!/usr/bin/env bash
# Installs or updates Printdash on a Raspberry Pi (Debian/Raspberry Pi OS).
# Run from the repository root:  sudo ./deploy/install.sh
set -euo pipefail

PREFIX=/opt/printdash
SRC="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

echo "==> Installing system packages"
apt-get install -y --no-install-recommends python3-venv python3-cups

echo "==> Creating user printdash (member of lpadmin)"
if ! id printdash &>/dev/null; then
  useradd --system --no-create-home --shell /usr/sbin/nologin printdash
fi
usermod -aG lpadmin printdash

echo "==> Copying files to $PREFIX"
mkdir -p "$PREFIX"
cp -r "$SRC/app" "$SRC/requirements.txt" "$PREFIX/"

echo "==> Creating virtual environment"
# --system-site-packages so that python3-cups from apt is visible in the venv
[[ -d "$PREFIX/.venv" ]] || python3 -m venv --system-site-packages "$PREFIX/.venv"
"$PREFIX/.venv/bin/pip" install --quiet --upgrade -r "$PREFIX/requirements.txt"

if [[ ! -f /etc/printdash.env ]]; then
  echo "==> Creating /etc/printdash.env"
  cat > /etc/printdash.env <<'EOF'
# Uncomment to require a password for the web interface
# PRINTDASH_PASSWORD=change-me
EOF
  chmod 640 /etc/printdash.env
  chgrp printdash /etc/printdash.env
fi

echo "==> Installing systemd service"
cp "$SRC/deploy/printdash.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now printdash
systemctl restart printdash

IP=$(hostname -I | awk '{print $1}')
echo
echo "Done! Open http://$IP:8080"
