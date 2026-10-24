# Security policy

## Threat model

fliptest executes a test command inside temporary copies of a repository. It
is exactly as trusted as running that repository's tests yourself. **Do not
run fliptest on code you would not run the tests of.**

What fliptest does guard against:

- **Self-grading changes.** `.fliptest.toml` is read from the *base* revision,
  so the change under review cannot swap the test command. Edits to it, and to
  other test-harness files, are reported as `HARNESS_CHANGED`.
- **Writes outside snapshots.** Paths from git are rejected if absolute or
  containing `..`; overlay copies refuse to write through a symlinked parent
  directory that resolves outside the snapshot.
- **Mutation of your repo.** No index, ref, worktree, stash, or file in your
  checkout is modified (covered by `test_repository_is_not_modified`).
  Dependency directories (`node_modules`, `.venv`) are symlinked, so a test
  suite that writes into them writes into your real directories. Use `--no-link`
  to avoid that.
- **Hostile JUnit reports.** Reports with a DTD/entities or over 64 MiB are
  refused.
- **Runaway processes.** Each run is its own process group, killed on timeout,
  SIGINT, or SIGTERM; temp directories are removed.
- **Network.** fliptest makes no network requests and has no telemetry.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting ("Security" tab → "Report a
vulnerability") rather than a public issue. Expect a first response within a
week.
