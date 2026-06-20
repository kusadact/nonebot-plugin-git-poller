from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import tempfile

from nonebot import logger
from nonebot_plugin_localstore import get_plugin_cache_dir
import py7zr

from .models import Subscription, UpdatePayload


@dataclass(frozen=True)
class ArchiveFile:
    path: Path
    name: str
    sha256: str
    password: str | None
    password_used: bool


class ArchiveBuilder:
    def __init__(self, default_password: str | None = None) -> None:
        self.default_password = _clean_password(default_password)
        self.archive_dir = get_plugin_cache_dir() / "archives"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        payload: UpdatePayload,
        subscription: Subscription,
        source_dir: Path,
    ) -> ArchiveFile:
        password = _clean_password(subscription.archive_password) or self.default_password
        archive_name = _archive_name(payload)
        archive_path = _unique_archive_path(self.archive_dir, payload.repo_key, archive_name)

        logger.info(
            f"git poller building archive: repo={payload.repo_key}, "
            f"target={payload.target_short_sha}, password={password is not None}"
        )
        with py7zr.SevenZipFile(archive_path, "w", password=password) as archive:
            archive.writeall(source_dir, arcname=source_dir.name)
        return ArchiveFile(
            path=archive_path,
            name=archive_name,
            sha256=_sha256_file(archive_path),
            password=password,
            password_used=password is not None,
        )

    def source_root(self, payload: UpdatePayload) -> Path:
        name = _source_root_name(payload)
        return Path(tempfile.mkdtemp(prefix=f"{name}-", dir=str(self.archive_dir))) / name

    def remove_archive(self, path: str | Path | None) -> bool:
        if not path:
            return False
        archive_path = Path(path)
        try:
            archive_path.resolve().relative_to(self.archive_dir.resolve())
        except ValueError:
            logger.warning(f"git poller refused to remove archive outside cache: {archive_path}")
            return False
        if not archive_path.exists():
            return False
        archive_path.unlink()
        logger.info(f"git poller removed archive: {archive_path}")
        return True

    def remove_archives_for_repo(self, repo_key: str) -> int:
        count = 0
        prefix = f"{_safe_name(repo_key)}-"
        for path in self.archive_dir.glob(f"{prefix}*.7z"):
            try:
                if path.is_file():
                    path.unlink()
                    count += 1
            except OSError:
                logger.exception(f"git poller failed to remove archive: {path}")
        if count:
            logger.info(f"git poller removed {count} archives for repo: {repo_key}")
        return count


def _archive_name(payload: UpdatePayload) -> str:
    return f"{_source_root_name(payload)}.7z"


def _unique_archive_path(archive_dir: Path, repo_key: str, archive_name: str) -> Path:
    stem = Path(archive_name).stem
    with tempfile.NamedTemporaryFile(
        prefix=f"{_safe_name(repo_key)}-{_safe_name(stem)}-",
        suffix=".7z",
        dir=archive_dir,
        delete=False,
    ) as file:
        return Path(file.name)


def _source_root_name(payload: UpdatePayload) -> str:
    repo = _safe_name(payload.repo_name)
    branch = _safe_name(payload.branch)
    return f"{repo}-{branch}-{payload.target_short_sha}"


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return cleaned[:80] or "repository"


def _clean_password(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
