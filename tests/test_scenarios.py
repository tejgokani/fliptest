"""End-to-end scenarios: real git repos, real pytest runs, the real CLI."""

from conftest import (
    CALC_V1,
    PYTEST_CMD,
    PYTEST_CMD_NOJUNIT,
    check_json,
    codes,
    git,
    run_fliptest,
)


def test_honest_fix_with_fail_to_pass_test(repo):
    # Task: div by zero should return None. Code fixed + a new test that fails on old code.
    (repo / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef div(a, b):\n    if b == 0:\n        return None\n"
        "    return a / b\n")
    (repo / "test_calc.py").write_text(
        (repo / "test_calc.py").read_text() + "\n\ndef test_div_zero():\n    assert div(1, 0) is None\n")
    proc, doc = check_json(repo)
    assert proc.returncode == 0, proc.stdout
    assert doc["verdict"] == "ok"
    assert "FAIL_TO_PASS" in codes(doc)
    f2p = next(f for f in doc["findings"] if f["code"] == "FAIL_TO_PASS")
    assert f2p["items"] == ["test_calc::test_div_zero"]
    assert doc["runs"]["new_tests"]["passed"] is False


def test_goalpost_moved_expected_value_edited(repo):
    # "Agent" breaks add() and edits the expected value so the suite stays green.
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text().replace("== 5", "== 6"))
    proc, doc = check_json(repo)
    assert proc.returncode == 1
    assert doc["verdict"] == "error"
    assert doc["runs"]["head"]["passed"] is True
    moved = next(f for f in doc["findings"] if f["code"] == "GOALPOST_MOVED")
    assert moved["items"] == ["test_calc::test_add"]


CALC_V1_BROKEN = "def add(a, b):\n    return a + b + 1\n\n\ndef div(a, b):\n    return a / b\n"


def test_goalpost_without_junit_uses_exit_codes(repo):
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text().replace("== 5", "== 6"))
    proc, doc = check_json(repo, cmd=PYTEST_CMD_NOJUNIT, junit=False)
    assert proc.returncode == 1
    assert "GOALPOST_MOVED" in codes(doc)


def test_deleted_test_file(repo):
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    (repo / "test_calc.py").unlink()
    (repo / "test_other.py").write_text("def test_ok():\n    assert True\n")
    proc, doc = check_json(repo)
    assert proc.returncode == 1
    c = codes(doc)
    assert {"TEST_FILES_DELETED", "GOALPOST_MOVED", "TESTS_DISAPPEARED"} <= c


def test_deleted_test_function_detected(repo):
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    src = (repo / "test_calc.py").read_text()
    (repo / "test_calc.py").write_text(src.split("def test_add")[0] + "def test_div" + src.split("def test_div")[1])
    proc, doc = check_json(repo)
    assert proc.returncode == 1
    assert "TESTS_DISAPPEARED" in codes(doc)
    assert "GOALPOST_MOVED" in codes(doc)


def test_newly_skipped(repo):
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    src = (repo / "test_calc.py").read_text()
    (repo / "test_calc.py").write_text(
        "import pytest\n" + src.replace("def test_add", "@pytest.mark.skip\ndef test_add"))
    proc, doc = check_json(repo)
    assert proc.returncode == 1
    skipped = next(f for f in doc["findings"] if f["code"] == "TESTS_NEWLY_SKIPPED")
    assert skipped["items"] == ["test_calc::test_add"]


def test_vacuous_new_test(repo):
    # Code changes, the added test would have passed on the old code too.
    (repo / "calc.py").write_text(CALC_V1 + "\n\ndef sub(a, b):\n    return a - b\n")
    (repo / "test_calc.py").write_text(
        (repo / "test_calc.py").read_text() + "\n\ndef test_add_more():\n    assert add(1, 1) == 2\n")
    proc, doc = check_json(repo)
    assert proc.returncode == 0  # warning only
    assert doc["verdict"] == "warn"
    vac = next(f for f in doc["findings"] if f["code"] == "VACUOUS_TESTS")
    assert vac["items"] == ["test_calc::test_add_more"]
    strict = run_fliptest(repo, "--cmd", PYTEST_CMD, "--junit", "report.xml", "--strict", "-q")
    assert strict.returncode == 1


def test_head_fails(repo):
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    proc, doc = check_json(repo)
    assert proc.returncode == 1
    assert "HEAD_FAILS" in codes(doc)
    assert "NO_TEST_CHANGES" in codes(doc)
    assert doc["runs"]["old_tests"] is None


def test_no_changes(repo):
    proc, doc = check_json(repo)
    assert proc.returncode == 0
    assert codes(doc) == {"NO_CHANGES"}


def test_untracked_test_file_is_included(repo):
    (repo / "calc.py").write_text(
        CALC_V1 + "\n\ndef mul(a, b):\n    return a * b\n")
    (repo / "test_mul.py").write_text("from calc import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n")
    proc, doc = check_json(repo)
    assert {"status": "A", "path": "test_mul.py"} in doc["changes"]["tests"]
    assert "FAIL_TO_PASS" in codes(doc)  # ImportError on old code counts as failing
    assert proc.returncode == 0


def test_config_is_read_from_base_not_head(repo):
    (repo / ".fliptest.toml").write_text(f'test_cmd = "{PYTEST_CMD}"\njunit = "report.xml"\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "cfg")
    # The change breaks code, edits the test, AND rewrites the config to always pass.
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text().replace("== 5", "== 6"))
    (repo / ".fliptest.toml").write_text('test_cmd = "true"\n')
    proc = run_fliptest(repo, "--json")
    import json
    doc = json.loads(proc.stdout)
    assert doc["test_cmd"] == PYTEST_CMD
    assert proc.returncode == 1
    assert {"GOALPOST_MOVED", "HARNESS_CHANGED"} <= codes(doc)


def test_commit_range_mode(repo):
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text().replace("== 5", "== 6"))
    git(repo, "commit", "-qam", "agent")
    # Dirty the working tree afterwards; --head HEAD must ignore it.
    (repo / "calc.py").write_text("garbage(\n")
    proc, doc = check_json(repo, "--base", base, "--head", "HEAD")
    assert "GOALPOST_MOVED" in codes(doc)
    assert doc["head"] != "WORKTREE"


def test_timeout_is_reported_and_killed(repo):
    (repo / "calc.py").write_text(CALC_V1 + "\n")
    proc, doc = check_json(repo, "--timeout", "1", cmd="sleep 30", junit=False)
    assert proc.returncode == 1
    assert "TIMEOUT" in codes(doc)


def test_plan_runs_nothing(repo):
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    (repo / "test_calc.py").write_text("")
    marker = repo.parent / "ran"
    proc = run_fliptest(repo, "plan", "--cmd", f"touch {marker}")
    assert proc.returncode == 0
    assert "test files (1)" in proc.stdout and "code files (1)" in proc.stdout
    assert not marker.exists()


def test_text_report(repo):
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text().replace("== 5", "== 6"))
    proc = run_fliptest(repo, "--cmd", PYTEST_CMD, "--junit", "report.xml")
    assert proc.returncode == 1
    assert "GOALPOST_MOVED" in proc.stdout
    assert "verdict: FAIL" in proc.stdout
    assert "\x1b[" not in proc.stdout  # NO_COLOR respected


def test_allow_downgrades_reviewed_finding(repo):
    (repo / "calc.py").write_text(CALC_V1_BROKEN)
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text().replace("== 5", "== 6"))
    proc, doc = check_json(repo, "--allow", "goalpost_moved")
    assert proc.returncode == 0
    moved = next(f for f in doc["findings"] if f["code"] == "GOALPOST_MOVED")
    assert moved["severity"] == "info" and moved["message"].endswith("[allowed]")


def test_base_failing_bugfix_is_not_a_warning(repo):
    (repo / "test_calc.py").write_text((repo / "test_calc.py").read_text()
                                       + "\n\ndef test_div_zero():\n    assert div(1, 0) is None\n")
    git(repo, "commit", "-qam", "failing test for bug")
    (repo / "calc.py").write_text(CALC_V1.replace("    return a / b", "    return None if b == 0 else a / b"))
    proc, doc = check_json(repo)
    assert proc.returncode == 0 and doc["verdict"] == "ok", doc["findings"]
    fixed = next(f for f in doc["findings"] if f["code"] == "FIXED")
    assert fixed["items"] == ["test_calc::test_div_zero"]
