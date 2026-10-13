#!/usr/bin/env bash
# Install hdmi-tester on Raspberry Pi OS (Bookworm or later).
# Usage: ./deploy/install.sh [--service] [--button-pin N]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV=/opt/hdmi-tester/venv
SERVICE=0
BUTTON_ARGS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) SERVICE=1 ;;
    --button-pin) BUTTON_ARGS="--button-pin $2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# Distro packages: prebuilt numpy/pygame (with the kmsdrm SDL backend) and
# gpiozero. Faster and more reliable on a Pi than building wheels with pip.
sudo apt-get update
sudo apt-get install -y python3-venv python3-numpy python3-pygame python3-gpiozero

# A venv that can see the apt packages; Bookworm blocks system-wide pip.
sudo mkdir -p /opt/hdmi-tester
sudo python3 -m venv --system-site-packages "$VENV"
sudo "$VENV/bin/pip" install --no-deps "$REPO_DIR"
sudo ln -sf "$VENV/bin/hdmi-tester" /usr/local/bin/hdmi-tester

# DRM (video) and keyboard (input) access without root.
sudo usermod -aG video,input,gpio "$USER"

if [[ $SERVICE == 1 ]]; then
  sed -e "s|@USER@|$USER|g" -e "s|@ARGS@|$BUTTON_ARGS|g" \
    "$REPO_DIR/deploy/hdmi-tester.service" \
    | sudo tee /etc/systemd/system/hdmi-tester.service >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable hdmi-tester.service
  echo "Service enabled: patterns will appear on HDMI at next boot."
fi

echo "Installed. Log out and back in (or reboot) for group changes to apply."
