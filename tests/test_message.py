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
    exception=lambda *args, **kwargs: None,
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
    _next_id = 0

    def __init__(
        self,
        upload_error: Exception | None = None,
        *,
        version_info: dict[str, object] | Exception | None = None,
        stream_complete: dict[str, object] | Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.upload_error = upload_error
        self.version_info = version_info
        self.stream_complete = stream_complete or {"file_path": "/napcat/temp/repo.7z"}
        type(self)._next_id += 1
        self.self_id = f"bot-{type(self)._next_id}"

    async def send_group_forward_msg(self, **kwargs: object) -> None:
        self.calls.append(("send_group_forward_msg", kwargs))

    async def upload_group_file(self, **kwargs: object) -> None:
        if self.upload_error is not None:
            raise self.upload_error
        self.calls.append(("upload_group_file", kwargs))

    async def get_version_info(self) -> dict[str, object]:
        self.calls.append(("get_version_info", {}))
        if isinstance(self.version_info, Exception):
            raise self.version_info
        return self.version_info or {"app_name": "Generic.OneBot"}

    async def call_api(self, api: str, **kwargs: object):
        self.calls.append((api, kwargs))
        if api == "upload_file_stream" and kwargs.get("is_complete"):
            if isinstance(self.stream_complete, Exception):
                raise self.stream_complete
            return self.stream_complete
        return {"status": "ok"}


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
        "git_poller_upload_api_timeout": 3600.0,
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
    )

    asyncio.run(message.upload_archive_to_group(bot, 10001, archive, config=_config()))

    assert bot.calls[0][0] == "get_version_info"
    assert bot.calls[1][0] == "upload_group_file"
    assert bot.calls[1][1]["group_id"] == 10001
    assert bot.calls[1][1]["file"] == "/tmp/repo.7z"
    assert bot.calls[1][1]["name"] == "repo.7z"
    assert bot.calls[1][1]["_timeout"] == 3600.0


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

    assert bot.calls[0][0] == "get_version_info"
    assert bot.calls[1][0] == "upload_group_file"
    parsed = urlparse(str(bot.calls[1][1]["file"]))
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:8080"
    assert parsed.path == "/git-poller/files/repo%20main.7z"
    assert "expires" in query
    assert "token" in query
    assert bot.calls[1][1]["name"] == "repo-main.7z"
    assert bot.calls[1][1]["_timeout"] == 3600.0


def test_upload_archive_to_group_uses_napcat_stream_api(tmp_path: Path, monkeypatch):
    bot = _Bot(
        version_info={"app_name": "NapCat.Onebot", "app_version": "test"},
        stream_complete={"file_path": "/app/.config/QQ/NapCat/temp/repo-main.7z"},
    )
    archive_path = tmp_path / "repo-main.7z"
    archive_path.write_bytes(b"abcdef")
    archive = SimpleNamespace(
        path=archive_path,
        name="repo-main.7z",
        sha256="0" * 64,
        password=None,
    )
    monkeypatch.setattr(message, "NAPCAT_STREAM_CHUNK_SIZE", 2)
    message._napcat_detection_cache.clear()

    asyncio.run(message.upload_archive_to_group(bot, 10001, archive, config=_config()))

    assert [call[0] for call in bot.calls] == [
        "get_version_info",
        "upload_file_stream",
        "upload_file_stream",
        "upload_file_stream",
        "upload_file_stream",
        "upload_file_stream",
        "upload_group_file",
    ]
    init_call = bot.calls[1][1]
    assert init_call["total_chunks"] == 3
    assert init_call["file_size"] == 6
    assert init_call["filename"] == "repo-main.7z"
    assert init_call["expected_sha256"] == "0" * 64
    assert init_call["file_retention"] == 4200000
    assert init_call["_timeout"] == 3600.0
    chunk_calls = [call[1] for call in bot.calls[2:5]]
    assert [call["chunk_index"] for call in chunk_calls] == [0, 1, 2]
    assert all(call["_timeout"] == 3600.0 for call in chunk_calls)
    assert bot.calls[5][1]["is_complete"] is True
    assert bot.calls[6][1]["file"] == "/app/.config/QQ/NapCat/temp/repo-main.7z"
    assert bot.calls[6][1]["name"] == "repo-main.7z"
    assert bot.calls[6][1]["_timeout"] == 3600.0


def test_upload_archive_to_group_falls_back_when_napcat_stream_completion_fails(
    tmp_path: Path,
):
    bot = _Bot(
        version_info={"app_name": "NapCat.Onebot"},
        stream_complete=RuntimeError("stream failed"),
    )
    archive_path = tmp_path / "repo.7z"
    archive_path.write_bytes(b"archive")
    archive = SimpleNamespace(
        path=archive_path,
        name="repo.7z",
        sha256="0" * 64,
        password=None,
        password_used=False,
    )
    message._napcat_detection_cache.clear()

    asyncio.run(message.upload_archive_to_group(bot, 10001, archive, config=_config()))

    assert any(call[0] == "upload_file_stream" for call in bot.calls)
    upload_calls = [call for call in bot.calls if call[0] == "upload_group_file"]
    assert upload_calls[-1][1]["file"] == str(archive_path)
    assert upload_calls[-1][1]["_timeout"] == 3600.0


def test_upload_archive_to_group_does_not_reset_completed_napcat_stream_without_file_path(
    tmp_path: Path,
):
    bot = _Bot(
        version_info={"app_name": "NapCat.Onebot"},
        stream_complete={"status": "ok"},
    )
    archive_path = tmp_path / "repo.7z"
    archive_path.write_bytes(b"archive")
    archive = SimpleNamespace(
        path=archive_path,
        name="repo.7z",
        sha256="0" * 64,
        password=None,
    )
    message._napcat_detection_cache.clear()

    asyncio.run(message.upload_archive_to_group(bot, 10001, archive, config=_config()))

    assert not any(
        call[0] == "upload_file_stream" and call[1].get("reset")
        for call in bot.calls
    )
    upload_calls = [call for call in bot.calls if call[0] == "upload_group_file"]
    assert upload_calls[-1][1]["file"] == str(archive_path)


def test_upload_file_to_napcat_stream_reraises_stream_errors(tmp_path: Path):
    archive_path = tmp_path / "repo.7z"
    archive_path.write_bytes(b"archive")
    original = message.NapCatStreamUploadError("stream ended early")

    class _StreamErrorBot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def call_api(self, api: str, **kwargs: object):
            self.calls.append((api, kwargs))
            if kwargs.get("reset"):
                return {"status": "ok"}
            raise original

    bot = _StreamErrorBot()

    try:
        asyncio.run(
            message._upload_file_to_napcat_stream(
                bot,
                archive_path,
                "repo.7z",
                _config(),
                expected_sha256="0" * 64,
            )
        )
    except message.NapCatStreamUploadError as exc:
        assert exc is original
        assert exc.__cause__ is None
    else:
        raise AssertionError("stream upload should fail")

    assert any(
        call[0] == "upload_file_stream" and call[1].get("reset")
        for call in bot.calls
    )


def test_is_napcat_bot_without_self_id_returns_false():
    class _NoSelfIdBot:
        async def get_version_info(self):
            raise AssertionError("self_id-less bot should not be queried")

    message._napcat_detection_cache.clear()

    assert asyncio.run(message._is_napcat_bot(_NoSelfIdBot())) is False
    assert message._napcat_detection_cache == {}


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


def test_build_subscription_list_text_uses_user_facing_fields_and_passwords():
    subscriptions = {
        "repo-key-a": models.Subscription(
            url="https://github.com/example/repo.git",
            branch="main",
            schedule="每日04:00",
            last_success_sha="oldsha1234567890",
            archive_password="repo-secret",
        ),
        "repo-key-b": models.Subscription(
            url="https://gitlab.example.com/team/api.git",
            branch="dev",
            schedule="周一04:30",
            last_success_sha=None,
            archive_password=None,
        ),
    }

    text = message.build_subscription_list_text(
        subscriptions,
        default_archive_password="global-secret",
    )

    assert text.splitlines() == [
        "本群关注的仓库：",
        "1. Git链接：https://github.com/example/repo.git",
        "   分支：main",
        "   计划时间：每日04:00",
        "   SHA：oldsha12",
        "   密码：repo-secret",
        "2. Git链接：https://gitlab.example.com/team/api.git",
        "   分支：dev",
        "   计划时间：周一04:30",
        "   SHA：未记录",
        "   密码：global-secret",
    ]
    assert "key:" not in text
    assert "archive_password" not in text
    assert "全局默认" not in text


def test_build_subscription_list_text_shows_no_password_without_defaults():
    text = message.build_subscription_list_text(
        {
            "repo-key": models.Subscription(
                url="https://github.com/example/repo.git",
                branch="main",
                schedule="每日04:00",
            )
        }
    )

    assert "密码：无" in text


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
