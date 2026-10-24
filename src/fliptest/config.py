"""Configuration: CLI flags over `.fliptest.toml` read from the BASE revision.

The config file is deliberately read from the base commit, not the working
tree. Otherwise the change under review could rewrite `test_cmd = "true"` and
grade itself; fliptest reports an edited config as HARNESS_CHANGED instead.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import classify, gitops

CONFIG_NAME = ".fliptest.toml"
DEFAULT_LINKS = ["node_modules", ".venv", "venv"]


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    test_cmd: str = ""
    test_patterns: list[str] = field(default_factory=lambda: list(classify.DEFAULT_TEST_PATTERNS))
    harness_patterns: list[str] = field(default_factory=lambda: list(classify.DEFAULT_HARNESS_PATTERNS))
    junit: str | None = None
    timeout: float = 900.0
    link: list[str] = field(default_factory=lambda: list(DEFAULT_LINKS))
    skip_base: bool = False
    detected_cmd: bool = False
    source: str = "defaults"


def _str_list(value, key: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{CONFIG_NAME}: '{key}' must be a list of non-empty strings")
    return value


def load(repo: Path, base_sha: str) -> Config:
    cfg = Config()
    blob = gitops.show_file(repo, base_sha, CONFIG_NAME)
    if blob is None:
        return cfg
    try:
        data = tomllib.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{CONFIG_NAME} at base is not valid TOML: {exc}") from exc
    cfg.source = f"{CONFIG_NAME} @ {base_sha[:12]}"
    known = {"test_cmd", "test_patterns", "extra_test_patterns", "harness_patterns",
             "junit", "timeout", "link"}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"{CONFIG_NAME}: unknown keys: {', '.join(sorted(unknown))}")
    if "test_cmd" in data:
        if not isinstance(data["test_cmd"], str) or not data["test_cmd"].strip():
            raise ConfigError(f"{CONFIG_NAME}: 'test_cmd' must be a non-empty string")
        cfg.test_cmd = data["test_cmd"]
    if "test_patterns" in data:
        cfg.test_patterns = _str_list(data["test_patterns"], "test_patterns")
    if "extra_test_patterns" in data:
        cfg.test_patterns += _str_list(data["extra_test_patterns"], "extra_test_patterns")
    if "harness_patterns" in data:
        cfg.harness_patterns = _str_list(data["harness_patterns"], "harness_patterns")
    if "junit" in data:
        if not isinstance(data["junit"], str):
            raise ConfigError(f"{CONFIG_NAME}: 'junit' must be a string path")
        cfg.junit = validate_junit_path(data["junit"])
    if "timeout" in data:
        t = data["timeout"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t <= 0:
            raise ConfigError(f"{CONFIG_NAME}: 'timeout' must be a positive number of seconds")
        cfg.timeout = float(t)
    if "link" in data:
        cfg.link = [validate_link(x) for x in _str_list(data["link"], "link")]
    return cfg


def validate_junit_path(p: str) -> str:
    try:
        return gitops.safe_relpath(p)
    except gitops.GitError as exc:
        raise ConfigError(f"junit path must be relative to the repo root: {p!r}") from exc


def validate_link(p: str) -> str:
    try:
        return gitops.safe_relpath(p)
    except gitops.GitError as exc:
        raise ConfigError(f"link path must be relative to the repo root: {p!r}") from exc


def detect_test_cmd(repo: Path, base_sha: str) -> str | None:
    """Guess a test command from files at the base revision."""
    pkg = gitops.show_file(repo, base_sha, "package.json")
    if pkg is not None:
        try:
            scripts = json.loads(pkg).get("scripts", {})
        except (ValueError, AttributeError):
            scripts = {}
        if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
            for lock, runner in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                                 ("bun.lockb", "bun"), ("bun.lock", "bun")):
                if gitops.show_file(repo, base_sha, lock) is not None:
                    return f"{runner} test"
            return "npm test"
    if gitops.show_file(repo, base_sha, "Cargo.toml") is not None:
        return "cargo test"
    if gitops.show_file(repo, base_sha, "go.mod") is not None:
        return "go test ./..."
    for marker in ("pytest.ini", "conftest.py", "pyproject.toml", "setup.py", "tox.ini"):
        if gitops.show_file(repo, base_sha, marker) is not None:
            for venv in (".venv", "venv"):
                if (repo / venv / "bin" / "python").exists():
                    return f"{venv}/bin/python -m pytest -q"
            return "python3 -m pytest -q"
    return None
