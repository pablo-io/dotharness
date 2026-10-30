"""Shared fixtures for the top-level (non-`build/`) test suites."""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Turn `tmp_path` into a git repo so configs with repo-root-relative paths load.

    CLI tests `monkeypatch.chdir(tmp_path)` and write a config whose `plan.*` values
    are relative; with repo-root-anchored path resolution those only load when the
    cwd is inside a git repository.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)  # noqa: S603, S607
    return tmp_path
