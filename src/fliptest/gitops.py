"""Read-only git access and tree materialization.

Nothing here writes to the user's repository: no index updates, no worktree
registrations, no refs. Snapshots are built in temporary directories using a
throwaway index file (GIT_INDEX_FILE), so an interrupted run leaves the repo
exactly as it was.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

WORKTREE = "WORKTREE"


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str, env: dict | None = None, check: bool = True) -> bytes:
    full_env = dict(os.environ)
    # Never let a user's pager or prompts block us.
    full_env.update({"GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            env=full_env,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    if check and proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {msg}")
    return proc.stdout


def repo_root(start: Path) -> Path:
    out = _git(start, "rev-parse", "--show-toplevel")
    return Path(out.decode().strip())


def resolve_commit(repo: Path, ref: str) -> str:
    out = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    sha = out.decode().strip()
    if not sha:
        raise GitError(f"cannot resolve '{ref}' to a commit")
    return sha


def show_file(repo: Path, sha: str, path: str) -> bytes | None:
    """Return the blob for path at sha, or None if it does not exist there."""
    out = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{sha}:{path}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if out.returncode != 0:
        return None
    return _git(repo, "show", f"{sha}:{path}")


@dataclass(frozen=True)
class Change:
    status: str  # "A" added, "M" modified, "D" deleted
    path: str


def safe_relpath(p: str) -> str:
    """Reject paths that could escape a snapshot root."""
    pp = PurePosixPath(p)
    if pp.is_absolute() or ".." in pp.parts or p == "" or "\x00" in p:
        raise GitError(f"refusing unsafe path from git: {p!r}")
    return str(pp)


def _split_z(data: bytes) -> list[str]:
    return [s for s in data.decode("utf-8", errors="surrogateescape").split("\0") if s]


def changed_files(repo: Path, base: str, head: str) -> list[Change]:
    """Files that differ between base and head (head may be WORKTREE)."""
    if head == WORKTREE:
        raw = _git(repo, "diff", "--no-renames", "--name-status", "-z", base, "--")
    else:
        raw = _git(repo, "diff", "--no-renames", "--name-status", "-z", base, head, "--")
    parts = _split_z(raw)
    changes: dict[str, Change] = {}
    i = 0
    while i + 1 < len(parts):
        status, path = parts[i][0], parts[i + 1]
        i += 2
        if status == "T":  # type change (e.g. file <-> symlink): treat as modify
            status = "M"
        if status not in "AMD":
            continue
        changes[path] = Change(status, safe_relpath(path))
    if head == WORKTREE:
        for path in _split_z(_git(repo, "ls-files", "-o", "--exclude-standard", "-z")):
            changes[path] = Change("A", safe_relpath(path))
    return sorted(changes.values(), key=lambda c: c.path)


def materialize_commit(repo: Path, sha: str, dest: Path) -> None:
    """Write the full tree of `sha` into dest using a private index file."""
    dest.mkdir(parents=True, exist_ok=True)
    index = dest.parent / f".{dest.name}.index"
    env = {"GIT_INDEX_FILE": str(index)}
    try:
        _git(repo, "read-tree", sha, env=env)
        prefix = str(dest) + os.sep
        _git(repo, "checkout-index", "-a", "-f", f"--prefix={prefix}", env=env)
    finally:
        index.unlink(missing_ok=True)


def materialize_worktree(repo: Path, dest: Path) -> None:
    """Copy tracked + untracked-but-not-ignored files of the working tree."""
    dest.mkdir(parents=True, exist_ok=True)
    listing = _git(repo, "ls-files", "-c", "-o", "--exclude-standard", "-z")
    for rel in _split_z(listing):
        rel = safe_relpath(rel)
        src = repo / rel
        if not os.path.lexists(src):
            continue  # deleted in the working tree
        if src.is_dir() and not src.is_symlink():
            continue  # submodule / gitlink: not supported, see README
        copy_entry(src, dest / rel, dest)


def copy_entry(src: Path, dst: Path, root: Path) -> None:
    """Copy one file or symlink into root, refusing writes outside root."""
    parent = dst.parent
    parent.mkdir(parents=True, exist_ok=True)
    real_parent = os.path.realpath(parent)
    real_root = os.path.realpath(root)
    if os.path.commonpath([real_parent, real_root]) != real_root:
        raise GitError(f"refusing to write outside snapshot: {dst}")
    if os.path.lexists(dst):
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_symlink():
        os.symlink(os.readlink(src), dst)
    else:
        shutil.copy2(src, dst)


def write_blob(root: Path, rel: str, data: bytes) -> None:
    dst = root / safe_relpath(rel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    real_parent = os.path.realpath(dst.parent)
    real_root = os.path.realpath(root)
    if os.path.commonpath([real_parent, real_root]) != real_root:
        raise GitError(f"refusing to write outside snapshot: {dst}")
    if os.path.lexists(dst):
        dst.unlink()
    dst.write_bytes(data)


def remove_entry(root: Path, rel: str) -> None:
    dst = root / safe_relpath(rel)
    real_parent = os.path.realpath(dst.parent)
    real_root = os.path.realpath(root)
    if os.path.commonpath([real_parent, real_root]) != real_root:
        raise GitError(f"refusing to delete outside snapshot: {dst}")
    if os.path.lexists(dst):
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
