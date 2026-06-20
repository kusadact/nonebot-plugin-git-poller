from __future__ import annotations

import pytest

from helpers import load_plugin_module

command_args = load_plugin_module("command_args")


def test_parse_repo_command_args_accepts_url_only():
    parsed = command_args.parse_repo_command_args("https://example.test/repo.git")

    assert parsed.url == "https://example.test/repo.git"
    assert parsed.branch is None


def test_parse_repo_command_args_accepts_branch_suffix():
    parsed = command_args.parse_repo_command_args("https://example.test/repo.git --dev")

    assert parsed.url == "https://example.test/repo.git"
    assert parsed.branch == "dev"


def test_parse_repo_command_args_rejects_unexpected_tail():
    with pytest.raises(ValueError):
        command_args.parse_repo_command_args("https://example.test/repo.git dev")


def test_parse_repo_command_args_rejects_empty_branch():
    with pytest.raises(ValueError):
        command_args.parse_repo_command_args("https://example.test/repo.git --")
