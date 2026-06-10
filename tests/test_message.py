from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace


def _load_message_module(refreshed_archive: object):
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "message.py"
    )
    spec = importlib.util.spec_from_file_location(
        "nonebot_plugin_eratw_mirror.message",
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
    config_module = types.ModuleType("nonebot_plugin_eratw_mirror.config")
    config_module.Config = object
    models_module = types.ModuleType("nonebot_plugin_eratw_mirror.models")
    models_module.ArchiveInfo = object
    models_module.UpdatePayload = object
    remote_worker_module = types.ModuleType("nonebot_plugin_eratw_mirror.remote_worker")

    async def build_remote_archive(*args, **kwargs):
        return refreshed_archive

    remote_worker_module.build_remote_archive = build_remote_archive
    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.logger = SimpleNamespace(debug=lambda *args, **kwargs: None, info=lambda *args, **kwargs: None)
    adapters_module = types.ModuleType("nonebot.adapters")
    onebot_module = types.ModuleType("nonebot.adapters.onebot")
    v11_module = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_module.Bot = object
    v11_module.Message = str
    v11_module.MessageSegment = SimpleNamespace(
        node_custom=lambda **kwargs: ("node", kwargs),
    )
    sys.modules["nonebot_plugin_eratw_mirror"] = package
    sys.modules["nonebot_plugin_eratw_mirror.config"] = config_module
    sys.modules["nonebot_plugin_eratw_mirror.models"] = models_module
    sys.modules["nonebot_plugin_eratw_mirror.remote_worker"] = remote_worker_module
    sys.modules["nonebot"] = nonebot_module
    sys.modules["nonebot.adapters"] = adapters_module
    sys.modules["nonebot.adapters.onebot"] = onebot_module
    sys.modules["nonebot.adapters.onebot.v11"] = v11_module
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@dataclass
class _Archive:
    name: str
    size: int
    download_url: str | None
    sha256: str = "sha"
    password: str = "pass"


@dataclass
class _Payload:
    target_sha: str
    target_short_sha: str
    archive: _Archive
    commits: list[object] = field(default_factory=list)
    changelog: str = ""


class _Bot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_api(self, api_name: str, **kwargs: object) -> None:
        self.calls.append((api_name, kwargs))

    async def send_group_forward_msg(self, **kwargs: object) -> None:
        self.calls.append(("send_group_forward_msg", kwargs))


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        eratw_timeout=3600,
        eratw_message_chunk_size=2048,
        eratw_git_url=None,
        eratw_project_url="https://gitgud.io/era-games-zh/touhou/eratw-sub-modding",
    )


def test_group_archive_upload_refreshes_worker_download_url():
    refreshed = _Archive(
        name="fresh.7z",
        size=1024,
        download_url="http://worker.example/files/repo/fresh.7z?expires=2&token=fresh",
    )
    message = _load_message_module(refreshed)
    bot = _Bot()
    payload = _Payload(
        target_sha="abc123",
        target_short_sha="abc123",
        archive=_Archive(
            name="stale.7z",
            size=1024,
            download_url="http://worker.example/files/repo/stale.7z?expires=1&token=stale",
        ),
    )
    config = _config()

    archive = asyncio.run(message.upload_payload_archive_to_group(bot, 10001, payload, config))

    assert archive is refreshed
    assert bot.calls == [
        (
            "upload_group_file",
            {
                "group_id": 10001,
                "file": "http://worker.example/files/repo/fresh.7z?expires=2&token=fresh",
                "name": "fresh.7z",
                "_timeout": 3600,
            },
        )
    ]


def test_send_payload_uses_refreshed_archive_metadata_in_forward_message():
    refreshed = _Archive(
        name="fresh.7z",
        size=1024,
        download_url="http://worker.example/files/repo/fresh.7z?expires=2&token=fresh",
        sha256="fresh-sha",
        password="fresh-pass",
    )
    message = _load_message_module(refreshed)
    bot = _Bot()
    payload = _Payload(
        target_sha="abc123",
        target_short_sha="abc123",
        archive=_Archive(
            name="stale.7z",
            size=1024,
            download_url="http://worker.example/files/repo/stale.7z?expires=1&token=stale",
            sha256="stale-sha",
            password="stale-pass",
        ),
    )

    asyncio.run(message.send_payload_to_group(bot, 10001, payload, _config()))

    assert bot.calls[0][0] == "upload_group_file"
    assert bot.calls[1][0] == "send_group_forward_msg"
    archive_node = bot.calls[1][1]["messages"][0]
    archive_text = archive_node[1]["content"]
    assert "fresh.7z" in archive_text
    assert "fresh-pass" in archive_text
    assert "fresh-sha" in archive_text
    assert "stale-pass" not in archive_text
    assert "stale-sha" not in archive_text
