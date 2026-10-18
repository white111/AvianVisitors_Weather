#!/usr/bin/env bash
# Install the ThermoPro receiver service and publish the collage weather badge.
# Run on the Pi from the repo:  bash ~/BirdNET-Pi/avian/thermopro/install.sh
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
user=${SUDO_USER:-$(id -un)}
env_file=/etc/avian/thermopro.env
unit=/etc/systemd/system/avian-thermopro.service

echo "Installing lgpio..."
sudo apt-get install -y python3-lgpio

if [ ! -f "$env_file" ]; then
  sudo install -d -m 0755 /etc/avian
  echo 'THERMOPRO_ARGS=--gpio 27 --units F --label 1=Outside --print' | sudo tee "$env_file" >/dev/null
  echo "Wrote $env_file (edit GPIO, units and channel labels there)."
fi

sed -e "s#__USER__#${user}#g" -e "s#__REPO__#${repo}#g" \
  "$repo/avian/thermopro/avian-thermopro.service" | sudo tee "$unit" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now avian-thermopro.service

echo "Publishing the badge files and API endpoint..."
sudo "$repo/scripts/link_webroot.sh"
sudo "$repo/scripts/update_caddyfile.sh"

echo
echo "Done. Watch readings with:  journalctl -fu avian-thermopro"
echo "or stop the service and run:  python3 $repo/avian/thermopro/thermopro_rx.py --print --no-write"
