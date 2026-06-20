from __future__ import annotations

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
    spec = schedule.parse_schedule("每日04-30")

    assert spec.trigger == "cron"
    assert spec.trigger_kwargs["hour"] == 4
    assert spec.trigger_kwargs["minute"] == 30


def test_parse_weekly_schedule_with_chinese_weekday():
    schedule = _load_schedule_module()
    spec = schedule.parse_schedule("星期一04-30")

    assert spec.trigger == "cron"
    assert spec.trigger_kwargs["day_of_week"] == "mon"
    assert spec.trigger_kwargs["hour"] == 4
    assert spec.trigger_kwargs["minute"] == 30


def test_parse_weekly_schedule_without_dash():
    schedule = _load_schedule_module()
    spec = schedule.parse_schedule("星期70430")

    assert spec.trigger == "cron"
    assert spec.trigger_kwargs["day_of_week"] == "sun"
    assert spec.trigger_kwargs["hour"] == 4
    assert spec.trigger_kwargs["minute"] == 30


def test_empty_schedule_disables_job():
    schedule = _load_schedule_module()

    assert schedule.parse_schedule("  ") is None


def test_ambiguous_weekly_schedule_raises():
    schedule = _load_schedule_module()

    with pytest.raises(ValueError, match="缺少星期几"):
        schedule.parse_schedule("每周04-30")


def test_invalid_schedule_raises():
    schedule = _load_schedule_module()

    with pytest.raises(ValueError):
        schedule.parse_schedule("daily@04:30")
