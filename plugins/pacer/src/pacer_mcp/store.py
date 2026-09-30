"""CSV persistence with one applying writer, compare-and-swap and crash recovery."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from filelock import FileLock, Timeout

from pacer_mcp.schema import HEADERS, ID_PATTERN, LEDGER, REGISTERS, contained_path, utc_now

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
    """Serialize quoted UTF-8 CSV without dropping custom columns."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


@dataclass
class Snapshot:
    """An isolated candidate web plus exact input bytes for concurrency control."""

    tables: dict[str, list[dict[str, str]]]
    headers: dict[str, list[str]]
    files: dict[str, bytes]

    @property
    def revision(self) -> str:
        """Bind a revision to paths and bytes, including canonical archived rows."""
        return digest(
            json.dumps(
                {k: digest(v) for k, v in sorted(self.files.items())}, separators=(",", ":")
            ).encode()
        )

    def encode(self) -> dict[str, bytes]:
        """Keep each absorbed nodule in exactly one canonical archive location."""
        result = {}
        for register, rows in self.tables.items():
            headers = list(self.headers[register])
            for row in rows:
                headers.extend(k for k in row if k not in headers)
            if register == "nodule":
                live = [r for r in rows if r.get("Status") != "ABSORBED"]
                result["nodule.PACER.csv"] = encode_csv(headers, live)
                for row in rows:
                    if row.get("Status") == "ABSORBED":
                        result[f"archive/nodules/{row['ID']}.PACER.csv"] = encode_csv(
                            headers, [row]
                        )
            else:
                result[f"{register}.PACER.csv"] = encode_csv(headers, rows)
        for name, data in result.items():
            parse_csv(data, name)
        return result


class Store:
    """Own canonical register I/O; callers hold locked() across read and publication."""

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Project root must be a directory")

    @contextmanager
    def locked(self):
        """Serialize reads and writes using a crash-released OS file lock."""
        state = contained_path(self.root, ".pacer")
        state.mkdir(exist_ok=True)
        lock_path = contained_path(self.root, ".pacer/lock")
        try:
            with FileLock(lock_path, timeout=5):
                yield
        except Timeout as exc:
            raise ValueError("PACER writer busy; retry with a fresh revision") from exc

    def load(self, *, missing_ok: bool = False, pending_ok: bool = False) -> Snapshot:
        """Load rows under the lock, refusing a partial interrupted publication."""
        journal = contained_path(self.root, ".pacer/transaction.json")
        if journal.exists() and not pending_ok:
            raise ValueError("PACER recovery required; run recover before queries or writes")
        files = {}
        headers = {}
        tables: dict[str, list[dict[str, str]]] = {}
        for register in REGISTERS:
            name = f"{register}.PACER.csv"
            path = contained_path(self.root, name)
            if not path.exists():
                if missing_ok:
                    headers[register], tables[register] = list(HEADERS[register]), []
                    continue
                raise ValueError(f"Missing register {name}; initialize or reconcile the project")
            files[name] = path.read_bytes()
            headers[register], tables[register] = parse_csv(files[name], name)
        archive = contained_path(self.root, "archive/nodules")
        if archive.exists():
            for path in sorted(archive.glob("*.PACER.csv")):
                name = path.relative_to(self.root).as_posix()
                path = contained_path(self.root, name)
                files[name] = path.read_bytes()
                _, rows = parse_csv(files[name], name)
                expected_id = path.name.removesuffix(".PACER.csv")
                if (
                    len(rows) != 1
                    or rows[0].get("Status") != "ABSORBED"
                    or rows[0].get("ID") != expected_id
                ):
                    raise ValueError(f"Invalid canonical nodule archive {name}")
                # Keep the root file's actual header for validation. Archived
                # row keys are validated separately and encode preserves extras.
                tables["nodule"].extend(rows)
        return Snapshot(tables, headers, files)

    def publish(self, before: Snapshot, after: dict[str, bytes]) -> str:
        """Stage the validated result, persist a journal, then atomically replace each file."""
        if self.load(missing_ok=True).revision != before.revision:
            raise ValueError("Stale revision; query the current web before applying")
        changes = {}
        for name in sorted(set(before.files) | set(after)):
            if before.files.get(name) == after.get(name):
                continue
            self._register_path(name)
            changes[name] = {
                "before": digest(before.files[name]) if name in before.files else None,
                "after": digest(after[name]) if name in after else None,
                "data": base64.b64encode(after[name]).decode() if name in after else None,
            }
        if not changes:
            return before.revision
        journal = contained_path(self.root, ".pacer/transaction.json")
        _atomic_write(
            journal,
            json.dumps(
                {
                    "version": 1,
                    "changes": changes,
                    "before": {name: digest(data) for name, data in before.files.items()},
                }
            ).encode(),
        )
        self.recover()
        return self.load().revision

    def recover(self) -> dict:
        """Roll forward a journal only when all current files match known old/new bytes."""
        journal = contained_path(self.root, ".pacer/transaction.json")
        if not journal.exists():
            return {"recovered": False}
        try:
            payload = json.loads(journal.read_text(encoding="utf-8"))
            if payload["version"] != 1 or not isinstance(payload["changes"], dict):
                raise ValueError("unsupported journal")
            changes = payload["changes"]
            decoded = {}
            for name, change in changes.items():
                path = self._register_path(name)
                current = digest(path.read_bytes()) if path.exists() else None
                if current not in {change["before"], change["after"]}:
                    raise ValueError(f"Recovery conflict: {name}; preserve journal and reconcile")
                data = (
                    base64.b64decode(change["data"], validate=True)
                    if change["data"] is not None
                    else None
                )
                if (digest(data) if data is not None else None) != change["after"]:
                    raise ValueError(f"Journal digest mismatch: {name}")
                if data is not None:
                    parse_csv(data, name)
                elif not name.startswith("archive/nodules/"):
                    raise ValueError("Journal cannot delete a persistent register")
                decoded[name] = data
            # Unchanged files also belong to the transaction's input revision.
            current_files = {}
            for register in REGISTERS:
                name = f"{register}.PACER.csv"
                path = self._register_path(name)
                if path.exists():
                    current_files[name] = path.read_bytes()
            archive = contained_path(self.root, "archive/nodules")
            if archive.exists():
                for path in archive.glob("*.PACER.csv"):
                    name = path.relative_to(self.root).as_posix()
                    current_files[name] = self._register_path(name).read_bytes()
            baseline = payload["before"]
            for name in set(baseline) | set(current_files):
                if name in changes:
                    continue
                actual = digest(current_files[name]) if name in current_files else None
                if name not in baseline or actual != baseline[name]:
                    raise ValueError(f"Recovery conflict: {name}; complete input revision changed")
            candidate = dict(current_files)
            for name, data in decoded.items():
                if data is None:
                    candidate.pop(name, None)
                else:
                    candidate[name] = data
            tables: dict[str, list[dict[str, str]]] = {name: [] for name in REGISTERS}
            headers = {}
            for name, data in candidate.items():
                register = "nodule" if name.startswith("archive/") else name.split(".")[0]
                columns, rows = parse_csv(data, name)
                if name.startswith("archive/") and (
                    len(rows) != 1
                    or rows[0].get("Status") != "ABSORBED"
                    or rows[0].get("ID") != Path(name).name.removesuffix(".PACER.csv")
                ):
                    raise ValueError(f"Invalid canonical nodule archive {name}")
                if register not in headers or not name.startswith("archive/"):
                    headers[register] = columns
                tables[register].extend(rows)
            from pacer_mcp.validation import validate_web

            report = validate_web(tables, self.root, headers)
            if not report["valid"]:
                raise ValueError("Recovery candidate invalid: " + report["errors"][0])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid PACER recovery journal: {exc}") from exc
        # All paths and preconditions have been checked before the first replacement.
        for name, data in decoded.items():
            path = self._register_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            if data is None:
                path.unlink(missing_ok=True)
            elif not path.exists() or digest(path.read_bytes()) != digest(data):
                _atomic_write(path, data)
        journal.unlink()
        return {"recovered": True, "files": sorted(decoded)}

    def ledger_append(self, entry: dict) -> None:
        """Append one dated event; history is never rewritten."""
        line = json.dumps({"at": utc_now(), **entry}, ensure_ascii=False, separators=(",", ":"))
        path = contained_path(self.root, LEDGER)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def ledger_read(self, row_id: str | None, limit: int) -> list[dict]:
        """Return the newest matching events, oldest first within the window."""
        path = contained_path(self.root, LEDGER)
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if (
                row_id is None
                or entry.get("id") == row_id
                or row_id in str(entry.get("detail", ""))
            ):
                entries.append(entry)
        return entries[-limit:]

    def _register_path(self, name: str) -> Path:
        valid_root = name in {f"{r}.PACER.csv" for r in HEADERS}
        parts = name.split("/")
        archive_id = parts[-1].removesuffix(".PACER.csv")
        valid_archive = (
            len(parts) == 3
            and parts[:2] == ["archive", "nodules"]
            and parts[-1].endswith(".PACER.csv")
            and ID_PATTERN.fullmatch(archive_id)
            and archive_id.startswith("NDL-")
        )
        if not (valid_root or valid_archive):
            raise ValueError(f"Non-register transaction path: {name}")
        return contained_path(self.root, name)


def _atomic_write(path: Path, content: bytes) -> None:
    import tempfile

    descriptor, temp_name = tempfile.mkstemp(prefix=".pacer-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)
