from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_DAILY_PATTERN = re.compile(r"^每日(\d{1,2})-(\d{2})$")
_WEEKLY_PATTERN = re.compile(r"^星期([1-7一二三四五六日天])(\d{1,2})(?:-?)(\d{2})$")
_WEEKDAY_MAP = {
    "1": "mon",
    "一": "mon",
    "2": "tue",
    "二": "tue",
    "3": "wed",
    "三": "wed",
    "4": "thu",
    "四": "thu",
    "5": "fri",
    "五": "fri",
    "6": "sat",
    "六": "sat",
    "7": "sun",
    "日": "sun",
    "天": "sun",
}


@dataclass(frozen=True)
class ScheduleSpec:
    raw: str
    trigger: str
    trigger_kwargs: dict[str, Any]
    description: str


def parse_schedule(value: str, timezone_name: str = "Asia/Shanghai") -> ScheduleSpec | None:
    raw = value.strip()
    if not raw:
        return None

    timezone = _parse_timezone(timezone_name)
    daily = _DAILY_PATTERN.fullmatch(raw)
    if daily:
        hour, minute = _parse_time(daily.group(1), daily.group(2))
        return ScheduleSpec(
            raw=raw,
            trigger="cron",
            trigger_kwargs={"hour": hour, "minute": minute, "timezone": timezone},
            description=f"每日 {_format_time(hour, minute)} ({timezone_name})",
        )

    weekly = _WEEKLY_PATTERN.fullmatch(raw)
    if weekly:
        day_of_week = _WEEKDAY_MAP[weekly.group(1)]
        hour, minute = _parse_time(weekly.group(2), weekly.group(3))
        return ScheduleSpec(
            raw=raw,
            trigger="cron",
            trigger_kwargs={
                "day_of_week": day_of_week,
                "hour": hour,
                "minute": minute,
                "timezone": timezone,
            },
            description=(
                f"每周 {day_of_week} {_format_time(hour, minute)} ({timezone_name})"
            ),
        )

    if raw.startswith("每周"):
        raise ValueError("每周HH-MM 缺少星期几，请使用 星期一04-30 或 星期10430。")

    raise ValueError("定时格式应为 每日HH-MM、星期xHH-MM 或 星期xHHMM。")


def _parse_time(hour_text: str, minute_text: str) -> tuple[int, int]:
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        raise ValueError("定时时间必须在 00-00 到 23-59 之间。")
    return hour, minute


def _parse_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"无效时区：{value!r}") from exc


def _format_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"
