from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

from helpers import load_plugin_module

nonebot_module = types.ModuleType("nonebot")
nonebot_module.logger = SimpleNamespace(
    debug=lambda *args, **kwargs: None,
    info=lambda *args, **kwargs: None,
)
nonebot_module.get_plugin_config = lambda config_cls: config_cls()
localstore_module = types.ModuleType("nonebot_plugin_localstore")
localstore_module.get_plugin_cache_dir = lambda: None
localstore_module.get_plugin_data_dir = lambda: None
sys.modules["nonebot"] = nonebot_module
sys.modules["nonebot_plugin_localstore"] = localstore_module

models = load_plugin_module("models")
config_module = load_plugin_module("config")
repository = load_plugin_module("repository")
git_module = load_plugin_module("git")
state_module = load_plugin_module("state")
mirror = load_plugin_module("mirror")


class _State:
    def __init__(self) -> None:
        self.data: dict[int, dict[str, object]] = {}
        self.successes: list[tuple[int, str, str]] = []

    def get_subscription(self, group_id: int, repo_key: str):
        return self.data.get(int(group_id), {}).get(repo_key)

    def list_group_subscriptions(self, group_id: int):
        return dict(self.data.get(int(group_id), {}))

    def list_all_subscriptions(self):
        return {group_id: dict(repos) for group_id, repos in self.data.items()}

    def upsert_subscription(self, group_id: int, repo_key: str, subscription: Subscription):
        self.data.setdefault(int(group_id), {})[repo_key] = subscription

    def remove_subscription(self, group_id: int, repo_key: str):
        return self.data.get(int(group_id), {}).pop(repo_key, None) is not None

    def update_last_success(self, group_id: int, repo_key: str, sha: str, updated_at: str):
        subscription = self.data[int(group_id)][repo_key]
        subscription.last_success_sha = sha
        subscription.updated_at = updated_at
        self.successes.append((int(group_id), repo_key, sha))

    def subscriptions_for_schedule(self, schedule: str):
        return [
            (group_id, repo_key, subscription)
            for group_id, repos in self.data.items()
            for repo_key, subscription in repos.items()
            if subscription.enabled and subscription.schedule == schedule
        ]


class _Fetched:
    def __init__(self, url: str, branch: str, head_sha: str, commits: list[object]) -> None:
        self.url = url
        self.branch = branch
        self.head_sha = head_sha
        self._commits = commits
        self.closed = False

    def commits_since(self, previous_sha: str | None, *, max_count: int):
        return self._commits[:max_count]

    def close(self) -> None:
        self.closed = True


class _GitCache:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.head_sha = "newsha1234567890"
        self.commits = [
            models.CommitInfo(
                sha="newsha1234567890",
                short_sha="newsha12",
                title="New commit",
                committed_at="2026-06-20T04:00:00+08:00",
                author="Alice",
                url="https://example.test/commit/newsha",
            )
        ]

    def fetch(self, repo_key: str, url: str, branch: str):
        self.calls.append((repo_key, url, branch))
        return _Fetched(url, branch, self.head_sha, self.commits)

    def peek_head(self, url: str, branch: str):
        self.calls.append(("peek", url, branch))
        return self.head_sha


def _config(**overrides):
    values = {
        "git_poller_default_schedule": "每日04-00",
        "git_poller_timezone": "Asia/Shanghai",
        "git_poller_default_branch": "main",
        "git_poller_push_on_first_follow": False,
        "git_poller_proxy": None,
        "git_poller_timeout": 60.0,
        "git_poller_command_priority": 10,
        "git_poller_max_commits": 20,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_follow_repo_records_head_without_first_push():
    state = _State()
    git_cache = _GitCache()
    service = mirror.GitPollerService(_config(), state=state, git_cache=git_cache)

    result = asyncio.run(service.follow_repo(10001, "https://example.test/repo"))

    assert result.already_following is False
    assert result.payload is None
    assert result.subscription.last_success_sha == "newsha1234567890"
    assert state.get_subscription(10001, result.identity.key).url == "https://example.test/repo.git"
    assert git_cache.calls == [("peek", "https://example.test/repo.git", "main")]


def test_follow_repo_can_prepare_first_push_payload():
    state = _State()
    git_cache = _GitCache()
    service = mirror.GitPollerService(
        _config(git_poller_push_on_first_follow=True),
        state=state,
        git_cache=git_cache,
    )

    result = asyncio.run(service.follow_repo(10001, "https://example.test/repo.git"))

    assert result.payload is not None
    assert result.subscription.last_success_sha is None
    assert result.payload.target_sha == "newsha1234567890"


def test_follow_repo_detects_duplicate_in_same_group():
    state = _State()
    git_cache = _GitCache()
    service = mirror.GitPollerService(_config(), state=state, git_cache=git_cache)

    first = asyncio.run(service.follow_repo(10001, "https://example.test/repo"))
    second = asyncio.run(service.follow_repo(10001, "https://example.test/repo.git"))

    assert first.identity.key == second.identity.key
    assert second.already_following is True
    assert len(git_cache.calls) == 1


def test_pull_repo_builds_payload_from_group_subscription_and_marks_success():
    state = _State()
    git_cache = _GitCache()
    service = mirror.GitPollerService(_config(), state=state, git_cache=git_cache)
    identity = repository.build_identity("https://example.test/repo.git")
    state.upsert_subscription(
        10001,
        identity.key,
        models.Subscription(
            url=identity.url,
            branch="main",
            schedule="每日04-00",
            last_success_sha="oldsha123",
        ),
    )

    result = asyncio.run(service.pull_repo(10001, "https://example.test/repo"))
    service.mark_success(result)

    assert result.payload.previous_sha == "oldsha123"
    assert result.payload.commits[0].title == "New commit"
    assert state.successes == [(10001, identity.key, "newsha1234567890")]


def test_poll_schedule_skips_unchanged_subscriptions():
    state = _State()
    git_cache = _GitCache()
    service = mirror.GitPollerService(_config(), state=state, git_cache=git_cache)
    identity = repository.build_identity("https://example.test/repo.git")
    state.upsert_subscription(
        10001,
        identity.key,
        models.Subscription(
            url=identity.url,
            branch="main",
            schedule="每日04-00",
            last_success_sha="newsha1234567890",
        ),
    )

    results = asyncio.run(service.poll_schedule("每日04-00"))

    assert results == []


def test_poll_schedule_returns_changed_subscriptions_per_group():
    state = _State()
    git_cache = _GitCache()
    service = mirror.GitPollerService(_config(), state=state, git_cache=git_cache)
    identity = repository.build_identity("https://example.test/repo.git")
    for group_id in (10001, 10002):
        state.upsert_subscription(
            group_id,
            identity.key,
            models.Subscription(
                url=identity.url,
                branch="main",
                schedule="每日04-00",
                last_success_sha=f"oldsha-{group_id}",
            ),
        )

    results = asyncio.run(service.poll_schedule("每日04-00"))

    assert [result.group_id for result in results] == [10001, 10002]
    assert [result.payload.previous_sha for result in results] == [
        "oldsha-10001",
        "oldsha-10002",
    ]
