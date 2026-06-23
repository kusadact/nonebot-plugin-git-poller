from __future__ import annotations

import base64
from math import ceil
from pathlib import Path
from uuid import uuid4

from nonebot import logger
from nonebot.adapters.onebot.v11 import ActionFailed, Bot, Message, MessageSegment

from .archive import sha256_file
from .config import Config
from .file_server import build_archive_download_url
from .models import Subscription, UpdatePayload


DEFAULT_NODE_USER_ID = 2854196310
NAPCAT_STREAM_CHUNK_SIZE = 1024 * 1024
NAPCAT_STREAM_FILE_RETENTION_BUFFER_SECONDS = 600
ARCHIVE_UPLOAD_URI_ERROR_MESSAGE = (
    "上传压缩包失败：OneBot 无法识别文件地址，"
    "请检查 git_poller_file_base_url 是否正确。"
)


class ArchiveUploadUriError(RuntimeError):
    pass


class NapCatStreamUploadError(RuntimeError):
    pass


_napcat_detection_cache: dict[str, bool] = {}


def build_forward_nodes(payload: UpdatePayload) -> list[MessageSegment]:
    nodes = [_node(_summary_text(payload), payload.repo_name)]
    for index, commit in enumerate(payload.commits, start=1):
        nodes.append(_node(_commit_text(index, commit), payload.repo_name))
    return nodes


def build_archive_delivery_text(payload: UpdatePayload, archive, *, title: str) -> str:
    lines = [
        f"{title}：{payload.repo_name}",
        f"分支：{payload.branch}",
        f"sha256：{archive.sha256}",
        f"密码：{archive.password or '无'}",
        "近期更新记录（由新到旧排列）：",
    ]
    if not payload.commits:
        lines.append("无新增 commit")
        return "\n".join(lines)

    for commit in reversed(payload.commits):
        lines.append(f"{commit.short_sha}：{commit.title}")
    return "\n".join(lines)


def build_subscription_list_text(
    subscriptions: dict[str, Subscription],
    *,
    default_archive_password: str | None = None,
) -> str:
    lines = ["本群关注的仓库："]
    default_password = _clean_password(default_archive_password)
    for index, subscription in enumerate(subscriptions.values(), start=1):
        last_sha = (
            subscription.last_success_sha[:8]
            if subscription.last_success_sha
            else "未记录"
        )
        password = (
            _clean_password(subscription.archive_password)
            or default_password
            or "无"
        )
        lines.append(
            f"{index}. Git链接：{subscription.url}\n"
            f"   分支：{subscription.branch}\n"
            f"   计划时间：{subscription.schedule}\n"
            f"   SHA：{last_sha}\n"
            f"   密码：{password}"
        )
    return "\n".join(lines)


async def send_update_to_group(bot: Bot, group_id: int, payload: UpdatePayload) -> None:
    nodes = build_forward_nodes(payload)
    logger.info(
        f"git poller sending update to group {group_id}: "
        f"repo={payload.repo_key}, target={payload.target_short_sha}, nodes={len(nodes)}"
    )
    await bot.send_group_forward_msg(group_id=int(group_id), messages=nodes)
    logger.info(f"git poller update sent to group {group_id}: {payload.repo_key}")


async def upload_archive_to_group(
    bot: Bot,
    group_id: int,
    archive,
    *,
    config: Config,
) -> None:
    if await _is_napcat_bot(bot):
        try:
            await _upload_archive_to_napcat_group(bot, group_id, archive, config=config)
            return
        except NapCatStreamUploadError:
            logger.exception(
                f"git poller NapCat stream upload failed before group upload; "
                f"falling back to generic upload: group={group_id}, name={archive.name}"
            )

    await _upload_archive_to_group_generic(bot, group_id, archive, config=config)


async def _upload_archive_to_group_generic(
    bot: Bot,
    group_id: int,
    archive,
    *,
    config: Config,
) -> None:
    upload_file = build_archive_download_url(archive.path, config)
    if upload_file:
        logger.info(
            f"git poller archive upload source for group {group_id} uses HTTP route: "
            f"{upload_file.split('?', 1)[0]}"
        )
    else:
        upload_file = str(archive.path)
        logger.warning(
            "git_poller_file_base_url is not configured; falling back to local archive path. "
            "This only works when the OneBot implementation can read the same filesystem."
        )
    password_used = getattr(archive, "password_used", False)
    logger.info(
        f"git poller uploading archive to group {group_id}: "
        f"name={archive.name}, password={password_used}, file={upload_file}"
    )
    try:
        await bot.upload_group_file(
            group_id=int(group_id),
            file=upload_file,
            name=archive.name,
            _timeout=config.git_poller_upload_api_timeout,
        )
    except ActionFailed as exc:
        if _is_unrecognized_upload_uri(exc):
            raise ArchiveUploadUriError(ARCHIVE_UPLOAD_URI_ERROR_MESSAGE) from exc
        raise
    logger.info(f"git poller archive uploaded to group {group_id}: {archive.name}")


async def _upload_archive_to_napcat_group(
    bot: Bot,
    group_id: int,
    archive,
    *,
    config: Config,
) -> None:
    password_used = getattr(archive, "password_used", False)
    logger.info(
        f"git poller uploading archive to NapCat stream for group {group_id}: "
        f"name={archive.name}, password={password_used}, file={archive.path}"
    )
    stream_file_path = await _upload_file_to_napcat_stream(
        bot,
        Path(archive.path),
        archive.name,
        config,
        expected_sha256=getattr(archive, "sha256", None),
    )
    logger.info(
        f"git poller NapCat stream upload complete for group {group_id}: "
        f"name={archive.name}, file={stream_file_path}"
    )
    await bot.upload_group_file(
        group_id=int(group_id),
        file=stream_file_path,
        name=archive.name,
        _timeout=config.git_poller_upload_api_timeout,
    )
    logger.info(f"git poller archive uploaded to group {group_id}: {archive.name}")


async def _upload_file_to_napcat_stream(
    bot: Bot,
    path: Path,
    filename: str,
    config: Config,
    *,
    expected_sha256: str | None = None,
) -> str:
    if not path.is_file():
        raise NapCatStreamUploadError(f"archive file does not exist: {path}")

    file_size = path.stat().st_size
    total_chunks = max(1, ceil(file_size / NAPCAT_STREAM_CHUNK_SIZE))
    stream_id = f"git-poller-{uuid4().hex}"
    expected_sha256 = expected_sha256 or sha256_file(path)
    file_retention_ms = int(
        (config.git_poller_upload_api_timeout + NAPCAT_STREAM_FILE_RETENTION_BUFFER_SECONDS)
        * 1000
    )

    try:
        await bot.call_api(
            "upload_file_stream",
            stream_id=stream_id,
            total_chunks=total_chunks,
            file_size=file_size,
            filename=filename,
            expected_sha256=expected_sha256,
            file_retention=file_retention_ms,
            _timeout=config.git_poller_upload_api_timeout,
        )
        with path.open("rb") as file:
            for chunk_index in range(total_chunks):
                chunk = file.read(NAPCAT_STREAM_CHUNK_SIZE)
                if not chunk and file_size:
                    raise NapCatStreamUploadError(
                        f"archive stream ended early: {path}, chunk={chunk_index}"
                    )
                await bot.call_api(
                    "upload_file_stream",
                    stream_id=stream_id,
                    chunk_index=chunk_index,
                    chunk_data=base64.b64encode(chunk).decode("ascii"),
                    _timeout=config.git_poller_upload_api_timeout,
                )
        response = await bot.call_api(
            "upload_file_stream",
            stream_id=stream_id,
            is_complete=True,
            _timeout=config.git_poller_upload_api_timeout,
        )
    except NapCatStreamUploadError:
        await _reset_napcat_stream(bot, stream_id, config)
        raise
    except Exception as exc:
        await _reset_napcat_stream(bot, stream_id, config)
        raise NapCatStreamUploadError(str(exc)) from exc

    file_path = _extract_napcat_stream_file_path(response)
    if not file_path:
        raise NapCatStreamUploadError(f"NapCat stream response has no file_path: {response!r}")
    return file_path


async def _reset_napcat_stream(bot: Bot, stream_id: str, config: Config) -> None:
    try:
        await bot.call_api(
            "upload_file_stream",
            stream_id=stream_id,
            reset=True,
            _timeout=config.git_poller_upload_api_timeout,
        )
    except Exception:
        logger.debug(f"git poller NapCat stream reset failed: stream={stream_id}")


def _extract_napcat_stream_file_path(response) -> str | None:
    if isinstance(response, dict):
        file_path = response.get("file_path")
        return str(file_path) if file_path else None
    return None


async def _is_napcat_bot(bot: Bot) -> bool:
    self_id = getattr(bot, "self_id", None)
    if self_id is None:
        logger.debug("git poller skipped NapCat detection without bot self_id")
        return False
    cache_key = str(self_id)
    if cache_key in _napcat_detection_cache:
        return _napcat_detection_cache[cache_key]
    try:
        info = await bot.get_version_info()
    except Exception:
        logger.debug("git poller failed to detect OneBot implementation")
        return False
    app_name = str(info.get("app_name", "") if isinstance(info, dict) else "").lower()
    result = "napcat" in app_name
    _napcat_detection_cache[cache_key] = result
    if result:
        logger.info(f"git poller detected NapCat OneBot implementation: {info}")
    return result

def _summary_text(payload: UpdatePayload) -> str:
    items = [
        f"仓库更新：{payload.repo_name}",
        f"分支：{payload.branch}",
        f"当前：{payload.target_short_sha}",
        f"新增 commit：{len(payload.commits)}",
    ]
    if payload.previous_sha:
        items.append(f"上次成功：{payload.previous_sha[:8]}")
    if payload.compare_url:
        items.append(payload.compare_url)
    return "\n".join(items)


def _commit_text(index: int, commit) -> str:
    items = [
        f"{index}. {commit.title}",
        f"commit: {commit.short_sha}",
    ]
    if commit.author:
        items.append(f"author: {commit.author}")
    if commit.committed_at:
        items.append(f"time: {commit.committed_at}")
    if commit.url:
        items.append(commit.url)
    return "\n".join(items)


def _node(content: str, nickname: str) -> MessageSegment:
    return MessageSegment.node_custom(
        user_id=DEFAULT_NODE_USER_ID,
        nickname=nickname or "Git 更新",
        content=Message(content),
    )


def _clean_password(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _is_unrecognized_upload_uri(exc: ActionFailed) -> bool:
    info = getattr(exc, "info", {})
    fields = []
    if isinstance(info, dict):
        fields.extend(str(info.get(key, "")) for key in ("message", "wording", "msg"))
    fields.append(repr(exc))
    text = "\n".join(fields)
    return "识别URL失败" in text and "uri=" in text
