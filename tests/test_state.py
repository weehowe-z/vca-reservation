from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

from vca_reservation.models import BoutiqueAvailability, DateAvailability
from vca_reservation.state import MonitorState, StateStore, StateWriteError

OLD_SNAPSHOT = (
    BoutiqueAvailability("boutique-1", "大阪", "店一", ()),
)
NEW_SNAPSHOT = (
    BoutiqueAvailability(
        "boutique-1",
        "大阪",
        "店一",
        (DateAvailability("2026-08-18", ("14:00",)),),
    ),
)


def test_state_round_trip_preserves_snapshot_and_private_permissions(tmp_path):
    store = StateStore(tmp_path / "nested" / "state.json")
    state = MonitorState(
        last_snapshot=NEW_SNAPSHOT,
        consecutive_failures=2,
        failure_alerted=True,
    )

    store.save(state)

    assert store.load() == state
    assert (store.path.stat().st_mode & 0o777) == 0o600


def test_missing_state_is_fresh(tmp_path):
    assert StateStore(tmp_path / "state.json").load() == MonitorState()


def test_failed_replace_leaves_previous_state_readable(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state.json")
    store.save(MonitorState(last_snapshot=OLD_SNAPSHOT))
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("disk error")))

    with pytest.raises(StateWriteError, match="could not persist monitor state"):
        store.save(MonitorState(last_snapshot=NEW_SNAPSHOT))

    assert store.load().last_snapshot == OLD_SNAPSHOT
    assert list(tmp_path.glob("*.tmp")) == []
