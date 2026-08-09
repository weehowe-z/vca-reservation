from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Boutique:
    id: str
    external_id: str
    city: str
    name: str


@dataclass(frozen=True)
class DateAvailability:
    date: str
    times: tuple[str, ...]


@dataclass(frozen=True)
class BoutiqueAvailability:
    boutique_id: str
    city: str
    name: str
    dates: tuple[DateAvailability, ...]


Snapshot = tuple[BoutiqueAvailability, ...]
