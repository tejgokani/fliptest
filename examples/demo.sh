#!/usr/bin/env bash
# Builds a throwaway repo where a "fix" only passes because a test was edited,
# then runs fliptest on it. Needs: git, python3 with pytest, fliptest on PATH.
# Usage: examples/demo.sh            (leaves nothing behind)
set -euo pipefail

PY="${PYTHON:-python3}"
"$PY" -m pytest --version >/dev/null 2>&1 || { echo "demo needs pytest: $PY -m pip install pytest" >&2; exit 2; }
command -v fliptest >/dev/null || { echo "demo needs fliptest on PATH (pipx install fliptest)" >&2; exit 2; }

dir="$(mktemp -d)"
trap 'rm -rf "$dir"' EXIT
cd "$dir"
git init -q -b main
git config user.email demo@example.com
git config user.name demo

cat > pricing.py <<'PY'
def total(prices, discount=0.0):
    """Sum prices, then apply a fractional discount (0.1 == 10% off)."""
    return round(sum(prices) * (1 - discount), 2)
PY
cat > test_pricing.py <<'PY'
from pricing import total


def test_total():
    assert total([10, 5]) == 15


def test_discount():
    assert total([100], discount=0.1) == 90
PY
printf 'report.xml\n__pycache__/\n' > .gitignore
git add -A && git commit -qm "pricing"

# The "agent" was asked to add a minimum-order fee. It broke discounts and
# quietly changed the expected value so the suite stays green.
cat > pricing.py <<'PY'
def total(prices, discount=0.0, min_fee=0.0):
    """Sum prices, then apply a fractional discount (0.1 == 10% off)."""
    subtotal = sum(prices) + min_fee
    return round(subtotal * (1 - discount * 10 / 100), 2)
PY
sed -i.bak 's/== 90/== 99/' test_pricing.py && rm test_pricing.py.bak

echo "\$ git diff --stat"
git --no-pager diff --stat
echo
echo "\$ $PY -m pytest -q"
"$PY" -m pytest -q -p no:cacheprovider | tail -1
echo
echo "\$ fliptest --junit report.xml --cmd '$PY -m pytest -q --junitxml=report.xml'"
NO_COLOR=1 fliptest -q --junit report.xml --cmd "$PY -m pytest -q -p no:cacheprovider --junitxml=report.xml" || true
