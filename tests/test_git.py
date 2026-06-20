from __future__ import annotations

from pathlib import Path
import sys
import types
from types import SimpleNamespace

from dulwich import porcelain

from helpers import load_plugin_module


def _load_git_module(cache_dir: Path):
    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.logger = SimpleNamespace(info=lambda *args, **kwargs: None)
    nonebot_module.get_plugin_config = lambda config_cls: config_cls()
    localstore_module = types.ModuleType("nonebot_plugin_localstore")
    localstore_module.get_plugin_cache_dir = lambda: cache_dir
    sys.modules["nonebot"] = nonebot_module
    sys.modules["nonebot_plugin_localstore"] = localstore_module

    load_plugin_module("models")
    load_plugin_module("config")
    load_plugin_module("repository")
    return load_plugin_module("git").GitRepositoryCache


def _commit(repo_path: Path, filename: str, content: str, message: str) -> str:
    (repo_path / filename).write_text(content, encoding="utf-8")
    porcelain.add(repo_path, paths=[filename])
    sha = porcelain.commit(
        repo_path,
        message=message,
        author=b"Alice <alice@example.test>",
        committer=b"Alice <alice@example.test>",
    )
    return sha.decode("ascii")


def test_git_repository_cache_fetches_local_repo_updates(tmp_path: Path):
    source = tmp_path / "source"
    porcelain.init(source)
    first_sha = _commit(source, "README.md", "one", "Initial commit")

    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    cache = GitRepositoryCache(
        SimpleNamespace(git_poller_proxy=None, git_poller_timeout=60.0)
    )

    fetched = cache.fetch("repo", str(source), "master")
    try:
        assert fetched.head_sha == first_sha
        assert fetched.commits_since(None, max_count=20)[0].title == "Initial commit"
    finally:
        fetched.close()

    second_sha = _commit(source, "README.md", "two", "Second commit")

    fetched = cache.fetch("repo", str(source), "master")
    try:
        assert fetched.head_sha == second_sha
        commits = fetched.commits_since(first_sha, max_count=20)
        assert [commit.title for commit in commits] == ["Second commit"]
    finally:
        fetched.close()


def test_git_repository_cache_peeks_remote_head_without_clone(tmp_path: Path):
    source = tmp_path / "source"
    porcelain.init(source)
    head_sha = _commit(source, "README.md", "one", "Initial commit")

    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    cache = GitRepositoryCache(
        SimpleNamespace(git_poller_proxy=None, git_poller_timeout=60.0)
    )

    assert cache.peek_head(str(source), "master") == head_sha
    assert not (tmp_path / "cache" / "repos" / "repo").exists()
