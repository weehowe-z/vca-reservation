from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

SEATALK_WEBHOOK_PREFIX = "https://openapi.seatalk.io/webhook/group/"
DEFAULT_STATE_PATH = Path("/var/lib/vca-reservation/state.json")


class ConfigError(ValueError):
    """Environment configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    webhook_url: str | None = field(repr=False)
    state_path: Path = DEFAULT_STATE_PATH
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls, require_webhook: bool) -> Config:
        webhook_url = os.environ.get("SEATALK_WEBHOOK_URL") or None
        if require_webhook and webhook_url is None:
            raise ConfigError("SEATALK_WEBHOOK_URL is required")
        if webhook_url is not None and (
            not webhook_url.startswith(SEATALK_WEBHOOK_PREFIX)
            or len(webhook_url) <= len(SEATALK_WEBHOOK_PREFIX)
        ):
            raise ConfigError("SEATALK_WEBHOOK_URL must be a SeaTalk group webhook URL")

        state_value = os.environ.get("VCA_STATE_PATH", str(DEFAULT_STATE_PATH))
        if not state_value.strip():
            raise ConfigError("VCA_STATE_PATH must not be empty")

        timeout_value = os.environ.get("VCA_HTTP_TIMEOUT_SECONDS", "15")
        try:
            timeout_seconds = float(timeout_value)
        except ValueError as exc:
            raise ConfigError("VCA_HTTP_TIMEOUT_SECONDS must be a positive number") from exc
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ConfigError("VCA_HTTP_TIMEOUT_SECONDS must be a positive number")

        return cls(webhook_url, Path(state_value), timeout_seconds)
