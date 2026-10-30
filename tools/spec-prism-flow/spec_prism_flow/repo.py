"""Generic git plumbing with no dependency on any other spec_prism_flow package.

`config` needs to resolve repo-relative paths but must stay a leaf module, and
`build` needs the same repo lookup -- keeping it here lets both import it without
making `config` depend on `build` (which itself depends on `config`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 30


class RepoError(RuntimeError):
    """A git subprocess needed to locate the repository failed."""

    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.cmd_args = args
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"`{' '.join(args)}` exited {returncode}: {stderr.strip()}")


def toplevel(cwd: Path) -> Path:
    """Absolute path to the toplevel of the git repo containing `cwd`."""
    args = ["git", "rev-parse", "--show-toplevel"]
    try:
        result = subprocess.run(  # noqa: S603
            args, cwd=cwd, capture_output=True, text=True, check=False, timeout=_GIT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise RepoError(args, -1, f"timed out after {_GIT_TIMEOUT_SECONDS}s: {exc.stderr or ''}") from exc
    if result.returncode != 0:
        raise RepoError(args, result.returncode, result.stderr)
    return Path(result.stdout.strip()).resolve()
