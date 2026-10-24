# Status and plan

Updated 2026-10-25.

## Plan / task states

| Task | State |
|---|---|
| Environment inspection | VERIFIED: macOS arm64; python 3.9–3.14, node 22, go 1.26, rust 1.93; gh authenticated as tejgokani |
| Prior-art research (agent-file linters, diff guards, fail-to-pass scripts, literature) | COMPLETE (docs/RESEARCH.md) |
| Candidate scoring and selection | COMPLETE |
| Thesis + acceptance criteria | COMPLETE (docs/DECISIONS.md) |
| Core: snapshots, four variants, judge, CLI, JSON | VERIFIED (67 tests) |
| JUnit per-test analysis | VERIFIED (pytest, mocha) |
| Adversarial testing + fixes | VERIFIED (5 bugs found and fixed, each with a regression test) |
| Real repos (is-number, google/uuid) | VERIFIED |
| Real agent (Claude Code, incl. Stop hook) | VERIFIED (4 runs, one fixture) |
| Codex / Gemini runs | BLOCKED (Codex blocked by local permission policy) / NOT STARTED |
| Clean install from wheel | VERIFIED (py3.12 venv) |
| Docs, CI config, templates, launch package | COMPLETE |
| Hosted CI run | Pending the push. See the final report |
| PyPI publication | NOT STARTED, deliberately. Needs the maintainer's PyPI account; install from git works meanwhile |

## Next command

```bash
cd ~/Desktop/fliptest && .venv/bin/python -m pytest -q
```
