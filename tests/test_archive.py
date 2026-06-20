from __future__ import annotations

from pathlib import Path
import sys
import types

import py7zr

from helpers import load_plugin_module


def _load_archive_module(cache_dir: Path):
    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.logger = types.SimpleNamespace(info=lambda *args, **kwargs: None)
    localstore_module = types.ModuleType("nonebot_plugin_localstore")
    localstore_module.get_plugin_cache_dir = lambda: cache_dir
    sys.modules["nonebot"] = nonebot_module
    sys.modules["nonebot_plugin_localstore"] = localstore_module

    models = load_plugin_module("models")
    archive = load_plugin_module("archive")
    return archive, models


def _payload(models):
    return models.UpdatePayload(
        repo_key="repo-main-abc",
        repo_url="https://example.test/repo.git",
        repo_name="repo",
        branch="main",
        previous_sha="old",
        target_sha="abcdef1234567890",
        target_short_sha="abcdef12",
        generated_at="2026-06-20T04:00:00+08:00",
        commits=[],
    )


def test_archive_builder_creates_plain_7z_by_default(tmp_path: Path):
    archive, models = _load_archive_module(tmp_path / "cache")
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("hello", encoding="utf-8")
    builder = archive.ArchiveBuilder()

    result = builder.build(
        _payload(models),
        models.Subscription(url="https://example.test/repo.git", branch="main", schedule="每日04-00"),
        source,
    )

    assert result.path.exists()
    assert result.name == "repo-main-abcdef12.7z"
    assert len(result.sha256) == 64
    assert result.password is None
    assert result.password_used is False
    with py7zr.SevenZipFile(result.path, "r") as compressed:
        assert "source/README.md" in compressed.getnames()


def test_archive_builder_uses_subscription_password(tmp_path: Path):
    archive, models = _load_archive_module(tmp_path / "cache")
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("hello", encoding="utf-8")
    builder = archive.ArchiveBuilder(default_password="global")

    result = builder.build(
        _payload(models),
        models.Subscription(
            url="https://example.test/repo.git",
            branch="main",
            schedule="每日04-00",
            archive_password="repo-secret",
        ),
        source,
    )

    assert result.password_used is True
    assert result.password == "repo-secret"
    with py7zr.SevenZipFile(result.path, "r", password="repo-secret") as compressed:
        assert "source/README.md" in compressed.getnames()
