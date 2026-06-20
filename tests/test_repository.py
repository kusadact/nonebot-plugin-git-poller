from __future__ import annotations

from helpers import load_plugin_module

repository = load_plugin_module("repository")


def test_normalize_repo_url_keeps_equivalent_https_urls_together():
    assert repository.normalize_repo_url("HTTPS://GitHub.com/Owner/Repo") == (
        "https://github.com/Owner/Repo.git"
    )
    assert repository.normalize_repo_url("https://github.com/Owner/Repo.git/") == (
        "https://github.com/Owner/Repo.git"
    )
    assert repository.repo_key_from_url(
        "https://github.com/Owner/Repo"
    ) == repository.repo_key_from_url(
        "https://github.com/Owner/Repo.git/"
    )


def test_repo_key_can_include_branch_scope():
    main = repository.build_identity("https://github.com/Owner/Repo", "main")
    dev = repository.build_identity("https://github.com/Owner/Repo.git", "dev")
    another_main = repository.build_identity("https://github.com/Owner/Repo.git/", "main")

    assert main.key != dev.key
    assert main.key == another_main.key
    assert "-main-" in main.key
    assert "-dev-" in dev.key


def test_normalize_repo_url_supports_scp_like_ssh():
    identity = repository.build_identity("git@GitLab.example:Group/Repo.git")

    assert identity.url == "git@gitlab.example:Group/Repo.git"
    assert identity.display_name == "Repo"
    assert identity.web_url == "https://gitlab.example/Group/Repo"


def test_normalize_repo_url_keeps_local_paths_without_git_suffix():
    assert repository.normalize_repo_url("/tmp/repo") == "/tmp/repo"
    assert repository.normalize_repo_url("./repo") == "./repo"


def test_provider_urls_use_expected_routes():
    github = "https://github.com/example/repo.git"
    gitlab = "https://gitlab.com/example/repo.git"
    gitgud = "https://gitgud.io/example/repo.git"

    assert repository.build_commit_url(github, "abc") == (
        "https://github.com/example/repo/commit/abc"
    )
    assert repository.build_commit_url(gitlab, "abc") == (
        "https://gitlab.com/example/repo/-/commit/abc"
    )
    assert repository.build_compare_url(gitgud, "old", "new") == (
        "https://gitgud.io/example/repo/-/compare/old...new"
    )
