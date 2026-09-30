"""Probes are commands; evidence is one bounded cell; freshness is derived from bound files."""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from pacer_mcp.schema import contained_path, refs, utc_now
from pacer_mcp.validation import EVIDENCE_PATTERN

_PARSE = re.compile(r"rev:(\S+) src:(\S+) exit:(-?\d+) out:(\S+) at:(\S+)")


def src_digest(root: Path, paths: list[str]) -> str:
    """Seven hex characters over sorted names and bytes; missing files hash as MISSING."""
    h = hashlib.sha256()
    for path in sorted(set(paths)):
        h.update(path.encode("utf-8") + b"\0")
        try:
            file = contained_path(root, path)
            h.update(file.read_bytes() if file.is_file() else b"MISSING")
        except ValueError:
            h.update(b"UNSAFE")
        h.update(b"\0")
    return h.hexdigest()[:7]


def git_rev(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "none"
    except (OSError, subprocess.SubprocessError):
        return "none"


def format_evidence(rev: str, src: str, exit_code: int, out: str, at: str) -> str:
    cell = f"rev:{rev} src:{src} exit:{exit_code} out:{out} at:{at}"
    if not EVIDENCE_PATTERN.fullmatch(cell):
        raise ValueError(f"Malformed evidence cell: {cell}")
    return cell


def parse_evidence(cell: str) -> dict | None:
    match = _PARSE.fullmatch(cell or "")
    if not match:
        return None
    rev, src, exit_code, out, at = match.groups()
    return {"rev": rev, "src": src, "exit": int(exit_code), "out": out, "at": at}


def bound_paths(row: dict, tables: dict) -> list[str]:
    index = {r["ID"]: r for r in tables["overlord"]}
    return sorted({index[k]["Path"] for k in refs(row.get("Binds", "")) if k in index})


def freshness(row: dict, tables: dict, root: Path) -> str:
    """UNBOUND without evidence; FAIL on nonzero exit; STALE when bound bytes moved."""
    evidence = parse_evidence(row.get("Evidence", ""))
    if evidence is None:
        return "UNBOUND"
    if evidence["exit"] != 0:
        return "FAIL"
    if src_digest(root, bound_paths(row, tables)) != evidence["src"]:
        return "STALE"
    return "CURRENT"


def run_probe(row: dict, tables: dict, root: Path, actor: str, timeout: int = 600) -> dict:
    """Execute the Probe, retain its full output on disk, return the evidence cell."""
    command = row.get("Probe", "").strip()
    if not command:
        raise ValueError(f"{row['ID']} has no Probe")
    src = src_digest(root, bound_paths(row, tables))
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        exit_code, output = completed.returncode, completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        output = f"timeout after {timeout}s\n{exc.stdout or ''}{exc.stderr or ''}"
    at = utc_now()
    out_dir = contained_path(root, f".pacer/probes/{row['ID']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / (at.replace(":", "") + ".txt")
    output_path.write_text(
        f"$ {command}\n# actor={actor} exit={exit_code} at={at}\n{output}", encoding="utf-8"
    )
    out = hashlib.sha256(output.encode("utf-8")).hexdigest()[:7]
    cell = format_evidence(git_rev(root), src, exit_code, out, at)
    return {
        "evidence": cell,
        "exit": exit_code,
        "output_path": output_path.relative_to(root).as_posix(),
        "freshness": "CURRENT" if exit_code == 0 else "FAIL",
    }
