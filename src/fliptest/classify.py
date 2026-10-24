"""Decide which changed files are tests, which are test harness, which are code."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath

# Files whose *content* is a test. Overlaying base<->head versions of these is
# the whole point of fliptest. Matched against the full posix path and the
# basename.
DEFAULT_TEST_PATTERNS = [
    # python
    "test_*.py", "*_test.py", "tests/**", "test/**", "conftest.py",
    # js / ts
    "*.test.*", "*.spec.*", "__tests__/**", "__snapshots__/**", "*.snap",
    # go, rust, ruby, java/kotlin, php, elixir, c#
    "*_test.go", "testdata/**", "spec/**", "*_spec.rb", "src/test/**",
    "*Test.java", "*Tests.java", "*Test.kt", "*Test.php", "*_test.exs", "*Tests.cs",
]

# Files that change *how* tests are run. Editing them can make a suite pass
# without fixing anything, and fliptest cannot safely revert them (they also
# carry dependencies and build settings), so changes are reported for review.
DEFAULT_HARNESS_PATTERNS = [
    "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "noxfile.py",
    "package.json", "jest.config.*", "vitest.config.*", "vite.config.*",
    ".mocharc*", "karma.conf.*", "playwright.config.*", "babel.config.*",
    "Makefile", "justfile", "Cargo.toml", "go.mod", ".fliptest.toml",
    ".github/workflows/**", ".gitlab-ci.yml", ".coveragerc", "codecov.yml",
]


def _match(path: str, pattern: str) -> bool:
    p = PurePosixPath(path)
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        # "tests/**" matches tests/ at any depth: tests/x.py, pkg/tests/x.py
        parts = p.parts[:-1]
        if "/" in prefix:
            return path.startswith(prefix + "/") or f"/{prefix}/" in f"/{path}"
        return prefix in parts
    if "/" in pattern:
        return fnmatchcase(path, pattern)
    return fnmatchcase(p.name, pattern)


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(_match(path, pat) for pat in patterns)


def is_test(path: str, patterns: list[str] | None = None) -> bool:
    return matches_any(path, patterns if patterns is not None else DEFAULT_TEST_PATTERNS)


def is_harness(path: str, patterns: list[str] | None = None) -> bool:
    return matches_any(path, patterns if patterns is not None else DEFAULT_HARNESS_PATTERNS)
