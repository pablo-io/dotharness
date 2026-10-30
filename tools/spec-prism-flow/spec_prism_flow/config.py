from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from spec_prism_flow import repo

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


def _expand_user(raw_value: str | Path, field_name: str) -> Path:
    try:
        return Path(raw_value).expanduser()
    except RuntimeError as e:
        raise ConfigError(  # noqa: TRY003
            f"Cannot resolve {field_name} '{raw_value}': home directory could not be determined"
        ) from e


def _resolve_path(raw_value: str | Path, field_name: str, base: Path | None) -> Path:
    """Return `raw_value` as a canonical absolute path.

    Absolute and `~` values ignore `base`; relative values are anchored at it.
    Every return value is `.resolve()`d, so equivalent spellings (relative vs.
    absolute, `..`, symlinks) produce the same `Path`.
    """
    p = _expand_user(raw_value, field_name)
    if not p.is_absolute():
        if base is None:
            raise ConfigError(f"Cannot resolve relative path for {field_name}: no base directory")  # noqa: TRY003
        p = base / p
    return p.resolve()


class _PathResolver:
    """Resolve config paths, looking up the repo root at most once.

    Classification and path math live in `_resolve_path`; this class only
    supplies the base directory for relative values, so absolute and `~`
    values work without a git repository.
    """

    def __init__(self) -> None:
        self._repo_root: Path | None = None

    def resolve(self, raw_value: str | Path, field_name: str) -> Path:
        p = _expand_user(raw_value, field_name)
        base = None if p.is_absolute() else self._repo_root_for(field_name)
        return _resolve_path(p, field_name, base)

    def _repo_root_for(self, field_name: str) -> Path:
        if self._repo_root is None:
            try:
                self._repo_root = repo.toplevel(Path.cwd())
            except (repo.RepoError, FileNotFoundError) as e:
                raise ConfigError(  # noqa: TRY003
                    f"Cannot resolve relative path for {field_name}: repo root could not be determined ({e})"
                ) from e
        return self._repo_root


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

    resolve_path = _PathResolver().resolve

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
        workspace_dir=resolve_path(p["workspace_dir"], "plan.workspace_dir"),
        phase_dir=resolve_path(p["phase_dir"], "plan.phase_dir"),
        conventions_path=resolve_path(raw_conventions_path, "plan.conventions_path") if raw_conventions_path else None,
    )

    r = data.get("review", {})
    review_enabled = r.get("enabled", False)
    raw_harness_config = r.get("harness_config")
    if review_enabled and not raw_harness_config:
        raise ConfigError("review.harness_config is required when review.enabled is true")  # noqa: TRY003
    review_tool_dir = resolve_path(r.get("tool_dir", DEFAULT_REVIEW_TOOL_DIR), "review.tool_dir")
    review_harness_config = resolve_path(raw_harness_config, "review.harness_config") if raw_harness_config else None
    review = ReviewConfig(
        enabled=review_enabled,
        command=r.get("command", DEFAULT_REVIEW_COMMAND),
        tool_dir=review_tool_dir,
        harness_config=review_harness_config,
    )

    vh = data.get("vibe_heal", {})
    vibe_heal_tool_dir = resolve_path(vh.get("tool_dir", DEFAULT_VIBE_HEAL_TOOL_DIR), "vibe_heal.tool_dir")
    vibe_heal = VibeHealConfig(
        enabled=vh.get("enabled", False),
        command=vh.get("command", DEFAULT_VIBE_HEAL_COMMAND),
        tool_dir=vibe_heal_tool_dir,
    )

    b = data.get("build", {})
    raw_commands = b.get("commands", [])
    if not isinstance(raw_commands, list) or not all(isinstance(c, str) for c in raw_commands):
        raise ConfigError("build.commands must be a list of strings")  # noqa: TRY003
    build_state_dir = resolve_path(b.get("state_dir", DEFAULT_BUILD_STATE_DIR), "build.state_dir")
    build = BuildConfig(
        commands=raw_commands,
        workers=b.get("workers", DEFAULT_BUILD_WORKERS),
        max_retry_cycles=b.get("max_retry_cycles", DEFAULT_BUILD_MAX_RETRY_CYCLES),
        state_dir=build_state_dir,
    )

    h = data.get("harness", {})
    harness_knowledge_dir = resolve_path(h.get("knowledge_dir", DEFAULT_HARNESS_KNOWLEDGE_DIR), "harness.knowledge_dir")
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
