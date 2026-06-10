from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

from dulwich import porcelain
import pytest


def _load_worker_module():
    path = Path(__file__).resolve().parents[1] / "worker" / "eratw_worker.py"
    spec = importlib.util.spec_from_file_location("eratw_worker", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_export_commit_tree_writes_clean_worktree(tmp_path: Path):
    worker = _load_worker_module()
    repo_dir = tmp_path / "repo"
    repo = porcelain.init(str(repo_dir))
    source_file = repo_dir / "dir" / "run.sh"
    source_file.parent.mkdir()
    source_file.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    source_file.chmod(0o755)
    porcelain.add(str(repo_dir), paths=[str(source_file)])
    commit_id = porcelain.commit(
        str(repo_dir),
        message=b"init",
        author=b"tester <tester@example.com>",
        committer=b"tester <tester@example.com>",
    )
    repo.close()

    destination = tmp_path / "export"
    destination.mkdir()
    worker._export_commit_tree(repo_dir, destination, commit_id.decode())

    exported = destination / "dir" / "run.sh"
    assert exported.read_text(encoding="utf-8") == "#!/bin/sh\necho ok\n"
    assert os.access(exported, os.X_OK)
    assert not (destination / ".git").exists()


def test_archive_response_uses_worker_download_url(tmp_path: Path, monkeypatch):
    worker = _load_worker_module()
    archive = tmp_path / "sample.7z"
    archive.write_bytes(b"content")
    monkeypatch.setattr(worker.CONFIG, "token", "secret")
    monkeypatch.setattr(worker.CONFIG, "file_token", "file-secret")
    monkeypatch.setattr(worker.CONFIG, "file_token_ttl", 3600)

    response = worker._archive_response(
        archive,
        "repo123",
        "eratoho",
        "http://worker.example",
    )

    assert response["name"] == "sample.7z"
    assert response["size"] == len(b"content")
    assert response["password"] == "eratoho"
    parsed = urlparse(response["download_url"])
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "worker.example"
    assert parsed.path == "/files/repo123/sample.7z"
    assert query["token"] != ["secret"]
    assert query["expires"] == [str(response["download_expires_at"])]
    assert worker._valid_download_token("repo123", "sample.7z", query)


def test_default_file_token_is_persisted(tmp_path: Path):
    worker = _load_worker_module()

    first = worker._load_file_token(tmp_path)
    second = worker._load_file_token(tmp_path)

    assert first == second
    assert first
    assert (tmp_path / "file_download_token").read_text(encoding="utf-8") == first


def test_worker_build_requires_token(monkeypatch):
    worker = _load_worker_module()
    monkeypatch.setattr(worker.CONFIG, "token", "")

    assert worker.Handler._authorized(object()) is False


def test_worker_main_requires_token(monkeypatch):
    worker = _load_worker_module()
    monkeypatch.setattr(worker.CONFIG, "token", "")

    with pytest.raises(RuntimeError, match="ERATW_WORKER_TOKEN is required"):
        worker.main()


def test_sync_git_repo_retries_transient_fetch_failure(tmp_path: Path, monkeypatch):
    worker = _load_worker_module()
    clone_attempts = 0
    fetch_attempts = 0
    sleeps: list[float] = []

    monkeypatch.setattr(worker.CONFIG, "git_retries", 5)
    monkeypatch.setattr(worker.CONFIG, "git_retry_delay", 1.0)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)
    monkeypatch.setattr(worker, "_remove_invalid_git_repo", lambda *args: None)

    def flaky_clone(*args):
        nonlocal clone_attempts
        clone_attempts += 1
        if clone_attempts < 2:
            raise OSError("connection broken during clone")

    def flaky_fetch(*args):
        nonlocal fetch_attempts
        fetch_attempts += 1
        if fetch_attempts < 3:
            raise OSError("connection broken during fetch")

    monkeypatch.setattr(worker, "_ensure_git_repo", flaky_clone)
    monkeypatch.setattr(worker, "_fetch_git_repo", flaky_fetch)
    monkeypatch.setattr(worker, "_verify_commit", lambda *args: None)

    worker._sync_git_repo(
        tmp_path / "repo.git",
        "https://example.test/repo.git",
        "main",
        1,
        "http://proxy.example:7890",
        "abc123",
    )

    assert clone_attempts == 2
    assert fetch_attempts == 3
    assert sleeps == [1.0, 1.0, 2.0]


def test_sync_git_repo_reports_final_retry_failure(tmp_path: Path, monkeypatch):
    worker = _load_worker_module()
    attempts = 0

    monkeypatch.setattr(worker.CONFIG, "git_retries", 3)
    monkeypatch.setattr(worker.CONFIG, "git_retry_delay", 0.0)
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)
    monkeypatch.setattr(worker, "_ensure_git_repo", lambda *args: None)
    monkeypatch.setattr(worker, "_remove_invalid_git_repo", lambda *args: None)

    def broken_fetch(*args):
        nonlocal attempts
        attempts += 1
        raise OSError("connection broken")

    monkeypatch.setattr(worker, "_fetch_git_repo", broken_fetch)
    monkeypatch.setattr(worker, "_verify_commit", lambda *args: None)

    with pytest.raises(RuntimeError, match="git fetch main failed after 3 attempts"):
        worker._sync_git_repo(
            tmp_path / "repo.git",
            "https://example.test/repo.git",
            "main",
            1,
            "http://proxy.example:7890",
            "abc123",
        )

    assert attempts == 3


def test_worker_log_format_preserves_numeric_placeholders():
    worker = _load_worker_module()

    message = worker._format_log_message(
        "code %d, message %s: /files/a.7z?token=secret",
        (404, "File not found"),
    )

    assert message == "code 404, message File not found: /files/a.7z?token=<redacted>"
