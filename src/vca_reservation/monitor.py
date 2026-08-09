from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Protocol

from vca_reservation.boutiques import BOUTIQUES
from vca_reservation.models import Boutique, Snapshot
from vca_reservation.state import MonitorState, StateStore

EventKind = Literal["initial", "heartbeat", "changed", "recovery", "recovery_changed"]


class MonitorRunError(RuntimeError):
    """The current upstream availability check failed."""


@dataclass(frozen=True, order=True)
class SlotRef:
    boutique_id: str
    city: str
    boutique_name: str
    date: str
    time: str


@dataclass(frozen=True)
class Event:
    kind: EventKind
    checked_at: datetime
    snapshot: Snapshot
    added: tuple[SlotRef, ...] = ()
    removed: tuple[SlotRef, ...] = ()
    mention_all: bool = False


class AvailabilityClient(Protocol):
    def fetch_snapshot(self, boutiques: tuple[Boutique, ...]) -> Snapshot: ...


class EventNotifier(Protocol):
    def notify_event(self, event: Event) -> None: ...

    def notify_failure(self, count: int, checked_at: datetime) -> None: ...


def decide_success(
    state: MonitorState,
    snapshot: Snapshot,
    checked_at: datetime,
) -> tuple[Event, MonitorState]:
    previous = state.last_snapshot
    changed = previous is not None and previous != snapshot
    if previous is None:
        kind: EventKind = "initial"
    elif state.failure_alerted and changed:
        kind = "recovery_changed"
    elif state.failure_alerted:
        kind = "recovery"
    elif changed:
        kind = "changed"
    else:
        kind = "heartbeat"

    previous_slots = {} if previous is None else _flatten(previous)
    current_slots = _flatten(snapshot)
    added_keys = current_slots.keys() - previous_slots.keys()
    removed_keys = previous_slots.keys() - current_slots.keys()
    event = Event(
        kind=kind,
        checked_at=checked_at,
        snapshot=snapshot,
        added=tuple(sorted(current_slots[key] for key in added_keys)),
        removed=tuple(sorted(previous_slots[key] for key in removed_keys)),
        mention_all=changed,
    )
    return event, MonitorState(last_snapshot=snapshot)


def record_failure(state: MonitorState) -> MonitorState:
    return replace(state, consecutive_failures=state.consecutive_failures + 1)


def run_monitor(
    client: AvailabilityClient,
    notifier: EventNotifier,
    store: StateStore,
    checked_at: datetime,
    boutiques: tuple[Boutique, ...] = BOUTIQUES,
) -> Event:
    state = store.load()
    try:
        snapshot = client.fetch_snapshot(boutiques)
    except Exception as exc:
        failed_state = record_failure(state)
        store.save(failed_state)
        if failed_state.consecutive_failures >= 3 and not failed_state.failure_alerted:
            notifier.notify_failure(failed_state.consecutive_failures, checked_at)
            failed_state = replace(failed_state, failure_alerted=True)
            store.save(failed_state)
        raise MonitorRunError("VCA availability check failed") from exc

    event, next_state = decide_success(state, snapshot, checked_at)
    notifier.notify_event(event)
    store.save(next_state)
    return event


def _flatten(snapshot: Snapshot) -> dict[tuple[str, str, str], SlotRef]:
    slots: dict[tuple[str, str, str], SlotRef] = {}
    for boutique in snapshot:
        for available_date in boutique.dates:
            for available_time in available_date.times:
                key = (boutique.boutique_id, available_date.date, available_time)
                slots[key] = SlotRef(
                    boutique_id=boutique.boutique_id,
                    city=boutique.city,
                    boutique_name=boutique.name,
                    date=available_date.date,
                    time=available_time,
                )
    return slots
