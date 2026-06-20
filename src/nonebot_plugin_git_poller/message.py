from __future__ import annotations

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from .models import UpdatePayload


DEFAULT_NODE_USER_ID = 2854196310


def build_forward_nodes(payload: UpdatePayload) -> list[MessageSegment]:
    nodes = [_node(_summary_text(payload), payload.repo_name)]
    for index, commit in enumerate(payload.commits, start=1):
        nodes.append(_node(_commit_text(index, commit), payload.repo_name))
    return nodes


async def send_update_to_group(bot: Bot, group_id: int, payload: UpdatePayload) -> None:
    nodes = build_forward_nodes(payload)
    logger.info(
        f"git poller sending update to group {group_id}: "
        f"repo={payload.repo_key}, target={payload.target_short_sha}, nodes={len(nodes)}"
    )
    await bot.send_group_forward_msg(group_id=int(group_id), messages=nodes)
    logger.info(f"git poller update sent to group {group_id}: {payload.repo_key}")


async def upload_archive_to_group(bot: Bot, group_id: int, archive) -> None:
    logger.info(
        f"git poller uploading archive to group {group_id}: "
        f"name={archive.name}, password={archive.password_used}"
    )
    await bot.upload_group_file(
        group_id=int(group_id),
        file=str(archive.path),
        name=archive.name,
    )
    logger.info(f"git poller archive uploaded to group {group_id}: {archive.name}")


def split_text(text: str, limit: int) -> list[str]:
    if limit <= 0:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit].rstrip())
            continue
        if current and len(current) + len(line) > limit:
            chunks.append(current.rstrip())
            current = ""
        current += line
    if current:
        chunks.append(current.rstrip())
    return chunks or [""]


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
