from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from spec_prism_flow.build import git_ops

DEFAULT_AGENT_BACKEND = "claude"
DEFAULT_REVIEW_COMMAND = "harness"
DEFAULT_REVIEW_TOOL_DIR = "~/.harness/tools/pr-review"
DEFAULT_VIBE_HEAL_COMMAND = "vibe-heal"
DEFAULT_VIBE_HEAL_TOOL_DIR = "~/.harness/vendor/vibe-heal"
DEFAULT_BUILD_WORKERS = 1
DEFAULT_BUILD_MAX_RETRY_CYCLES = 3
DEFAULT_BUILD_STATE_DIR = "~/.local/share/dotharness/spec-prism-flow/state"
DEFAULT_HARNESS_KNOWLEDGE_DIR = "~/.harness/knowledge"
DEFAULT_CONFIG_FILE = ".spec-prism-flow.toml"


class ConfigError(ValueError):
    pass


def parse_backend(value: str, field_name: str) -> str:
    if value not in ("claude", "opencode"):
        raise ConfigError(f"Invalid {field_name} '{value}': must be 'claude' or 'opencode'")  # noqa: TRY003
    return value


def resolve_config_path(config_path_str: str | None) -> Path:
    return Path(config_path_str).expanduser() if config_path_str else Path(DEFAULT_CONFIG_FILE)


def _resolve_path_maybe_repo_relative(raw_value: str | Path, field_name: str, repo_root_cache: dict) -> Path:
    s = str(raw_value)
    p = Path(s).expanduser()
    if p.is_absolute():
        return p
    if s.startswith("~"):
        return p
    if "repo_root" not in repo_root_cache:
        try:
            repo_root_cache["repo_root"] = git_ops.toplevel(Path.cwd())
        except (git_ops.GitCommandError, FileNotFoundError) as e:
            raise ConfigError(  # noqa: TRY003
                f"Cannot resolve relative path for {field_name}: repo root could not be determined ({e})"
            ) from e
    repo_root = repo_root_cache["repo_root"]
    resolved = (repo_root / p).resolve()
    return resolved


@dataclass
class AgentConfig:
    backend: str = DEFAULT_AGENT_BACKEND


@dataclass
class PlanConfig:
    workspace_dir: Path
    phase_dir: Path
    conventions_path: Path | None = None


@dataclass
class ReviewConfig:
    enabled: bool = False
    command: str = DEFAULT_REVIEW_COMMAND
    tool_dir: Path = field(default_factory=lambda: Path(DEFAULT_REVIEW_TOOL_DIR).expanduser())
    harness_config: Path | None = None


@dataclass
class VibeHealConfig:
    enabled: bool = False
    command: str = DEFAULT_VIBE_HEAL_COMMAND
    tool_dir: Path = field(default_factory=lambda: Path(DEFAULT_VIBE_HEAL_TOOL_DIR).expanduser())


@dataclass
class ProseReviewConfig:
    enabled: bool = False
    backend: str = DEFAULT_AGENT_BACKEND


@dataclass
class BuildConfig:
    commands: list[str] = field(default_factory=list)
    workers: int = DEFAULT_BUILD_WORKERS
    max_retry_cycles: int = DEFAULT_BUILD_MAX_RETRY_CYCLES
    state_dir: Path = field(default_factory=lambda: Path(DEFAULT_BUILD_STATE_DIR).expanduser())


@dataclass
class HarnessSection:
    knowledge_dir: Path = field(default_factory=lambda: Path(DEFAULT_HARNESS_KNOWLEDGE_DIR).expanduser())


@dataclass
class SpecPrismFlowConfig:
    agent: AgentConfig
    plan: PlanConfig
    review: ReviewConfig
    vibe_heal: VibeHealConfig
    build: BuildConfig
    harness: HarnessSection
    prose_review: ProseReviewConfig = field(default_factory=ProseReviewConfig)


def load_config(path: Path) -> SpecPrismFlowConfig:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")  # noqa: TRY003

    with open(path, "rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Invalid TOML in config file: {e}") from None  # noqa: TRY003

    repo_root_cache: dict = {}

    a = data.get("agent", {})
    backend = parse_backend(a.get("backend", DEFAULT_AGENT_BACKEND), "agent.backend")
    agent = AgentConfig(backend=backend)

    p = data.get("plan", {})
    if not p.get("workspace_dir"):
        raise ConfigError("plan.workspace_dir is required")  # noqa: TRY003
    if not p.get("phase_dir"):
        raise ConfigError("plan.phase_dir is required")  # noqa: TRY003
    raw_conventions_path = p.get("conventions_path")
    plan = PlanConfig(
        workspace_dir=_resolve_path_maybe_repo_relative(p["workspace_dir"], "plan.workspace_dir", repo_root_cache),
        phase_dir=_resolve_path_maybe_repo_relative(p["phase_dir"], "plan.phase_dir", repo_root_cache),
        conventions_path=_resolve_path_maybe_repo_relative(
            raw_conventions_path, "plan.conventions_path", repo_root_cache
        )
        if raw_conventions_path
        else None,
    )

    r = data.get("review", {})
    review_enabled = r.get("enabled", False)
    raw_harness_config = r.get("harness_config")
    if review_enabled and not raw_harness_config:
        raise ConfigError("review.harness_config is required when review.enabled is true")  # noqa: TRY003
    review_tool_dir = _resolve_path_maybe_repo_relative(
        r.get("tool_dir", DEFAULT_REVIEW_TOOL_DIR), "review.tool_dir", repo_root_cache
    )
    review_harness_config = (
        _resolve_path_maybe_repo_relative(raw_harness_config, "review.harness_config", repo_root_cache)
        if raw_harness_config
        else None
    )
    review = ReviewConfig(
        enabled=review_enabled,
        command=r.get("command", DEFAULT_REVIEW_COMMAND),
        tool_dir=review_tool_dir,
        harness_config=review_harness_config,
    )

    vh = data.get("vibe_heal", {})
    vibe_heal_tool_dir = _resolve_path_maybe_repo_relative(
        vh.get("tool_dir", DEFAULT_VIBE_HEAL_TOOL_DIR), "vibe_heal.tool_dir", repo_root_cache
    )
    vibe_heal = VibeHealConfig(
        enabled=vh.get("enabled", False),
        command=vh.get("command", DEFAULT_VIBE_HEAL_COMMAND),
        tool_dir=vibe_heal_tool_dir,
    )

    b = data.get("build", {})
    raw_commands = b.get("commands", [])
    if not isinstance(raw_commands, list) or not all(isinstance(c, str) for c in raw_commands):
        raise ConfigError("build.commands must be a list of strings")  # noqa: TRY003
    build_state_dir = _resolve_path_maybe_repo_relative(
        b.get("state_dir", DEFAULT_BUILD_STATE_DIR), "build.state_dir", repo_root_cache
    )
    build = BuildConfig(
        commands=raw_commands,
        workers=b.get("workers", DEFAULT_BUILD_WORKERS),
        max_retry_cycles=b.get("max_retry_cycles", DEFAULT_BUILD_MAX_RETRY_CYCLES),
        state_dir=build_state_dir,
    )

    h = data.get("harness", {})
    harness_knowledge_dir = _resolve_path_maybe_repo_relative(
        h.get("knowledge_dir", DEFAULT_HARNESS_KNOWLEDGE_DIR), "harness.knowledge_dir", repo_root_cache
    )
    harness = HarnessSection(
        knowledge_dir=harness_knowledge_dir,
    )

    pr = data.get("prose_review", {})
    prose_review_backend = parse_backend(pr.get("backend", DEFAULT_AGENT_BACKEND), "prose_review.backend")
    prose_review = ProseReviewConfig(
        enabled=pr.get("enabled", False),
        backend=prose_review_backend,
    )

    return SpecPrismFlowConfig(
        agent=agent,
        plan=plan,
        review=review,
        vibe_heal=vibe_heal,
        build=build,
        harness=harness,
        prose_review=prose_review,
    )
