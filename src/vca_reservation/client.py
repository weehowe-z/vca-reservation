from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from vca_reservation.models import (
    Boutique,
    BoutiqueAvailability,
    DateAvailability,
    Snapshot,
)

API_BASE_URL = "https://api-canvas.rdv.richemont.com/api/v1"
OpenRequest = Callable[[Request, float], bytes]


class VcaError(RuntimeError):
    """Base exception for upstream VCA failures."""


class VcaRequestError(VcaError):
    """The VCA endpoint could not be reached successfully."""


class VcaResponseError(VcaError):
    """The VCA endpoint returned an unexpected response."""


def _default_open_request(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS origin
        return response.read()


class VcaClient:
    def __init__(
        self,
        timeout_seconds: float = 15.0,
        open_request: OpenRequest | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds
        self._open_request = open_request or _default_open_request

    def fetch_snapshot(self, boutiques: tuple[Boutique, ...]) -> Snapshot:
        return tuple(self._fetch_boutique(boutique) for boutique in boutiques)

    def _fetch_boutique(self, boutique: Boutique) -> BoutiqueAvailability:
        availability = self._fetch_json(
            {
                "apiMethod": "getBoutiqueAvailabilities",
                "boutiqueId": boutique.id,
                "language": "ja",
                "origin": "web",
            }
        )
        if not isinstance(availability, list):
            raise VcaResponseError("availability response must be a list")

        dates: list[DateAvailability] = []
        sales_dates: list[str] = []
        for item in availability:
            if not isinstance(item, dict):
                raise VcaResponseError("availability response contains an invalid item")
            record_date = _require_date(item, "recordDate", "availability response")
            sales_count = _require_non_negative_int(
                item, "salesSlotsCount", "availability response"
            )
            if sales_count > 0:
                sales_dates.append(record_date)

        for record_date in sorted(set(sales_dates)):
            times = self._fetch_open_times(boutique.id, record_date)
            if times:
                dates.append(DateAvailability(date=record_date, times=times))

        return BoutiqueAvailability(
            boutique_id=boutique.id,
            city=boutique.city,
            name=boutique.name,
            dates=tuple(dates),
        )

    def _fetch_open_times(self, boutique_id: str, record_date: str) -> tuple[str, ...]:
        slots = self._fetch_json(
            {
                "apiMethod": "getTimeSlotsByDateAndType",
                "date": record_date,
                "boutiqueId": boutique_id,
                "type": "RICBA_Sales",
                "useBoutiqueDuration": "true",
            }
        )
        if not isinstance(slots, list):
            raise VcaResponseError("time slot response must be a list")

        open_times: set[str] = set()
        for item in slots:
            if not isinstance(item, dict):
                raise VcaResponseError("time slot response contains an invalid item")
            capacity = _require_non_negative_int(item, "appointmentsNumber", "time slot response")
            assigned = _require_non_negative_int(
                item, "currentlyAssignedAppointmentsNumber", "time slot response"
            )
            blocked = _require_bool(item, "isBlocked", "time slot response")
            blocked_for_web = _require_bool(item, "isBlockedForWeb", "time slot response")
            start = item.get("startT")
            if not isinstance(start, str) or len(start) < 5 or start[2] != ":":
                raise VcaResponseError("time slot response has invalid startT")
            if assigned < capacity and not blocked and not blocked_for_web:
                open_times.add(start[:5])
        return tuple(sorted(open_times))

    def _fetch_json(self, params: dict[str, str]) -> Any:
        request = Request(
            f"{API_BASE_URL}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "vca-reservation-monitor/0.1",
            },
        )
        try:
            raw = self._open_request(request, self._timeout_seconds)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise VcaRequestError(f"VCA request failed: {type(exc).__name__}") from exc
        try:
            return json.loads(raw)
        except (JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise VcaResponseError("VCA response is not valid JSON") from exc


def _require_non_negative_int(item: dict[str, Any], key: str, context: str) -> int:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VcaResponseError(f"{context} has invalid {key}")
    return value


def _require_bool(item: dict[str, Any], key: str, context: str) -> bool:
    value = item.get(key)
    if not isinstance(value, bool):
        raise VcaResponseError(f"{context} has invalid {key}")
    return value


def _require_date(item: dict[str, Any], key: str, context: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise VcaResponseError(f"{context} has invalid {key}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise VcaResponseError(f"{context} has invalid {key}") from exc
    return value
