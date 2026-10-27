#!/usr/bin/env bash
# Installerar eller uppdaterar Printdash på en Raspberry Pi (Debian/Raspberry Pi OS).
# Kör från repots rotkatalog:  sudo ./deploy/install.sh
set -euo pipefail

PREFIX=/opt/printdash
SRC="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Kör med sudo: sudo $0" >&2
  exit 1
fi

echo "==> Installerar systempaket"
apt-get install -y --no-install-recommends python3-venv python3-cups

echo "==> Skapar användaren printdash (medlem i lpadmin)"
if ! id printdash &>/dev/null; then
  useradd --system --no-create-home --shell /usr/sbin/nologin printdash
fi
usermod -aG lpadmin printdash

echo "==> Kopierar filer till $PREFIX"
mkdir -p "$PREFIX"
cp -r "$SRC/app" "$SRC/requirements.txt" "$PREFIX/"

echo "==> Skapar virtuell miljö"
# --system-site-packages så att python3-cups från apt syns i miljön
[[ -d "$PREFIX/.venv" ]] || python3 -m venv --system-site-packages "$PREFIX/.venv"
"$PREFIX/.venv/bin/pip" install --quiet --upgrade -r "$PREFIX/requirements.txt"

if [[ ! -f /etc/printdash.env ]]; then
  echo "==> Skapar /etc/printdash.env"
  cat > /etc/printdash.env <<'EOF'
# Avkommentera för att kräva lösenord i webbgränssnittet
# PRINTDASH_PASSWORD=byt-mig
EOF
  chmod 640 /etc/printdash.env
  chgrp printdash /etc/printdash.env
fi

echo "==> Installerar systemd-tjänsten"
cp "$SRC/deploy/printdash.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now printdash
systemctl restart printdash

IP=$(hostname -I | awk '{print $1}')
echo
echo "Klart! Öppna http://$IP:8080"
