from __future__ import annotations

from .config import Config
from .models import ArchiveInfo
from .remote_worker import build_remote_archive


async def build_encrypted_archive(
    sha: str,
    short_sha: str,
    config: Config,
) -> ArchiveInfo:
    return await build_remote_archive(sha, short_sha, config)
