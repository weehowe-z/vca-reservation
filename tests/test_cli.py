from __future__ import annotations

from datetime import datetime
from unittest.mock import ANY, Mock

from vca_reservation import cli
from vca_reservation.models import BoutiqueAvailability, DateAvailability

OPEN_SNAPSHOT = (
    BoutiqueAvailability(
        "shop",
        "广岛",
        "福屋八丁堀本店",
        (DateAvailability("2026-08-18", ("14:00",)),),
    ),
)


class StubClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def fetch_snapshot(self, boutiques):
        del boutiques
        return self.snapshot


def test_smoke_never_constructs_notifier(monkeypatch, capsys):
    monkeypatch.delenv("SEATALK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(cli, "build_client", lambda config: StubClient(OPEN_SNAPSHOT))
    monkeypatch.setattr(cli, "build_notifier", Mock(side_effect=AssertionError("must not run")))

    assert cli.main(["smoke"]) == 0
    assert "福屋八丁堀本店" in capsys.readouterr().out


def test_test_webhook_never_queries_vca(monkeypatch):
    monkeypatch.setenv(
        "SEATALK_WEBHOOK_URL", "https://openapi.seatalk.io/webhook/group/test"
    )
    notifier = Mock()
    monkeypatch.setattr(cli, "build_notifier", lambda config: notifier)
    monkeypatch.setattr(cli, "build_client", Mock(side_effect=AssertionError("must not run")))

    assert cli.main(["test-webhook"]) == 0
    notifier.send.assert_called_once_with(ANY, mention_all=False)


def test_run_builds_production_dependencies(monkeypatch):
    monkeypatch.setenv(
        "SEATALK_WEBHOOK_URL", "https://openapi.seatalk.io/webhook/group/test"
    )
    client = Mock()
    notifier = Mock()
    store = Mock()
    run = Mock()
    monkeypatch.setattr(cli, "build_client", lambda config: client)
    monkeypatch.setattr(cli, "build_notifier", lambda config: notifier)
    monkeypatch.setattr(cli, "build_store", lambda config: store)
    monkeypatch.setattr(cli, "run_monitor", run)
    monkeypatch.setattr(cli, "japan_now", lambda: datetime(2026, 8, 10, 12, 0))

    assert cli.main(["run"]) == 0
    run.assert_called_once_with(client, notifier, store, datetime(2026, 8, 10, 12, 0))


def test_config_error_returns_one_without_secret(monkeypatch, capsys):
    secret = "https://invalid.example/secret-token"
    monkeypatch.setenv("SEATALK_WEBHOOK_URL", secret)

    assert cli.main(["test-webhook"]) == 1
    assert secret not in capsys.readouterr().err
