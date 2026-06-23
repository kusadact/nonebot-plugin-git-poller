from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
import re
from typing import Any


_DAILY_PATTERN = re.compile(r"^每日(\d{1,2}):(\d{2})$")
_INTERVAL_DAYS_PATTERN = re.compile(r"^每([1-9]\d*)天(\d{1,2}):(\d{2})$")
_WEEKLY_PATTERN = re.compile(r"^周([一二三四五六日天])(\d{1,2}):(\d{2})$")
_UTC_OFFSET_PATTERN = re.compile(r"^([+-]?)(0|[1-9]\d?)(?:\.5)?$")
_INTERVAL_ANCHOR_ORDINAL = date(1970, 1, 1).toordinal()
_MAX_INTERVAL_DAYS = 30
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
_MIN_UTC_OFFSET_HOURS = -12
_MAX_UTC_OFFSET_HOURS = 14
_HALF_HOUR_UTC_OFFSET_MINUTES = {
    -570,  # UTC-09:30, Marquesas Islands
    -210,  # UTC-03:30, Newfoundland standard time
    210,  # UTC+03:30, Iran
    270,  # UTC+04:30, Afghanistan
    330,  # UTC+05:30, India/Sri Lanka
    390,  # UTC+06:30, Myanmar/Cocos Islands
    570,  # UTC+09:30, central Australia
    630,  # UTC+10:30, Lord Howe / Australia DST offsets
}


@dataclass(frozen=True)
class ScheduleSpec:
    raw: str
    trigger: str
    trigger_kwargs: dict[str, Any]
    description: str


def parse_schedule(value: str, timezone_name: str = "+8") -> ScheduleSpec | None:
    raw = value.strip()
    if not raw:
        return None

    schedule_timezone, timezone_label = parse_utc_offset(timezone_name)
    daily = _DAILY_PATTERN.fullmatch(raw)
    if daily:
        hour, minute = _parse_time(daily.group(1), daily.group(2))
        return ScheduleSpec(
            raw=raw,
            trigger="cron",
            trigger_kwargs={
                "hour": hour,
                "minute": minute,
                "timezone": schedule_timezone,
            },
            description=f"每日 {_format_time(hour, minute)} ({timezone_label})",
        )

    interval_days = _INTERVAL_DAYS_PATTERN.fullmatch(raw)
    if interval_days:
        days = int(interval_days.group(1))
        if days > _MAX_INTERVAL_DAYS:
            raise ValueError(f"间隔天数必须在 1 到 {_MAX_INTERVAL_DAYS} 天之间。")
        hour, minute = _parse_time(interval_days.group(2), interval_days.group(3))
        return ScheduleSpec(
            raw=raw,
            trigger="interval",
            trigger_kwargs={
                "days": days,
                "start_date": _next_interval_start_date(
                    days,
                    hour,
                    minute,
                    schedule_timezone,
                ),
                "timezone": schedule_timezone,
            },
            description=f"每 {days} 天 {_format_time(hour, minute)} ({timezone_label})",
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
                "timezone": schedule_timezone,
            },
            description=(
                f"周{_WEEKDAY_NAME_MAP[weekday_text]} "
                f"{_format_time(hour, minute)} ({timezone_label})"
            ),
        )

    raise ValueError(
        "定时格式应为 每日hh:mm、每x天hh:mm 或 周xhh:mm，"
        f"天数 x 使用 1 到 {_MAX_INTERVAL_DAYS} 的整数，"
        "周 x 使用一二三四五六日/天。"
    )


def _parse_time(hour_text: str, minute_text: str) -> tuple[int, int]:
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        raise ValueError("定时时间必须在 00:00 到 23:59 之间。")
    return hour, minute


def parse_utc_offset(value: str) -> tuple[tzinfo, str]:
    raw = value.strip()
    match = _UTC_OFFSET_PATTERN.fullmatch(raw)
    if not match:
        raise ValueError(f"无效 UTC 偏移：{value!r}")

    sign_text, hours_text = match.groups()
    is_half_hour = raw.endswith(".5")
    sign = -1 if sign_text == "-" else 1
    offset_minutes = sign * (int(hours_text) * 60 + (30 if is_half_hour else 0))
    if is_half_hour and offset_minutes not in _HALF_HOUR_UTC_OFFSET_MINUTES:
        raise ValueError(f"无效 UTC 偏移：{value!r}")

    min_offset_minutes = _MIN_UTC_OFFSET_HOURS * 60
    max_offset_minutes = _MAX_UTC_OFFSET_HOURS * 60
    if offset_minutes < min_offset_minutes or offset_minutes > max_offset_minutes:
        raise ValueError(
            "UTC 偏移必须在 "
            f"{_MIN_UTC_OFFSET_HOURS} 到 {_MAX_UTC_OFFSET_HOURS} 之间。"
        )

    offset = timedelta(minutes=offset_minutes)
    label = _format_utc_offset_label(offset_minutes)
    return timezone(offset, name=label), label


def _format_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _format_utc_offset_label(offset_minutes: int) -> str:
    sign = "-" if offset_minutes < 0 else "+"
    absolute_minutes = abs(offset_minutes)
    hours, minutes = divmod(absolute_minutes, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _next_interval_start_date(
    days: int,
    hour: int,
    minute: int,
    schedule_timezone: tzinfo,
) -> datetime:
    now = datetime.now(schedule_timezone)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    offset = (candidate.date().toordinal() - _INTERVAL_ANCHOR_ORDINAL) % days
    if offset:
        candidate += timedelta(days=days - offset)
    return candidate
