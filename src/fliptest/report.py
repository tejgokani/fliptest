"""Human and JSON renderings of an Outcome."""

from __future__ import annotations

import json
import os
import sys

from .engine import Outcome, Plan
from .runner import RunResult

SCHEMA_VERSION = 1
MAX_ITEMS = 20


def _color_enabled(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class _Style:
    def __init__(self, on: bool):
        self.on = on

    def _w(self, code: str, s: str) -> str:
        return f"\x1b[{code}m{s}\x1b[0m" if self.on else s

    def red(self, s): return self._w("31;1", s)
    def yellow(self, s): return self._w("33;1", s)
    def green(self, s): return self._w("32;1", s)
    def dim(self, s): return self._w("2", s)
    def bold(self, s): return self._w("1", s)


def _run_cell(res: RunResult | None, st: _Style) -> str:
    if res is None:
        return st.dim("skipped")
    if res.timed_out:
        return st.red("TIMEOUT")
    if res.exit_code is None:
        return st.red("ERROR")
    label = "pass" if res.passed else f"FAIL (exit {res.exit_code})"
    if res.tests is not None:
        counts = {}
        for o in res.tests.values():
            counts[o] = counts.get(o, 0) + 1
        label += "  " + ", ".join(f"{counts[k]} {k}" for k in ("pass", "fail", "error", "skip") if k in counts)
    return st.green(label) if res.passed else st.red(label)


def render_plan(plan: Plan, test_cmd: str, stream=sys.stdout) -> str:
    st = _Style(_color_enabled(stream))
    lines = [
        st.bold("fliptest plan"),
        f"  base  {plan.base[:12]}",
        f"  head  {plan.head_label}",
        f"  cmd   {test_cmd or st.dim('(none)')}",
        "",
    ]
    def group(title, items):
        lines.append(f"  {title} ({len(items)})")
        for c in items[:50]:
            lines.append(f"    {c.status} {c.path}")
        if len(items) > 50:
            lines.append(st.dim(f"    ... {len(items) - 50} more"))
    group("test files", plan.test_changes)
    group("code files", plan.code_changes)
    if plan.harness_changes:
        group("harness files (reported, not reverted)", plan.harness_changes)
    lines.append("")
    if plan.test_changes and plan.code_changes:
        lines.append("  will run: head, base, old_tests (new code + old tests), new_tests (old code + new tests)")
    else:
        lines.append("  will run: head, base (cross-checks need both test and code changes)")
    return "\n".join(lines)


def render_text(out: Outcome, test_cmd: str, stream=sys.stdout, verbose: bool = False) -> str:
    st = _Style(_color_enabled(stream))
    p = out.plan
    lines = [
        st.bold("fliptest") + st.dim(f"  base {p.base[:12]} -> head {p.head_label}"),
        st.dim(f"  cmd: {test_cmd}"),
        st.dim(f"  {len(p.test_changes)} test file(s), {len(p.code_changes)} code file(s) changed"),
        "",
        "  variant     code  tests  result",
    ]
    rows = [("head", "new", "new"), ("base", "old", "old"),
            ("old_tests", "new", "old"), ("new_tests", "old", "new")]
    for name, code, tests in rows:
        lines.append(f"  {name:<10}  {code:<4}  {tests:<5}  {_run_cell(out.runs.get(name), st)}")
    lines.append("")
    if not out.findings:
        lines.append(st.green("  no findings"))
    for fd in out.findings:
        tag = {"error": st.red("ERROR"), "warn": st.yellow("WARN "), "info": st.dim("info ")}[fd.severity]
        lines.append(f"  {tag} {fd.code}: {fd.message}")
        cap = MAX_ITEMS if fd.severity != "info" or verbose else 3
        for item in fd.items[:cap]:
            lines.append(f"          - {item}")
        if len(fd.items) > cap:
            lines.append(st.dim(f"          ... {len(fd.items) - cap} more (use --json)"))
    if verbose or out.worst == "error":
        for name in ("head", "old_tests"):
            res = out.runs.get(name)
            if res is not None and not res.passed and res.output_tail:
                lines += ["", st.dim(f"  --- tail of {name} output ---")]
                lines += ["  " + ln for ln in res.output_tail.strip().splitlines()[-25:]]
    if out.workdir:
        lines += ["", st.dim(f"  snapshots kept in {out.workdir}")]
    verdict = {"error": st.red("FAIL"), "warn": st.yellow("REVIEW"), "ok": st.green("OK")}[out.worst]
    lines += ["", f"  verdict: {verdict}"]
    return "\n".join(lines)


def to_json(out: Outcome, test_cmd: str) -> str:
    p = out.plan
    def run(res: RunResult | None):
        if res is None:
            return None
        return {
            "exit_code": res.exit_code,
            "passed": res.passed,
            "timed_out": res.timed_out,
            "duration_s": round(res.duration, 3),
            "error": res.error,
            "tests": res.tests,
            "junit_error": res.junit_error,
            "log_path": res.log_path if out.workdir else None,
        }
    doc = {
        "schema": SCHEMA_VERSION,
        "verdict": out.worst,
        "base": p.base,
        "head": p.head,
        "test_cmd": test_cmd,
        "changes": {
            "tests": [{"status": c.status, "path": c.path} for c in p.test_changes],
            "code": [{"status": c.status, "path": c.path} for c in p.code_changes],
            "harness": [c.path for c in p.harness_changes],
        },
        "runs": {k: run(out.runs.get(k)) for k in ("head", "base", "old_tests", "new_tests")},
        "findings": [
            {"code": f.code, "severity": f.severity, "message": f.message, "items": f.items}
            for f in out.findings
        ],
        "workdir": out.workdir,
    }
    return json.dumps(doc, indent=2, sort_keys=False)
