from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_DAILY_PATTERN = re.compile(r"^每日(\d{1,2}):(\d{2})$")
_INTERVAL_DAYS_PATTERN = re.compile(r"^每([1-9]\d*)天(\d{1,2}):(\d{2})$")
_WEEKLY_PATTERN = re.compile(r"^周([一二三四五六日天])(\d{1,2}):(\d{2})$")
_INTERVAL_ANCHOR_ORDINAL = date(1970, 1, 1).toordinal()
_WEEKDAY_MAP = {
    "一": "mon",
    "二": "tue",
    "三": "wed",
    "四": "thu",
    "五": "fri",
    "六": "sat",
    "日": "sun",
    "天": "sun",
}
_WEEKDAY_NAME_MAP = {
    "一": "一",
    "二": "二",
    "三": "三",
    "四": "四",
    "五": "五",
    "六": "六",
    "日": "日",
    "天": "日",
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

    interval_days = _INTERVAL_DAYS_PATTERN.fullmatch(raw)
    if interval_days:
        days = int(interval_days.group(1))
        hour, minute = _parse_time(interval_days.group(2), interval_days.group(3))
        return ScheduleSpec(
            raw=raw,
            trigger="interval",
            trigger_kwargs={
                "days": days,
                "start_date": _next_interval_start_date(days, hour, minute, timezone),
                "timezone": timezone,
            },
            description=f"每 {days} 天 {_format_time(hour, minute)} ({timezone_name})",
        )

    weekly = _WEEKLY_PATTERN.fullmatch(raw)
    if weekly:
        weekday_text = weekly.group(1)
        day_of_week = _WEEKDAY_MAP[weekday_text]
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
                f"周{_WEEKDAY_NAME_MAP[weekday_text]} "
                f"{_format_time(hour, minute)} ({timezone_name})"
            ),
        )

    raise ValueError(
        "定时格式应为 每日hh:mm、每x天hh:mm 或 周xhh:mm，"
        "天数 x 使用正整数，周 x 使用一二三四五六日/天。"
    )


def _parse_time(hour_text: str, minute_text: str) -> tuple[int, int]:
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        raise ValueError("定时时间必须在 00:00 到 23:59 之间。")
    return hour, minute


def _parse_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"无效时区：{value!r}") from exc


def _format_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _next_interval_start_date(
    days: int,
    hour: int,
    minute: int,
    timezone: ZoneInfo,
) -> datetime:
    now = datetime.now(timezone)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    while (
        candidate <= now
        or (candidate.date().toordinal() - _INTERVAL_ANCHOR_ORDINAL) % days != 0
    ):
        candidate += timedelta(days=1)
    return candidate
