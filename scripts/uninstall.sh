#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this uninstaller with sudo." >&2
  exit 1
fi

purge=false
if [[ ${1:-} == "--purge" ]]; then
  purge=true
elif [[ $# -ne 0 ]]; then
  echo "Usage: sudo ./scripts/uninstall.sh [--purge]" >&2
  exit 1
fi

systemctl disable --now vca-reservation.timer >/dev/null 2>&1 || true
systemctl stop vca-reservation.service >/dev/null 2>&1 || true
rm -f -- /etc/systemd/system/vca-reservation.timer
rm -f -- /etc/systemd/system/vca-reservation.service
rm -rf -- /opt/vca-reservation
systemctl daemon-reload
systemctl reset-failed vca-reservation.service >/dev/null 2>&1 || true

if [[ ${purge} == true ]]; then
  rm -f -- /etc/vca-reservation.env
  rm -rf -- /var/lib/vca-reservation
  if id -u vca-reservation >/dev/null 2>&1; then
    userdel vca-reservation
  fi
  echo "Uninstalled and purged configuration, state, and the service user."
else
  echo "Uninstalled; configuration and state were preserved. Use --purge to remove them."
fi
