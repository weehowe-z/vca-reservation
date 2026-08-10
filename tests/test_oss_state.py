from __future__ import annotations

from pathlib import Path

import pytest

from vca_reservation.oss_state import ObjectNotFoundError, OssStateStore
from vca_reservation.state import MonitorState, StateStore


class FakeObjectStore:
    def __init__(self) -> None:
        self.blobs: dict[str, str] = {}
        self.puts: list[str] = []

    def get_object_to_file(self, key: str, filename: str) -> None:
        if key not in self.blobs:
            raise ObjectNotFoundError(key)
        Path(filename).write_text(self.blobs[key], encoding="utf-8")

    def put_object_from_file(self, key: str, filename: str) -> None:
        self.blobs[key] = Path(filename).read_text(encoding="utf-8")
        self.puts.append(key)


@pytest.fixture
def objects() -> FakeObjectStore:
    return FakeObjectStore()


def test_load_returns_empty_state_when_object_missing(tmp_path, objects):
    store = OssStateStore(objects, "state.json", tmp_path / "state.json")

    assert store.load() == MonitorState()


def test_save_then_load_round_trips_state(objects):
    initial = StateStore(Path("unused")).load()
    store = OssStateStore(objects, "state.json", "/tmp/vca-faas-state.json")

    store.save(MonitorState(consecutive_failures=2))

    assert objects.blobs["state.json"] is not None
    loaded = store.load()
    assert loaded == MonitorState(consecutive_failures=2)
    assert loaded.last_snapshot is None
    assert initial == MonitorState()


def test_save_puts_remote_object(objects):
    store = OssStateStore(objects, "state.json", "/tmp/vca-faas-state.json")

    store.save(MonitorState())

    assert objects.puts == ["state.json"]