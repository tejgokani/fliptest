"""Build the four snapshot variants, run the suite in each, and judge the results.

    variant      code   tests   question it answers
    -----------  -----  ------  ---------------------------------------------
    base         old    old     control: was the suite green before?
    head         new    new     does the change pass its own tests?
    old_tests    new    old     do the *original* tests still pass?  (goalpost)
    new_tests    old    new     do the new tests detect the change?  (vacuity)
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import classify, gitops, junit
from .config import Config
from .runner import RunResult, run_command

VARIANTS = ("head", "base", "old_tests", "new_tests")


@dataclass
class Plan:
    repo: Path
    base: str
    head: str  # sha or gitops.WORKTREE
    changes: list[gitops.Change]
    test_changes: list[gitops.Change]
    code_changes: list[gitops.Change]
    harness_changes: list[gitops.Change]

    @property
    def head_label(self) -> str:
        return "working tree" if self.head == gitops.WORKTREE else self.head[:12]


@dataclass
class Finding:
    code: str
    severity: str  # error | warn | info
    message: str
    items: list[str] = field(default_factory=list)


@dataclass
class Outcome:
    plan: Plan
    runs: dict[str, RunResult]
    findings: list[Finding]
    workdir: str | None = None

    @property
    def worst(self) -> str:
        sev = {f.severity for f in self.findings}
        return "error" if "error" in sev else "warn" if "warn" in sev else "ok"


def make_plan(repo: Path, base_ref: str, head_ref: str | None, cfg: Config) -> Plan:
    base = gitops.resolve_commit(repo, base_ref)
    head = gitops.WORKTREE if head_ref is None else gitops.resolve_commit(repo, head_ref)
    changes = gitops.changed_files(repo, base, head)
    tests, code, harness = [], [], []
    for ch in changes:
        if classify.is_test(ch.path, cfg.test_patterns):
            tests.append(ch)
        else:
            code.append(ch)
            if classify.is_harness(ch.path, cfg.harness_patterns):
                harness.append(ch)
    return Plan(repo, base, head, changes, tests, code, harness)


def execute(plan: Plan, cfg: Config, keep: bool = False, progress=None) -> Outcome:
    say = progress or (lambda msg: None)
    workdir = Path(tempfile.mkdtemp(prefix="fliptest-"))
    try:
        trees = _build_trees(plan, cfg, workdir, say)
        runs: dict[str, RunResult] = {}
        for variant in VARIANTS:
            if variant not in trees:
                continue
            tree = trees[variant]
            say(f"running {variant} ({_describe(variant)})")
            res = run_command(cfg.test_cmd, tree, variant, cfg.timeout, workdir / "logs" / f"{variant}.log")
            if cfg.junit:
                _attach_junit(res, tree / cfg.junit)
            runs[variant] = res
            say(f"  {variant}: {_status(res)} in {res.duration:.1f}s")
        findings = judge(plan, runs)
        return Outcome(plan, runs, findings, str(workdir) if keep else None)
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)


def _describe(variant: str) -> str:
    return {
        "head": "new code, new tests",
        "base": "old code, old tests",
        "old_tests": "new code, old tests",
        "new_tests": "old code, new tests",
    }[variant]


def _status(res: RunResult) -> str:
    if res.timed_out:
        return "TIMEOUT"
    if res.exit_code is None:
        return "ERROR"
    return "pass" if res.passed else f"fail (exit {res.exit_code})"


def _build_trees(plan: Plan, cfg: Config, workdir: Path, say) -> dict[str, Path]:
    trees: dict[str, Path] = {}
    say(f"snapshotting base {plan.base[:12]}")
    base = workdir / "base"
    gitops.materialize_commit(plan.repo, plan.base, base)
    say(f"snapshotting head ({plan.head_label})")
    head = workdir / "head"
    if plan.head == gitops.WORKTREE:
        gitops.materialize_worktree(plan.repo, head)
    else:
        gitops.materialize_commit(plan.repo, plan.head, head)
    trees["head"] = head
    if not cfg.skip_base:
        trees["base"] = base

    # Cross variants only make sense when both tests and code changed. With no
    # test changes, old_tests == head; with no code changes, new_tests == head.
    if plan.test_changes and plan.code_changes:
        old_tests = workdir / "old_tests"
        _copy_tree(head, old_tests)
        new_tests = workdir / "new_tests"
        _copy_tree(base, new_tests)
        for ch in plan.test_changes:
            # old_tests: head code with the base version of every changed test.
            if ch.status == "A":
                gitops.remove_entry(old_tests, ch.path)
            else:
                gitops.copy_entry(base / ch.path, old_tests / ch.path, old_tests)
            # new_tests: base code with the head version of every changed test.
            if ch.status == "D":
                gitops.remove_entry(new_tests, ch.path)
            else:
                gitops.copy_entry(head / ch.path, new_tests / ch.path, new_tests)
        trees["old_tests"] = old_tests
        trees["new_tests"] = new_tests

    for tree in trees.values():
        if cfg.junit:
            gitops.remove_entry(tree, cfg.junit)  # never read a stale, committed report
        _link_deps(plan.repo, tree, cfg.link)
    return trees


def _copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, symlinks=True)


def _link_deps(repo: Path, tree: Path, names: list[str]) -> None:
    """Symlink ignored dependency dirs (node_modules, .venv) into a snapshot."""
    for name in names:
        rel = gitops.safe_relpath(name)
        src = repo / rel
        dst = tree / rel
        if not src.exists() or os.path.lexists(dst):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(src.resolve(), dst)


def _attach_junit(res: RunResult, path: Path) -> None:
    try:
        res.tests = junit.parse(path)
    except junit.JUnitError as exc:
        res.junit_error = str(exc)


def judge(plan: Plan, runs: dict[str, RunResult]) -> list[Finding]:
    f: list[Finding] = []
    head = runs["head"]
    base = runs.get("base")
    cross = bool(plan.test_changes and plan.code_changes)

    for name, res in runs.items():
        if res.timed_out:
            f.append(Finding("TIMEOUT", "error", f"{name} run timed out; result is inconclusive"))
        elif res.exit_code is None:
            f.append(Finding("RUN_ERROR", "error", f"{name} run could not start: {res.error}"))
        if res.junit_error and name in ("head", "base", "old_tests", "new_tests"):
            msg = f"{name}: {res.junit_error}"
            if not any(x.message == msg for x in f):
                f.append(Finding("JUNIT_UNREADABLE", "warn", msg + "; falling back to exit codes"))

    if not plan.changes:
        f.append(Finding("NO_CHANGES", "info", "no differences between base and head"))
        return f

    if not head.passed and head.exit_code is not None:
        f.append(Finding("HEAD_FAILS", "error", "the test suite fails on the change itself"))

    if base is not None and not base.passed and base.exit_code is not None:
        f.append(Finding(
            "BASE_FAILS", "warn",
            "the suite already failed before the change; cross-checks are less reliable",
        ))

    deleted = [c.path for c in plan.test_changes if c.status == "D"]
    if deleted:
        f.append(Finding("TEST_FILES_DELETED", "warn", "test files were deleted", deleted))

    if plan.harness_changes:
        f.append(Finding(
            "HARNESS_CHANGED", "warn",
            "files that control how tests run were changed; review them by hand",
            [c.path for c in plan.harness_changes],
        ))

    if not plan.test_changes and plan.code_changes:
        f.append(Finding(
            "NO_TEST_CHANGES", "info",
            "code changed but no tests did; only head and base were compared",
        ))
    if plan.test_changes and not plan.code_changes:
        f.append(Finding("TESTS_ONLY", "info", "only tests changed; cross-checks skipped"))

    old = runs.get("old_tests")
    new = runs.get("new_tests")

    # --- goalpost: original tests vs new code -------------------------------
    if cross and old is not None and old.exit_code is not None and not old.timed_out:
        moved = _per_test_regressions(base, old) if (base and base.tests and old.tests) else None
        if moved:
            f.append(Finding(
                "GOALPOST_MOVED", "error",
                "tests that passed before the change fail against the new code; "
                "the change only passes because these tests were edited or removed",
                moved,
            ))
        elif moved == [] and not old.passed and head.passed:
            f.append(Finding(
                "GOALPOST_INCONCLUSIVE", "warn",
                "the original suite exits non-zero against the new code, but no "
                "individual test regression appears in the JUnit report "
                "(collection or import error?)",
            ))
        elif moved is None and not old.passed and head.passed:
            if base is None or base.passed:
                f.append(Finding(
                    "GOALPOST_MOVED", "error",
                    "the original test suite fails against the new code, but the "
                    "edited suite passes; the change only passes because tests were edited",
                ))
            else:
                f.append(Finding(
                    "GOALPOST_INCONCLUSIVE", "warn",
                    "the original tests fail against the new code, but they also "
                    "failed before the change",
                ))

    # --- tests that vanished or were skipped (needs per-test data) ----------
    if base is not None and base.tests and head.tests:
        gone = sorted(t for t, o in base.tests.items() if o == "pass" and t not in head.tests)
        if gone:
            f.append(Finding("TESTS_DISAPPEARED", "warn",
                             "tests that passed before no longer run at all", gone))
        skipped = sorted(t for t, o in base.tests.items()
                         if o == "pass" and head.tests.get(t) == "skip")
        if skipped:
            f.append(Finding("TESTS_NEWLY_SKIPPED", "warn",
                             "tests that passed before are now skipped", skipped))

    # --- vacuity: new tests vs old code -------------------------------------
    if cross and new is not None and new.exit_code is not None and not new.timed_out:
        if new.tests and head.tests:
            known = set(base.tests) if (base and base.tests) else set()
            added = [t for t in head.tests if t not in known and head.tests[t] == "pass"]
            vacuous = sorted(t for t in added if new.tests.get(t) == "pass")
            # A test absent from a failing run usually could not be collected
            # (e.g. it imports a name the old code lacks): that counts as failing.
            caught = sorted(t for t in added if new.tests.get(t) in ("fail", "error")
                            or (t not in new.tests and not new.passed))
            if vacuous:
                f.append(Finding(
                    "VACUOUS_TESTS", "warn",
                    "new tests also pass on the old code, so they do not detect this change",
                    vacuous,
                ))
            if caught:
                f.append(Finding("FAIL_TO_PASS", "info",
                                 "new tests fail on the old code and pass on the new code", caught))
        elif new.passed and head.passed:
            f.append(Finding(
                "VACUOUS_TESTS", "warn",
                "the edited test suite also passes on the old code, so the test "
                "changes do not detect this change",
            ))
        elif not new.passed and head.passed:
            f.append(Finding("FAIL_TO_PASS", "info",
                             "the edited tests fail on the old code and pass on the new code"))
    return f


def _per_test_regressions(base: RunResult, old: RunResult) -> list[str] | None:
    """Tests green at base that are red (or missing) when old tests meet new code.

    Returns None when per-test data cannot answer the question.
    """
    if base.tests is None or old.tests is None:
        return None
    return sorted(
        t for t, o in base.tests.items()
        if o == "pass" and old.tests.get(t, "missing") in ("fail", "error", "missing")
    )
