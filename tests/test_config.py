from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types


def _load_config_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_git_poller"
        / "config.py"
    )
    spec = importlib.util.spec_from_file_location(
        "nonebot_plugin_git_poller.config",
        path,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    package = types.ModuleType("nonebot_plugin_git_poller")
    package.__path__ = [str(path.parent)]

    def get_plugin_config(config_cls):
        return config_cls()

    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.get_plugin_config = get_plugin_config
    sys.modules["nonebot_plugin_git_poller"] = package
    sys.modules["nonebot"] = nonebot_module
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_config_defaults_are_global_only():
    config = _load_config_module().Config()

    assert config.git_poller_default_schedule == "每日04-00"
    assert config.git_poller_timezone == "Asia/Shanghai"
    assert config.git_poller_default_branch == "main"
    assert config.git_poller_archive_password is None
    assert config.git_poller_file_base_url is None
    assert config.git_poller_file_route_prefix == "/git-poller/files"
    assert config.git_poller_file_token is None
    assert config.git_poller_file_token_ttl == 3600
    assert config.git_poller_command_priority == 10
    assert config.git_poller_max_commits == 20
