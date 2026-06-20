# Agent Guidelines

## Versioning

- Before pushing this project to a remote repository, bump the package version.
- Keep `pyproject.toml` and the editable package entry in `uv.lock` in sync.
- Local-only commits do not require a version bump unless they will be pushed later.
- After finishing code or documentation changes, create a local commit before handing the work back.

## Checks

- Run the relevant tests before committing code changes.
- For broad behavior changes, prefer the full test suite: `.venv/bin/python -m pytest -q`.
