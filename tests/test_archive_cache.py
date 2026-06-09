from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_worker_module():
    path = Path(__file__).resolve().parents[1] / "worker" / "eratw_worker.py"
    spec = importlib.util.spec_from_file_location("eratw_worker_cache", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_worker_archive_cache_requires_metadata(tmp_path: Path, monkeypatch):
    worker = _load_worker_module()
    monkeypatch.setattr(worker.CONFIG, "token", "")
    archive_path = tmp_path / "sample.7z"
    metadata_path = tmp_path / "sample.7z.json"
    archive_path.write_bytes(b"partial")

    assert worker._cached_archive_response(
        archive_path,
        metadata_path,
        "abc123",
        "https://example.test/repo.git",
        "main",
        "eratoho",
        "http://worker.example",
        "repo123",
    ) is None


def test_worker_archive_cache_rejects_password_change(tmp_path: Path, monkeypatch):
    worker = _load_worker_module()
    monkeypatch.setattr(worker.CONFIG, "token", "")
    archive_path = tmp_path / "sample.7z"
    metadata_path = tmp_path / "sample.7z.json"
    archive_path.write_bytes(b"archive bytes")
    response = worker._archive_response(
        archive_path,
        "repo123",
        "old-pass",
        "http://worker.example",
    )
    worker._write_archive_metadata(
        metadata_path,
        "abc123",
        "https://example.test/repo.git",
        "main",
        "old-pass",
        response,
    )

    assert worker._cached_archive_response(
        archive_path,
        metadata_path,
        "abc123",
        "https://example.test/repo.git",
        "main",
        "new-pass",
        "http://worker.example",
        "repo123",
    ) is None


def test_worker_archive_cache_accepts_matching_metadata(tmp_path: Path, monkeypatch):
    worker = _load_worker_module()
    monkeypatch.setattr(worker.CONFIG, "token", "")
    archive_path = tmp_path / "sample.7z"
    metadata_path = tmp_path / "sample.7z.json"
    archive_path.write_bytes(b"archive bytes")
    response = worker._archive_response(
        archive_path,
        "repo123",
        "same-pass",
        "http://worker.example",
    )
    worker._write_archive_metadata(
        metadata_path,
        "abc123",
        "https://example.test/repo.git",
        "main",
        "same-pass",
        response,
    )

    cached = worker._cached_archive_response(
        archive_path,
        metadata_path,
        "abc123",
        "https://example.test/repo.git",
        "main",
        "same-pass",
        "http://worker.example",
        "repo123",
    )

    assert cached is not None
    assert cached["password"] == "same-pass"
    assert cached["sha256"] == response["sha256"]
