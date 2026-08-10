from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Protocol

from vca_reservation.state import MonitorState, StateError, StateStore


class ObjectStore(Protocol):
    def get_object_to_file(self, key: str, filename: str) -> None: ...

    def put_object_from_file(self, key: str, filename: str) -> None: ...


class ObjectNotFoundError(RuntimeError):
    """The requested object does not exist in the object store."""


class OssStateStore:
    def __init__(self, objects: ObjectStore, object_key: str, local_path: Path | str) -> None:
        self._objects = objects
        self._object_key = object_key
        self._local_state = StateStore(Path(local_path))

    def load(self) -> MonitorState:
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            local_path = Path(temporary.name)
        try:
            try:
                self._objects.get_object_to_file(self._object_key, str(local_path))
            except ObjectNotFoundError:
                return MonitorState()
            return self._local_state.load()
        except StateError:
            raise
        except OSError as exc:
            raise StateError("could not read remote state") from exc
        finally:
            local_path.unlink(missing_ok=True)

    def save(self, state: MonitorState) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            local_path = Path(temporary.name)
        try:
            self._local_state.save(state)
            self._objects.put_object_from_file(self._object_key, str(local_path))
        except StateError:
            raise
        except OSError as exc:
            raise StateError("could not persist remote state") from exc
        finally:
            local_path.unlink(missing_ok=True)