# Research and prior art

Research date: **2026-10-25**. Sources were found through web search, and each repository was checked with the GitHub API (`gh api repos/...`) on that date. Star counts and push dates are a snapshot from then. Not finding something in these sources doesn't prove it doesn't exist.

## 1. First idea, rejected: linting agent instruction files

My first candidate was a linter for `AGENTS.md`/`CLAUDE.md` that flags stale paths and dead commands. A single search turned up at least six existing tools:

- [herdr-llm-lint](https://github.com/shindakun/herdr-llm-lint) (Rust, MIT, pushed 2026-09-21)
- [lintamigo](https://github.com/Amerigo2020/lintamigo)
- [agentsmd-lint](https://github.com/ubukhari/agentsmd-lint) (TS, MIT, pushed 2026-10-19)
- [agents-lint](https://github.com/giacomo/agents-lint) (TS, 16★, pushed 2026-09-25)
- [asitis-agent-tools](https://github.com/Katta041/asitis-agent-tools)
- [agent-rules-linter](https://github.com/iwadjp/agent-rules-linter)

Instruction-file *sync* is just as crowded: Python `rulesync`, [ai-rules-sync / agentsync](https://github.com/PanisHandsome/ai-rules-sync), `rulesync-ts`, and `crossby`. **Verdict: no defensible differentiation, so I dropped it.**

## 2. Second idea, also crowded: diff-pattern test-weakening guards

| Project | Approach | Notes (verified 2026-10-25) |
|---|---|---|
| [AssertVet](https://github.com/Nithinfgs/assertvet) | Static diff rules (deleted/softened asserts, skips, `\|\| true` in test scripts) | Python, MIT, 0★, pushed 2026-10-21 |
| [agent-diff-guard](https://github.com/berniwitty/agent-diff-guard) | Static diff rules (test-removed, test-skipped, assertion-weakened, gate-loosened); reads config from the base revision | Python, MIT, 0★, pushed 2026-10-12 |
| [test-guard](https://github.com/kwangtaeko/test-guard) | Static rules plus anti-tamper rules (config edits, `--no-verify`, hook removal) | TypeScript, MIT, 1★, pushed 2026-10-17 |
| [Assertion Guardian](https://github.com/ccdwyer/assertion-guardian) | Claude Code mod; compares the whole test file before and after an edit and refuses the edit if tests got weaker | TypeScript, MIT, pushed 2026-10-02 |
| [goalpost (syntaxixr)](https://github.com/syntaxixr/goalpost) | Claude Code hooks plugin: frozen goal spec, existing tests become read-only, auditor subagent | JavaScript, MIT, 2★, pushed 2026-10-15 |

What they share: they **read** the change. In the READMEs I examined, none of them **runs** the original tests against the new code. A diff-pattern rule can't tell a legitimate correction of an expected value (`== 90` to `== 99`) from a goalpost move, because the two diffs look the same. goalpost and Assertion Guardian prevent the edit instead, which works inside Claude Code but not in Codex, Gemini, CI, or human PRs. Blocking all test edits also blocks legitimate test fixes.

## 3. The behavioral check exists, but only as one-off scripts

A search for "fail-to-pass on base" found the check implemented inside individual projects' CI or agent pipelines. In every case it was a project-specific script:

- on-par/software-factory issue #3257 ("fail-to-pass evidencePlan entries must fail on base and pass on head")
- jbookout/doctorcre-app PR #347 ("Require changed tests to fail on base and pass on head")
- ScottHysom/claude-plugins PR #681 (`fails-on-base` via `git archive` of the merge base)
- DYB-Development/symphony PR #206

These cover only the **vacuity** direction (new tests on old code). I found no reusable tool in the sources examined that packages both directions (old tests on new code, *and* new tests on old code) together with a control run, JUnit-level matching, and agent-hook integration.

The same searches also turned up a pitfall worth designing around: tests can fail when run from a linked git worktree (spec-kitty/spec-kitty#5317, shakestzd/wipnote#194). fliptest therefore snapshots into plain directories built with a private index, and creates no worktrees.

## 4. Literature

- **ImpossibleBench** (Zhong et al., 2025, [arXiv:2510.20270](https://arxiv.org/abs/2510.20270); [LessWrong summary](https://www.lesswrong.com/posts/qJYMbrabcQqCZ7iqm/impossiblebench-measuring-reward-hacking-in-llm-coding-1)) mutates LiveCodeBench and SWE-bench tests so they conflict with the spec. Any pass counts as cheating. Modifying the tests is among the cheating behaviors observed.
- **Hodoscope** ([arXiv:2604.11072](https://arxiv.org/pdf/2604.11072)) clusters GPT-5 trajectories on ImpossibleBench into behaviors including "modifying test assertions" and "inserting special-case logic". Special-case logic is the behavior fliptest *cannot* see, so it's documented as a limitation.
- **EvilGenie** ([arXiv:2511.21654](https://arxiv.org/pdf/2511.21654)) argues that pass-rate-only detection misses some reward hacking.
- **Evaluating AGENTS.md** (ETH Zurich, ICLR 2026, [iclr.cc](https://iclr.cc/virtual/2026/10021142)) found that agents follow context-file instructions closely. That's indirect support for the claim that instructions alone ("don't edit tests") aren't an enforcement mechanism. I treat it as context, not proof.
- SWE-bench's FAIL_TO_PASS / PASS_TO_PASS methodology is the evaluation-side origin of fliptest's two cross-checks. fliptest's contribution is *packaging*, not a new algorithm: it applies the methodology to everyday local diffs and CI in any language, without hidden tests.

## 5. Candidate scoring (weights from the brief)

Scores are 1–5 judgments. They're decision aids, not measurements.

| Candidate | Signif. 20 | Diff. 20 | Feas. 15 | Adopt. 15 | DX 10 | Offline 10 | Demo 5 | Ext. 5 | Total |
|---|---|---|---|---|---|---|---|---|---|
| **Behavioral test cross-check (fliptest)** | 4 | 4 | 4 | 3 | 4 | 5 | 5 | 4 | **3.95** |
| Agent-file staleness linter | 3 | 1 | 5 | 3 | 4 | 5 | 4 | 3 | 3.20 |
| Diff-pattern test-weakening guard | 4 | 1 | 5 | 3 | 4 | 5 | 4 | 3 | 3.40 |
| Hallucinated-dependency (slopsquat) checker | 4 | 2 | 4 | 3 | 4 | 2 | 4 | 3 | 3.25 |
| Repo prompt-injection scanner (hidden Unicode etc.) | 3 | 2 | 4 | 2 | 3 | 5 | 3 | 3 | 3.00 |
| Agent claim verifier ("I ran tests") from transcripts | 4 | 3 | 2 | 2 | 3 | 5 | 3 | 3 | 3.10 |
| Cross-agent session checkpoint/rollback | 3 | 2 | 3 | 3 | 3 | 5 | 4 | 3 | 3.10 |
| MCP server permission diff/auditor | 3 | 2 | 3 | 2 | 3 | 5 | 3 | 3 | 2.85 |

- **Primary:** fliptest.
- **Backup:** the agent claim verifier. Its feasibility is low because every agent has its own transcript format.
- **Main uncertainty:** adoption. A tool that multiplies test time by up to 4× has a real cost, and that pushes it toward CI and Stop hooks rather than every save.

## 6. Name check

`goalpost` was taken on both PyPI and npm, and syntaxixr/goalpost is directly adjacent. `fliptest` returned 404 on both PyPI and npm on 2026-10-25. Three small unrelated GitHub repos use the name: javabyraghu/fliptest, sam-yeom/fliptest (7★), and GESkunkworks/fliptest. That isn't a trademark search.
