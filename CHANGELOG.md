# Changelog

## 0.1.0 (unreleased)

First release.

- Four-way cross-check (`head`, `base`, `old_tests`, `new_tests`) in isolated snapshots
- Findings: `GOALPOST_MOVED`, `HEAD_FAILS`, `TESTS_DISAPPEARED`, `TESTS_NEWLY_SKIPPED`,
  `TEST_FILES_DELETED`, `VACUOUS_TESTS`, `HARNESS_CHANGED`, `FAIL_TO_PASS`, `FIXED`, and more
- Optional per-test analysis via JUnit XML; exit-code mode for everything else
- `.fliptest.toml` read from the base revision
- `fliptest plan`, `--json`, `--strict`, `--allow`, `--keep`, `--claude-hook`
- Test-command auto-detection for npm/pnpm/yarn/bun, cargo, go, pytest
