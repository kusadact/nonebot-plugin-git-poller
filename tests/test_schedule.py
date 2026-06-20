from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import sys

import pytest


def _load_schedule_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_git_poller"
        / "schedule.py"
    )
    spec = importlib.util.spec_from_file_location("git_poller_schedule", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_daily_schedule():
    schedule = _load_schedule_module()
    spec = schedule.parse_schedule("每日04:30")

    assert spec.trigger == "cron"
    assert spec.trigger_kwargs["hour"] == 4
    assert spec.trigger_kwargs["minute"] == 30


def test_parse_weekly_schedule_with_chinese_weekday():
    schedule = _load_schedule_module()
    spec = schedule.parse_schedule("周一04:30")

    assert spec.trigger == "cron"
    assert spec.trigger_kwargs["day_of_week"] == "mon"
    assert spec.trigger_kwargs["hour"] == 4
    assert spec.trigger_kwargs["minute"] == 30


def test_parse_weekly_schedule_with_sunday_alias():
    schedule = _load_schedule_module()
    spec = schedule.parse_schedule("周日04:30")

    assert spec.trigger == "cron"
    assert spec.trigger_kwargs["day_of_week"] == "sun"
    assert spec.trigger_kwargs["hour"] == 4
    assert spec.trigger_kwargs["minute"] == 30


def test_parse_interval_days_schedule(monkeypatch):
    schedule = _load_schedule_module()

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 20, 5, 0, tzinfo=tz)

    monkeypatch.setattr(schedule, "datetime", _FixedDateTime)
    spec = schedule.parse_schedule("每3天04:30")

    assert spec.trigger == "interval"
    assert spec.trigger_kwargs["days"] == 3
    assert spec.trigger_kwargs["start_date"].isoformat() == "2026-06-21T04:30:00+08:00"


def test_empty_schedule_disables_job():
    schedule = _load_schedule_module()

    assert schedule.parse_schedule("  ") is None


def test_weekly_schedule_without_weekday_is_not_supported():
    schedule = _load_schedule_module()

    with pytest.raises(ValueError, match="定时格式应为"):
        schedule.parse_schedule("每周04:30")


def test_zero_interval_days_is_not_supported():
    schedule = _load_schedule_module()

    with pytest.raises(ValueError, match="定时格式应为"):
        schedule.parse_schedule("每0天04:30")


def test_numeric_weekday_is_not_supported():
    schedule = _load_schedule_module()

    with pytest.raises(ValueError, match="定时格式应为"):
        schedule.parse_schedule("周704:30")


def test_xingqi_prefix_is_not_supported():
    schedule = _load_schedule_module()

    with pytest.raises(ValueError, match="定时格式应为"):
        schedule.parse_schedule("星期一04:30")


def test_dash_time_is_not_supported():
    schedule = _load_schedule_module()

    with pytest.raises(ValueError, match="定时格式应为"):
        schedule.parse_schedule("每日04-30")


def test_invalid_schedule_raises():
    schedule = _load_schedule_module()

    with pytest.raises(ValueError):
        schedule.parse_schedule("daily@04:30")
