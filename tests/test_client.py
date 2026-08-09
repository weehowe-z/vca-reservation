from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from vca_reservation.boutiques import BOUTIQUES
from vca_reservation.client import VcaClient, VcaResponseError
from vca_reservation.models import BoutiqueAvailability, DateAvailability


class FixtureTransport:
    def __init__(self, availability_by_boutique, slots_by_boutique_and_date):
        self.availability_by_boutique = availability_by_boutique
        self.slots_by_boutique_and_date = slots_by_boutique_and_date
        self.queries: list[dict[str, list[str]]] = []

    def __call__(self, request, timeout):
        del timeout
        query = parse_qs(urlparse(request.full_url).query)
        self.queries.append(query)
        method = query["apiMethod"][0]
        boutique_id = query["boutiqueId"][0]
        if method == "getBoutiqueAvailabilities":
            payload = self.availability_by_boutique[boutique_id]
        else:
            payload = self.slots_by_boutique_and_date[(boutique_id, query["date"][0])]
        return json.dumps(payload).encode()


def test_fetch_snapshot_returns_only_bookable_sales_slots_in_stable_order():
    first, second = BOUTIQUES[:2]
    transport = FixtureTransport(
        {
            first.id: [
                {"recordDate": "2026-08-12", "salesSlotsCount": 1},
                {"recordDate": "2026-08-11", "salesSlotsCount": 2},
                {"recordDate": "2026-08-13", "salesSlotsCount": 0},
            ],
            second.id: [],
        },
        {
            (first.id, "2026-08-11"): [
                {
                    "startT": "15:00:00.000Z",
                    "appointmentsNumber": 2,
                    "currentlyAssignedAppointmentsNumber": 1,
                    "isBlocked": False,
                    "isBlockedForWeb": False,
                },
                {
                    "startT": "10:00:00.000Z",
                    "appointmentsNumber": 1,
                    "currentlyAssignedAppointmentsNumber": 0,
                    "isBlocked": False,
                    "isBlockedForWeb": False,
                },
                {
                    "startT": "11:00:00.000Z",
                    "appointmentsNumber": 1,
                    "currentlyAssignedAppointmentsNumber": 1,
                    "isBlocked": False,
                    "isBlockedForWeb": False,
                },
            ],
            (first.id, "2026-08-12"): [
                {
                    "startT": "13:00:00.000Z",
                    "appointmentsNumber": 1,
                    "currentlyAssignedAppointmentsNumber": 0,
                    "isBlocked": True,
                    "isBlockedForWeb": False,
                }
            ],
        },
    )

    snapshot = VcaClient(open_request=transport).fetch_snapshot((second, first))

    assert snapshot == (
        BoutiqueAvailability(
            boutique_id=second.id,
            city=second.city,
            name=second.name,
            dates=(),
        ),
        BoutiqueAvailability(
            boutique_id=first.id,
            city=first.city,
            name=first.name,
            dates=(DateAvailability(date="2026-08-11", times=("10:00", "15:00")),),
        ),
    )
    time_queries = [q for q in transport.queries if q["apiMethod"] == ["getTimeSlotsByDateAndType"]]
    assert all(query["type"] == ["RICBA_Sales"] for query in time_queries)


@pytest.mark.parametrize("payload", [{}, "bad", None])
def test_fetch_snapshot_rejects_malformed_availability_payload(payload):
    boutique = BOUTIQUES[0]
    transport = FixtureTransport({boutique.id: payload}, {})

    with pytest.raises(VcaResponseError, match="availability response"):
        VcaClient(open_request=transport).fetch_snapshot((boutique,))


def test_fetch_snapshot_rejects_invalid_slot_capacity():
    boutique = BOUTIQUES[0]
    transport = FixtureTransport(
        {boutique.id: [{"recordDate": "2026-08-11", "salesSlotsCount": 1}]},
        {
            (boutique.id, "2026-08-11"): [
                {
                    "startT": "10:00:00.000Z",
                    "appointmentsNumber": 1,
                    "currentlyAssignedAppointmentsNumber": "zero",
                    "isBlocked": False,
                    "isBlockedForWeb": False,
                }
            ]
        },
    )

    with pytest.raises(VcaResponseError, match="time slot response"):
        VcaClient(open_request=transport).fetch_snapshot((boutique,))
