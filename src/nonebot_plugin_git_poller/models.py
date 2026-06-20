from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RepositoryIdentity:
    key: str
    url: str
    display_name: str
    web_url: str | None


@dataclass
class Subscription:
    url: str
    branch: str
    schedule: str
    last_success_sha: str | None = None
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "branch": self.branch,
            "schedule": self.schedule,
            "last_success_sha": self.last_success_sha,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Subscription":
        return cls(
            url=str(data["url"]),
            branch=str(data.get("branch") or "main"),
            schedule=str(data.get("schedule") or ""),
            last_success_sha=(
                str(data["last_success_sha"])
                if data.get("last_success_sha")
                else None
            ),
            enabled=bool(data.get("enabled", True)),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    short_sha: str
    title: str
    committed_at: str
    author: str
    url: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "sha": self.sha,
            "short_sha": self.short_sha,
            "title": self.title,
            "committed_at": self.committed_at,
            "author": self.author,
            "url": self.url,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CommitInfo":
        sha = str(data["sha"])
        return cls(
            sha=sha,
            short_sha=str(data.get("short_sha") or sha[:8]),
            title=str(data.get("title") or sha[:8]).strip(),
            committed_at=str(data.get("committed_at") or ""),
            author=str(data.get("author") or ""),
            url=str(data["url"]) if data.get("url") else None,
        )


@dataclass(frozen=True)
class UpdatePayload:
    repo_key: str
    repo_url: str
    repo_name: str
    branch: str
    previous_sha: str | None
    target_sha: str
    target_short_sha: str
    generated_at: str
    commits: list[CommitInfo]
    compare_url: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "repo_key": self.repo_key,
            "repo_url": self.repo_url,
            "repo_name": self.repo_name,
            "branch": self.branch,
            "previous_sha": self.previous_sha,
            "target_sha": self.target_sha,
            "target_short_sha": self.target_short_sha,
            "generated_at": self.generated_at,
            "commits": [commit.to_json() for commit in self.commits],
            "compare_url": self.compare_url,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "UpdatePayload":
        return cls(
            repo_key=str(data["repo_key"]),
            repo_url=str(data["repo_url"]),
            repo_name=str(data["repo_name"]),
            branch=str(data.get("branch") or "main"),
            previous_sha=(
                str(data["previous_sha"]) if data.get("previous_sha") else None
            ),
            target_sha=str(data["target_sha"]),
            target_short_sha=str(data.get("target_short_sha") or str(data["target_sha"])[:8]),
            generated_at=str(data.get("generated_at") or ""),
            commits=[
                CommitInfo.from_json(item)
                for item in data.get("commits", [])
                if isinstance(item, dict)
            ],
            compare_url=str(data["compare_url"]) if data.get("compare_url") else None,
        )


@dataclass(frozen=True)
class PollResult:
    group_id: int
    repo_key: str
    subscription: Subscription
    payload: UpdatePayload
