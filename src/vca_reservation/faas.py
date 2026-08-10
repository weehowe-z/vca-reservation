from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from vca_reservation.boutiques import BOUTIQUES
from vca_reservation.cli import build_client, build_notifier
from vca_reservation.config import Config, ConfigError
from vca_reservation.monitor import run_monitor
from vca_reservation.oss_state import OssStateStore

LOCAL_STATE_PATH = Path("/tmp/vca-reservation-state.json")


class Credentials(NamedTuple):
    access_key_id: str
    access_key_secret: str
    security_token: str


def japan_now() -> datetime:
    return datetime.now(tz=ZoneInfo("Asia/Tokyo"))


def _credentials_from(context: Any) -> Credentials:
    credentials = getattr(context, "credentials", None)
    if credentials is not None:
        access_key_id = getattr(credentials, "access_key_id", None)
        access_key_secret = getattr(credentials, "access_key_secret", None)
        security_token = getattr(credentials, "security_token", None)
        if access_key_id and access_key_secret and security_token:
            return Credentials(access_key_id, access_key_secret, security_token)

    access_key_id = os.environ.get("VCA_OSS_ACCESS_KEY_ID")
    access_key_secret = os.environ.get("VCA_OSS_ACCESS_KEY_SECRET")
    security_token = os.environ.get("VCA_OSS_SECURITY_TOKEN", "")
    if access_key_id and access_key_secret:
        return Credentials(access_key_id, access_key_secret, security_token)
    raise ConfigError("VCA_OSS_ACCESS_KEY_ID and VCA_OSS_ACCESS_KEY_SECRET are required")


def build_oss_store(config: Config, credentials: Credentials) -> OssStateStore:
    endpoint = os.environ.get("VCA_OSS_ENDPOINT")
    bucket_name = os.environ.get("VCA_OSS_BUCKET")
    if not endpoint or not bucket_name:
        raise ConfigError("VCA_OSS_ENDPOINT and VCA_OSS_BUCKET are required")
    object_key = os.environ.get("VCA_OSS_STATE_KEY", "state.json")

    try:
        import oss2
    except ImportError as exc:
        raise ConfigError("oss2 is required for Function Compute deployment") from exc

    auth = oss2.StsAuth(
        credentials.access_key_id,
        credentials.access_key_secret,
        credentials.security_token,
    )
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    return OssStateStore(bucket, object_key, LOCAL_STATE_PATH)


def handler(event: Any = None, context: Any = None) -> str:
    config = Config.from_env(require_webhook=True)
    store = build_oss_store(config, _credentials_from(context))
    run_monitor(
        build_client(config),
        build_notifier(config),
        store,
        japan_now(),
        BOUTIQUES,
    )
    return "ok"