from __future__ import annotations

from nonebot import logger
from nonebot.adapters.onebot.v11 import ActionFailed, Bot, Message, MessageSegment

from .config import Config
from .file_server import build_archive_download_url
from .models import UpdatePayload


DEFAULT_NODE_USER_ID = 2854196310
ARCHIVE_UPLOAD_URI_ERROR_MESSAGE = (
    "上传压缩包失败：OneBot 无法识别文件地址，"
    "请检查 git_poller_file_base_url 是否正确。"
)


class ArchiveUploadUriError(RuntimeError):
    pass


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
    ]
    if not payload.commits:
        lines.append("无新增 commit")
        return "\n".join(lines)

    for index, commit in enumerate(payload.commits):
        prefix = f"最新{commit.short_sha}" if index == len(payload.commits) - 1 else commit.short_sha
        lines.append(f"{prefix}：{commit.title}")
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
    logger.info(
        f"git poller uploading archive to group {group_id}: "
        f"name={archive.name}, password={archive.password_used}, file={upload_file}"
    )
    try:
        await bot.upload_group_file(
            group_id=int(group_id),
            file=upload_file,
            name=archive.name,
        )
    except ActionFailed as exc:
        if _is_unrecognized_upload_uri(exc):
            raise ArchiveUploadUriError(ARCHIVE_UPLOAD_URI_ERROR_MESSAGE) from exc
        raise
    logger.info(f"git poller archive uploaded to group {group_id}: {archive.name}")


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


def _is_unrecognized_upload_uri(exc: ActionFailed) -> bool:
    info = getattr(exc, "info", {})
    fields = []
    if isinstance(info, dict):
        fields.extend(str(info.get(key, "")) for key in ("message", "wording", "msg"))
    fields.append(repr(exc))
    text = "\n".join(fields)
    return "识别URL失败" in text and "uri=" in text
