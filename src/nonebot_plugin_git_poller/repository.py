from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse

from .models import RepositoryIdentity


_SCP_LIKE_PATTERN = re.compile(r"^(?P<user>[^@/:]+)@(?P<host>[^:]+):(?P<path>.+)$")


def normalize_repo_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise ValueError("仓库 URL 不能为空。")

    scp_like = _SCP_LIKE_PATTERN.fullmatch(value)
    if scp_like:
        host = scp_like.group("host").lower()
        path = _clean_path(scp_like.group("path"))
        return f"{scp_like.group('user')}@{host}:{path}"

    if _is_local_path(value):
        return value.rstrip("/")

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        scheme = parsed.scheme.lower()
        netloc = _normalize_netloc(parsed)
        path = _clean_path(parsed.path)
        return urlunparse((scheme, netloc, path, "", "", ""))

    return _clean_path(value)


def repo_key_from_url(url: str, branch: str | None = None) -> str:
    normalized = normalize_repo_url(url)
    key_source = normalized if branch is None else f"{normalized}#{normalize_branch(branch)}"
    digest = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:12]
    parts = [display_name_from_url(normalized)]
    if branch is not None:
        parts.append(_safe_key_part(normalize_branch(branch)))
    parts.append(digest)
    return "-".join(parts)


def build_identity(url: str, branch: str | None = None) -> RepositoryIdentity:
    normalized = normalize_repo_url(url)
    return RepositoryIdentity(
        key=repo_key_from_url(normalized, branch),
        url=normalized,
        display_name=display_name_from_url(normalized),
        web_url=web_url_from_git_url(normalized),
    )


def normalize_branch(branch: str) -> str:
    value = branch.strip()
    if not value:
        raise ValueError("分支名不能为空。")
    return value


def display_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    elif ":" in url and _SCP_LIKE_PATTERN.fullmatch(url):
        name = url.rsplit("/", 1)[-1]
    else:
        name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repository"


def web_url_from_git_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        path = parsed.path[:-4] if parsed.path.endswith(".git") else parsed.path
        return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))

    scp_like = _SCP_LIKE_PATTERN.fullmatch(url)
    if scp_like:
        path = scp_like.group("path")
        if path.endswith(".git"):
            path = path[:-4]
        return f"https://{scp_like.group('host').lower()}/{path.strip('/')}"

    return None


def build_commit_url(repo_url: str, sha: str) -> str | None:
    web_url = web_url_from_git_url(repo_url)
    if not web_url:
        return None
    return f"{web_url}/-/commit/{sha}" if _uses_gitlab_routes(web_url) else f"{web_url}/commit/{sha}"


def build_compare_url(repo_url: str, from_sha: str | None, to_sha: str) -> str | None:
    if not from_sha:
        return None
    web_url = web_url_from_git_url(repo_url)
    if not web_url:
        return None
    separator = "..." if _uses_github_routes(web_url) else "..."
    path = f"/-/compare/{from_sha}{separator}{to_sha}" if _uses_gitlab_routes(web_url) else f"/compare/{from_sha}{separator}{to_sha}"
    return f"{web_url}{path}"


def _uses_gitlab_routes(web_url: str) -> bool:
    host = urlparse(web_url).netloc.lower()
    return "gitlab" in host or "gitgud.io" in host


def _uses_github_routes(web_url: str) -> bool:
    return "github.com" in urlparse(web_url).netloc.lower()


def _clean_path(path: str) -> str:
    cleaned = path.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    return f"{cleaned}.git"


def _is_local_path(value: str) -> bool:
    return (
        value.startswith(("/", "./", "../", "~"))
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None
    )


def _normalize_netloc(parsed) -> str:
    host = (parsed.hostname or "").lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        return f"{userinfo}@{host}"
    return host


def _safe_key_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return safe[:48] or "branch"
