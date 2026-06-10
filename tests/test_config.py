from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest


def _load_config_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "config.py"
    )
    spec = importlib.util.spec_from_file_location(
        "nonebot_plugin_eratw_mirror.config",
        path,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    package = types.ModuleType("nonebot_plugin_eratw_mirror")
    package.__path__ = [str(path.parent)]
    package.__spec__ = importlib.util.spec_from_loader(
        "nonebot_plugin_eratw_mirror",
        loader=None,
        is_package=True,
    )

    def get_plugin_config(config_cls):
        return config_cls(
            eratw_worker_base_url="http://worker.example:18721",
            eratw_worker_token="secret",
        )

    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.get_plugin_config = get_plugin_config
    sys.modules["nonebot_plugin_eratw_mirror"] = package
    sys.modules["nonebot"] = nonebot_module
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_worker_config_requires_base_url():
    config_module = _load_config_module()
    config = config_module.Config(
        eratw_worker_base_url="",
        eratw_worker_token="secret",
    )

    with pytest.raises(RuntimeError, match="eratw_worker_base_url is required"):
        config_module.validate_worker_config(config)


def test_worker_config_requires_token():
    config_module = _load_config_module()
    config = config_module.Config(
        eratw_worker_base_url="http://worker.example:18721",
        eratw_worker_token="",
    )

    with pytest.raises(RuntimeError, match="eratw_worker_token is required"):
        config_module.validate_worker_config(config)


def test_worker_config_accepts_required_fields():
    config_module = _load_config_module()
    config = config_module.Config(
        eratw_worker_base_url="http://worker.example:18721",
        eratw_worker_token="secret",
    )

    config_module.validate_worker_config(config)
