from __future__ import annotations

from datetime import datetime, timezone, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from dulwich import porcelain
from dulwich.errors import NotGitRepository
from dulwich.objects import Commit
from dulwich.repo import Repo
from nonebot import logger
from nonebot_plugin_localstore import get_plugin_cache_dir
import urllib3

from .config import Config
from .models import CommitInfo
from .repository import build_commit_url


class GitRepositoryCache:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.cache_dir = get_plugin_cache_dir() / "repos"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, repo_key: str, url: str, branch: str) -> "FetchedRepository":
        repo_path = self.cache_dir / repo_key
        transport_kwargs = self._transport_kwargs(url)
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
                **transport_kwargs,
            )
        else:
            logger.info(f"git poller fetching repository cache: {url} -> {repo_path}")
            fetch_result = porcelain.fetch(
                repo_path,
                url,
                errstream=BytesIO(),
                outstream=StringIO(),
                prune=True,
                force=True,
                **transport_kwargs,
            )

        repo = Repo(repo_path)
        head_sha = _resolve_branch_head(repo, branch, remote_refs=getattr(fetch_result, "refs", None))
        return FetchedRepository(repo=repo, url=url, branch=branch, head_sha=head_sha)

    def peek_head(self, url: str, branch: str) -> str:
        logger.info(f"git poller checking remote head: {url} branch={branch}")
        result = porcelain.ls_remote(
            url,
            **self._transport_kwargs(url),
        )
        head_sha = _resolve_remote_branch_head(result.refs, branch)
        logger.info(
            f"git poller remote head resolved: {url} branch={branch} sha={head_sha[:8]}"
        )
        return head_sha

    def _transport_kwargs(self, url: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"quiet": True}
        if url.startswith(("http://", "https://")):
            pool_manager: urllib3.PoolManager | urllib3.ProxyManager
            if self.config.git_poller_proxy:
                pool_manager = urllib3.ProxyManager(
                    self.config.git_poller_proxy,
                    timeout=self.config.git_poller_timeout,
                )
            else:
                pool_manager = urllib3.PoolManager(
                    timeout=self.config.git_poller_timeout,
                )
            kwargs["pool_manager"] = pool_manager
        return kwargs


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

    def close(self) -> None:
        self.repo.close()


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
        f"refs/remotes/origin/HEAD".encode("utf-8"),
        b"HEAD",
    ]
    for candidate in candidates:
        value = refs.get(candidate)
        if value:
            return value.decode("ascii")
    raise RuntimeError(f"找不到分支：{branch}")


def _resolve_remote_branch_head(refs: dict[bytes, bytes | None], branch: str) -> str:
    candidates = [
        f"refs/heads/{branch}".encode("utf-8"),
        b"HEAD",
    ]
    for candidate in candidates:
        value = refs.get(candidate)
        if value:
            return value.decode("ascii")
    raise RuntimeError(f"找不到分支：{branch}")


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


def _has_object(repo: Repo, sha: str) -> bool:
    try:
        repo.get_object(sha.encode("ascii"))
    except KeyError:
        return False
    return True


def _looks_like_bare_repo(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "objects").is_dir()
        and (path / "refs").is_dir()
        and (path / "HEAD").is_file()
    )
