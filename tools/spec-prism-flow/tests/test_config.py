from pathlib import Path

import pytest

from spec_prism_flow.build import git_ops
from spec_prism_flow.config import ConfigError, load_config, resolve_config_path

MINIMAL_TOML = """
[plan]
workspace_dir = "docs"
phase_dir = "docs/phases"
"""


@pytest.fixture(autouse=True)
def repo_root(tmp_path, monkeypatch) -> Path:
    """Anchor every relative config path at a fake repo root instead of whatever repo
    (if any) the test process happens to be running inside."""
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(git_ops, "toplevel", lambda _cwd: root)
    return root


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / ".spec-prism-flow.toml"
    p.write_text(content)
    return p


def test_load_minimal(tmp_path, repo_root):
    cfg = load_config(_write(tmp_path, MINIMAL_TOML))

    assert cfg.plan.workspace_dir == repo_root / "docs"
    assert cfg.plan.phase_dir == repo_root / "docs/phases"
    assert cfg.plan.conventions_path is None
    assert cfg.agent.backend == "claude"


def test_resolve_config_path_expands_user():
    assert resolve_config_path("~/.spec-prism-flow.toml") == Path.home() / ".spec-prism-flow.toml"


def test_resolve_config_path_defaults_when_absent():
    assert resolve_config_path(None) == Path(".spec-prism-flow.toml")


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / ".spec-prism-flow.toml")


def test_malformed_toml_raises_config_error(tmp_path):
    p = _write(
        tmp_path,
        """
[plan
workspace_dir = "docs"
""",
    )

    with pytest.raises(ConfigError, match="Invalid TOML"):
        load_config(p)


def test_missing_workspace_dir_raises(tmp_path):
    p = _write(tmp_path, '[plan]\nphase_dir = "docs/phases"\n')

    with pytest.raises(ConfigError, match=r"plan\.workspace_dir"):
        load_config(p)


def test_missing_phase_dir_raises(tmp_path):
    p = _write(tmp_path, '[plan]\nworkspace_dir = "docs"\n')

    with pytest.raises(ConfigError, match=r"plan\.phase_dir"):
        load_config(p)


def test_conventions_path_parsed(tmp_path, repo_root):
    p = _write(
        tmp_path,
        MINIMAL_TOML
        + """
conventions_path = "docs/CONVENTIONS.md"
""",
    )

    cfg = load_config(p)

    assert cfg.plan.conventions_path == repo_root / "docs/CONVENTIONS.md"


def test_absolute_path_is_returned_untouched(tmp_path):
    raw = f"{tmp_path}/docs/../workspace"
    p = _write(tmp_path, f'[plan]\nworkspace_dir = "{raw}"\nphase_dir = "docs/phases"\n')

    cfg = load_config(p)

    assert cfg.plan.workspace_dir == Path(raw)


def test_tilde_path_is_expanded_without_looking_up_repo_root(tmp_path, monkeypatch):
    def _unexpected_toplevel(_cwd):
        raise AssertionError("toplevel lookup must not happen for ~ paths")  # noqa: TRY003

    monkeypatch.setattr(git_ops, "toplevel", _unexpected_toplevel)
    p = _write(tmp_path, f'[plan]\nworkspace_dir = "~/docs"\nphase_dir = "{tmp_path}/phases"\n')

    cfg = load_config(p)

    assert cfg.plan.workspace_dir == Path.home() / "docs"


def test_relative_path_is_resolved_against_repo_toplevel(tmp_path, repo_root):
    cfg = load_config(_write(tmp_path, MINIMAL_TOML))

    assert cfg.plan.workspace_dir == (repo_root / "docs").resolve()
    assert cfg.plan.phase_dir == (repo_root / "docs/phases").resolve()


def test_relative_path_outside_git_repo_raises(tmp_path, monkeypatch):
    def _not_a_repo(_cwd):
        raise RuntimeError("fatal: not a git repository")  # noqa: TRY003

    monkeypatch.setattr(git_ops, "toplevel", _not_a_repo)

    with pytest.raises(ConfigError, match=r"plan\.workspace_dir.*not in a git repository"):
        load_config(_write(tmp_path, MINIMAL_TOML))


def test_repo_root_is_looked_up_once_across_relative_fields(tmp_path, repo_root, monkeypatch):
    calls = []

    def _counting_toplevel(cwd):
        calls.append(cwd)
        return repo_root

    monkeypatch.setattr(git_ops, "toplevel", _counting_toplevel)
    p = _write(
        tmp_path,
        MINIMAL_TOML
        + """
conventions_path = "docs/CONVENTIONS.md"

[build]
state_dir = "state"
""",
    )

    cfg = load_config(p)

    assert len(calls) == 1
    assert cfg.plan.workspace_dir == repo_root / "docs"
    assert cfg.plan.phase_dir == repo_root / "docs/phases"
    assert cfg.plan.conventions_path == repo_root / "docs/CONVENTIONS.md"
    assert cfg.build.state_dir == repo_root / "state"


def test_agent_backend_defaults_to_claude_when_section_absent(tmp_path):
    cfg = load_config(_write(tmp_path, MINIMAL_TOML))

    assert cfg.agent.backend == "claude"


def test_agent_backend_parsed(tmp_path):
    p = _write(tmp_path, MINIMAL_TOML + '\n[agent]\nbackend = "opencode"\n')

    cfg = load_config(p)

    assert cfg.agent.backend == "opencode"


def test_invalid_agent_backend_raises(tmp_path):
    p = _write(tmp_path, MINIMAL_TOML + '\n[agent]\nbackend = "bogus"\n')

    with pytest.raises(ConfigError, match=r"agent\.backend"):
        load_config(p)


def test_build_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, MINIMAL_TOML))

    assert cfg.build.commands == []
    assert cfg.build.workers == 1
    assert cfg.build.max_retry_cycles == 3
    assert str(cfg.build.state_dir).endswith("dotharness/spec-prism-flow/state")
    assert not str(cfg.build.state_dir).startswith("~")


def test_build_parsed(tmp_path):
    p = _write(
        tmp_path,
        MINIMAL_TOML
        + """
[build]
commands = ["pnpm build", "pnpm lint", "pnpm test"]
workers = 4
max_retry_cycles = 5
state_dir = "~/custom/state"
""",
    )

    cfg = load_config(p)

    assert cfg.build.commands == ["pnpm build", "pnpm lint", "pnpm test"]
    assert cfg.build.workers == 4
    assert cfg.build.max_retry_cycles == 5
    assert not str(cfg.build.state_dir).startswith("~")
    assert str(cfg.build.state_dir).endswith("custom/state")


def test_review_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, MINIMAL_TOML))

    assert cfg.review.enabled is False
    assert cfg.review.command == "harness"
    assert not str(cfg.review.tool_dir).startswith("~")
    assert cfg.review.harness_config is None


def test_review_enabled_without_harness_config_raises(tmp_path):
    p = _write(tmp_path, MINIMAL_TOML + "\n[review]\nenabled = true\n")

    with pytest.raises(ConfigError, match=r"review\.harness_config"):
        load_config(p)


def test_review_enabled_with_harness_config_parses(tmp_path):
    p = _write(
        tmp_path,
        MINIMAL_TOML
        + """
[review]
enabled = true
harness_config = "~/.harness-spec_prism_flow.toml"
""",
    )

    cfg = load_config(p)

    assert cfg.review.enabled is True
    assert not str(cfg.review.harness_config).startswith("~")
    assert str(cfg.review.harness_config).endswith(".harness-spec_prism_flow.toml")


def test_vibe_heal_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, MINIMAL_TOML))

    assert cfg.vibe_heal.enabled is False
    assert cfg.vibe_heal.command == "vibe-heal"
    assert not str(cfg.vibe_heal.tool_dir).startswith("~")


def test_prose_review_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, MINIMAL_TOML))

    assert cfg.prose_review.enabled is False
    assert cfg.prose_review.backend == "claude"


def test_prose_review_parsed(tmp_path):
    p = _write(tmp_path, MINIMAL_TOML + '\n[prose_review]\nenabled = true\nbackend = "opencode"\n')

    cfg = load_config(p)

    assert cfg.prose_review.enabled is True
    assert cfg.prose_review.backend == "opencode"


def test_invalid_prose_review_backend_raises(tmp_path):
    p = _write(tmp_path, MINIMAL_TOML + '\n[prose_review]\nbackend = "bogus"\n')

    with pytest.raises(ConfigError, match=r"prose_review\.backend"):
        load_config(p)


def test_harness_knowledge_dir_default(tmp_path):
    cfg = load_config(_write(tmp_path, MINIMAL_TOML))

    assert not str(cfg.harness.knowledge_dir).startswith("~")
    assert str(cfg.harness.knowledge_dir).endswith(".harness/knowledge")


def test_harness_knowledge_dir_parsed(tmp_path):
    p = _write(
        tmp_path,
        MINIMAL_TOML
        + """
[harness]
knowledge_dir = "~/custom/knowledge"
""",
    )

    cfg = load_config(p)

    assert not str(cfg.harness.knowledge_dir).startswith("~")
    assert str(cfg.harness.knowledge_dir).endswith("custom/knowledge")
