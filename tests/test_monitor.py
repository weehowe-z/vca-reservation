from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vca_reservation.models import BoutiqueAvailability, DateAvailability
from vca_reservation.monitor import (
    MonitorRunError,
    decide_success,
    record_failure,
    run_monitor,
)
from vca_reservation.state import MonitorState

CHECKED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
EMPTY_SNAPSHOT = (BoutiqueAvailability("shop", "广岛", "店", ()),)
OPEN_SNAPSHOT = (
    BoutiqueAvailability(
        "shop",
        "广岛",
        "店",
        (DateAvailability("2026-08-18", ("14:00",)),),
    ),
)


@pytest.mark.parametrize(
    ("state", "snapshot", "kind", "mention_all"),
    [
        (MonitorState(), EMPTY_SNAPSHOT, "initial", False),
        (MonitorState(last_snapshot=EMPTY_SNAPSHOT), EMPTY_SNAPSHOT, "heartbeat", False),
        (MonitorState(last_snapshot=EMPTY_SNAPSHOT), OPEN_SNAPSHOT, "changed", True),
        (
            MonitorState(last_snapshot=OPEN_SNAPSHOT, failure_alerted=True),
            OPEN_SNAPSHOT,
            "recovery",
            False,
        ),
        (
            MonitorState(last_snapshot=EMPTY_SNAPSHOT, failure_alerted=True),
            OPEN_SNAPSHOT,
            "recovery_changed",
            True,
        ),
    ],
)
def test_decide_success(state, snapshot, kind, mention_all):
    event, next_state = decide_success(state, snapshot, CHECKED_AT)

    assert event.kind == kind
    assert event.mention_all is mention_all
    assert next_state == MonitorState(last_snapshot=snapshot)


def test_changed_event_contains_added_and_removed_slots():
    newer = (
        BoutiqueAvailability(
            "shop",
            "广岛",
            "店",
            (DateAvailability("2026-08-18", ("15:00",)),),
        ),
    )

    event, _ = decide_success(MonitorState(last_snapshot=OPEN_SNAPSHOT), newer, CHECKED_AT)

    assert [(slot.date, slot.time) for slot in event.added] == [("2026-08-18", "15:00")]
    assert [(slot.date, slot.time) for slot in event.removed] == [("2026-08-18", "14:00")]


def test_third_failure_becomes_alertable_once():
    third = record_failure(MonitorState(consecutive_failures=2))
    fourth = record_failure(replace(third, failure_alerted=True))

    assert third.consecutive_failures == 3
    assert third.failure_alerted is False
    assert fourth.consecutive_failures == 4
    assert fourth.failure_alerted is True


class StubClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def fetch_snapshot(self, boutiques):
        del boutiques
        if self.error:
            raise self.error
        return self.result


class MemoryStore:
    def __init__(self, state):
        self.state = state
        self.saved = []

    def load(self):
        return self.state

    def save(self, state):
        self.state = state
        self.saved.append(state)


class RecordingNotifier:
    def __init__(self, event_error=None):
        self.events = []
        self.failures = []
        self.event_error = event_error

    def notify_event(self, event):
        if self.event_error:
            raise self.event_error
        self.events.append(event)

    def notify_failure(self, count, checked_at):
        self.failures.append((count, checked_at))


def test_success_sends_once_then_saves_snapshot():
    store = MemoryStore(MonitorState(last_snapshot=EMPTY_SNAPSHOT))
    notifier = RecordingNotifier()

    event = run_monitor(StubClient(OPEN_SNAPSHOT), notifier, store, CHECKED_AT, boutiques=())

    assert event.kind == "changed"
    assert notifier.events == [event]
    assert store.state == MonitorState(last_snapshot=OPEN_SNAPSHOT)


def test_delivery_failure_does_not_advance_success_snapshot():
    store = MemoryStore(MonitorState(last_snapshot=EMPTY_SNAPSHOT))
    notifier = RecordingNotifier(event_error=RuntimeError("send failed"))

    with pytest.raises(RuntimeError, match="send failed"):
        run_monitor(StubClient(OPEN_SNAPSHOT), notifier, store, CHECKED_AT, boutiques=())

    assert store.saved == []
    assert store.state.last_snapshot == EMPTY_SNAPSHOT


def test_third_check_failure_sends_one_alert_and_preserves_snapshot():
    store = MemoryStore(MonitorState(last_snapshot=OPEN_SNAPSHOT, consecutive_failures=2))
    notifier = RecordingNotifier()

    with pytest.raises(MonitorRunError, match="availability check failed"):
        run_monitor(
            StubClient(error=RuntimeError("upstream")),
            notifier,
            store,
            CHECKED_AT,
            boutiques=(),
        )

    assert notifier.failures == [(3, CHECKED_AT)]
    assert store.state == MonitorState(
        last_snapshot=OPEN_SNAPSHOT,
        consecutive_failures=3,
        failure_alerted=True,
    )


def test_fourth_check_failure_does_not_repeat_alert():
    store = MemoryStore(
        MonitorState(last_snapshot=OPEN_SNAPSHOT, consecutive_failures=3, failure_alerted=True)
    )
    notifier = RecordingNotifier()

    with pytest.raises(MonitorRunError):
        run_monitor(
            StubClient(error=RuntimeError("upstream")),
            notifier,
            store,
            CHECKED_AT,
            boutiques=(),
        )

    assert notifier.failures == []
    assert store.state.consecutive_failures == 4
