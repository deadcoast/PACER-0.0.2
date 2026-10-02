"""Probes are commands; evidence is one bounded cell; freshness is derived from bound files.

    rev:<git sha7|none> src:<bound-files sha7> exit:<n> out:<output sha7> at:<UTC>

`src` is a digest over the files a requirement binds, with line endings
normalised, so an uncommitted edit makes evidence STALE and a checkout on another
platform does not.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

from pacer.config import PROBE_TIMEOUT
from pacer.layout import Layout
from pacer.schema import contained_path, refs, utc_now
from pacer.validation import EVIDENCE_PATTERN

_PARSE = re.compile(r"rev:(\S+) src:(\S+) exit:(-?\d+) out:(\S+) at:(\S+)")


def _content(root: Path, path: str) -> bytes:
    """A bound file's bytes with line endings normalised; a marker when it cannot be read."""
    try:
        file = contained_path(root, path)
        return file.read_bytes().replace(b"\r\n", b"\n") if file.is_file() else b"MISSING"
    except (ValueError, OSError):
        return b"UNREADABLE"


def src_digest(root: Path, paths: list[str]) -> str:
    """Seven hex characters over sorted names and EOL-normalised bytes."""
    h = hashlib.sha256()
    for path in sorted(set(paths)):
        h.update(path.encode("utf-8") + b"\0" + _content(root, path) + b"\0")
    return h.hexdigest()[:7]


def file_digests(root: Path, paths: list[str]) -> dict[str, str]:
    """One digest per bound file. Kept in the ledger so a later STALE can name what moved."""
    return {p: hashlib.sha256(_content(root, p)).hexdigest()[:7] for p in sorted(set(paths))}


def git_rev(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "none"
    rev = out.stdout.strip()
    return rev if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{7}", rev) else "none"


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
    """Files a requirement constrains, through the assets its Binds names."""
    index = {r["ID"]: r for r in tables["overlord"]}
    return sorted({index[k]["Path"] for k in refs(row.get("Binds", "")) if k in index})


def freshness(row: dict, tables: dict, root: Path) -> str:
    """UNBOUND without evidence; FAIL on a nonzero exit; STALE when bound bytes moved."""
    evidence = parse_evidence(row.get("Evidence", ""))
    if evidence is None:
        return "UNBOUND"
    if evidence["exit"] != 0:
        return "FAIL"
    if src_digest(root, bound_paths(row, tables)) != evidence["src"]:
        return "STALE"
    return "CURRENT"


def _text(captured: str | bytes | None) -> str:
    """Output captured before a timeout arrives as bytes on some platforms."""
    if isinstance(captured, bytes):
        return captured.decode("utf-8", "replace")
    return captured or ""


def run_probe(
    row: dict, tables: dict, root: Path, actor: str, timeout: int = PROBE_TIMEOUT
) -> dict:
    """Execute the Probe, keep its full output under run/, return the evidence cell."""
    command = row.get("Probe", "").strip()
    if not command:
        raise ValueError(f"{row['ID']} has no Probe")
    layout = Layout(root)
    # Digests are taken before the run: a file edited while it runs must show as STALE.
    paths = bound_paths(row, tables)
    src, files = src_digest(root, paths), file_digests(root, paths)
    # A harness may start PACER with a bare PATH; keep this interpreter reachable.
    env = dict(os.environ)
    env["PATH"] = env.get("PATH", "") + os.pathsep + str(Path(sys.executable).parent)
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            shell=True,
            # Never inherit stdin: inside the MCP server it is the JSON-RPC pipe.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            # Tools write UTF-8; the platform's legacy code page would garble their output.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        exit_code, output = completed.returncode, completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        output = f"timeout after {timeout}s\n{_text(exc.stdout)}{_text(exc.stderr)}"
    at = utc_now()
    out_dir = layout.probe_dir(row["ID"])
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / (at.replace(":", "") + ".txt")
    output_path.write_text(
        f"$ {command}\n# actor={actor} exit={exit_code} at={at}\n{output}", encoding="utf-8"
    )
    out = hashlib.sha256(output.encode("utf-8")).hexdigest()[:7]
    return {
        "evidence": format_evidence(git_rev(root), src, exit_code, out, at),
        "exit": exit_code,
        "output_path": layout.relative(output_path),
        "freshness": "CURRENT" if exit_code == 0 else "FAIL",
        "files": files,
    }
