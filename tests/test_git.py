from __future__ import annotations

from pathlib import Path
import sys
import types
from types import SimpleNamespace

from dulwich.client import LsRemoteResult
from dulwich.objects import Blob, Tree
from dulwich import porcelain

from helpers import load_plugin_module


def _load_git_module(cache_dir: Path):
    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
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
        export_dir = tmp_path / "export"
        fetched.export_head_tree(export_dir)
        assert (export_dir / "README.md").read_text(encoding="utf-8") == "two"
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


def test_git_repository_cache_lists_cached_repo_keys(tmp_path: Path):
    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    cache = GitRepositoryCache(
        SimpleNamespace(git_poller_proxy=None, git_poller_timeout=60.0)
    )
    repo_path = cache.cache_dir / "repo-key"
    porcelain.init(repo_path, bare=True)
    unrelated = cache.cache_dir / "not-a-repo"
    unrelated.mkdir()

    assert cache.cached_repo_keys() == {"repo-key"}


def test_git_repository_cache_peeks_http_head_without_porcelain_ls_remote(
    tmp_path: Path,
    monkeypatch,
):
    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    git_module = sys.modules["nonebot_plugin_git_poller.git"]
    head_sha = "a" * 40
    calls = {}

    class FakeClient:
        def get_refs(self, path: bytes):
            calls["path"] = path
            return LsRemoteResult({b"refs/heads/main": head_sha.encode("ascii")}, {})

    def fake_get_transport_and_path(location: str, **kwargs):
        calls["location"] = location
        calls["kwargs"] = kwargs
        return FakeClient(), "/owner/repo.git"

    def fail_ls_remote(*args, **kwargs):
        raise AssertionError("porcelain.ls_remote should not receive transport kwargs")

    monkeypatch.setattr(git_module, "get_transport_and_path", fake_get_transport_and_path)
    monkeypatch.setattr(git_module.porcelain, "ls_remote", fail_ls_remote)

    cache = GitRepositoryCache(
        SimpleNamespace(
            git_poller_proxy="http://127.0.0.1:7890",
            git_poller_timeout=12.5,
        )
    )

    assert cache.peek_head("https://example.test/owner/repo.git", "main") == head_sha
    assert calls["location"] == "https://example.test/owner/repo.git"
    assert calls["path"] == b"/owner/repo.git"
    assert calls["kwargs"]["quiet"] is True
    assert calls["kwargs"]["config"] is not None
    assert calls["kwargs"]["pool_manager"] is not None


def test_git_repository_cache_resolves_remote_default_branch_from_symref(
    tmp_path: Path,
    monkeypatch,
):
    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    git_module = sys.modules["nonebot_plugin_git_poller.git"]
    master_sha = "a" * 40
    main_sha = "b" * 40

    class FakeClient:
        def get_refs(self, path: bytes):
            return LsRemoteResult(
                {
                    b"HEAD": master_sha.encode("ascii"),
                    b"refs/heads/master": master_sha.encode("ascii"),
                    b"refs/heads/main": main_sha.encode("ascii"),
                },
                {b"HEAD": b"refs/heads/master"},
            )

    monkeypatch.setattr(
        git_module,
        "get_transport_and_path",
        lambda location, **kwargs: (FakeClient(), "/owner/repo.git"),
    )

    cache = GitRepositoryCache(
        SimpleNamespace(git_poller_proxy=None, git_poller_timeout=60.0)
    )

    remote_head = cache.resolve_remote_head("https://example.test/owner/repo.git")

    assert remote_head.branch == "master"
    assert remote_head.sha == master_sha


def test_git_repository_cache_resolves_remote_default_branch_from_head_sha(
    tmp_path: Path,
    monkeypatch,
):
    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    git_module = sys.modules["nonebot_plugin_git_poller.git"]
    head_sha = "a" * 40

    class FakeClient:
        def get_refs(self, path: bytes):
            return LsRemoteResult(
                {
                    b"HEAD": head_sha.encode("ascii"),
                    b"refs/heads/master": head_sha.encode("ascii"),
                },
                {},
            )

    monkeypatch.setattr(
        git_module,
        "get_transport_and_path",
        lambda location, **kwargs: (FakeClient(), "/owner/repo.git"),
    )

    cache = GitRepositoryCache(
        SimpleNamespace(git_poller_proxy=None, git_poller_timeout=60.0)
    )

    remote_head = cache.resolve_remote_head("https://example.test/owner/repo.git")

    assert remote_head.branch == "master"
    assert remote_head.sha == head_sha


def test_git_repository_cache_does_not_fallback_to_head_for_missing_branch(
    tmp_path: Path,
    monkeypatch,
):
    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    git_module = sys.modules["nonebot_plugin_git_poller.git"]
    head_sha = "a" * 40

    class FakeClient:
        def get_refs(self, path: bytes):
            return LsRemoteResult(
                {
                    b"HEAD": head_sha.encode("ascii"),
                    b"refs/heads/main": head_sha.encode("ascii"),
                },
                {},
            )

    monkeypatch.setattr(
        git_module,
        "get_transport_and_path",
        lambda location, **kwargs: (FakeClient(), "/owner/repo.git"),
    )

    cache = GitRepositoryCache(
        SimpleNamespace(git_poller_proxy=None, git_poller_timeout=60.0)
    )

    try:
        cache.peek_head("https://example.test/owner/repo.git", "dev")
    except RuntimeError as exc:
        assert "找不到分支：dev" in str(exc)
    else:
        raise AssertionError("missing branch must not fallback to remote HEAD")


def test_git_repository_cache_allows_explicit_head_branch(
    tmp_path: Path,
    monkeypatch,
):
    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    git_module = sys.modules["nonebot_plugin_git_poller.git"]
    head_sha = "a" * 40

    class FakeClient:
        def get_refs(self, path: bytes):
            return LsRemoteResult({b"HEAD": head_sha.encode("ascii")}, {})

    monkeypatch.setattr(
        git_module,
        "get_transport_and_path",
        lambda location, **kwargs: (FakeClient(), "/owner/repo.git"),
    )

    cache = GitRepositoryCache(
        SimpleNamespace(git_poller_proxy=None, git_poller_timeout=60.0)
    )

    assert cache.peek_head("https://example.test/owner/repo.git", "HEAD") == head_sha


def test_export_head_tree_writes_symlink_as_plain_file(tmp_path: Path):
    source = tmp_path / "source"
    repo = porcelain.init(source)

    link = Blob.from_string(b"../outside.txt")
    repo.object_store.add_object(link)
    tree = Tree()
    tree.add(b"link", 0o120000, link.id)
    repo.object_store.add_object(tree)
    sha = porcelain.commit_tree(
        repo,
        tree.id,
        message=b"Add symlink",
        author=b"Alice <alice@example.test>",
        committer=b"Alice <alice@example.test>",
    ).decode("ascii")

    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    cache = GitRepositoryCache(
        SimpleNamespace(git_poller_proxy=None, git_poller_timeout=60.0)
    )

    fetched = cache.fetch("repo", str(source), "master")
    try:
        assert fetched.head_sha == sha
        export_dir = tmp_path / "export"
        fetched.export_head_tree(export_dir)
        exported = export_dir / "link"
        assert exported.is_file()
        assert not exported.is_symlink()
        assert exported.read_text(encoding="utf-8") == "../outside.txt"
    finally:
        fetched.close()


def test_export_head_tree_skips_paths_outside_target_dir(tmp_path: Path):
    source = tmp_path / "source"
    repo = porcelain.init(source)

    blob = Blob.from_string(b"owned")
    repo.object_store.add_object(blob)
    tree = Tree()
    tree.add(b"../../outside.txt", 0o100644, blob.id)
    repo.object_store.add_object(tree)
    sha = porcelain.commit_tree(
        repo,
        tree.id,
        message=b"Add unsafe path",
        author=b"Alice <alice@example.test>",
        committer=b"Alice <alice@example.test>",
    ).decode("ascii")

    GitRepositoryCache = _load_git_module(tmp_path / "cache")
    cache = GitRepositoryCache(
        SimpleNamespace(git_poller_proxy=None, git_poller_timeout=60.0)
    )

    fetched = cache.fetch("repo", str(source), "master")
    try:
        assert fetched.head_sha == sha
        export_dir = tmp_path / "export"
        fetched.export_head_tree(export_dir)
        assert not (tmp_path / "outside.txt").exists()
        assert list(export_dir.rglob("*")) == []
    finally:
        fetched.close()
