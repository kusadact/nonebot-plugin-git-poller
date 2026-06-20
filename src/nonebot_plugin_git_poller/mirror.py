from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import shutil
from threading import RLock

from nonebot import logger

from .archive import ArchiveBuilder, ArchiveFile
from .config import Config
from .git import GitRepositoryCache
from .models import PollResult, RepositoryIdentity, Subscription, UpdatePayload
from .repository import build_compare_url, build_identity, normalize_branch
from .state import StateStore

MAX_COMMITS = 20


@dataclass(frozen=True)
class FollowResult:
    identity: RepositoryIdentity
    subscription: Subscription
    already_following: bool


@dataclass(frozen=True)
class PullResult:
    identity: RepositoryIdentity
    subscription: Subscription
    previous_sha: str | None
    target_sha: str
    payload: UpdatePayload
    archive: ArchiveFile


@dataclass(frozen=True)
class SummaryResult:
    result: PollResult
    behind_count: int | None


@dataclass(frozen=True)
class DeliveryResult:
    result: PollResult
    archive: ArchiveFile


class GitPollerService:
    def __init__(
        self,
        config: Config,
        *,
        state: StateStore | None = None,
        git_cache: GitRepositoryCache | None = None,
        archive_builder: ArchiveBuilder | None = None,
    ) -> None:
        self.config = config
        self.state = state or StateStore()
        self.git_cache = git_cache or GitRepositoryCache(config)
        self.archive_builder = archive_builder or ArchiveBuilder(
            config.git_poller_archive_password
        )
        self._lock = asyncio.Lock()
        self._state_lock = RLock()

    async def follow_repo(self, group_id: int, url: str, branch: str | None = None) -> FollowResult:
        async with self._lock:
            return await asyncio.to_thread(self._follow_repo_sync, group_id, url, branch)

    async def pull_repo(self, group_id: int, url: str, branch: str | None = None) -> PullResult:
        async with self._lock:
            return await asyncio.to_thread(self._pull_repo_sync, group_id, url, branch)

    async def summarize_repo(self, group_id: int, url: str, branch: str | None = None) -> SummaryResult:
        async with self._lock:
            return await asyncio.to_thread(self._summarize_repo_sync, group_id, url, branch)

    async def poll_schedule(self, schedule: str) -> list[DeliveryResult]:
        async with self._lock:
            return await asyncio.to_thread(self._poll_schedule_sync, schedule)

    def update_repo_schedule(
        self,
        group_id: int,
        url: str,
        branch: str | None,
        schedule: str,
    ) -> tuple[RepositoryIdentity, Subscription]:
        with self._state_lock:
            identity, _ = self._get_subscription(group_id, url, branch)
            subscription = self.state.update_schedule(
                group_id,
                identity.key,
                schedule,
                _now_iso(),
            )
            return identity, subscription

    def update_repo_archive_password(
        self,
        group_id: int,
        url: str,
        branch: str | None,
        password: str | None,
    ) -> tuple[RepositoryIdentity, Subscription]:
        with self._state_lock:
            identity, _ = self._get_subscription(group_id, url, branch)
            subscription = self.state.update_archive_password(
                group_id,
                identity.key,
                password,
                _now_iso(),
            )
            return identity, subscription

    def unfollow_repo(
        self,
        group_id: int,
        url: str,
        branch: str | None = None,
    ) -> tuple[RepositoryIdentity, bool]:
        with self._state_lock:
            identity, existing = self._find_subscription(group_id, url, branch)
            if existing is None:
                return identity, False
            removed = self.state.remove_subscription(group_id, identity.key)
            if removed and existing.last_archive_path:
                self.archive_builder.remove_archive(existing.last_archive_path)
            return identity, removed

    def get_repo_subscription(
        self,
        group_id: int,
        url: str,
        branch: str | None = None,
    ) -> tuple[RepositoryIdentity, Subscription]:
        with self._state_lock:
            return self._get_subscription(group_id, url, branch)

    def list_group_subscriptions(self, group_id: int) -> dict[str, Subscription]:
        with self._state_lock:
            return self.state.list_group_subscriptions(group_id)

    def scheduled_rules(self) -> set[str]:
        with self._state_lock:
            rules = {self.config.git_poller_default_schedule.strip()}
            for subscriptions in self.state.list_all_subscriptions().values():
                for subscription in subscriptions.values():
                    if subscription.schedule.strip():
                        rules.add(subscription.schedule.strip())
            return {rule for rule in rules if rule}

    def mark_success(self, result: PollResult) -> None:
        with self._state_lock:
            self.state.update_last_success(
                result.group_id,
                result.repo_key,
                result.payload.target_sha,
                _now_iso(),
            )

    def mark_pull_success(self, group_id: int, repo_key: str, target_sha: str) -> None:
        with self._state_lock:
            self.state.update_last_success(group_id, repo_key, target_sha, _now_iso())

    def cleanup_unsubscribed_repo(self, repo_key: str) -> bool:
        with self._state_lock:
            if self.state.is_repo_key_subscribed(repo_key):
                logger.info(f"git poller cleanup skipped for subscribed repo: {repo_key}")
                return False
            removed_cache = self.git_cache.remove_cache(repo_key)
            removed_archives = self.archive_builder.remove_archives_for_repo(repo_key)
            logger.info(
                f"git poller cleanup finished: repo={repo_key}, "
                f"cache={removed_cache}, archives={removed_archives}"
            )
            return removed_cache or bool(removed_archives)

    def cleanup_orphaned_storage(self) -> tuple[int, int]:
        with self._state_lock:
            active_repo_keys = {
                repo_key
                for subscriptions in self.state.list_all_subscriptions().values()
                for repo_key in subscriptions
            }
            removed_caches = 0
            for repo_key in sorted(self.git_cache.cached_repo_keys() - active_repo_keys):
                if self.git_cache.remove_cache(repo_key):
                    removed_caches += 1
            removed_archives = self.archive_builder.remove_archives_except(active_repo_keys)
            logger.info(
                f"git poller orphan cleanup finished: "
                f"cache={removed_caches}, archives={removed_archives}"
            )
            return removed_caches, removed_archives

    def _follow_repo_sync(self, group_id: int, url: str, branch: str | None) -> FollowResult:
        with self._state_lock:
            remote_head = self.git_cache.resolve_remote_head(
                build_identity(url).url,
                self._explicit_branch(branch),
            )
            target_branch = remote_head.branch
            identity = build_identity(url, target_branch)
            existing = self.state.get_subscription(group_id, identity.key)
            if existing is not None:
                return FollowResult(
                    identity=identity,
                    subscription=existing,
                    already_following=True,
                )

            now = _now_iso()
            subscription = Subscription(
                url=identity.url,
                branch=target_branch,
                schedule=self.config.git_poller_default_schedule,
                last_success_sha=None,
                enabled=True,
                created_at=now,
                updated_at=now,
            )

            subscription.last_success_sha = remote_head.sha
            self.state.upsert_subscription(group_id, identity.key, subscription)
            return FollowResult(
                identity=identity,
                subscription=subscription,
                already_following=False,
            )

    def _pull_repo_sync(self, group_id: int, url: str, branch: str | None) -> PullResult:
        with self._state_lock:
            identity, subscription = self._get_subscription(group_id, url, branch)
            fetched = self.git_cache.fetch(identity.key, subscription.url, subscription.branch)
            try:
                previous_sha = subscription.last_success_sha
                payload = self._build_payload(identity, subscription, fetched, previous_sha)
                archive = self._build_archive(
                    payload,
                    subscription,
                    fetched,
                    group_id=group_id,
                )
                return PullResult(
                    identity=identity,
                    subscription=subscription,
                    previous_sha=previous_sha,
                    target_sha=fetched.head_sha,
                    payload=payload,
                    archive=archive,
                )
            finally:
                fetched.close()

    def _summarize_repo_sync(self, group_id: int, url: str, branch: str | None) -> SummaryResult:
        with self._state_lock:
            identity, subscription = self._get_subscription(group_id, url, branch)
            return self._poll_subscription(group_id, identity.key, identity, subscription)

    def _get_subscription(
        self,
        group_id: int,
        url: str,
        branch: str | None,
    ) -> tuple[RepositoryIdentity, Subscription]:
        identity, subscription = self._find_subscription(group_id, url, branch)
        if subscription is None:
            raise KeyError("本群尚未关注这个仓库。")
        return identity, subscription

    def _poll_subscription(
        self,
        group_id: int,
        repo_key: str,
        identity: RepositoryIdentity,
        subscription: Subscription,
    ) -> SummaryResult:
        fetched = self.git_cache.fetch(repo_key, subscription.url, subscription.branch)
        try:
            behind_count = fetched.count_commits_since(subscription.last_success_sha)
            payload = self._build_payload(
                identity,
                subscription,
                fetched,
                subscription.last_success_sha,
            )
            return SummaryResult(
                result=PollResult(
                    group_id=group_id,
                    repo_key=repo_key,
                    subscription=subscription,
                    payload=payload,
                ),
                behind_count=behind_count,
            )
        finally:
            fetched.close()

    def _poll_schedule_sync(self, schedule: str) -> list[DeliveryResult]:
        with self._state_lock:
            results: list[DeliveryResult] = []
            for group_id, repo_key, subscription in self.state.subscriptions_for_schedule(schedule):
                try:
                    identity = build_identity(subscription.url, subscription.branch)
                    fetched = self.git_cache.fetch(repo_key, subscription.url, subscription.branch)
                    try:
                        if not subscription.last_success_sha:
                            self.state.update_last_success(
                                group_id,
                                repo_key,
                                fetched.head_sha,
                                _now_iso(),
                            )
                            continue
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
                        result = PollResult(
                            group_id=group_id,
                            repo_key=repo_key,
                            subscription=subscription,
                            payload=payload,
                        )
                        results.append(
                            DeliveryResult(
                                result=result,
                                archive=self._build_archive(
                                    payload,
                                    subscription,
                                    fetched,
                                    group_id=group_id,
                                ),
                            )
                        )
                    finally:
                        fetched.close()
                except Exception:
                    logger.exception(
                        f"git poller scheduled subscription failed: "
                        f"group={group_id}, repo={repo_key}"
                    )
                    continue
            return results

    def _build_payload(
        self,
        identity: RepositoryIdentity,
        subscription: Subscription,
        fetched,
        previous_sha: str | None,
    ) -> UpdatePayload:
        if previous_sha == fetched.head_sha:
            commits = []
        else:
            commits = fetched.commits_since(
                previous_sha,
                max_count=MAX_COMMITS,
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

    def _build_archive(
        self,
        payload: UpdatePayload,
        subscription: Subscription,
        fetched,
        *,
        group_id: int,
    ) -> ArchiveFile:
        if subscription.last_archive_path:
            self.archive_builder.remove_archive(subscription.last_archive_path)
            self.state.update_last_archive_path(
                group_id,
                payload.repo_key,
                None,
                _now_iso(),
            )
        source_dir = self.archive_builder.source_root(payload)
        try:
            fetched.export_head_tree(source_dir)
            archive = self.archive_builder.build(payload, subscription, source_dir)
            self.state.update_last_archive_path(
                group_id,
                payload.repo_key,
                str(archive.path),
                _now_iso(),
            )
            return archive
        finally:
            shutil.rmtree(source_dir.parent, ignore_errors=True)

    def _find_subscription(
        self,
        group_id: int,
        url: str,
        branch: str | None,
    ) -> tuple[RepositoryIdentity, Subscription | None]:
        explicit = self._explicit_branch(branch)
        if explicit is not None:
            identity = build_identity(url, explicit)
            return identity, self.state.get_subscription(group_id, identity.key)

        requested = build_identity(url)
        matches = [
            (repo_key, subscription)
            for repo_key, subscription in self.state.list_group_subscriptions(group_id).items()
            if subscription.url == requested.url
        ]
        if not matches:
            return requested, None
        if len(matches) > 1:
            raise ValueError("本群关注了这个仓库的多个分支，请使用 --分支名 指定。")
        _, subscription = matches[0]
        return build_identity(subscription.url, subscription.branch), subscription

    @staticmethod
    def _explicit_branch(branch: str | None) -> str | None:
        if branch is None:
            return None
        return normalize_branch(branch)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
