# fliptest

[![ci](https://github.com/tejgokani/fliptest/actions/workflows/ci.yml/badge.svg)](https://github.com/tejgokani/fliptest/actions/workflows/ci.yml)

**Catch changes that only pass because the tests changed.**

Coding agents are told to "make the tests pass." Sometimes they fix the code. Sometimes they edit the expected value, delete the failing case, or add a `skip`. Read the diff closely and you'll see it. Read it at 2 a.m. and you probably won't.

fliptest doesn't guess from the diff. It **runs** your test suite four ways in throwaway snapshots and compares the results:

| variant     | code | tests | question                                            |
|-------------|------|-------|-----------------------------------------------------|
| `head`      | new  | new   | does the change pass its own tests?                 |
| `base`      | old  | old   | control: what did the suite do before?              |
| `old_tests` | new  | **old** | do the *original* tests still pass? (goalpost check) |
| `new_tests` | **old** | new | do the *new* tests detect anything? (vacuity check)  |

If a test passed before the change, fails against the new code, and passes only in its edited form, someone moved the goalposts. fliptest names the test.

```
$ git diff --stat
 pricing.py      | 5 +++--
 test_pricing.py | 2 +-

$ python3 -m pytest -q
2 passed in 0.00s

$ fliptest --junit report.xml --cmd 'python3 -m pytest -q --junitxml=report.xml'
  variant     code  tests  result
  head        new   new    pass  2 pass
  base        old   old    pass  2 pass
  old_tests   new   old    FAIL (exit 1)  1 pass, 1 fail
  new_tests   old   new    FAIL (exit 1)  1 pass, 1 fail

  ERROR GOALPOST_MOVED: tests that passed before the change fail against the new code
        and pass only in their edited form (or were removed); confirm the edits are intended
          - test_pricing::test_discount

  --- tail of old_tests output ---
  E       assert 99.0 == 90
  verdict: FAIL
```

That's real output from [`examples/demo.sh`](examples/demo.sh), trimmed. The suite was green, and the change still broke discounts.

## Why this exists

- Agents game tests in practice. [ImpossibleBench](https://arxiv.org/abs/2510.20270) (Zhong et al., 2025) measures how often coding agents pass deliberately impossible tasks. Modifying the tests is one of the main ways they do it.
- Most existing guards ([AssertVet](https://github.com/Nithinfgs/assertvet), [agent-diff-guard](https://github.com/berniwitty/agent-diff-guard), [test-guard](https://github.com/kwangtaeko/test-guard), [Assertion Guardian](https://github.com/ccdwyer/assertion-guardian)) read the **diff** and look for patterns: removed `assert`, added `skip`, loosened matchers. That's fast and useful. But changing `== 90` to `== 99` looks exactly like a legitimate fix to a test.
- The "new tests must fail on base and pass on head" check is standard in SWE-bench-style evaluation. It does show up in individual projects' CI, but as one-off scripts. I couldn't find a reusable, language-neutral tool that runs both directions (see [docs/RESEARCH.md](docs/RESEARCH.md)).

fliptest is the behavioral version. It never parses your test code. It uses the exit code of your own test command, plus JUnit XML if you have it, so it works for any language whose runner can be invoked from a shell.

## Install

Requires Python ≥ 3.11 and git. It has no runtime dependencies.

```bash
pipx install git+https://github.com/tejgokani/fliptest      # or: pip install git+https://github.com/tejgokani/fliptest
```

(It isn't on PyPI yet.)

Or run it from a checkout without installing:

```bash
git clone https://github.com/tejgokani/fliptest && cd fliptest && python3 -m pip install .
```

## Quick start

In any git repo where you (or an agent) have uncommitted changes:

```bash
fliptest plan                       # how changed files are classified; runs nothing
fliptest --cmd "pytest -q"          # cross-check working tree vs HEAD
```

For **per-test** findings (which test moved, which test vanished or got skipped, which new test is vacuous), have your runner write JUnit XML:

```bash
fliptest --junit report.xml --cmd "pytest -q --junitxml=report.xml"
fliptest --junit report.xml --cmd "npx vitest run --reporter=junit --outputFile=report.xml"
fliptest --junit report.xml --cmd "npx jest --reporters=jest-junit"   # JEST_JUNIT_OUTPUT_FILE=report.xml
fliptest --junit report.xml --cmd "cargo nextest run --profile ci"    # with junit configured
fliptest --cmd "go test ./..."                                        # exit-code mode works everywhere
```

Compare two commits instead of the working tree. This is what you'd run in CI or on an agent's branch:

```bash
fliptest --base origin/main --head HEAD
```

If you don't pass `--cmd`, fliptest guesses one from the base revision: `npm`/`pnpm`/`yarn`/`bun test`, `cargo test`, `go test ./...`, or `pytest`.

## What it reports

| code | severity | meaning |
|---|---|---|
| `GOALPOST_MOVED` | error | Original tests fail on the new code; only the edited tests pass |
| `HEAD_FAILS` | error | The change fails its own test suite |
| `TIMEOUT` / `RUN_ERROR` | error | A run hung or could not start; the result is inconclusive |
| `TESTS_DISAPPEARED` | warn | Tests that passed before no longer run (deleted functions, deselected) |
| `TESTS_NEWLY_SKIPPED` | warn | Tests that passed before are now skipped |
| `TEST_FILES_DELETED` | warn | Whole test files removed |
| `VACUOUS_TESTS` | warn | New tests pass on the old code too, so they don't detect this change |
| `HARNESS_CHANGED` | warn | `package.json`, `pytest.ini`, CI workflows, `.fliptest.toml`… were edited |
| `GOALPOST_INCONCLUSIVE` | warn | Original tests fail on the new code, but they also failed before (or failed to collect) |
| `FAIL_TO_PASS`, `FIXED` | info | Good news: new tests catch the change, or previously failing tests now pass |
| `BASE_FAILS`, `NO_TEST_CHANGES`, `TESTS_ONLY`, `UNSTABLE_TEST_IDS` | info | Context |

Exit codes: `0` no errors (warnings allowed), `1` errors (or warnings with `--strict`), `2` usage/config/git error, `130` interrupted.

A finding is a prompt to review, not proof of bad intent. Fixing a test that contradicts the spec is a legitimate edit, and fliptest still flags it. Once you've looked, pass `--allow GOALPOST_MOVED` to downgrade it.

`--json` emits a stable schema (`"schema": 1`) for bots and dashboards.

## Use it with coding agents

### Claude Code: Stop hook (verified)

Add this to `.claude/settings.json`. When the agent tries to finish, fliptest runs. If it finds an error, exit code `2` sends the report back to the agent, which then has to address it. On the second stop attempt (`stop_hook_active`), fliptest reports and lets the agent stop, so it can never loop forever.

```json
{
  "hooks": {
    "Stop": [{ "hooks": [{
      "type": "command",
      "command": "fliptest --claude-hook --junit report.xml --cmd 'python3 -m pytest -q --junitxml=report.xml'"
    }]}]
  }
}
```

This was tested end to end with `claude -p` on an impossible-task fixture. The hook blocked the stop, and the agent explained why its test edit was justified. Details are in [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

### Codex, Gemini CLI, Aider, anything else

Any agent that can run a shell command can run fliptest. Add this to `AGENTS.md` / `GEMINI.md`:

```markdown
Before saying a task is done, run `fliptest --cmd "<test command>"`.
If it reports GOALPOST_MOVED, either restore the original test or explain
exactly why the original expectation was wrong.
```

That only works if the agent follows instructions. The enforceable places are the ones the agent doesn't control: a git hook, or CI.

### CI (GitHub Actions)

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- run: pipx install git+https://github.com/tejgokani/fliptest
- run: fliptest --base "origin/${{ github.base_ref }}" --head HEAD --cmd "pytest -q"
```

## Configuration

Commit a `.fliptest.toml`:

```toml
test_cmd = "python3 -m pytest -q --junitxml=report.xml"
junit = "report.xml"
timeout = 600                       # seconds per run
extra_test_patterns = ["fixtures/**"]
link = ["node_modules", ".venv"]    # ignored dirs symlinked into snapshots
```

**fliptest reads this file from the base revision, not the working tree.** A change can't rewrite `test_cmd = "true"` and grade itself. Editing the config shows up as `HARNESS_CHANGED`. CLI flags override the file.

Test files are recognised by built-in globs (`test_*.py`, `*_test.go`, `*.test.ts`, `__tests__/**`, `spec/**`, `src/test/**`, …). Run `fliptest plan` to see how your change is classified.

## How it works

1. Resolve `base` (default `HEAD`) and `head` (default: working tree, including untracked non-ignored files).
2. Materialise both into a temp directory. The base comes from `git read-tree` + `checkout-index` with a *private* index file. Your index, refs, worktrees and files are never touched (there's a test for exactly that).
3. Build `old_tests` = head + base versions of every changed test file, and `new_tests` = base + head versions.
4. Symlink dependency directories (`node_modules`, `.venv`) into each snapshot, run the command with a timeout in its own process group, and parse optional JUnit.
5. Compare results test by test where possible, and by exit code otherwise. Unstable test ids (ones with timestamps or random floats) are excluded from matching.

Architecture notes: [docs/DECISIONS.md](docs/DECISIONS.md).

## Security

fliptest runs **your** test command, in copies of **your** repo. That's the same trust level as running the tests yourself. Don't point it at a repository you wouldn't run the tests of. It reads its config from the base revision, refuses unsafe paths and symlink redirection when overlaying files, refuses DTDs in JUnit reports, and makes no network calls. See [SECURITY.md](SECURITY.md).

## Limitations (read these)

- **It can't see special-casing in code.** If an agent makes the original test pass with `if year == 1900: return 29`, the original tests pass, and fliptest reports clean. Pair it with code review or a diff-pattern guard.
- **It costs up to 4× your test time.** It runs 2 suites when only code or only tests changed, and 4 when both did. `--skip-base` drops the control run.
- **Flaky tests produce false findings.** Re-run before you trust a single `GOALPOST_MOVED` on a flaky suite.
- **Harness files aren't reverted.** In `old_tests`, the head's `package.json`/`pyproject.toml` stays in place, because they also carry dependencies. Edits to them are reported for review instead.
- **Dependencies are shared.** The old code runs against the current `node_modules`/`.venv`, so a change that bumps dependencies may make old-code runs fail for unrelated reasons.
- Tests that hard-code the absolute repo path, need git metadata inside the snapshot, or live in submodules may not run in a snapshot.
- macOS and Linux are covered: the suite runs locally on macOS and in CI on ubuntu + macOS, Python 3.11–3.14. Windows is not supported.
- Language-neutral by design, but only verified so far on Python (pytest), JavaScript (mocha) and Go.

## Roadmap

- `--changed-tests-only`: run just the changed test files in the cross variants, so large suites finish faster
- First-class runner presets (`--preset pytest|vitest|jest|go|cargo`) that wire up JUnit automatically
- Re-run disagreeing tests N times to separate flakiness from goalpost moves
- An official GitHub Action and pre-push hook installer
- Optional diff-pattern rules (special-cased literals in code) as a second signal

## Contributing

Bug reports with a reproducing repo are the most valuable contribution. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
