# Launch package

## Repository metadata

- **Description:** Catch changes that only pass because the tests changed: runs old tests on new code and new tests on old code. Language-neutral, works with any coding agent or CI.
- **Topics:** `testing`, `git`, `coding-agents`, `claude-code`, `codex`, `reward-hacking`, `code-review`, `ci`, `developer-tools`, `python`

## Announcement draft (Show HN / dev.to)

> **Show HN: fliptest – run your old tests against the new code to catch moved goalposts**
>
> When a coding agent says "all tests pass," there are two ways that can be true. It fixed the code, or it changed the tests. The second can be legitimate (the test was wrong) or not (it edited `== 90` to `== 99`). From the diff alone, the two look identical.
>
> The tools I found for this read the diff. They look for removed asserts, added skips, and loosened matchers. fliptest takes the SWE-bench approach instead and runs your test command four ways in throwaway snapshots:
>
> - new code + new tests
> - old code + old tests (the control)
> - new code + **old** tests: if these fail, the goalposts moved
> - old code + **new** tests: if these pass, the new tests are vacuous
>
> It never parses test code. It uses your test command's exit code, plus JUnit XML when available for per-test results. So it works for pytest, mocha, and go test today, and should work for anything else you can run from a shell. Your repo is never modified (it uses a private git index, not worktrees). Config is read from the base commit, so a change can't rewrite the test command and grade itself.
>
> It ships with a Claude Code Stop hook. I tested it on a fixture where a test contradicts the spec. The agent fixed the test, the hook blocked the stop with the finding, and the agent had to justify the edit before finishing.
>
> Limits, up front: it costs up to 4× your test time. It can't see special-cased code (`if x == 1900: return 29`). Flaky tests cause false findings.
>
> MIT, zero dependencies, Python ≥ 3.11. Feedback I'd love: repos where it's wrong.

## Key design decision, short version

The goalpost check runs the old tests on the new code. That puts the burden of proof on the change: either the original tests still pass, or a human confirms the new expectations. A diff linter has to guess intent from syntax. fliptest asks the original tests directly.

## Demo script (terminal recording, about 40 seconds)

```bash
examples/demo.sh
```

1. `git diff --stat`: two files changed.
2. `pytest -q`: `2 passed`. The suite is green.
3. `fliptest ...`: the four-row table appears, the `old_tests` row is red, and GOALPOST_MOVED names `test_pricing::test_discount`.
4. The output tail shows `assert 99.0 == 90`: the original expectation, failing against the new code.

## Where to share (relevant + permitted)

- Show HN (self-posted tools are allowed under Show HN rules)
- r/ClaudeAI and r/ChatGPTCoding (both allow tool posts; check current sidebar rules first)
- dev.to post: "Your agent's tests pass. Do the *old* tests?"
- Claude Code community hooks lists, as a Stop-hook recipe

No vote solicitation, no sock puppets.

## Good first issues

1. **Runner presets.** Add `--preset pytest|vitest|jest|go` to wire JUnit flags automatically. Touches `cli.py` and `config.py`.
2. **Verify and document the jest-junit and vitest recipes** on a real repo. Add a scenario script under `examples/`.
3. **`--changed-tests-only`.** In the cross variants, run only the changed test files (requires a per-runner file-argument template).
4. **Flake retry.** Re-run disagreeing tests N times before reporting GOALPOST_MOVED.
5. **GitHub Action wrapper** (`action.yml`) with JSON-to-annotations output.
6. **Windows support.** Process groups (`CREATE_NEW_PROCESS_GROUP`) and symlink fallbacks.
7. **Markdown report format** (`--format md`) for PR comments.
