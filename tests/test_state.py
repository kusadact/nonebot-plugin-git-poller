from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace


def _load_state_module(data_dir: Path):
    package_dir = Path(__file__).resolve().parents[1] / "src" / "nonebot_plugin_git_poller"
    package = types.ModuleType("nonebot_plugin_git_poller")
    package.__path__ = [str(package_dir)]
    package.__spec__ = importlib.util.spec_from_loader(
        "nonebot_plugin_git_poller",
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

    sys.modules["nonebot_plugin_git_poller"] = package
    sys.modules["nonebot"] = nonebot_module
    sys.modules["nonebot_plugin_localstore"] = localstore_module

    for name in ("models", "state"):
        module_name = f"nonebot_plugin_git_poller.{name}"
        spec = importlib.util.spec_from_file_location(module_name, package_dir / f"{name}.py")
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return sys.modules["nonebot_plugin_git_poller.state"], sys.modules["nonebot_plugin_git_poller.models"]


def test_subscriptions_are_group_and_repo_scoped(tmp_path: Path):
    state, models = _load_state_module(tmp_path)
    store = state.StateStore()

    store.upsert_subscription(
        10001,
        "repo-a",
        models.Subscription(url="https://example.test/a.git", branch="main", schedule="每天04:00"),
    )
    store.upsert_subscription(
        10001,
        "repo-b",
        models.Subscription(url="https://example.test/b.git", branch="dev", schedule="周一04:30"),
    )
    store.upsert_subscription(
        10002,
        "repo-a",
        models.Subscription(url="https://example.test/a.git", branch="main", schedule="每天04:00"),
    )

    group_one = store.list_group_subscriptions(10001)
    group_two = store.list_group_subscriptions(10002)

    assert sorted(group_one) == ["repo-a", "repo-b"]
    assert sorted(group_two) == ["repo-a"]
    assert group_one["repo-b"].branch == "dev"


def test_update_last_success_only_changes_target_subscription(tmp_path: Path):
    state, models = _load_state_module(tmp_path)
    store = state.StateStore()
    store.upsert_subscription(
        10001,
        "repo-a",
        models.Subscription(url="https://example.test/a.git", branch="main", schedule="每天04:00"),
    )
    store.upsert_subscription(
        10001,
        "repo-b",
        models.Subscription(url="https://example.test/b.git", branch="main", schedule="每天04:00"),
    )

    store.update_last_success(10001, "repo-a", "abc123", "2026-06-20T04:00:00+08:00")

    assert store.get_subscription(10001, "repo-a").last_success_sha == "abc123"
    assert store.get_subscription(10001, "repo-b").last_success_sha is None


def test_update_last_archive_path_only_changes_target_subscription(tmp_path: Path):
    state, models = _load_state_module(tmp_path)
    store = state.StateStore()
    store.upsert_subscription(
        10001,
        "repo-a",
        models.Subscription(url="https://example.test/a.git", branch="main", schedule="每天04:00"),
    )
    store.upsert_subscription(
        10001,
        "repo-b",
        models.Subscription(url="https://example.test/b.git", branch="main", schedule="每天04:00"),
    )

    store.update_last_archive_path(
        10001,
        "repo-a",
        "/tmp/archive.7z",
        "2026-06-20T04:00:00+08:00",
    )

    assert store.get_subscription(10001, "repo-a").last_archive_path == "/tmp/archive.7z"
    assert store.get_subscription(10001, "repo-b").last_archive_path is None


def test_update_schedule_and_archive_password(tmp_path: Path):
    state, models = _load_state_module(tmp_path)
    store = state.StateStore()
    store.upsert_subscription(
        10001,
        "repo-a",
        models.Subscription(url="https://example.test/a.git", branch="main", schedule="每天04:00"),
    )

    store.update_schedule(10001, "repo-a", "周一04:30", "2026-06-20T04:00:00+08:00")
    store.update_archive_password(10001, "repo-a", "secret", "2026-06-20T04:01:00+08:00")

    subscription = store.get_subscription(10001, "repo-a")
    assert subscription.schedule == "周一04:30"
    assert subscription.archive_password == "secret"

    store.update_archive_password(10001, "repo-a", None, "2026-06-20T04:02:00+08:00")

    assert store.get_subscription(10001, "repo-a").archive_password is None


def test_subscriptions_for_schedule_filters_enabled_entries(tmp_path: Path):
    state, models = _load_state_module(tmp_path)
    store = state.StateStore()
    store.upsert_subscription(
        10001,
        "repo-a",
        models.Subscription(url="https://example.test/a.git", branch="main", schedule="每天04:00"),
    )
    store.upsert_subscription(
        10001,
        "repo-b",
        models.Subscription(
            url="https://example.test/b.git",
            branch="main",
            schedule="每天04:00",
            enabled=False,
        ),
    )
    store.upsert_subscription(
        10002,
        "repo-c",
        models.Subscription(url="https://example.test/c.git", branch="main", schedule="周一04:30"),
    )

    matches = store.subscriptions_for_schedule("每天04:00")

    assert [(group_id, repo_key) for group_id, repo_key, _ in matches] == [
        (10001, "repo-a")
    ]


def test_is_repo_key_subscribed_checks_all_groups(tmp_path: Path):
    state, models = _load_state_module(tmp_path)
    store = state.StateStore()
    store.upsert_subscription(
        10002,
        "repo-a",
        models.Subscription(url="https://example.test/a.git", branch="main", schedule="每天04:00"),
    )

    assert store.is_repo_key_subscribed("repo-a") is True
    assert store.is_repo_key_subscribed("repo-b") is False
