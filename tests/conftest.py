import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PY = sys.executable
# A real pytest run inside each snapshot, emitting JUnit XML.
PYTEST_CMD = f"{PY} -m pytest -q -p no:cacheprovider --junitxml=report.xml"
PYTEST_CMD_NOJUNIT = f"{PY} -m pytest -q -p no:cacheprovider"

CALC_V1 = "def add(a, b):\n    return a + b\n\n\ndef div(a, b):\n    return a / b\n"
TEST_V1 = (
    "from calc import add, div\n\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n\n\n"
    "def test_div():\n    assert div(6, 3) == 2\n"
)


def git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=env).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "calc.py").write_text(CALC_V1)
    (r / "test_calc.py").write_text(TEST_V1)
    (r / ".gitignore").write_text("report.xml\n__pycache__/\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    return r


def run_fliptest(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(SRC), NO_COLOR="1")
    return subprocess.run([PY, "-m", "fliptest", "-C", str(repo), *args], capture_output=True,
                          text=True, env=env, input=stdin, timeout=300)


def check_json(repo: Path, *args: str, cmd: str = PYTEST_CMD, junit: bool = True):
    extra = ["--junit", "report.xml"] if junit else []
    proc = run_fliptest(repo, "--cmd", cmd, *extra, "--json", *args)
    assert proc.stdout, proc.stderr
    return proc, json.loads(proc.stdout)


def codes(doc) -> set[str]:
    return {f["code"] for f in doc["findings"]}
