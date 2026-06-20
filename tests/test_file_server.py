from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from helpers import load_plugin_module


class _App:
    def __init__(self) -> None:
        self.routes: dict[str, object] = {}

    def add_api_route(self, path: str, endpoint, *, methods: list[str]) -> None:
        self.routes[path] = endpoint


def _load_file_server_module(cache_dir: Path, driver: object):
    responses_module = types.ModuleType("starlette.responses")

    class Response:
        def __init__(self, status_code: int = 200) -> None:
            self.status_code = status_code

    class FileResponse(Response):
        def __init__(
            self,
            path: Path,
            *,
            media_type: str,
            filename: str,
        ) -> None:
            super().__init__(200)
            self.path = str(path)
            self.media_type = media_type
            self.filename = filename

    responses_module.Response = Response
    responses_module.FileResponse = FileResponse
    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.get_driver = lambda: driver
    nonebot_module.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    localstore_module = types.ModuleType("nonebot_plugin_localstore")
    localstore_module.get_plugin_cache_dir = lambda: cache_dir
    sys.modules["nonebot"] = nonebot_module
    sys.modules["nonebot_plugin_localstore"] = localstore_module
    sys.modules["starlette.responses"] = responses_module

    module = load_plugin_module("file_server")
    module._route_registered = False
    return module


def _config(**overrides):
    values = {
        "git_poller_file_base_url": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_configured_file_base_url_requires_http_route(tmp_path: Path):
    file_server = _load_file_server_module(tmp_path / "cache", SimpleNamespace())
    config = _config(git_poller_file_base_url="http://bot.example")

    with pytest.raises(RuntimeError, match="git_poller_file_base_url is configured"):
        file_server.register_archive_file_route(config)


def test_missing_http_route_is_allowed_without_file_base_url(tmp_path: Path):
    file_server = _load_file_server_module(tmp_path / "cache", SimpleNamespace())

    assert file_server.register_archive_file_route(_config()) is False


def test_archive_download_url_uses_expiring_signature(tmp_path: Path, monkeypatch):
    file_server = _load_file_server_module(tmp_path / "cache", SimpleNamespace())
    config = _config(git_poller_file_base_url="http://bot.example")
    monkeypatch.setattr(file_server.time, "time", lambda: 1000)

    url = file_server.build_archive_download_url(Path("repo main.7z"), config)
    assert url is not None

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path == "/git-poller/files/repo%20main.7z"
    assert query["expires"] == ["4600"]
    assert "token" in query
    assert file_server.valid_archive_download_token(
        "repo main.7z",
        query["expires"][0],
        query["token"][0],
    )


def test_archive_download_url_rejects_expired_signature(tmp_path: Path, monkeypatch):
    file_server = _load_file_server_module(tmp_path / "cache", SimpleNamespace())
    config = _config(git_poller_file_base_url="http://bot.example")
    token = file_server.archive_download_token("sample.7z", 1000)
    monkeypatch.setattr(file_server.time, "time", lambda: 1001)

    assert not file_server.valid_archive_download_token("sample.7z", "1000", token)


def test_archive_file_route_serves_cached_archive(tmp_path: Path, monkeypatch):
    app = _App()
    file_server = _load_file_server_module(tmp_path / "cache", SimpleNamespace(server_app=app))
    archive_dir = tmp_path / "cache" / "archives"
    archive_dir.mkdir(parents=True)
    archive_path = archive_dir / "repo-main.7z"
    archive_path.write_bytes(b"archive bytes")
    config = _config(git_poller_file_base_url="http://bot.example")
    monkeypatch.setattr(file_server.time, "time", lambda: 1000)

    assert file_server.register_archive_file_route(config) is True
    route = app.routes["/git-poller/files/{filename}"]
    token = file_server.archive_download_token("repo-main.7z", 4600)
    response = asyncio.run(route("repo-main.7z", expires="4600", token=token))

    assert response.path == str(archive_path)
    assert response.media_type == "application/x-7z-compressed"
