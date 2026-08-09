from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from vca_reservation.models import Snapshot
from vca_reservation.monitor import Event, SlotRef

APPOINTMENT_URL = "https://www.vancleefarpels.com/jp/ja/in-store-appointment.html#"
MAX_MESSAGE_BYTES = 4000
OpenRequest = Callable[[Request, float], bytes]


class SeaTalkDeliveryError(RuntimeError):
    """SeaTalk did not accept a webhook message."""


def _default_open_request(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured HTTPS webhook
        return response.read()


@dataclass
class SeaTalkNotifier:
    _webhook_url: str = field(repr=False)
    timeout_seconds: float = 15.0
    open_request: OpenRequest = field(default=_default_open_request, repr=False)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def send(self, content: str, mention_all: bool) -> None:
        payload = {
            "tag": "text",
            "text": {"content": content, "at_all": mention_all},
        }
        request = Request(
            self._webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            self.open_request(request, self.timeout_seconds)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SeaTalkDeliveryError("SeaTalk webhook delivery failed") from exc

    def notify_event(self, event: Event) -> None:
        self.send(format_event(event), mention_all=event.mention_all)

    def notify_failure(self, count: int, checked_at: datetime) -> None:
        self.send(format_failure(count, checked_at), mention_all=False)


def format_event(event: Event) -> str:
    headings = {
        "initial": "VCA 预约监控：初始状态",
        "heartbeat": "VCA 预约监控：本小时无变化",
        "changed": "VCA 预约号源有变化",
        "recovery": "VCA 预约监控恢复",
        "recovery_changed": "VCA 监控恢复且号源有变化",
    }
    lines = [headings[event.kind], f"日本时间：{_format_checked_at(event.checked_at)}"]
    if event.kind in {"changed", "recovery_changed"}:
        lines.extend(_format_diff(event.added, event.removed))
    lines.extend(("", "当前可预约："))
    lines.extend(_format_snapshot(event.snapshot))
    return _fit_message("\n".join(lines))


def format_failure(count: int, checked_at: datetime) -> str:
    body = "\n".join(
        (
            "VCA 预约监控异常",
            f"已连续 {count} 次检查失败，请查看 Linux 服务日志。",
            f"日本时间：{_format_checked_at(checked_at)}",
        )
    )
    return _fit_message(body)


def _format_diff(added: tuple[SlotRef, ...], removed: tuple[SlotRef, ...]) -> list[str]:
    lines = [""]
    if added:
        lines.append("新增：")
        lines.extend(
            f"+ {slot.city} {slot.boutique_name} {slot.date} {slot.time}" for slot in added
        )
    if removed:
        lines.append("减少：")
        lines.extend(
            f"- {slot.city} {slot.boutique_name} {slot.date} {slot.time}" for slot in removed
        )
    if not added and not removed:
        lines.append("可预约信息内容发生变化。")
    return lines


def _format_snapshot(snapshot: Snapshot) -> list[str]:
    lines: list[str] = []
    any_open = any(boutique.dates for boutique in snapshot)
    if not any_open:
        lines.append("当前六家门店均无珠宝预约号源")
    for boutique in snapshot:
        if not boutique.dates:
            lines.append(f"{boutique.city} {boutique.name}：无号")
            continue
        lines.append(f"{boutique.city} {boutique.name}：")
        lines.extend(
            f"  {available_date.date}：{'、'.join(available_date.times)}"
            for available_date in boutique.dates
        )
    return lines


def _format_checked_at(checked_at: datetime) -> str:
    if checked_at.tzinfo is not None:
        checked_at = checked_at.astimezone(ZoneInfo("Asia/Tokyo"))
    return checked_at.strftime("%Y-%m-%d %H:%M")


def _fit_message(body: str) -> str:
    footer = f"\n\n预约页面：{APPOINTMENT_URL}"
    content = body + footer
    if len(content.encode("utf-8")) <= MAX_MESSAGE_BYTES:
        return content
    suffix = "\n…内容已截断，请打开预约页面查看全部信息。"
    budget = MAX_MESSAGE_BYTES - len((suffix + footer).encode("utf-8"))
    shortened = body.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return shortened + suffix + footer
