"""Trying to break fliptest: hostile inputs, repo safety, failure paths."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest
from conftest import CALC_V1, PY, PYTEST_CMD, SRC, check_json, codes, git, run_fliptest

from fliptest import classify, junit

CALC_BROKEN = CALC_V1.replace("a + b", "a + b + 1")


def _repo_state(repo):
    return (
        git(repo, "status", "--porcelain=v2", "--untracked-files=all", "--ignored"),
        git(repo, "worktree", "list", "--porcelain"),
        (repo / ".git" / "index").read_bytes(),
        git(repo, "for-each-ref"),
        git(repo, "stash", "list"),
    )


def test_repository_is_not_modified(repo):
    (repo / "calc.py").write_text(CALC_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text().replace("== 5", "== 6"))
    git(repo, "add", "calc.py")  # a partially staged state must survive too
    (repo / "new_untracked.txt").write_text("x")
    before = _repo_state(repo)
    mtimes = {p: p.stat().st_mtime_ns for p in repo.iterdir() if p.is_file()}
    proc, _ = check_json(repo)
    assert proc.returncode == 1
    assert _repo_state(repo) == before
    assert {p: p.stat().st_mtime_ns for p in repo.iterdir() if p.is_file()} == mtimes
    assert not (repo / "report.xml").exists()


def test_temp_dirs_cleaned_up(repo, tmp_path):
    (repo / "calc.py").write_text(CALC_BROKEN)
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    env = dict(os.environ, PYTHONPATH=str(SRC), TMPDIR=str(tmp))
    subprocess.run([PY, "-m", "fliptest", "-C", str(repo), "--cmd", "true", "-q"], env=env, check=False)
    assert list(tmp.iterdir()) == []


def test_keep_leaves_snapshots(repo):
    (repo / "calc.py").write_text(CALC_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text() + "\n")
    proc, doc = check_json(repo, "--keep")
    wd = doc["workdir"]
    try:
        assert os.path.isdir(os.path.join(wd, "old_tests"))
        assert os.path.isfile(doc["runs"]["head"]["log_path"])
    finally:
        subprocess.run(["rm", "-rf", wd], check=True)


def test_sigint_kills_children_and_cleans_up(repo, tmp_path):
    (repo / "calc.py").write_text(CALC_BROKEN)
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    pidfile = tmp_path / "child.pid"
    env = dict(os.environ, PYTHONPATH=str(SRC), TMPDIR=str(tmp))
    proc = subprocess.Popen(
        [PY, "-m", "fliptest", "-C", str(repo), "--cmd", f"echo $$ > {pidfile}; exec sleep 60", "-q"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    deadline = time.time() + 20
    while not (pidfile.exists() and pidfile.read_text().strip()) and time.time() < deadline:
        time.sleep(0.1)
    child = int(pidfile.read_text())
    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=20)
    assert proc.returncode == 130
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    assert list(tmp.iterdir()) == []


def test_sigterm_also_cleans_up(repo, tmp_path):
    (repo / "calc.py").write_text(CALC_BROKEN)
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    env = dict(os.environ, PYTHONPATH=str(SRC), TMPDIR=str(tmp))
    proc = subprocess.Popen([PY, "-m", "fliptest", "-C", str(repo), "--cmd", "sleep 60", "-q"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1.5)
    proc.terminate()
    proc.wait(timeout=20)
    assert proc.returncode == 130
    assert list(tmp.iterdir()) == []


def test_not_a_git_repo(tmp_path):
    proc = run_fliptest(tmp_path, "--cmd", "true")
    assert proc.returncode == 2
    assert "error" in proc.stderr and "Traceback" not in proc.stderr


def test_missing_directory(tmp_path):
    proc = run_fliptest(tmp_path / "nope", "--cmd", "true")
    assert proc.returncode == 2 and "not a directory" in proc.stderr


def test_bad_base_ref(repo):
    proc = run_fliptest(repo, "--base", "does-not-exist", "--cmd", "true")
    assert proc.returncode == 2 and "cannot resolve" in proc.stderr


def test_ref_that_looks_like_an_option(repo):
    proc = run_fliptest(repo, "--base=--output=/tmp/pwned", "--cmd", "true")
    assert proc.returncode == 2
    assert not os.path.exists("/tmp/pwned")


def test_empty_repo_without_commits(tmp_path):
    git(tmp_path, "init", "-q")
    proc = run_fliptest(tmp_path, "--cmd", "true")
    assert proc.returncode == 2 and "cannot resolve" in proc.stderr


def test_no_test_command_anywhere(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "x.txt").write_text("x")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "x")
    (tmp_path / "x.txt").write_text("y")
    proc = run_fliptest(tmp_path)
    assert proc.returncode == 2 and "no test command" in proc.stderr


def test_invalid_config(repo):
    (repo / ".fliptest.toml").write_text("test_cmd = [\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "bad cfg")
    proc = run_fliptest(repo, "--cmd", "true")
    assert proc.returncode == 2 and "not valid TOML" in proc.stderr


@pytest.mark.parametrize("body,msg", [
    ('unknown_key = 1\n', "unknown keys"),
    ('timeout = -5\n', "positive"),
    ('junit = "../outside.xml"\n', "relative"),
    ('link = ["/etc"]\n', "relative"),
    ('test_cmd = ""\n', "non-empty"),
])
def test_config_validation(repo, body, msg):
    (repo / ".fliptest.toml").write_text(body)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "cfg")
    proc = run_fliptest(repo, "--cmd", "true")
    assert proc.returncode == 2 and msg in proc.stderr, proc.stderr


def test_junit_path_traversal_rejected(repo):
    (repo / "calc.py").write_text(CALC_BROKEN)
    proc = run_fliptest(repo, "--cmd", "true", "--junit", "../../etc/passwd")
    assert proc.returncode == 2


def test_symlinked_dir_cannot_redirect_overlay_writes(repo, tmp_path):
    """A head tree that turns tests/ into a symlink must not let overlays write outside."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "tests dir")
    subprocess.run(["rm", "-rf", str(repo / "tests")], check=True)
    os.symlink(outside, repo / "tests")
    (repo / "calc.py").write_text(CALC_BROKEN)
    proc = run_fliptest(repo, "--cmd", "true", "--json")
    assert list(outside.iterdir()) == []
    assert proc.returncode in (1, 2)
    assert "Traceback" not in proc.stderr


def test_malicious_junit_report(repo):
    bomb = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
            '<testsuite><testcase name="&b;"/></testsuite>')
    (repo / "calc.py").write_text(CALC_BROKEN)
    proc, doc = check_json(repo, cmd=f"printf '%s' '{bomb}' > report.xml")
    assert "JUNIT_UNREADABLE" in codes(doc)
    assert doc["runs"]["head"]["tests"] is None


def test_command_not_found(repo):
    (repo / "calc.py").write_text(CALC_BROKEN)
    proc, doc = check_json(repo, cmd="definitely-not-a-command-xyz", junit=False)
    assert proc.returncode == 1
    assert "HEAD_FAILS" in codes(doc)


def test_paths_with_spaces_and_unicode(repo):
    d = repo / "dir with space" / "ünï"
    d.mkdir(parents=True)
    (d / "test_ü.py").write_text("def test_u():\n    assert True\n")
    (repo / "calc.py").write_text(CALC_V1 + "\n")
    proc, doc = check_json(repo, cmd="test -f 'dir with space/ünï/test_ü.py'", junit=False)
    assert doc["runs"]["head"]["passed"] is True
    assert doc["runs"]["new_tests"]["passed"] is True  # overlaid onto base too


def test_deps_dir_is_linked_not_copied(repo):
    (repo / ".gitignore").write_text("report.xml\n__pycache__/\nnode_modules/\n")
    git(repo, "commit", "-qam", "ignore nm")
    (repo / "node_modules" / "dep").mkdir(parents=True)
    (repo / "node_modules" / "dep" / "index.js").write_text("x")
    (repo / "calc.py").write_text(CALC_V1 + "\n")
    proc, doc = check_json(repo, cmd="test -L node_modules && test -f node_modules/dep/index.js", junit=False)
    assert doc["runs"]["head"]["passed"] and doc["runs"]["base"]["passed"]
    proc, doc = check_json(repo, "--no-link", cmd="test -e node_modules", junit=False)
    assert doc["runs"]["head"]["passed"] is False


def test_variant_env_is_exposed(repo):
    (repo / "calc.py").write_text(CALC_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text() + "\n")
    proc, doc = check_json(repo, cmd='test "$FLIPTEST_VARIANT" != old_tests', junit=False)
    assert doc["runs"]["old_tests"]["passed"] is False
    assert doc["runs"]["head"]["passed"] is True


def test_harness_package_json_change_reported(repo):
    (repo / "package.json").write_text('{"scripts": {"test": "jest"}}')
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "pkg")
    (repo / "package.json").write_text('{"scripts": {"test": "true"}}')
    proc, doc = check_json(repo, cmd="true", junit=False)
    harness = next(f for f in doc["findings"] if f["code"] == "HARNESS_CHANGED")
    assert harness["items"] == ["package.json"]


def test_claude_hook_mode(repo):
    (repo / "calc.py").write_text(CALC_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text().replace("== 5", "== 6"))
    payload = json.dumps({"hook_event_name": "Stop", "stop_hook_active": False, "cwd": str(repo)})
    proc = run_fliptest(repo, "--cmd", PYTEST_CMD, "--claude-hook", stdin=payload)
    assert proc.returncode == 2
    assert "GOALPOST_MOVED" in proc.stderr and proc.stdout == ""
    again = json.dumps({"hook_event_name": "Stop", "stop_hook_active": True})
    proc = run_fliptest(repo, "--cmd", PYTEST_CMD, "--claude-hook", stdin=again)
    assert proc.returncode == 0
    proc = run_fliptest(repo, "--cmd", PYTEST_CMD, "--claude-hook", stdin="not json")
    assert proc.returncode == 2


def test_claude_hook_clean_change_allows_stop(repo):
    (repo / "README").write_text("docs\n")
    proc = run_fliptest(repo, "--cmd", "true", "--claude-hook", stdin="{}")
    assert proc.returncode == 0


# --- unit level --------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("test_calc.py", True), ("pkg/calc_test.py", True), ("tests/helpers.py", True),
    ("src/pkg/tests/data.json", True), ("conftest.py", True), ("web/a.test.ts", True),
    ("web/__tests__/x.js", True), ("x_test.go", True), ("spec/models/user_spec.rb", True),
    ("src/test/java/FooTest.java", True), ("calc.py", False), ("src/testing_utils.py", False),
    ("latest.py", False), ("contest/main.py", False), ("README.md", False),
])
def test_classify(path, expected):
    assert classify.is_test(path) is expected


def test_classify_harness():
    assert classify.is_harness("package.json")
    assert classify.is_harness(".github/workflows/ci.yml")
    assert not classify.is_harness("src/app.py")


def test_junit_parse_outcomes(tmp_path):
    p = tmp_path / "r.xml"
    p.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="a" name="ok"/>'
        '<testcase classname="a" name="bad"><failure/></testcase>'
        '<testcase classname="a" name="err"><error/></testcase>'
        '<testcase classname="a" name="sk"><skipped/></testcase>'
        '<testcase classname="a" name="dup"/><testcase classname="a" name="dup"><failure/></testcase>'
        '</testsuite></testsuites>')
    assert junit.parse(p) == {"a::ok": "pass", "a::bad": "fail", "a::err": "error",
                              "a::sk": "skip", "a::dup": "fail"}


def test_junit_missing_and_malformed(tmp_path):
    with pytest.raises(junit.JUnitError):
        junit.parse(tmp_path / "nope.xml")
    bad = tmp_path / "bad.xml"
    bad.write_text("<testsuite><testcase")
    with pytest.raises(junit.JUnitError):
        junit.parse(bad)


def test_cli_version():
    proc = subprocess.run([PY, "-m", "fliptest", "--version"], capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=str(SRC)))
    assert proc.stdout.startswith("fliptest ")


def test_python_version_floor():
    assert sys.version_info >= (3, 11)


def test_run_dependent_test_ids_do_not_cause_findings(repo):
    """Regression: is-number names tests after Math.random() / Date values."""
    (repo / "test_calc.py").write_text(
        (repo / "test_calc.py").read_text()
        + "\n\nimport random, pytest\n\n"
        "@pytest.mark.parametrize('x', [random.random(), 10**12 + random.randint(0, 10**6)])\n"
        "def test_rand(x):\n    assert x == x\n")
    git(repo, "commit", "-qam", "random ids")
    (repo / "calc.py").write_text(CALC_V1 + "\n")
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text() + "\n")
    proc, doc = check_json(repo)
    assert proc.returncode == 0, doc["findings"]
    assert "TESTS_DISAPPEARED" not in codes(doc) and "GOALPOST_MOVED" not in codes(doc)
    assert "UNSTABLE_TEST_IDS" in codes(doc)


def test_root_test_js_is_a_test():
    assert classify.is_test("test.js") and classify.is_test("tests.py")


def test_concurrent_and_repeated_runs_agree(repo):
    (repo / "calc.py").write_text(CALC_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text().replace("== 5", "== 6"))
    env = dict(os.environ, PYTHONPATH=str(SRC), NO_COLOR="1")
    args = [PY, "-m", "fliptest", "-C", str(repo), "--cmd", PYTEST_CMD, "--junit", "report.xml", "--json"]
    procs = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
             for _ in range(3)]
    docs = [json.loads(p.communicate(timeout=300)[0]) for p in procs]
    summaries = {json.dumps([(f["code"], f["items"]) for f in d["findings"]]) for d in docs}
    assert len(summaries) == 1 and all(d["verdict"] == "error" for d in docs)
