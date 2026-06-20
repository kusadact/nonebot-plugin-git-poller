from __future__ import annotations

import asyncio
from pathlib import Path
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
        if previous_sha == self.head_sha:
            return []
        return self._commits[:max_count]

    def count_commits_since(self, previous_sha: str | None):
        if previous_sha == self.head_sha:
            return 0
        if previous_sha:
            return len(self._commits)
        return None

    def export_head_tree(self, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "README.md").write_text("archive", encoding="utf-8")

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


class _ArchiveBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def source_root(self, payload):
        return Path("/tmp") / f"{payload.repo_key}-{payload.target_short_sha}"

    def build(self, payload, subscription, source_dir):
        self.calls.append((payload.repo_key, subscription.archive_password))
        return SimpleNamespace(
            path=Path("/tmp/archive.7z"),
            name=f"{payload.repo_name}.7z",
            password_used=subscription.archive_password is not None,
        )


def _service(
    state: _State,
    git_cache: _GitCache,
    archive_builder: _ArchiveBuilder | None = None,
):
    return mirror.GitPollerService(
        _config(),
        state=state,
        git_cache=git_cache,
        archive_builder=archive_builder or _ArchiveBuilder(),
    )


def _config(**overrides):
    values = {
        "git_poller_default_schedule": "每日04-00",
        "git_poller_timezone": "Asia/Shanghai",
        "git_poller_default_branch": "main",
        "git_poller_proxy": None,
        "git_poller_timeout": 60.0,
        "git_poller_archive_password": None,
        "git_poller_command_priority": 10,
        "git_poller_max_commits": 20,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_follow_repo_records_head():
    state = _State()
    git_cache = _GitCache()
    service = _service(state, git_cache)

    result = asyncio.run(service.follow_repo(10001, "https://example.test/repo"))

    assert result.already_following is False
    assert result.subscription.last_success_sha == "newsha1234567890"
    assert state.get_subscription(10001, result.identity.key).url == "https://example.test/repo.git"
    assert git_cache.calls == [("peek", "https://example.test/repo.git", "main")]


def test_follow_repo_accepts_branch_override():
    state = _State()
    git_cache = _GitCache()
    service = _service(state, git_cache)

    result = asyncio.run(service.follow_repo(10001, "https://example.test/repo.git", "dev"))

    assert result.subscription.branch == "dev"
    assert "-dev-" in result.identity.key
    assert git_cache.calls == [("peek", "https://example.test/repo.git", "dev")]


def test_follow_repo_detects_duplicate_in_same_group():
    state = _State()
    git_cache = _GitCache()
    service = _service(state, git_cache)

    first = asyncio.run(service.follow_repo(10001, "https://example.test/repo"))
    second = asyncio.run(service.follow_repo(10001, "https://example.test/repo.git"))

    assert first.identity.key == second.identity.key
    assert second.already_following is True
    assert len(git_cache.calls) == 1


def test_follow_repo_allows_same_url_with_different_branches():
    state = _State()
    git_cache = _GitCache()
    service = _service(state, git_cache)

    main = asyncio.run(service.follow_repo(10001, "https://example.test/repo"))
    dev = asyncio.run(service.follow_repo(10001, "https://example.test/repo", "dev"))

    assert main.identity.key != dev.identity.key
    assert sorted(state.list_group_subscriptions(10001)) == sorted(
        [main.identity.key, dev.identity.key]
    )


def test_pull_repo_builds_archive_without_marking_success():
    state = _State()
    git_cache = _GitCache()
    archive_builder = _ArchiveBuilder()
    service = _service(state, git_cache, archive_builder)
    identity = repository.build_identity("https://example.test/repo.git", "main")
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

    assert state.successes == []
    assert result.previous_sha == "oldsha123"
    assert result.target_sha == "newsha1234567890"
    assert result.archive.name == "repo.7z"
    assert archive_builder.calls == [(identity.key, None)]

    service.mark_pull_success(10001, identity.key, result.target_sha)

    assert state.successes == [(10001, identity.key, "newsha1234567890")]


def test_summarize_repo_builds_payload_without_marking_success():
    state = _State()
    git_cache = _GitCache()
    archive_builder = _ArchiveBuilder()
    service = _service(state, git_cache, archive_builder)
    identity = repository.build_identity("https://example.test/repo.git", "main")
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

    summary = asyncio.run(service.summarize_repo(10001, "https://example.test/repo"))

    assert summary.behind_count == 1
    assert summary.result.payload.previous_sha == "oldsha123"
    assert summary.result.payload.commits[0].title == "New commit"
    assert state.successes == []


def test_summarize_repo_reports_same_head_with_empty_commits():
    state = _State()
    git_cache = _GitCache()
    service = _service(state, git_cache)
    identity = repository.build_identity("https://example.test/repo.git", "main")
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

    summary = asyncio.run(service.summarize_repo(10001, "https://example.test/repo"))

    assert summary.behind_count == 0
    assert summary.result.payload.previous_sha == "newsha1234567890"
    assert summary.result.payload.commits == []


def test_poll_schedule_skips_unchanged_subscriptions():
    state = _State()
    git_cache = _GitCache()
    service = _service(state, git_cache)
    identity = repository.build_identity("https://example.test/repo.git", "main")
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
    service = _service(state, git_cache)
    identity = repository.build_identity("https://example.test/repo.git", "main")
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

    assert [delivery.result.group_id for delivery in results] == [10001, 10002]
    assert [delivery.result.payload.previous_sha for delivery in results] == [
        "oldsha-10001",
        "oldsha-10002",
    ]
    assert [delivery.archive.name for delivery in results] == ["repo.7z", "repo.7z"]
