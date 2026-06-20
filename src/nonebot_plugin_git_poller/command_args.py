from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoCommandArgs:
    url: str
    branch: str | None = None


def parse_repo_command_args(text: str, *, allow_tail: bool = False) -> RepoCommandArgs | None:
    value = text.strip()
    if not value:
        return None

    parts = value.split()
    url = parts[0]
    branch: str | None = None
    index = 1

    if index < len(parts) and parts[index].startswith("--"):
        branch = parts[index][2:].strip()
        if not branch:
            raise ValueError("分支名不能为空。")
        index += 1

    if index < len(parts) and not allow_tail:
        raise ValueError("参数格式错误，请使用：仓库url [--分支名]")

    return RepoCommandArgs(url=url, branch=branch)
