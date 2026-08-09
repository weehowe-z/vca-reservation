#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE=/etc/vca-reservation.env
INSTALL_DIR=/opt/vca-reservation

if [[ ! -f ${ENV_FILE} ]]; then
  echo "Missing /etc/vca-reservation.env; create it from deploy/vca-reservation.env.example." >&2
  exit 1
fi

webhook_value=""
while IFS='=' read -r key value; do
  if [[ ${key} == "SEATALK_WEBHOOK_URL" ]]; then
    webhook_value=${value%$'\r'}
  fi
done < "${ENV_FILE}"

case "${webhook_value}" in
  https://openapi.seatalk.io/webhook/group/?*) ;;
  *)
    echo "SEATALK_WEBHOOK_URL is missing or invalid." >&2
    exit 1
    ;;
esac

chmod 0600 "${ENV_FILE}"
chown root:root "${ENV_FILE}"

if ! id -u vca-reservation >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/vca-reservation --shell /usr/sbin/nologin vca-reservation
fi

python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || {
  echo "Python 3.11 or newer is required." >&2
  exit 1
}

install -d -m 0755 "${INSTALL_DIR}"
if [[ ! -x ${INSTALL_DIR}/.venv/bin/python ]]; then
  python3 -m venv "${INSTALL_DIR}/.venv"
fi
"${INSTALL_DIR}/.venv/bin/python" -m pip install --upgrade --no-deps "${REPO_ROOT}"

install -m 0644 "${REPO_ROOT}/deploy/vca-reservation.service" /etc/systemd/system/
install -m 0644 "${REPO_ROOT}/deploy/vca-reservation.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vca-reservation.timer

echo "Installed. Next run:"
systemctl list-timers vca-reservation.timer --no-pager
