from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from vca_reservation.models import BoutiqueAvailability, DateAvailability, Snapshot

STATE_VERSION = 1


class StateError(RuntimeError):
    """Base exception for local state failures."""


class StateReadError(StateError):
    """The persisted monitor state is unreadable or malformed."""


class StateWriteError(StateError):
    """The monitor state could not be safely persisted."""


@dataclass(frozen=True)
class MonitorState:
    last_snapshot: Snapshot | None = None
    consecutive_failures: int = 0
    failure_alerted: bool = False


class StateStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> MonitorState:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return MonitorState()
        except OSError as exc:
            raise StateReadError("could not read monitor state") from exc
        try:
            payload = json.loads(raw)
            return _state_from_json(payload)
        except (JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise StateReadError("monitor state is malformed") from exc

    def save(self, state: MonitorState) -> None:
        temp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": STATE_VERSION,
                "last_snapshot": (
                    None
                    if state.last_snapshot is None
                    else [asdict(boutique) for boutique in state.last_snapshot]
                ),
                "consecutive_failures": state.consecutive_failures,
                "failure_alerted": state.failure_alerted,
            }
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temp_path = Path(temporary.name)
                os.chmod(temporary.name, 0o600)
                json.dump(payload, temporary, ensure_ascii=False, separators=(",", ":"))
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
        except (OSError, TypeError, ValueError) as exc:
            raise StateWriteError("could not persist monitor state") from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass


def _state_from_json(payload: Any) -> MonitorState:
    if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
        raise ValueError("unsupported state version")
    failure_count = payload["consecutive_failures"]
    failure_alerted = payload["failure_alerted"]
    if isinstance(failure_count, bool) or not isinstance(failure_count, int) or failure_count < 0:
        raise ValueError("invalid consecutive_failures")
    if not isinstance(failure_alerted, bool):
        raise ValueError("invalid failure_alerted")
    snapshot_payload = payload["last_snapshot"]
    snapshot = None if snapshot_payload is None else _snapshot_from_json(snapshot_payload)
    return MonitorState(snapshot, failure_count, failure_alerted)


def _snapshot_from_json(payload: Any) -> Snapshot:
    if not isinstance(payload, list):
        raise ValueError("invalid snapshot")
    boutiques: list[BoutiqueAvailability] = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("dates"), list):
            raise ValueError("invalid boutique snapshot")
        dates: list[DateAvailability] = []
        for date_item in item["dates"]:
            if not isinstance(date_item, dict) or not isinstance(date_item.get("times"), list):
                raise ValueError("invalid date snapshot")
            record_date = date_item.get("date")
            times = date_item["times"]
            if not isinstance(record_date, str) or not all(isinstance(value, str) for value in times):
                raise ValueError("invalid date snapshot values")
            dates.append(DateAvailability(record_date, tuple(times)))
        boutique_id = item.get("boutique_id")
        city = item.get("city")
        name = item.get("name")
        if not all(isinstance(value, str) for value in (boutique_id, city, name)):
            raise ValueError("invalid boutique snapshot values")
        boutiques.append(BoutiqueAvailability(boutique_id, city, name, tuple(dates)))
    return tuple(boutiques)
