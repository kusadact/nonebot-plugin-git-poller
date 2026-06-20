from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from nonebot import logger

from .config import Config
from .git import GitRepositoryCache
from .models import PollResult, RepositoryIdentity, Subscription, UpdatePayload
from .repository import build_compare_url, build_identity
from .state import StateStore


@dataclass(frozen=True)
class FollowResult:
    identity: RepositoryIdentity
    subscription: Subscription
    already_following: bool
    payload: UpdatePayload | None = None


class GitPollerService:
    def __init__(
        self,
        config: Config,
        *,
        state: StateStore | None = None,
        git_cache: GitRepositoryCache | None = None,
    ) -> None:
        self.config = config
        self.state = state or StateStore()
        self.git_cache = git_cache or GitRepositoryCache(config)
        self._lock = asyncio.Lock()

    async def follow_repo(self, group_id: int, url: str) -> FollowResult:
        async with self._lock:
            return await asyncio.to_thread(self._follow_repo_sync, group_id, url)

    async def pull_repo(self, group_id: int, url: str) -> PollResult:
        async with self._lock:
            return await asyncio.to_thread(self._pull_repo_sync, group_id, url)

    async def poll_schedule(self, schedule: str) -> list[PollResult]:
        async with self._lock:
            return await asyncio.to_thread(self._poll_schedule_sync, schedule)

    def unfollow_repo(self, group_id: int, url: str) -> tuple[RepositoryIdentity, bool]:
        identity = build_identity(url)
        return identity, self.state.remove_subscription(group_id, identity.key)

    def list_group_subscriptions(self, group_id: int) -> dict[str, Subscription]:
        return self.state.list_group_subscriptions(group_id)

    def scheduled_rules(self) -> set[str]:
        rules = {self.config.git_poller_default_schedule.strip()}
        for subscriptions in self.state.list_all_subscriptions().values():
            for subscription in subscriptions.values():
                if subscription.schedule.strip():
                    rules.add(subscription.schedule.strip())
        return {rule for rule in rules if rule}

    def mark_success(self, result: PollResult) -> None:
        self.state.update_last_success(
            result.group_id,
            result.repo_key,
            result.payload.target_sha,
            _now_iso(),
        )

    def _follow_repo_sync(self, group_id: int, url: str) -> FollowResult:
        identity = build_identity(url)
        existing = self.state.get_subscription(group_id, identity.key)
        if existing is not None:
            return FollowResult(
                identity=identity,
                subscription=existing,
                already_following=True,
            )

        fetched = self.git_cache.fetch(
            identity.key,
            identity.url,
            self.config.git_poller_default_branch,
        )
        try:
            now = _now_iso()
            subscription = Subscription(
                url=identity.url,
                branch=self.config.git_poller_default_branch,
                schedule=self.config.git_poller_default_schedule,
                last_success_sha=(
                    None
                    if self.config.git_poller_push_on_first_follow
                    else fetched.head_sha
                ),
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            self.state.upsert_subscription(group_id, identity.key, subscription)
            payload = (
                self._build_payload(identity, subscription, fetched, None)
                if self.config.git_poller_push_on_first_follow
                else None
            )
            return FollowResult(
                identity=identity,
                subscription=subscription,
                already_following=False,
                payload=payload,
            )
        finally:
            fetched.close()

    def _pull_repo_sync(self, group_id: int, url: str) -> PollResult:
        identity = build_identity(url)
        subscription = self.state.get_subscription(group_id, identity.key)
        if subscription is None:
            raise KeyError("本群尚未关注这个仓库。")

        fetched = self.git_cache.fetch(identity.key, subscription.url, subscription.branch)
        try:
            payload = self._build_payload(
                identity,
                subscription,
                fetched,
                subscription.last_success_sha,
            )
            return PollResult(
                group_id=group_id,
                repo_key=identity.key,
                subscription=subscription,
                payload=payload,
            )
        finally:
            fetched.close()

    def _poll_schedule_sync(self, schedule: str) -> list[PollResult]:
        results: list[PollResult] = []
        for group_id, repo_key, subscription in self.state.subscriptions_for_schedule(schedule):
            identity = build_identity(subscription.url)
            fetched = self.git_cache.fetch(repo_key, subscription.url, subscription.branch)
            try:
                if not subscription.last_success_sha:
                    if not self.config.git_poller_push_on_first_follow:
                        self.state.update_last_success(
                            group_id,
                            repo_key,
                            fetched.head_sha,
                            _now_iso(),
                        )
                        continue
                    previous_sha = None
                else:
                    previous_sha = subscription.last_success_sha
                    if previous_sha == fetched.head_sha:
                        logger.debug(
                            f"git poller no update: group={group_id}, repo={repo_key}, "
                            f"head={fetched.head_sha[:8]}"
                        )
                        continue

                payload = self._build_payload(
                    identity,
                    subscription,
                    fetched,
                    previous_sha,
                )
                results.append(
                    PollResult(
                        group_id=group_id,
                        repo_key=repo_key,
                        subscription=subscription,
                        payload=payload,
                    )
                )
            finally:
                fetched.close()
        return results

    def _build_payload(
        self,
        identity: RepositoryIdentity,
        subscription: Subscription,
        fetched,
        previous_sha: str | None,
    ) -> UpdatePayload:
        commits = fetched.commits_since(
            previous_sha,
            max_count=self.config.git_poller_max_commits,
        )
        return UpdatePayload(
            repo_key=identity.key,
            repo_url=subscription.url,
            repo_name=identity.display_name,
            branch=subscription.branch,
            previous_sha=previous_sha,
            target_sha=fetched.head_sha,
            target_short_sha=fetched.head_sha[:8],
            generated_at=_now_iso(),
            commits=commits,
            compare_url=build_compare_url(subscription.url, previous_sha, fetched.head_sha),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
