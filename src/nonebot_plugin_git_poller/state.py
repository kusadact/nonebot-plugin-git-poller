from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nonebot import logger
from nonebot_plugin_localstore import get_plugin_data_dir

from .models import Subscription


class StateStore:
    def __init__(self) -> None:
        self.data_dir = get_plugin_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "state.json"

    def read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            logger.debug(f"git poller state file does not exist yet: {self.state_path}")
            return {"groups": {}}
        logger.debug(f"git poller reading state file: {self.state_path}")
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"groups": {}}
        if not isinstance(data.get("groups"), dict):
            data["groups"] = {}
        return data

    def write_state(self, state: dict[str, Any]) -> None:
        if not isinstance(state.get("groups"), dict):
            state["groups"] = {}
        self._write_json(self.state_path, state)

    def get_subscription(self, group_id: int, repo_key: str) -> Subscription | None:
        raw = self._repo_entry(group_id, repo_key)
        if raw is None:
            return None
        return Subscription.from_json(raw)

    def list_group_subscriptions(self, group_id: int) -> dict[str, Subscription]:
        state = self.read_state()
        repos = self._repos_from_state(state, group_id)
        result: dict[str, Subscription] = {}
        for repo_key, raw in repos.items():
            if isinstance(raw, dict):
                try:
                    result[str(repo_key)] = Subscription.from_json(raw)
                except (KeyError, TypeError, ValueError):
                    logger.warning(
                        f"git poller skipped invalid subscription for group {group_id}: {repo_key}"
                    )
        return result

    def list_all_subscriptions(self) -> dict[int, dict[str, Subscription]]:
        state = self.read_state()
        groups = state.get("groups")
        if not isinstance(groups, dict):
            return {}
        result: dict[int, dict[str, Subscription]] = {}
        for group_id_text in groups:
            try:
                group_id = int(group_id_text)
            except (TypeError, ValueError):
                continue
            subscriptions = self.list_group_subscriptions(group_id)
            if subscriptions:
                result[group_id] = subscriptions
        return result

    def upsert_subscription(
        self,
        group_id: int,
        repo_key: str,
        subscription: Subscription,
    ) -> None:
        state = self.read_state()
        repos = self._ensure_repos(state, group_id)
        repos[repo_key] = subscription.to_json()
        logger.info(
            f"git poller subscription saved: group={group_id}, "
            f"repo={repo_key}, branch={subscription.branch}, enabled={subscription.enabled}"
        )
        self.write_state(state)

    def remove_subscription(self, group_id: int, repo_key: str) -> bool:
        state = self.read_state()
        repos = self._repos_from_state(state, group_id)
        if repo_key not in repos:
            return False
        del repos[repo_key]
        logger.info(f"git poller subscription removed: group={group_id}, repo={repo_key}")
        self.write_state(state)
        return True

    def update_last_success(
        self,
        group_id: int,
        repo_key: str,
        sha: str,
        updated_at: str,
    ) -> None:
        subscription = self.get_subscription(group_id, repo_key)
        if subscription is None:
            raise KeyError(f"subscription not found: group={group_id}, repo={repo_key}")
        subscription.last_success_sha = sha
        subscription.updated_at = updated_at
        self.upsert_subscription(group_id, repo_key, subscription)
        logger.info(
            f"git poller last_success_sha updated: group={group_id}, "
            f"repo={repo_key}, sha={sha[:8]}"
        )

    def update_last_archive_path(
        self,
        group_id: int,
        repo_key: str,
        archive_path: str | None,
        updated_at: str,
    ) -> None:
        subscription = self.get_subscription(group_id, repo_key)
        if subscription is None:
            raise KeyError(f"subscription not found: group={group_id}, repo={repo_key}")
        subscription.last_archive_path = archive_path
        subscription.updated_at = updated_at
        self.upsert_subscription(group_id, repo_key, subscription)
        logger.info(
            f"git poller last archive path updated: group={group_id}, "
            f"repo={repo_key}, has_archive={archive_path is not None}"
        )

    def update_schedule(
        self,
        group_id: int,
        repo_key: str,
        schedule: str,
        updated_at: str,
    ) -> Subscription:
        subscription = self.get_subscription(group_id, repo_key)
        if subscription is None:
            raise KeyError(f"subscription not found: group={group_id}, repo={repo_key}")
        subscription.schedule = schedule
        subscription.updated_at = updated_at
        self.upsert_subscription(group_id, repo_key, subscription)
        logger.info(
            f"git poller schedule updated: group={group_id}, repo={repo_key}, schedule={schedule}"
        )
        return subscription

    def update_archive_password(
        self,
        group_id: int,
        repo_key: str,
        password: str | None,
        updated_at: str,
    ) -> Subscription:
        subscription = self.get_subscription(group_id, repo_key)
        if subscription is None:
            raise KeyError(f"subscription not found: group={group_id}, repo={repo_key}")
        subscription.archive_password = password
        subscription.updated_at = updated_at
        self.upsert_subscription(group_id, repo_key, subscription)
        logger.info(
            f"git poller archive password updated: group={group_id}, "
            f"repo={repo_key}, has_password={password is not None}"
        )
        return subscription

    def subscriptions_for_schedule(
        self,
        schedule: str,
    ) -> list[tuple[int, str, Subscription]]:
        target = schedule.strip()
        result: list[tuple[int, str, Subscription]] = []
        for group_id, subscriptions in self.list_all_subscriptions().items():
            for repo_key, subscription in subscriptions.items():
                if subscription.enabled and subscription.schedule.strip() == target:
                    result.append((group_id, repo_key, subscription))
        return result

    def is_repo_key_subscribed(self, repo_key: str) -> bool:
        for subscriptions in self.list_all_subscriptions().values():
            if repo_key in subscriptions:
                return True
        return False

    def _repo_entry(self, group_id: int, repo_key: str) -> dict[str, Any] | None:
        repos = self._repos_from_state(self.read_state(), group_id)
        raw = repos.get(repo_key)
        return raw if isinstance(raw, dict) else None

    @staticmethod
    def _repos_from_state(state: dict[str, Any], group_id: int) -> dict[str, Any]:
        groups = state.get("groups")
        if not isinstance(groups, dict):
            return {}
        group_state = groups.get(str(int(group_id)))
        if not isinstance(group_state, dict):
            return {}
        repos = group_state.get("repos")
        return repos if isinstance(repos, dict) else {}

    @staticmethod
    def _ensure_repos(state: dict[str, Any], group_id: int) -> dict[str, Any]:
        groups = state.get("groups")
        if not isinstance(groups, dict):
            groups = {}
            state["groups"] = groups
        group_text = str(int(group_id))
        group_state = groups.get(group_text)
        if not isinstance(group_state, dict):
            group_state = {}
            groups[group_text] = group_state
        repos = group_state.get("repos")
        if not isinstance(repos, dict):
            repos = {}
            group_state["repos"] = repos
        return repos

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
