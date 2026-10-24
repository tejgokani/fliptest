"""Minimal JUnit XML reader: test id -> outcome.

JUnit XML is the one result format nearly every runner can emit (pytest
--junitxml, jest-junit, vitest --reporter=junit, go-junit-report, cargo
nextest, gradle, maven surefire), which keeps fliptest language-neutral.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024


class JUnitError(ValueError):
    pass


def parse(path: Path) -> dict[str, str]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise JUnitError(f"no JUnit report at {path.name}") from exc
    if size > MAX_BYTES:
        raise JUnitError(f"JUnit report too large ({size} bytes)")
    data = path.read_bytes()
    # ElementTree does not resolve external entities, but refuse DTDs outright
    # so a hostile report cannot attempt entity-expansion tricks.
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise JUnitError("JUnit report contains a DTD; refusing to parse")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise JUnitError(f"malformed JUnit XML: {exc}") from exc
    results: dict[str, str] = {}
    for case in root.iter("testcase"):
        name = case.get("name", "")
        cls = case.get("classname", "") or case.get("file", "")
        tid = f"{cls}::{name}" if cls else name
        outcome = "pass"
        for child in case:
            tag = child.tag
            if tag == "failure":
                outcome = "fail"
            elif tag == "error":
                outcome = "error"
            elif tag == "skipped":
                outcome = "skip"
        # Duplicate ids (parametrized tests reported twice, retries): worst wins.
        prev = results.get(tid)
        results[tid] = _worse(prev, outcome) if prev else outcome
    return results


_RANK = {"pass": 0, "skip": 1, "fail": 2, "error": 3}


def _worse(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b
