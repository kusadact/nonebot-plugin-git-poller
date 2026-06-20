from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from helpers import load_plugin_module

nonebot_module = types.ModuleType("nonebot")
nonebot_module.logger = SimpleNamespace(
    debug=lambda *args, **kwargs: None,
    info=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
)
nonebot_module.get_plugin_config = lambda config_cls: config_cls()
nonebot_module.get_driver = lambda: SimpleNamespace()
adapters_module = types.ModuleType("nonebot.adapters")
onebot_module = types.ModuleType("nonebot.adapters.onebot")
v11_module = types.ModuleType("nonebot.adapters.onebot.v11")
v11_module.Bot = object
v11_module.Message = str
v11_module.MessageSegment = SimpleNamespace(node_custom=lambda **kwargs: ("node", kwargs))


class _ActionFailed(Exception):
    def __init__(self, **kwargs):
        self.info = kwargs

    def __repr__(self):
        return (
            "ActionFailed("
            + ", ".join(f"{key}={value!r}" for key, value in self.info.items())
            + ")"
        )


v11_module.ActionFailed = _ActionFailed
localstore_module = types.ModuleType("nonebot_plugin_localstore")
localstore_module.get_plugin_cache_dir = lambda: Path("/tmp/cache")
sys.modules["nonebot"] = nonebot_module
sys.modules["nonebot.adapters"] = adapters_module
sys.modules["nonebot.adapters.onebot"] = onebot_module
sys.modules["nonebot.adapters.onebot.v11"] = v11_module
sys.modules["nonebot_plugin_localstore"] = localstore_module

models = load_plugin_module("models")
message = load_plugin_module("message")


class _Bot:
    def __init__(self, upload_error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.upload_error = upload_error

    async def send_group_forward_msg(self, **kwargs: object) -> None:
        self.calls.append(("send_group_forward_msg", kwargs))

    async def upload_group_file(self, **kwargs: object) -> None:
        if self.upload_error is not None:
            raise self.upload_error
        self.calls.append(("upload_group_file", kwargs))


def _payload():
    return models.UpdatePayload(
        repo_key="repo-a",
        repo_url="https://github.com/example/repo.git",
        repo_name="repo",
        branch="main",
        previous_sha="oldsha123",
        target_sha="newsha123",
        target_short_sha="newsha12",
        generated_at="2026-06-20T04:30:00+08:00",
        compare_url="https://github.com/example/repo/compare/oldsha123...newsha123",
        commits=[
            models.CommitInfo(
                sha="midsha123",
                short_sha="midsha12",
                title="Prepare feature",
                committed_at="2026-06-20T03:50:00+08:00",
                author="Bob",
                url="https://github.com/example/repo/commit/midsha123",
            ),
            models.CommitInfo(
                sha="newsha123",
                short_sha="newsha12",
                title="Add feature",
                committed_at="2026-06-20T04:00:00+08:00",
                author="Alice",
                url="https://github.com/example/repo/commit/newsha123",
            )
        ],
    )


def _config(**overrides):
    values = {
        "git_poller_file_base_url": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_build_forward_nodes_contains_summary_and_commits():
    nodes = message.build_forward_nodes(_payload())

    assert len(nodes) == 3
    summary = nodes[0][1]["content"]
    assert "仓库更新：repo" in summary
    assert "新增 commit：2" in summary
    assert "oldsha12" in summary
    assert any("Add feature" in node[1]["content"] for node in nodes)
    assert any("Alice" in node[1]["content"] for node in nodes)


def test_send_update_to_group_uses_forward_message_only():
    bot = _Bot()

    asyncio.run(message.send_update_to_group(bot, 10001, _payload()))

    assert bot.calls[0][0] == "send_group_forward_msg"
    assert bot.calls[0][1]["group_id"] == 10001
    assert len(bot.calls[0][1]["messages"]) == 3


def test_upload_archive_to_group_uses_group_file_api():
    bot = _Bot()
    archive = SimpleNamespace(
        path=Path("/tmp/repo.7z"),
        name="repo.7z",
        sha256="0" * 64,
        password=None,
        password_used=False,
    )

    asyncio.run(message.upload_archive_to_group(bot, 10001, archive, config=_config()))

    assert bot.calls[0][0] == "upload_group_file"
    assert bot.calls[0][1]["group_id"] == 10001
    assert bot.calls[0][1]["file"] == "/tmp/repo.7z"
    assert bot.calls[0][1]["name"] == "repo.7z"


def test_upload_archive_to_group_uses_file_base_url():
    bot = _Bot()
    archive = SimpleNamespace(
        path=Path("/tmp/repo main.7z"),
        name="repo-main.7z",
        sha256="0" * 64,
        password=None,
        password_used=False,
    )

    asyncio.run(
        message.upload_archive_to_group(
            bot,
            10001,
            archive,
            config=_config(git_poller_file_base_url="http://127.0.0.1:8080"),
        )
    )

    assert bot.calls[0][0] == "upload_group_file"
    parsed = urlparse(str(bot.calls[0][1]["file"]))
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:8080"
    assert parsed.path == "/git-poller/files/repo%20main.7z"
    assert "expires" in query
    assert "token" in query
    assert bot.calls[0][1]["name"] == "repo-main.7z"


def test_build_archive_delivery_text_lists_commits_with_latest_last():
    archive = SimpleNamespace(
        sha256="f" * 64,
        password="secret",
    )

    text = message.build_archive_delivery_text(_payload(), archive, title="拉取完成")

    assert text.splitlines() == [
        "拉取完成：repo",
        "分支：main",
        f"sha256：{'f' * 64}",
        "密码：secret",
        "midsha12：Prepare feature",
        "最新newsha12：Add feature",
    ]


def test_upload_archive_to_group_reports_file_base_url_for_unrecognized_uri():
    bot = _Bot(
        upload_error=_ActionFailed(
            message="识别URL失败, uri= /workspace/cache/repo.7z",
            wording="识别URL失败, uri= /workspace/cache/repo.7z",
        )
    )
    archive = SimpleNamespace(
        path=Path("/tmp/repo.7z"),
        name="repo.7z",
        sha256="0" * 64,
        password=None,
        password_used=False,
    )

    try:
        asyncio.run(message.upload_archive_to_group(bot, 10001, archive, config=_config()))
    except message.ArchiveUploadUriError as exc:
        assert str(exc) == message.ARCHIVE_UPLOAD_URI_ERROR_MESSAGE
        assert "git_poller_file_base_url" in str(exc)
    else:
        raise AssertionError("upload should report file base URL guidance")


def test_upload_archive_to_group_keeps_other_action_failed_errors_scoped():
    original = _ActionFailed(message="上传失败")
    bot = _Bot(upload_error=original)
    archive = SimpleNamespace(
        path=Path("/tmp/repo.7z"),
        name="repo.7z",
        sha256="0" * 64,
        password=None,
        password_used=False,
    )

    try:
        asyncio.run(message.upload_archive_to_group(bot, 10001, archive, config=_config()))
    except _ActionFailed as exc:
        assert exc is original
    else:
        raise AssertionError("unrelated ActionFailed should not be converted")
