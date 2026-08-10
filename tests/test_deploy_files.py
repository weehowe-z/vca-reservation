from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_timer_is_hourly_and_persistent():
    timer = (ROOT / "deploy/vca-reservation.timer").read_text()

    assert "OnCalendar=hourly" in timer
    assert "Persistent=true" in timer
    assert "Unit=vca-reservation.service" in timer


def test_service_uses_dedicated_user_state_directory_and_hardening():
    service = (ROOT / "deploy/vca-reservation.service").read_text()

    assert "Type=oneshot" in service
    assert "User=vca-reservation" in service
    assert "StateDirectory=vca-reservation" in service
    assert "EnvironmentFile=/etc/vca-reservation.env" in service
    assert "ExecStart=/opt/vca-reservation/.venv/bin/vca-reservation run" in service
    for setting in (
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
    ):
        assert setting in service


def test_scripts_are_executable_and_valid_bash():
    for relative in ("scripts/install.sh", "scripts/uninstall.sh", "scripts/build-fc-package.sh"):
        path = ROOT / relative
        assert os.access(path, os.X_OK)
        subprocess.run(["bash", "-n", path], check=True)


def test_environment_example_has_no_usable_webhook():
    example = (ROOT / "deploy/vca-reservation.env.example").read_text()

    assert "SEATALK_WEBHOOK_URL=" in example
    assert "REPLACE_WITH_YOUR_GROUP_WEBHOOK" in example


def test_repository_contains_no_real_seatalk_webhook():
    credential_pattern = re.compile(
        r"https://openapi\.seatalk\.io/webhook/group/[A-Za-z0-9_-]{10,}"
    )
    tracked_and_untracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    for relative in tracked_and_untracked:
        path = ROOT / relative
        if path.is_file():
            assert credential_pattern.search(path.read_text(errors="ignore")) is None, relative
