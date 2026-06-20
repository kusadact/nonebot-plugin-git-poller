from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

from helpers import load_plugin_module

nonebot_module = types.ModuleType("nonebot")
nonebot_module.logger = SimpleNamespace(debug=lambda *args, **kwargs: None, info=lambda *args, **kwargs: None)
adapters_module = types.ModuleType("nonebot.adapters")
onebot_module = types.ModuleType("nonebot.adapters.onebot")
v11_module = types.ModuleType("nonebot.adapters.onebot.v11")
v11_module.Bot = object
v11_module.Message = str
v11_module.MessageSegment = SimpleNamespace(node_custom=lambda **kwargs: ("node", kwargs))
sys.modules["nonebot"] = nonebot_module
sys.modules["nonebot.adapters"] = adapters_module
sys.modules["nonebot.adapters.onebot"] = onebot_module
sys.modules["nonebot.adapters.onebot.v11"] = v11_module

models = load_plugin_module("models")
message = load_plugin_module("message")


class _Bot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def send_group_forward_msg(self, **kwargs: object) -> None:
        self.calls.append(("send_group_forward_msg", kwargs))


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
                sha="newsha123",
                short_sha="newsha12",
                title="Add feature",
                committed_at="2026-06-20T04:00:00+08:00",
                author="Alice",
                url="https://github.com/example/repo/commit/newsha123",
            )
        ],
    )


def test_build_forward_nodes_contains_summary_and_commits():
    nodes = message.build_forward_nodes(_payload())

    assert len(nodes) == 2
    summary = nodes[0][1]["content"]
    commit = nodes[1][1]["content"]
    assert "仓库更新：repo" in summary
    assert "新增 commit：1" in summary
    assert "oldsha12" in summary
    assert "Add feature" in commit
    assert "Alice" in commit


def test_send_update_to_group_uses_forward_message_only():
    bot = _Bot()

    asyncio.run(message.send_update_to_group(bot, 10001, _payload()))

    assert bot.calls[0][0] == "send_group_forward_msg"
    assert bot.calls[0][1]["group_id"] == 10001
    assert len(bot.calls[0][1]["messages"]) == 2
