from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace


class _FakePayload:
    received: dict[str, object] | None = None

    @classmethod
    def from_json(cls, data: dict[str, object]):
        cls.received = data
        return cls


def _load_state_module(data_dir: Path):
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "state.py"
    )
    spec = importlib.util.spec_from_file_location(
        "nonebot_plugin_eratw_mirror.state",
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
    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    localstore_module = types.ModuleType("nonebot_plugin_localstore")
    localstore_module.get_plugin_data_dir = lambda: data_dir
    models_module = types.ModuleType("nonebot_plugin_eratw_mirror.models")
    models_module.UpdatePayload = _FakePayload
    sys.modules["nonebot_plugin_eratw_mirror"] = package
    sys.modules["nonebot_plugin_eratw_mirror.models"] = models_module
    sys.modules["nonebot"] = nonebot_module
    sys.modules["nonebot_plugin_localstore"] = localstore_module
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_group_upload_state_is_independent_from_push_success(tmp_path: Path):
    state = _load_state_module(tmp_path)
    store = state.StateStore()

    store.add_uploaded_group("abc123", "sha-a", 10001)

    assert store.read_uploaded_groups("abc123", "sha-a") == {10001}
    assert store.read_uploaded_groups("abc123", "sha-b") == set()
    assert store.read_successful_groups("abc123") == set()

    store.add_successful_group("abc123", 10001)

    assert store.read_uploaded_groups("abc123", "sha-a") == {10001}
    assert store.read_successful_groups("abc123") == {10001}


def test_group_upload_state_is_cleared_after_final_success(tmp_path: Path):
    state = _load_state_module(tmp_path)
    store = state.StateStore()

    store.add_uploaded_group("abc123", "sha-a", 10001)
    store.add_successful_group("abc123", 10001)
    store.set_last_success("abc123", "2026-06-10T04:00:00+08:00")

    assert store.read_uploaded_groups("abc123", "sha-a") == set()
    assert store.read_successful_groups("abc123") == set()


def test_cached_payload_is_not_rejected_by_expired_worker_url(tmp_path: Path):
    state = _load_state_module(tmp_path)
    store = state.StateStore()
    payload_data = {
        "target_sha": "abc123",
        "archive": {
            "download_url": "http://worker.example/archive.7z?expires=1&token=old",
            "download_expires_at": 1,
        },
    }
    store.payload_path.write_text(state.json.dumps(payload_data), encoding="utf-8")

    payload = store.read_last_payload()

    assert payload is _FakePayload
    assert _FakePayload.received == payload_data
