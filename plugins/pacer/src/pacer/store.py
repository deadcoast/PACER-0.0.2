"""Persistence for `.pacer/`: one writer, atomic publication, crash recovery, event ledger.

A Snapshot holds two views of each register: live rows, which the compiler reads,
and archived rows, which only keep identifiers resolvable. Both are CSV files with
the same columns. Publication writes a journal first so an interrupted multi-file
replace can be rolled forward, never left half-applied.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from pacer.layout import ARCHIVE_DIR, STATE_DIR, Layout, register_name
from pacer.lock import FileLock, LockTimeout
from pacer.schema import HEADERS, REGISTERS, utc_now

JOURNAL_VERSION = 2
STATE_FILES = {register_name(r): r for r in REGISTERS} | {
    f"{ARCHIVE_DIR}/{register_name(r)}": r for r in REGISTERS
}
_CSV_LIMIT_LOCK = Lock()


def digest(content: bytes) -> str:
    """Hash exact bytes for revision and recovery checks."""
    return hashlib.sha256(content).hexdigest()


def parse_csv(content: bytes, name: str) -> tuple[list[str], list[dict[str, str]]]:
    """Reject lossy CSV parsing, including duplicate headers and ragged records."""
    # A decoded field cannot exceed its already-loaded UTF-8 input in length.
    # Grow the process-wide limit under a lock; another parse must not shrink it.
    with _CSV_LIMIT_LOCK:
        csv.field_size_limit(max(csv.field_size_limit(), len(content)))
    try:
        reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        headers = next(reader)
        if not headers or any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
            raise ValueError("empty or duplicate columns")
        rows = []
        for values in reader:
            if len(values) != len(headers):
                raise ValueError(f"ragged row at line {reader.line_num}")
            rows.append(dict(zip(headers, values, strict=True)))
        return headers, rows
    except (UnicodeError, csv.Error, StopIteration, ValueError) as exc:
        raise ValueError(f"Invalid CSV {name}: {exc}") from exc


def encode_csv(headers: list[str], rows: list[dict[str, str]]) -> bytes:
    """Serialize UTF-8 CSV with LF line ends; unknown project columns are kept."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n", restval="")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    """Replace a file in one step so readers never see a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".pacer-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


@dataclass
class Snapshot:
    """One consistent read of the state directory, plus the exact bytes it came from."""

    tables: dict[str, list[dict[str, str]]]
    archive: dict[str, list[dict[str, str]]]
    headers: dict[str, list[str]]
    files: dict[str, bytes]

    @property
    def revision(self) -> str:
        """Identity of this exact state: every file name bound to its bytes."""
        names = {k: digest(v) for k, v in sorted(self.files.items())}
        return digest(json.dumps(names, separators=(",", ":")).encode())

    def archived_ids(self) -> set[str]:
        return {r["ID"] for rows in self.archive.values() for r in rows}

    def encode(self) -> dict[str, bytes]:
        """Serialize every register; an archive file exists once it has ever held a row."""
        result = {}
        for register in REGISTERS:
            headers = list(self.headers[register])
            for row in [*self.tables[register], *self.archive[register]]:
                headers.extend(k for k in row if k not in headers)
            name = register_name(register)
            result[name] = encode_csv(headers, self.tables[register])
            archive_name = f"{ARCHIVE_DIR}/{name}"
            if self.archive[register] or archive_name in self.files:
                result[archive_name] = encode_csv(headers, self.archive[register])
        return result


class Store:
    """Own all I/O under `.pacer/`; callers hold locked() across read and publication."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Project root must be a directory")
        self.layout = Layout(self.root)

    @contextmanager
    def locked(self, *, create: bool = False):
        """Serialize readers and the writer across processes."""
        if not create and not self.layout.state.is_dir():
            raise ValueError(f"No {STATE_DIR}/ in {self.root}; run `pacer init` or `pacer migrate`")
        try:
            with FileLock(self.layout.lock, timeout=5.0):
                yield
        except LockTimeout as exc:
            raise ValueError("PACER is busy in another process; retry") from exc

    def _state_path(self, name: str) -> Path:
        if name not in STATE_FILES:
            raise ValueError(f"Not a PACER state file: {name}")
        return self.layout.state / name

    def _read_files(self) -> dict[str, bytes]:
        return {
            name: self._state_path(name).read_bytes()
            for name in STATE_FILES
            if self._state_path(name).is_file()
        }

    @staticmethod
    def _assemble(files: dict[str, bytes], *, missing_ok: bool) -> Snapshot:
        tables: dict[str, list[dict[str, str]]] = {}
        archive: dict[str, list[dict[str, str]]] = {}
        headers: dict[str, list[str]] = {}
        for register in REGISTERS:
            name = register_name(register)
            tables[register], archive[register] = [], []
            headers[register] = list(HEADERS[register])
            if name in files:
                headers[register], tables[register] = parse_csv(files[name], name)
            elif not missing_ok:
                raise ValueError(f"Missing register {STATE_DIR}/{name}; run `pacer migrate`")
            archive_name = f"{ARCHIVE_DIR}/{name}"
            if archive_name in files:
                _, archive[register] = parse_csv(files[archive_name], archive_name)
        return Snapshot(tables, archive, headers, dict(files))

    def load(self, *, missing_ok: bool = False, pending_ok: bool = False) -> Snapshot:
        """Read every register; refuse while an interrupted publication is pending."""
        if self.layout.journal.exists() and not pending_ok:
            raise ValueError("An interrupted PACER write is pending; run `pacer recover`")
        return self._assemble(self._read_files(), missing_ok=missing_ok)

    def publish(self, before: Snapshot, after: dict[str, bytes]) -> str:
        """Journal the validated result, then replace each changed file atomically."""
        if self.load(missing_ok=True).revision != before.revision:
            raise ValueError("State changed underneath this write; reload and retry")
        missing = set(before.files) - set(after)
        if missing:
            raise ValueError(f"A write may not delete state files: {', '.join(sorted(missing))}")
        changes = {}
        for name in sorted(after):
            if before.files.get(name) == after[name]:
                continue
            self._state_path(name)
            changes[name] = {
                "before": digest(before.files[name]) if name in before.files else None,
                "after": digest(after[name]),
                "data": base64.b64encode(after[name]).decode(),
            }
        if not changes:
            return before.revision
        journal = {
            "version": JOURNAL_VERSION,
            "changes": changes,
            "before": {name: digest(data) for name, data in before.files.items()},
        }
        atomic_write(self.layout.journal, json.dumps(journal).encode())
        self.recover()
        return self.load().revision

    def recover(self) -> dict:
        """Roll a journal forward only when every file still matches a known old or new state."""
        journal = self.layout.journal
        if not journal.exists():
            return {"recovered": False}
        from pacer.validation import validate_web

        try:
            payload = json.loads(journal.read_text(encoding="utf-8"))
            if payload["version"] != JOURNAL_VERSION or not isinstance(payload["changes"], dict):
                raise ValueError("unsupported journal version")
            decoded: dict[str, bytes] = {}
            for name, change in payload["changes"].items():
                path = self._state_path(name)
                current = digest(path.read_bytes()) if path.exists() else None
                if current not in {change["before"], change["after"]}:
                    raise ValueError(
                        f"{name} was edited outside PACER; keep the journal, reconcile"
                    )
                data = base64.b64decode(change["data"], validate=True)
                if digest(data) != change["after"]:
                    raise ValueError(f"journal digest mismatch for {name}")
                parse_csv(data, name)
                decoded[name] = data
            current_files = self._read_files()
            baseline = payload["before"]
            for name in set(baseline) | set(current_files):
                if name in decoded:
                    continue
                actual = digest(current_files[name]) if name in current_files else None
                if baseline.get(name) != actual:
                    raise ValueError(f"{name} changed since the interrupted write began")
            candidate = self._assemble(current_files | decoded, missing_ok=True)
            report = validate_web(candidate.tables, self.root, candidate.headers, candidate.archive)
            if not report["valid"]:
                raise ValueError("recovery candidate invalid: " + report["errors"][0])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unreadable PACER journal: {exc}") from exc
        # Every precondition holds; from here each replace is individually atomic.
        for name, data in decoded.items():
            path = self._state_path(name)
            if not path.exists() or digest(path.read_bytes()) != digest(data):
                atomic_write(path, data)
        journal.unlink()
        return {"recovered": True, "files": sorted(decoded)}

    # -- ledger --------------------------------------------------------------
    def ledger_append(self, entry: dict) -> None:
        """Append one dated event; history is never rewritten."""
        line = json.dumps({"at": utc_now(), **entry}, ensure_ascii=False, separators=(",", ":"))
        self.layout.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.layout.ledger.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")

    def ledger_read(self, row_id: str | None, limit: int) -> list[dict]:
        """Newest matching events, oldest first. Reads from the end; cost follows `limit`."""
        path = self.layout.ledger
        if limit <= 0 or not path.is_file():
            return []
        needle = row_id.encode("utf-8") if row_id else None
        found: list[dict] = []
        for raw in _lines_from_end(path):
            if needle is not None and needle not in raw:
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if row_id is not None and entry.get("id") != row_id:
                # Batch events (archive, repath) name their rows in the detail.
                detail = json.dumps(entry.get("detail", ""), ensure_ascii=False)
                if row_id not in detail:
                    continue
            found.append(entry)
            if len(found) >= limit:
                break
        found.reverse()
        return found


def _lines_from_end(path: Path, block: int = 65536) -> Iterator[bytes]:
    """Yield non-empty lines last to first without loading the file."""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        position = stream.tell()
        tail = b""
        while position > 0:
            size = min(block, position)
            position -= size
            stream.seek(position)
            lines = (stream.read(size) + tail).split(b"\n")
            tail = lines[0]
            for line in reversed(lines[1:]):
                if line.strip():
                    yield line
        if tail.strip():
            yield tail
