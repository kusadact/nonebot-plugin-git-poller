from __future__ import annotations

from pydantic import BaseModel, Field
from nonebot import get_plugin_config


class Config(BaseModel):
    git_poller_default_schedule: str = "每日04:00"
    git_poller_timezone: str = "Asia/Shanghai"

    git_poller_proxy: str | None = None
    git_poller_timeout: float = Field(default=60.0, gt=0)
    git_poller_archive_password: str | None = None
    git_poller_file_base_url: str | None = None


plugin_config = get_plugin_config(Config)
