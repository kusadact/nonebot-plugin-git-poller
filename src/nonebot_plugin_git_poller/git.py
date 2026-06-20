from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
import shutil
from typing import Any

from dulwich import porcelain
from dulwich.client import _import_remote_refs, get_transport_and_path
from dulwich.config import StackedConfig, env_config
from dulwich.errors import NotGitRepository
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from nonebot import logger
from nonebot_plugin_localstore import get_plugin_cache_dir
import os
import urllib3

from .config import Config
from .models import CommitInfo
from .repository import build_commit_url


@dataclass(frozen=True)
class RemoteHead:
    branch: str
    sha: str


class GitRepositoryCache:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.cache_dir = get_plugin_cache_dir() / "repos"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, repo_key: str, url: str, branch: str) -> "FetchedRepository":
        repo_path = self.cache_dir / repo_key
        fetch_result = None
        if not _looks_like_bare_repo(repo_path):
            if repo_path.exists():
                raise NotGitRepository(str(repo_path))
            logger.info(f"git poller cloning repository cache: {url} -> {repo_path}")
            porcelain.clone(
                url,
                repo_path,
                bare=True,
                branch=branch,
                errstream=BytesIO(),
                **self._porcelain_transport_kwargs(url),
            )
        else:
            logger.info(f"git poller fetching repository cache: {url} -> {repo_path}")
            fetch_result = self._fetch_existing_repo(repo_path, url)

        repo = Repo(repo_path)
        head_sha = _resolve_branch_head(repo, branch, remote_refs=getattr(fetch_result, "refs", None))
        return FetchedRepository(repo=repo, url=url, branch=branch, head_sha=head_sha)

    def peek_head(self, url: str, branch: str) -> str:
        return self.resolve_remote_head(url, branch).sha

    def resolve_remote_head(self, url: str, branch: str | None = None) -> RemoteHead:
        logger.info(f"git poller checking remote head: {url} branch={branch or '<default>'}")
        client, path = get_transport_and_path(
            url,
            config=self._git_config(),
            quiet=True,
            pool_manager=self._pool_manager(url),
        )
        result = client.get_refs(_encode_path(path))
        if branch is None:
            remote_head = _resolve_remote_default_head(result.refs, result.symrefs)
        else:
            remote_head = RemoteHead(
                branch=branch,
                sha=_resolve_remote_branch_head(result.refs, branch),
            )
        logger.info(
            f"git poller remote head resolved: {url} "
            f"branch={remote_head.branch} sha={remote_head.sha[:8]}"
        )
        return remote_head

    def remove_cache(self, repo_key: str) -> bool:
        repo_path = self.cache_dir / repo_key
        try:
            repo_path.resolve().relative_to(self.cache_dir.resolve())
        except ValueError:
            logger.warning(f"git poller refused to remove cache outside repo cache: {repo_path}")
            return False
        if not repo_path.exists():
            return False
        shutil.rmtree(repo_path)
        logger.info(f"git poller removed repository cache: {repo_path}")
        return True

    def cached_repo_keys(self) -> set[str]:
        result: set[str] = set()
        for path in self.cache_dir.iterdir():
            if path.is_dir() and _looks_like_bare_repo(path):
                result.add(path.name)
        return result

    def _porcelain_transport_kwargs(self, url: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"quiet": True}
        pool_manager = self._pool_manager(url)
        if pool_manager is not None:
            kwargs["pool_manager"] = pool_manager
        return kwargs

    def _fetch_existing_repo(self, repo_path: Path, url: str):
        repo = Repo(repo_path)
        try:
            client, path = get_transport_and_path(
                url,
                config=repo.get_config_stack(),
                quiet=True,
                pool_manager=self._pool_manager(url),
            )
            fetch_result = client.fetch(
                _encode_path(path),
                repo,
                progress=lambda data: None,
            )
            _import_remote_refs(
                repo.refs,
                "origin",
                fetch_result.refs,
                message=b"fetch: from " + url.encode("utf-8"),
                prune=True,
            )
            return fetch_result
        finally:
            repo.close()

    def _pool_manager(self, url: str) -> urllib3.PoolManager | urllib3.ProxyManager | None:
        if url.startswith(("http://", "https://")):
            if self.config.git_poller_proxy:
                return urllib3.ProxyManager(
                    self.config.git_poller_proxy,
                    timeout=self.config.git_poller_timeout,
                )
            return urllib3.PoolManager(
                timeout=self.config.git_poller_timeout,
            )
        return None

    @staticmethod
    def _git_config() -> StackedConfig:
        config = StackedConfig.default()
        env_override = env_config(os.environ)
        if env_override is not None:
            config.backends.insert(0, env_override)
        return config


class FetchedRepository:
    def __init__(self, repo: Repo, url: str, branch: str, head_sha: str) -> None:
        self.repo = repo
        self.url = url
        self.branch = branch
        self.head_sha = head_sha

    def head_commit(self) -> CommitInfo:
        return self.commit_info(self.head_sha)

    def commit_info(self, sha: str) -> CommitInfo:
        commit = self.repo.get_object(sha.encode("ascii"))
        if not isinstance(commit, Commit):
            raise TypeError(f"object is not a commit: {sha}")
        return _commit_to_info(commit, self.url)

    def commits_since(self, previous_sha: str | None, *, max_count: int) -> list[CommitInfo]:
        if previous_sha and _has_object(self.repo, previous_sha):
            include = [self.head_sha.encode("ascii")]
            exclude = [previous_sha.encode("ascii")]
            walker = self.repo.get_walker(
                include=include,
                exclude=exclude,
                reverse=True,
                max_entries=max_count,
            )
            commits = [
                _commit_to_info(entry.commit, self.url)
                for entry in walker
                if isinstance(entry.commit, Commit)
            ]
            return commits or [self.head_commit()]

        return [self.head_commit()]

    def count_commits_since(self, previous_sha: str | None) -> int | None:
        if not previous_sha:
            return None
        if not _has_object(self.repo, previous_sha):
            return None
        walker = self.repo.get_walker(
            include=[self.head_sha.encode("ascii")],
            exclude=[previous_sha.encode("ascii")],
        )
        return sum(1 for entry in walker if isinstance(entry.commit, Commit))

    def export_head_tree(self, target_dir: Path) -> None:
        commit = self.repo.get_object(self.head_sha.encode("ascii"))
        if not isinstance(commit, Commit):
            raise TypeError(f"object is not a commit: {self.head_sha}")
        target_dir.mkdir(parents=True, exist_ok=True)
        tree = self.repo.get_object(commit.tree)
        if not isinstance(tree, Tree):
            raise TypeError(f"object is not a tree: {commit.tree!r}")
        self._export_tree(tree, target_dir, target_dir.resolve())

    def close(self) -> None:
        self.repo.close()

    def _export_tree(self, tree: Tree, target_dir: Path, root_dir: Path) -> None:
        for entry in tree.iteritems(name_order=True):
            name = entry.path.decode("utf-8", errors="replace")
            if not _safe_tree_entry_name(name):
                logger.warning(f"git poller skipped unsafe tree path while exporting: {name!r}")
                continue
            path = _safe_export_path(target_dir, name, root_dir)
            if path is None:
                logger.warning(f"git poller skipped tree path outside export root: {name!r}")
                continue
            mode = entry.mode
            obj = self.repo.get_object(entry.sha)
            if isinstance(obj, Tree):
                path.mkdir(parents=True, exist_ok=True)
                self._export_tree(obj, path, root_dir)
                continue
            if not isinstance(obj, Blob):
                logger.warning(f"git poller skipped non-blob object while exporting: {path}")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            data = obj.as_raw_string()
            if _is_symlink_mode(mode):
                # Keep archive generation inside the exported tree even when
                # a repository contains links that point elsewhere.
                path.write_text(data.decode("utf-8", errors="replace"), encoding="utf-8")
                continue
            path.write_bytes(data)
            if _is_executable_mode(mode):
                path.chmod(path.stat().st_mode | 0o111)


def _resolve_branch_head(
    repo: Repo,
    branch: str,
    *,
    remote_refs: dict[bytes, bytes | None] | None = None,
) -> str:
    if remote_refs:
        return _resolve_remote_branch_head(remote_refs, branch)
    refs = repo.get_refs()
    candidates = [
        f"refs/remotes/origin/{branch}".encode("utf-8"),
        f"refs/heads/{branch}".encode("utf-8"),
    ]
    if _is_head_branch(branch):
        candidates.extend(
            [
                f"refs/remotes/origin/HEAD".encode("utf-8"),
                b"HEAD",
            ]
        )
    for candidate in candidates:
        value = refs.get(candidate)
        if value:
            return value.decode("ascii")
    raise RuntimeError(f"找不到分支：{branch}")


def _resolve_remote_branch_head(refs: dict[bytes, bytes | None], branch: str) -> str:
    candidates = [
        f"refs/heads/{branch}".encode("utf-8"),
    ]
    if _is_head_branch(branch):
        candidates.append(b"HEAD")
    for candidate in candidates:
        value = refs.get(candidate)
        if value:
            return value.decode("ascii")
    raise RuntimeError(f"找不到分支：{branch}")


def _resolve_remote_default_head(
    refs: dict[bytes, bytes | None],
    symrefs: dict[bytes, bytes],
) -> RemoteHead:
    head_ref = symrefs.get(b"HEAD")
    if head_ref:
        branch = _branch_name_from_ref(head_ref)
        if branch:
            value = refs.get(head_ref) or refs.get(b"HEAD")
            if value:
                return RemoteHead(branch=branch, sha=value.decode("ascii"))

    head_value = refs.get(b"HEAD")
    if head_value:
        matches = [
            RemoteHead(branch=branch, sha=value.decode("ascii"))
            for branch, value in _remote_branch_refs(refs)
            if value == head_value
        ]
        if matches:
            return _choose_default_head_match(matches)

    branch_refs = _remote_branch_refs(refs)
    if len(branch_refs) == 1:
        branch, value = branch_refs[0]
        return RemoteHead(branch=branch, sha=value.decode("ascii"))

    raise RuntimeError("无法解析远端默认分支。")


def _remote_branch_refs(refs: dict[bytes, bytes | None]) -> list[tuple[str, bytes]]:
    result: list[tuple[str, bytes]] = []
    for ref, value in refs.items():
        if not value:
            continue
        branch = _branch_name_from_ref(ref)
        if branch:
            result.append((branch, value))
    return result


def _branch_name_from_ref(ref: bytes) -> str | None:
    prefix = b"refs/heads/"
    if not ref.startswith(prefix):
        return None
    branch = ref[len(prefix):].decode("utf-8", errors="replace").strip()
    return branch or None


def _choose_default_head_match(matches: list[RemoteHead]) -> RemoteHead:
    for preferred in ("main", "master"):
        for match in matches:
            if match.branch == preferred:
                return match
    return sorted(matches, key=lambda item: item.branch)[0]


def _is_head_branch(branch: str) -> bool:
    return branch.strip().upper() == "HEAD"


def _commit_to_info(commit: Commit, repo_url: str) -> CommitInfo:
    sha = commit.id.decode("ascii")
    title = _decode(commit.message).splitlines()[0].strip() or sha[:8]
    author = _author_name(_decode(commit.author))
    committed_at = _format_git_time(commit.commit_time, commit.commit_timezone)
    return CommitInfo(
        sha=sha,
        short_sha=sha[:8],
        title=title,
        committed_at=committed_at,
        author=author,
        url=build_commit_url(repo_url, sha),
    )


def _format_git_time(timestamp: int, offset: int) -> str:
    tz = timezone(timedelta(seconds=offset))
    return datetime.fromtimestamp(timestamp, tz=tz).isoformat(timespec="seconds")


def _author_name(value: str) -> str:
    if "<" in value:
        return value.split("<", 1)[0].strip()
    return value.strip()


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _safe_tree_entry_name(name: str) -> bool:
    return (
        name not in {"", ".", ".."}
        and "/" not in name
        and "\\" not in name
        and not Path(name).is_absolute()
    )


def _safe_export_path(target_dir: Path, name: str, root_dir: Path) -> Path | None:
    path = target_dir / name
    try:
        path.resolve().relative_to(root_dir)
    except ValueError:
        return None
    return path


def _encode_path(path: str | bytes) -> bytes:
    return path.encode("utf-8") if isinstance(path, str) else path


def _has_object(repo: Repo, sha: str) -> bool:
    try:
        repo.get_object(sha.encode("ascii"))
    except KeyError:
        return False
    return True


def _is_symlink_mode(mode: int) -> bool:
    return mode == 0o120000


def _is_executable_mode(mode: int) -> bool:
    return mode == 0o100755


def _looks_like_bare_repo(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "objects").is_dir()
        and (path / "refs").is_dir()
        and (path / "HEAD").is_file()
    )
