from __future__ import annotations

import json
from datetime import datetime
from urllib.error import URLError
from zoneinfo import ZoneInfo

import pytest

from vca_reservation.models import BoutiqueAvailability, DateAvailability
from vca_reservation.monitor import Event, SlotRef
from vca_reservation.seatalk import (
    APPOINTMENT_URL,
    SeaTalkDeliveryError,
    SeaTalkNotifier,
    format_event,
    format_failure,
)

CHECKED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
EMPTY = (BoutiqueAvailability("shop", "大阪", "阪急梅田本店", ()),)
OPEN = (
    BoutiqueAvailability(
        "shop",
        "广岛",
        "福屋八丁堀本店",
        (DateAvailability("2026-08-18", ("14:00", "16:00")),),
    ),
)


def test_changed_message_lists_diff_and_current_snapshot():
    added = SlotRef("shop", "广岛", "福屋八丁堀本店", "2026-08-18", "14:00")
    event = Event("changed", CHECKED_AT, OPEN, added=(added,), mention_all=True)

    content = format_event(event)

    assert "VCA 预约号源有变化" in content
    assert "+ 广岛 福屋八丁堀本店 2026-08-18 14:00" in content
    assert "当前可预约" in content
    assert "日本时间：2026-08-10 12:00" in content
    assert APPOINTMENT_URL in content


def test_heartbeat_explicitly_says_no_change_and_lists_empty_store():
    content = format_event(Event("heartbeat", CHECKED_AT, EMPTY))

    assert "本小时无变化" in content
    assert "大阪 阪急梅田本店：无号" in content
    assert "当前六家门店均无珠宝预约号源" in content


def test_recovery_changed_has_recovery_heading():
    content = format_event(Event("recovery_changed", CHECKED_AT, OPEN, mention_all=True))

    assert "监控恢复且号源有变化" in content


def test_failure_message_is_not_an_all_mention_decision():
    content = format_failure(3, CHECKED_AT)

    assert "连续 3 次检查失败" in content
    assert "日本时间：2026-08-10 12:00" in content


def test_message_is_below_seatalk_utf8_limit():
    oversized = tuple(
        BoutiqueAvailability(
            f"shop-{index}",
            "广岛",
            f"非常长的珠宝门店名称{index}",
            tuple(
                DateAvailability(f"2026-09-{day:02d}", tuple(f"{hour:02d}:00" for hour in range(24)))
                for day in range(1, 29)
            ),
        )
        for index in range(10)
    )

    content = format_event(Event("initial", CHECKED_AT, oversized))

    assert len(content.encode("utf-8")) <= 4000
    assert "内容已截断" in content
    assert APPOINTMENT_URL in content


class RecordingOpener:
    def __init__(self):
        self.request = None
        self.timeout = None

    def __call__(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return b'{"code": 0}'


def test_changed_delivery_sets_at_all_true():
    recorder = RecordingOpener()
    notifier = SeaTalkNotifier("https://example.invalid/secret", open_request=recorder)

    notifier.send("changed", mention_all=True)

    assert recorder.request.get_method() == "POST"
    assert recorder.request.headers["Content-type"] == "application/json"
    assert json.loads(recorder.request.data) == {
        "tag": "text",
        "text": {"content": "changed", "at_all": True},
    }


def test_notify_event_formats_and_uses_event_mention_flag():
    recorder = RecordingOpener()
    notifier = SeaTalkNotifier("https://example.invalid/secret", open_request=recorder)
    event = Event("changed", CHECKED_AT, OPEN, mention_all=True)

    notifier.notify_event(event)

    assert json.loads(recorder.request.data)["text"]["at_all"] is True
    assert "预约号源有变化" in json.loads(recorder.request.data)["text"]["content"]


def test_delivery_error_and_repr_do_not_disclose_webhook():
    secret_url = "https://example.invalid/a-real-secret"

    def fail(request, timeout):
        del request, timeout
        raise URLError("offline")

    notifier = SeaTalkNotifier(secret_url, open_request=fail)

    with pytest.raises(SeaTalkDeliveryError) as error:
        notifier.send("message", mention_all=False)

    assert secret_url not in str(error.value)
    assert secret_url not in repr(notifier)
