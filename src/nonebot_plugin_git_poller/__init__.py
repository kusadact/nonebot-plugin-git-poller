from __future__ import annotations

from nonebot import get_bots, logger, on_command, require
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")

from nonebot_plugin_apscheduler import scheduler

from .command_args import parse_repo_command_args
from .config import Config, plugin_config
from .message import send_update_to_group
from .mirror import GitPollerService
from .schedule import parse_schedule

__plugin_meta__ = PluginMetadata(
    name="Git Poller",
    description="按群订阅多个 Git 仓库并推送 commit 更新摘要",
    usage=(
        "/关注仓库 仓库url [--分支名]\n"
        "/取关仓库 仓库url [--分支名]\n"
        "/设置仓库 仓库url [--分支名]\n"
        "/仓库列表\n"
        "/拉取仓库 仓库url [--分支名]\n"
        "/仓库摘要 仓库url [--分支名]"
    ),
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

service = GitPollerService(plugin_config)

follow_repo = on_command(
    "关注仓库",
    priority=plugin_config.git_poller_command_priority,
    block=True,
)
unfollow_repo = on_command(
    "取关仓库",
    priority=plugin_config.git_poller_command_priority,
    block=True,
)
configure_repo = on_command(
    "设置仓库",
    priority=plugin_config.git_poller_command_priority,
    block=True,
)
list_repos = on_command(
    "仓库列表",
    priority=plugin_config.git_poller_command_priority,
    block=True,
)
pull_repo = on_command(
    "拉取仓库",
    priority=plugin_config.git_poller_command_priority,
    block=True,
)
summarize_repo = on_command(
    "仓库摘要",
    priority=plugin_config.git_poller_command_priority,
    block=True,
)


@follow_repo.handle()
async def _(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()) -> None:
    try:
        parsed = _repo_args(args)
    except ValueError as exc:
        await matcher.finish(f"用法：/关注仓库 仓库url [--分支名]\n{exc}")
    if parsed is None:
        await matcher.finish("用法：/关注仓库 仓库url [--分支名]")
    group_id = int(event.group_id)
    try:
        result = await service.follow_repo(group_id, parsed.url, parsed.branch)
        if result.already_following:
            await matcher.finish(
                f"本群已经关注：{result.identity.display_name}\n"
                f"分支：{result.subscription.branch}\n"
                f"定时：{result.subscription.schedule}"
            )
        await matcher.finish(
            f"已关注：{result.identity.display_name}\n"
            f"分支：{result.subscription.branch}\n"
            f"定时：{result.subscription.schedule}\n"
            f"当前 commit 已记录，后续有新提交时推送。"
        )
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("git poller follow command failed")
        await matcher.finish(f"关注仓库失败：{exc}")


@unfollow_repo.handle()
async def _(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()) -> None:
    try:
        parsed = _repo_args(args)
    except ValueError as exc:
        await matcher.finish(f"用法：/取关仓库 仓库url [--分支名]\n{exc}")
    if parsed is None:
        await matcher.finish("用法：/取关仓库 仓库url [--分支名]")
    try:
        identity, removed = service.unfollow_repo(
            int(event.group_id),
            parsed.url,
            parsed.branch,
        )
        if removed:
            await matcher.finish(f"已取关：{identity.display_name}")
        await matcher.finish(f"本群没有关注：{identity.display_name}")
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("git poller unfollow command failed")
        await matcher.finish(f"取关仓库失败：{exc}")


@configure_repo.handle()
async def _(matcher: Matcher, args: Message = CommandArg()) -> None:
    try:
        parsed = _repo_args(args, allow_tail=True)
    except ValueError as exc:
        await matcher.finish(f"用法：/设置仓库 仓库url [--分支名]\n{exc}")
    if parsed is None:
        await matcher.finish("用法：/设置仓库 仓库url [--分支名]")
    branch_suffix = f" --{parsed.branch}" if parsed.branch else ""
    await matcher.finish(
        "设置仓库第一阶段还不会直接修改配置。\n"
        "后续格式示例：\n"
        f"/设置仓库 {parsed.url}{branch_suffix} 每日04-30\n"
        f"/设置仓库 {parsed.url}{branch_suffix} 星期一04-30\n"
        f"/设置仓库 {parsed.url}{branch_suffix} 星期10430"
    )


@list_repos.handle()
async def _(event: GroupMessageEvent, matcher: Matcher) -> None:
    subscriptions = service.list_group_subscriptions(int(event.group_id))
    if not subscriptions:
        await matcher.finish("本群还没有关注任何仓库。")
    lines = ["本群关注的仓库："]
    for index, (repo_key, subscription) in enumerate(subscriptions.items(), start=1):
        status = "启用" if subscription.enabled else "停用"
        last_sha = subscription.last_success_sha[:8] if subscription.last_success_sha else "未记录"
        lines.append(
            f"{index}. {subscription.url}\n"
            f"   key: {repo_key}\n"
            f"   branch: {subscription.branch} / schedule: {subscription.schedule} / {status}\n"
            f"   last_success_sha: {last_sha}"
        )
    await matcher.finish("\n".join(lines))


@pull_repo.handle()
async def _(event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()) -> None:
    try:
        parsed = _repo_args(args)
    except ValueError as exc:
        await matcher.finish(f"用法：/拉取仓库 仓库url [--分支名]\n{exc}")
    if parsed is None:
        await matcher.finish("用法：/拉取仓库 仓库url [--分支名]")
    group_id = int(event.group_id)
    try:
        result = await service.pull_repo(group_id, parsed.url, parsed.branch)
        previous = result.previous_sha[:8] if result.previous_sha else "未记录"
        target = result.target_sha[:8]
        status = "本地与远程相同" if result.previous_sha == result.target_sha else "已更新本地记录"
        await matcher.finish(
            f"拉取完成：{result.identity.display_name}\n"
            f"分支：{result.subscription.branch}\n"
            f"原记录：{previous}\n"
            f"当前：{target}\n"
            f"{status}"
        )
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("git poller pull command failed")
        await matcher.finish(f"拉取仓库失败：{exc}")


@summarize_repo.handle()
async def _(bot: Bot, event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()) -> None:
    try:
        parsed = _repo_args(args)
    except ValueError as exc:
        await matcher.finish(f"用法：/仓库摘要 仓库url [--分支名]\n{exc}")
    if parsed is None:
        await matcher.finish("用法：/仓库摘要 仓库url [--分支名]")
    group_id = int(event.group_id)
    try:
        summary = await service.summarize_repo(group_id, parsed.url, parsed.branch)
        payload = summary.result.payload
        if payload.previous_sha == payload.target_sha:
            await matcher.finish(
                f"仓库摘要：{payload.repo_name}\n"
                f"分支：{payload.branch}\n"
                f"本地与远程相同：{payload.target_short_sha}"
            )
        await send_update_to_group(bot, group_id, payload)
        behind_text = (
            f"本地记录落后远程 {summary.behind_count} 个 commit。"
            if summary.behind_count is not None
            else "本地记录与远程存在差异。"
        )
        await matcher.finish(
            f"仓库摘要已发送：{payload.repo_name}\n"
            f"分支：{payload.branch}\n"
            f"{behind_text}\n"
            f"本地记录未更新。"
        )
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("git poller summary command failed")
        await matcher.finish(f"仓库摘要失败：{exc}")


async def run_scheduled_check(schedule: str) -> None:
    bots = get_bots()
    if not bots:
        logger.warning("git poller scheduled check skipped: no bot is connected")
        return
    bot = next(iter(bots.values()))
    try:
        results = await service.poll_schedule(schedule)
        for result in results:
            try:
                await send_update_to_group(bot, result.group_id, result.payload)
            except Exception:
                logger.exception(
                    f"git poller scheduled push failed: "
                    f"group={result.group_id}, repo={result.repo_key}"
                )
                continue
            service.mark_success(result)
    except Exception:
        logger.exception(f"git poller scheduled check failed: {schedule}")


def _register_schedules() -> None:
    for schedule_rule in sorted(service.scheduled_rules()):
        try:
            spec = parse_schedule(schedule_rule, plugin_config.git_poller_timezone)
        except ValueError:
            logger.exception(f"git poller skipped invalid schedule: {schedule_rule}")
            continue
        if spec is None:
            continue
        scheduler.add_job(
            run_scheduled_check,
            spec.trigger,
            args=[schedule_rule],
            id=f"git_poller:{schedule_rule}",
            max_instances=1,
            coalesce=True,
            **spec.trigger_kwargs,
        )
        logger.info(f"git poller scheduler registered: {spec.description}")


def _repo_args(args: Message, *, allow_tail: bool = False):
    return parse_repo_command_args(str(args), allow_tail=allow_tail)


_register_schedules()
