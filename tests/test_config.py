from __future__ import annotations

import pytest

from vca_reservation.config import Config, ConfigError


def test_run_requires_seatalk_webhook(monkeypatch):
    monkeypatch.delenv("SEATALK_WEBHOOK_URL", raising=False)

    with pytest.raises(ConfigError, match="SEATALK_WEBHOOK_URL is required"):
        Config.from_env(require_webhook=True)


def test_config_rejects_non_positive_timeout(monkeypatch):
    monkeypatch.setenv("VCA_HTTP_TIMEOUT_SECONDS", "0")

    with pytest.raises(ConfigError, match="must be a positive number"):
        Config.from_env(require_webhook=False)


def test_config_rejects_non_seatalk_url_without_disclosing_it(monkeypatch):
    secret = "https://invalid.example/super-secret"
    monkeypatch.setenv("SEATALK_WEBHOOK_URL", secret)

    with pytest.raises(ConfigError) as error:
        Config.from_env(require_webhook=True)

    assert secret not in str(error.value)


def test_config_repr_hides_webhook(monkeypatch):
    secret = "https://openapi.seatalk.io/webhook/group/test"
    monkeypatch.setenv("SEATALK_WEBHOOK_URL", secret)

    config = Config.from_env(require_webhook=True)

    assert secret not in repr(config)
    assert config.webhook_url == secret
