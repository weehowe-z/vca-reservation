from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from vca_reservation.config import ConfigError
from vca_reservation.faas import Credentials, _credentials_from, build_oss_store, handler


def test_credentials_from_context_sts_auth():
    context = SimpleNamespace(
        credentials=SimpleNamespace(
            access_key_id="ak",
            access_key_secret="sk",
            security_token="token",
        )
    )

    assert _credentials_from(context) == Credentials("ak", "sk", "token")


def test_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("VCA_OSS_ACCESS_KEY_ID", "env-ak")
    monkeypatch.setenv("VCA_OSS_ACCESS_KEY_SECRET", "env-sk")

    assert _credentials_from(None) == Credentials("env-ak", "env-sk", "")


def test_credentials_require_keys(monkeypatch):
    monkeypatch.delenv("VCA_OSS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("VCA_OSS_ACCESS_KEY_SECRET", raising=False)

    with pytest.raises(ConfigError, match="VCA_OSS_ACCESS_KEY_ID"):
        _credentials_from(None)


def test_build_oss_store_requires_endpoint_and_bucket(monkeypatch):
    monkeypatch.delenv("VCA_OSS_ENDPOINT", raising=False)
    monkeypatch.delenv("VCA_OSS_BUCKET", raising=False)

    with pytest.raises(ConfigError, match="VCA_OSS_ENDPOINT"):
        build_oss_store(SimpleNamespace(), Credentials("a", "b", ""))


def test_build_oss_store_requires_oss2(monkeypatch):
    monkeypatch.setenv("VCA_OSS_ENDPOINT", "https://oss-cn-hangzhou.aliyuncs.com")
    monkeypatch.setenv("VCA_OSS_BUCKET", "bucket")
    monkeypatch.setitem(sys.modules, "oss2", None)

    with pytest.raises(ConfigError, match="oss2"):
        build_oss_store(SimpleNamespace(), Credentials("a", "b", ""))


def test_handler_runs_monitor(monkeypatch):
    calls: list[str] = []

    def fake_config(*args, **kwargs):
        return SimpleNamespace(timeout_seconds=15.0)

    def fake_run(client, notifier, store, checked_at, boutiques):
        calls.append("run")

    monkeypatch.setattr("vca_reservation.faas.Config.from_env", fake_config)
    monkeypatch.setattr("vca_reservation.faas._credentials_from", lambda *a: Credentials("a", "b", ""))
    monkeypatch.setattr("vca_reservation.faas.build_oss_store", lambda *a: object())
    monkeypatch.setattr("vca_reservation.faas.build_client", lambda config: object())
    monkeypatch.setattr("vca_reservation.faas.build_notifier", lambda config: object())
    monkeypatch.setattr("vca_reservation.faas.run_monitor", fake_run)

    assert handler(event={}, context=None) == "ok"
    assert calls == ["run"]