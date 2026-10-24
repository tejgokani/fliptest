"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from . import __version__, config, engine, gitops, report

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130

DESCRIPTION = """\
Cross-check a change against its tests. fliptest snapshots the base and head
revisions into temporary directories and runs your test command four ways:
new code + new tests, old code + old tests, new code + OLD tests (did the
change move the goalposts?), and old code + NEW tests (do the new tests
detect anything?). Your repository is never modified.
"""


COMMANDS = ("check", "plan")
# Options that consume the following argv token as their value.
VALUE_OPTS = {"-C", "--base", "--head", "--cmd", "--test-pattern", "--junit", "--timeout", "--link", "--allow"}


def build_parser(command: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=f"fliptest {command}" if command == "plan" else "fliptest",
        description=DESCRIPTION + "\ncommands: check (default), plan (classify files, run nothing)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--version", action="version", version=f"fliptest {__version__}")
    _common(ap)
    if command == "check":
        _check_opts(ap)
    return ap


def split_command(argv: list[str]) -> tuple[str, list[str]]:
    """Find the subcommand wherever it appears (`fliptest -C dir plan` works)."""
    for i, tok in enumerate(argv):
        if tok == "--":
            break
        if tok in COMMANDS and (i == 0 or argv[i - 1] not in VALUE_OPTS):
            return tok, argv[:i] + argv[i + 1:]
    return "check", argv


def _common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("-C", dest="directory", default=".", help="repository directory (default: .)")
    sp.add_argument("--base", default="HEAD", help="base revision (default: HEAD)")
    sp.add_argument("--head", default=None,
                    help="head revision (default: the working tree, including untracked files)")
    sp.add_argument("--cmd", default=None, help="test command, run with the shell in each snapshot")
    sp.add_argument("--test-pattern", action="append", default=[], metavar="GLOB",
                    help="extra glob marking files as tests (repeatable)")


def _check_opts(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--junit", default=None, metavar="PATH",
                    help="JUnit XML path (relative to repo root) your command writes; enables per-test findings")
    sp.add_argument("--timeout", type=float, default=None, help="seconds per run (default: 900)")
    sp.add_argument("--link", action="append", default=None, metavar="DIR",
                    help="ignored dir to symlink into snapshots (default: node_modules .venv venv)")
    sp.add_argument("--no-link", action="store_true", help="do not symlink any dependency dirs")
    sp.add_argument("--skip-base", action="store_true", help="skip the old-code/old-tests control run")
    sp.add_argument("--json", action="store_true", help="machine-readable output on stdout")
    sp.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    sp.add_argument("--allow", action="append", default=[], metavar="CODE",
                    help="downgrade a finding code (e.g. GOALPOST_MOVED) to info after review (repeatable)")
    sp.add_argument("--keep", action="store_true", help="keep snapshot directories and logs")
    sp.add_argument("-q", "--quiet", action="store_true", help="no progress output")
    sp.add_argument("-v", "--verbose", action="store_true", help="show failing output tails")
    sp.add_argument("--claude-hook", action="store_true",
                    help="Claude Code Stop-hook mode: report on stderr, exit 2 to make the agent continue")


def _sigterm(_signum, _frame):
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command, rest = split_command(argv)
    args = build_parser(command).parse_args(rest)
    args.command = command
    signal.signal(signal.SIGTERM, _sigterm)
    err = sys.stderr
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("fliptest: interrupted; temporary snapshots removed", file=err)
        return EXIT_INTERRUPTED
    except (gitops.GitError, config.ConfigError) as exc:
        print(f"fliptest: error: {exc}", file=err)
        return EXIT_USAGE


def _hook_input() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read(1_000_000)
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _run(args) -> int:
    start = Path(args.directory)
    if not start.is_dir():
        raise config.ConfigError(f"not a directory: {start}")
    hook = getattr(args, "claude_hook", False)
    hook_data = _hook_input() if hook else {}
    if hook and hook_data.get("cwd") and args.directory == ".":
        start = Path(hook_data["cwd"])

    repo = gitops.repo_root(start)
    base_sha = gitops.resolve_commit(repo, args.base)
    cfg = config.load(repo, base_sha)
    if args.cmd:
        cfg.test_cmd = args.cmd
    if not cfg.test_cmd:
        guess = config.detect_test_cmd(repo, base_sha)
        if guess:
            cfg.test_cmd, cfg.detected_cmd = guess, True
    cfg.test_patterns += args.test_pattern

    plan = engine.make_plan(repo, args.base, args.head, cfg)
    if args.command == "plan":
        print(report.render_plan(plan, cfg.test_cmd, sys.stdout))
        return EXIT_OK

    if args.junit is not None:
        cfg.junit = config.validate_junit_path(args.junit)
    if args.timeout is not None:
        if args.timeout <= 0:
            raise config.ConfigError("--timeout must be positive")
        cfg.timeout = args.timeout
    if args.no_link:
        cfg.link = []
    elif args.link is not None:
        cfg.link = [config.validate_link(x) for x in args.link]
    cfg.skip_base = args.skip_base
    if not cfg.test_cmd:
        raise config.ConfigError(
            "no test command: pass --cmd, or set test_cmd in .fliptest.toml (committed at base)")

    out_stream = sys.stderr if hook else sys.stdout
    progress = None
    if not (args.quiet or args.json or hook):
        def progress(msg):
            print(f"fliptest: {msg}", file=sys.stderr, flush=True)
        if cfg.detected_cmd:
            progress(f"no test command configured; detected `{cfg.test_cmd}`")

    if not plan.changes:
        outcome = engine.Outcome(plan, {}, [engine.Finding("NO_CHANGES", "info",
                                 "no differences between base and head")])
    else:
        outcome = engine.execute(plan, cfg, keep=args.keep, progress=progress)

    allowed = {c.strip().upper() for c in args.allow}
    for fd in outcome.findings:
        if fd.code in allowed and fd.severity != "info":
            fd.severity = "info"
            fd.message += " [allowed]"

    if args.json:
        print(report.to_json(outcome, cfg.test_cmd))
    elif outcome.runs or not hook:
        print(report.render_text(outcome, cfg.test_cmd, out_stream, args.verbose), file=out_stream)

    failed = outcome.worst == "error" or (args.strict and outcome.worst == "warn")
    if hook:
        if failed and hook_data.get("stop_hook_active"):
            # Already blocked once this turn: report, but do not loop forever.
            print("fliptest: findings remain after a retry; letting the agent stop", file=sys.stderr)
            return EXIT_OK
        return 2 if failed else EXIT_OK
    return EXIT_FINDINGS if failed else EXIT_OK
