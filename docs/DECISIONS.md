# Decisions

## Product thesis

- **Name:** fliptest
- **One line:** Catch changes that pass only because the tests changed. It runs the old tests on the new code and the new tests on the old code.
- **User:** Developers who review coding-agent output, whether locally, in a Stop hook, or in CI. Maintainers who review AI-assisted PRs.
- **Existing workflow:** Read the diff, or rely on a diff-pattern linter. Both fail when an edit is semantically a goalpost move but syntactically an ordinary edit.
- **Contribution:** A packaged, language-neutral, behavioral version of SWE-bench's FAIL_TO_PASS / PASS_TO_PASS checks for everyday diffs. The algorithm isn't new; the packaging and integration are.
- **Won't do:** Judge intent. Parse test source. Use an LLM. Phone home. Block edits inside an agent (other tools prevent edits; fliptest verifies).
- **Smallest proof:** `examples/demo.sh`. A green suite and a broken change; fliptest names the moved test.

## Acceptance criteria (written before the core; status in TEST_REPORT.md)

1. Installs from a wheel into a clean venv, with no runtime deps, and runs the demo.
2. Detects an edited expected value (GOALPOST_MOVED) with and without JUnit.
3. Detects deleted test files, deleted test functions, newly skipped tests, and vacuous new tests.
4. Does not flag an honest fix that adds a fail-to-pass test.
5. Never modifies the user's repository: index, refs, worktrees, files, mtimes.
6. Cleans up temp dirs and kills child process groups on timeout, SIGINT, and SIGTERM.
7. Controlled exit 2 with no traceback for: not a repo, bad ref, no commits, bad config, unsafe paths.
8. Can't be graded by its own target: config is read from the base revision.
9. Works with at least one real agent workflow end to end (Claude Code Stop hook).
10. Works on at least one non-Python repo.

## Architecture choices

- **Python stdlib, ≥3.11.** I wanted zero install friction and `tomllib`. A Rust binary would start faster, but startup cost is noise next to running a test suite four times.
- **Snapshots via a private `GIT_INDEX_FILE` + `checkout-index`, not `git worktree` or `git archive`.** `git archive` honours `export-ignore`, which some repos (e.g. PHP packages) set on their tests. Worktrees register state in `.git` and are known to break some suites. A private index leaves no trace, even if the process is killed with SIGKILL.
- **Working-tree snapshot = `git ls-files -c -o --exclude-standard`.** Agents usually leave uncommitted changes, so the default `head` is the working tree, untracked files included.
- **Full copies per variant, not hardlinks.** Tests that write to their own files must not corrupt sibling variants. The cost is disk, and it's temporary.
- **Dependency dirs are symlinked** (`node_modules`, `.venv`). Copying them would be slow; omitting them would break every JS project. The trade-off (shared deps, writes reach the real dir) is documented.
- **Exit code first, JUnit optional.** Exit codes work for every runner, and JUnit XML is the closest thing to a universal per-test format. I didn't write a per-framework parser.
- **Harness files are reported, not reverted.** Reverting `package.json` in `old_tests` would also revert dependencies and scripts the new code needs. HARNESS_CHANGED puts the decision in front of a human.
- **Config read from base.** [agent-diff-guard](https://github.com/berniwitty/agent-diff-guard) independently made the same choice for the same reason.
- **Severity design.** Errors are things a reviewer must look at (moved goalposts, failing head, inconclusive runs). Warnings are suspicious but common in legitimate work (vacuous tests in refactors, deleted tests). Plain-English messages avoid implying intent, because real agent runs showed that legitimate test corrections also trigger GOALPOST_MOVED. `--allow CODE` records "reviewed".
- **Claude Code hook loops at most once.** After one block (`stop_hook_active`), fliptest reports and allows the stop. An infinite block loop is worse than a missed enforcement.

## Changes driven by testing (see TEST_REPORT.md)

- Run-dependent test ids (Math.random(), timestamps) caused false findings on jonschlinkert/is-number. Such ids are now excluded from cross-run matching and listed as UNSTABLE_TEST_IDS.
- Root-level `test.js` / `tests.py` weren't classified as tests. I added patterns.
- A failing base is normal for bug-fix tasks. BASE_FAILS was downgraded to info, and I added FIXED.
- `fliptest -C dir plan` wasn't recognised as the plan subcommand, so the subcommand is now found anywhere in argv.
- A new test that can't import on the old code is missing from the JUnit report rather than failing. It now counts as fail-to-pass.
