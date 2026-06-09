from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

from dulwich import porcelain


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

    response = worker._archive_response(
        archive,
        "repo123",
        "eratoho",
        "http://worker.example",
    )

    assert response["name"] == "sample.7z"
    assert response["size"] == len(b"content")
    assert response["password"] == "eratoho"
    assert response["download_url"] == "http://worker.example/files/repo123/sample.7z?token=secret"
