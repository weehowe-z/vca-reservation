from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from vca_reservation.boutiques import BOUTIQUES
from vca_reservation.client import VcaClient, VcaError
from vca_reservation.config import Config, ConfigError
from vca_reservation.monitor import Event, MonitorRunError, run_monitor
from vca_reservation.seatalk import SeaTalkDeliveryError, SeaTalkNotifier, format_event
from vca_reservation.state import StateError, StateStore


def build_client(config: Config) -> VcaClient:
    return VcaClient(timeout_seconds=config.timeout_seconds)


def build_notifier(config: Config) -> SeaTalkNotifier:
    if config.webhook_url is None:
        raise ConfigError("SEATALK_WEBHOOK_URL is required")
    return SeaTalkNotifier(config.webhook_url, timeout_seconds=config.timeout_seconds)


def build_store(config: Config) -> StateStore:
    return StateStore(config.state_path)


def japan_now() -> datetime:
    return datetime.now(tz=ZoneInfo("Asia/Tokyo"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor VCA Japan jewelry appointments")
    parser.add_argument("command", choices=("run", "smoke", "test-webhook"))
    args = parser.parse_args(argv)

    try:
        if args.command == "smoke":
            config = Config.from_env(require_webhook=False)
            snapshot = build_client(config).fetch_snapshot(BOUTIQUES)
            print(format_event(Event("initial", japan_now(), snapshot)))
            return 0

        config = Config.from_env(require_webhook=True)
        notifier = build_notifier(config)
        if args.command == "test-webhook":
            checked_at = japan_now().strftime("%Y-%m-%d %H:%M")
            notifier.send(
                f"VCA 预约监控测试：Webhook 已连接成功。\n日本时间：{checked_at}",
                mention_all=False,
            )
            return 0

        run_monitor(build_client(config), notifier, build_store(config), japan_now())
        return 0
    except (ConfigError, VcaError, MonitorRunError, StateError, SeaTalkDeliveryError) as exc:
        print(f"vca-reservation: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("vca-reservation: unexpected failure", file=sys.stderr)
        return 1


def entrypoint() -> None:
    raise SystemExit(main())
