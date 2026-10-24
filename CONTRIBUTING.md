# Contributing

Thanks for helping. The most useful contributions, in order:

1. **A repo where fliptest is wrong.** A false `GOALPOST_MOVED`, a missed one,
   a test runner that misbehaves in a snapshot. A minimal script that builds the
   repo (like `examples/demo.sh`) makes it fixable.
2. Runner recipes (JUnit flags for your language) for the README.
3. Code.

## Development

```bash
uv venv && uv pip install -e . pytest ruff     # or: python3 -m venv .venv && pip install -e . pytest ruff
.venv/bin/python -m pytest -q                  # ~70 tests; they create real git repos in tmp dirs
.venv/bin/ruff check src tests
```

The test suite is end-to-end on purpose: each scenario builds a real git repo
and runs the real CLI with a real pytest. When you fix a bug, add the scenario
that would have caught it (see `tests/test_adversarial.py`).

## Ground rules

- No runtime dependencies. The standard library is enough.
- fliptest must never modify the user's repository. Any change that touches
  `gitops.py` needs to keep `test_repository_is_not_modified` passing.
- Findings must be explainable in one sentence a reviewer can act on.
- Be kind: see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
