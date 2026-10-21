#!/usr/bin/env bash
# Install the weather sensor receiver service, prepare the local forecast and
# sensor settings, and publish the collage weather badge.
# Run on the Pi from the repo:  bash ~/BirdNET-Pi/avian/thermopro/install.sh
# Safe to run again after every update: it restarts the receiver on new code.
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
user=${SUDO_USER:-$(id -un)}
env_file=/etc/avian/thermopro.env
unit=/etc/systemd/system/avian-thermopro.service

echo "Installing lgpio (RXB6) and rtl_433 (RTL-SDR dongle)..."
sudo apt-get install -y python3-lgpio rtl-sdr rtl-433

if [ ! -f "$env_file" ]; then
  sudo install -d -m 0755 /etc/avian
  echo 'THERMOPRO_ARGS=--gpio 27 --units F --print' | sudo tee "$env_file" >/dev/null
  echo "Wrote $env_file (GPIO, units and receivers; name sensors in Settings > Weather sensors)."
fi

# An RTL2832U dongle (R820T/R820T2 tuner) becomes the receiver: rtl_433 hears the
# AcuRite and ThermoPro far better than the RXB6 and also the 915 MHz La Crosse
# sensors, taking turns between the two bands and then resting (off, cool) for
# a minute each round. A streaming dongle deafens the RXB6, so the RXB6 listens
# only while the dongle rests or is missing.
if lsusb 2>/dev/null | grep -qiE '0bda:(2838|2832)'; then
  echo "RTL-SDR dongle found."
  # Linux claims these dongles as TV tuners; release it for rtl_433.
  if lsmod | grep -q '^dvb_usb_rtl28xxu'; then
    sudo modprobe -r dvb_usb_rtl28xxu rtl2832_sdr rtl2832 2>/dev/null || true
  fi
  if ! grep -q -- '--rtl433' "$env_file"; then
    sudo sed -i 's/^THERMOPRO_ARGS=\(.*\)$/THERMOPRO_ARGS=\1 --rtl433 --rtl433-freq 433.92M --rtl433-freq 915M/' "$env_file"
    echo "Switched to the RTL-SDR receiver, taking turns on 433.92 MHz and 915 MHz, in $env_file."
  elif grep -q -- '--rtl433 --no-gpio' "$env_file"; then
    # Older installs turned the RXB6 off entirely; now it covers the dongle's rests.
    sudo sed -i 's/--rtl433 --no-gpio/--rtl433/' "$env_file"
    echo "The RXB6 now listens while the dongle rests ($env_file)."
  fi
else
  echo "No RTL-SDR dongle plugged in; using the RXB6 on GPIO."
fi

sed -e "s#__USER__#${user}#g" -e "s#__REPO__#${repo}#g" \
  "$repo/avian/thermopro/avian-thermopro.service" | sudo tee "$unit" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable avian-thermopro.service
sudo systemctl restart avian-thermopro.service

echo "Preparing forecast and sensor settings storage..."
if [ ! -d /var/lib/avian-forecast ]; then
  sudo install -d -o caddy -g caddy -m 0750 /var/lib/avian-forecast
fi

echo "Publishing the badge files and API endpoints..."
sudo "$repo/scripts/link_webroot.sh"
sudo "$repo/scripts/update_caddyfile.sh"

echo
echo "Done. Watch readings with:  journalctl -fu avian-thermopro"
echo "Name or hide sensors in the pibird menu: Settings > Weather sensors."
