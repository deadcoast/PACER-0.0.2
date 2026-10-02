"""The application boundary shared by the CLI, the hooks and the MCP server."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pacer import migrate
from pacer.cards import card
from pacer.commands import Editor
from pacer.config import read_config, render_config
from pacer.frames import Compiler, active_pace
from pacer.gates import edit_decision, stop_decision
from pacer.layout import FORMAT, STATE_DIR, register_name
from pacer.probe import freshness, run_probe
from pacer.provider import Provider, select_provider
from pacer.rank import rank
from pacer.schema import HEADERS, REF_PATTERN, REGISTER_OF, REGISTERS, TAG_PATTERN, refs
from pacer.store import Snapshot, Store, atomic_write, encode_csv
from pacer.tree import render_tree
from pacer.validation import validate_web

MAX_BATCH = 200


class Service:
    """Every operation on one governed project."""

    def __init__(self, root: Path):
        self.store = Store(root)
        self.root = self.store.root
        self.layout = self.store.layout
        self.config = read_config(self.root)
        self._provider: Provider | None = None

    @property
    def provider(self) -> Provider:
        if self._provider is None:
            self._provider = select_provider(
                self.root, self.config["provider"], self.config["exclude"]
            )
        return self._provider

    def _compiler(self, snapshot: Snapshot) -> Compiler:
        return Compiler(snapshot.tables, self.root, self.store, self.provider, self.config)

    def _validate(self, snapshot: Snapshot) -> dict:
        return validate_web(
            snapshot.tables, self.root, snapshot.headers, snapshot.archive, self.config["tier"]
        )

    def _commit(self, snapshot: Snapshot, editor: Editor) -> str:
        """Validate, publish, then append the events; nothing is written on failure."""
        report = self._validate(snapshot)
        if not report["valid"]:
            raise ValueError(report["errors"][0])
        revision = self.store.publish(snapshot, snapshot.encode())
        for event in editor.events:
            self.store.ledger_append(event)
        return revision

    # -- reads ---------------------------------------------------------------
    def frame(self, kind: str, focus: str = "") -> str:
        with self.store.locked():
            compiler = self._compiler(self.store.load())
            if kind == "session":
                return compiler.session()
            if kind == "edit":
                return compiler.edit(focus)
            if kind == "prompt":
                return compiler.prompt(focus)
            if kind == "stop":
                return stop_decision(compiler)["text"]
            raise ValueError("frame kind must be session, edit, prompt or stop")

    def q(self, query: str, limit: int = 40) -> str:
        """Cards for an ID and its neighbours, a #tag, a register, register:STATUS or a path."""
        with self.store.locked():
            snapshot = self.store.load()
            tables, compiler = snapshot.tables, self._compiler(snapshot)
            query = query.strip()
            if REF_PATTERN.fullmatch(query):
                if query in compiler.index:
                    keys = [k for d, k in rank(tables, self.provider, [query]) if d <= 2]
                else:
                    return self._archived_card(snapshot, query)
            elif TAG_PATTERN.fullmatch(query):
                keys = [
                    r["ID"]
                    for register in REGISTERS
                    for r in tables[register]
                    if query in r.get("Tags", "").split()
                ]
            elif ":" in query and query.split(":", 1)[0] in REGISTERS:
                register, status = query.split(":", 1)
                keys = [r["ID"] for r in tables[register] if r.get("Status") == status]
            elif query in REGISTERS:
                keys = [r["ID"] for r in tables[query]]
            else:
                return compiler.edit(query.replace("\\", "/"))
            lines = [compiler.render(k) for k in keys[:limit]]
            if len(keys) > limit:
                lines.append(f"+{len(keys) - limit} more")
            return "\n".join(lines)

    def _archived_card(self, snapshot: Snapshot, key: str) -> str:
        register = REGISTER_OF.get(key.split("-")[0], "")
        for row in snapshot.archive.get(register, []):
            if row["ID"] == key:
                return card(register, row, {"archived": "1"})
        raise ValueError(f"REFUSAL: Unknown ID {key}")

    def log(self, row_id: str | None, limit: int = 20) -> list[dict]:
        return self.store.ledger_read(row_id, limit)

    def validate(self) -> dict:
        with self.store.locked():
            snapshot = self.store.load()
            return {"revision": snapshot.revision, **self._validate(snapshot)}

    def edit_decision(self, path: str) -> dict:
        with self.store.locked():
            return edit_decision(self._compiler(self.store.load()), path)

    def tree(self) -> str:
        with self.store.locked():
            return render_tree(self.store.load().tables, self.config)

    # -- writes --------------------------------------------------------------
    def write(self, operations: list[dict], actor: str, preview: bool = False) -> dict:
        """Apply a batch of lexicon operations atomically."""
        _check_actor(actor)
        if not 1 <= len(operations) <= MAX_BATCH:
            raise ValueError(f"A batch holds 1..{MAX_BATCH} operations")
        with self.store.locked():
            snapshot = self.store.load()
            editor = Editor(snapshot.tables, snapshot.archive, actor, self.root)
            for op in operations:
                try:
                    editor.execute(op)
                except (KeyError, TypeError, AttributeError) as exc:
                    raise ValueError(
                        f"Malformed {op.get('op', 'unknown')} operation: {exc}"
                    ) from exc
            report = self._validate(snapshot)
            if not report["valid"]:
                raise ValueError(report["errors"][0])
            result = {
                "preview": preview,
                "changed_ids": sorted(editor.changed),
                "events": len(editor.events),
                "warnings": report["warnings"],
            }
            if preview:
                return {**result, "revision": snapshot.revision}
            return {**result, "revision": self._commit(snapshot, editor)}

    def probe(self, row_id: str, actor: str) -> dict:
        """Run a requirement's Probe and record its evidence.

        The command runs with the project lock released. It may take minutes, and it may
        use PACER itself (a test suite, `pacer validate`); holding the lock would stall
        every hook for that long and deadlock the second case.
        """
        _check_actor(actor)

        def requirement(snapshot: Snapshot) -> dict:
            row = next((r for r in snapshot.tables["organism"] if r["ID"] == row_id), None)
            if row is None:
                raise ValueError(f"REFUSAL: Unknown ID {row_id}")
            return row

        with self.store.locked():
            before = self.store.load()
            row = requirement(before)
        command = row["Probe"]
        result = run_probe(row, before.tables, self.root, actor, self.config["probe_timeout"])
        with self.store.locked():
            snapshot = self.store.load()
            row = requirement(snapshot)
            if row["Probe"] != command:
                raise ValueError(f"{row_id}: Probe changed while it ran; run it again")
            row["Evidence"] = result["evidence"]
            # The digest was taken before the run; a file edited meanwhile shows as STALE.
            result["freshness"] = freshness(row, snapshot.tables, self.root)
            editor = Editor(snapshot.tables, snapshot.archive, actor, self.root)
            editor.event("probe", row_id, result)
            self._commit(snapshot, editor)
            # Per-file digests stay in the ledger event; the caller gets the card instead.
            shown = {key: value for key, value in result.items() if key != "files"}
            return {"id": row_id, **shown, "card": self._compiler(snapshot).render(row_id)}

    def record(
        self,
        edited: list[str],
        renames: list[tuple[str, str]],
        actor: str,
        *,
        register_new: bool,
    ) -> str:
        """Record source changes against the active pace; one line of feedback or none.

        `renames` are followed in every path cell. An edited file that has no asset
        row is registered only when `register_new` is set: a deliberate edit earns a
        row, a shell command that happened to write files does not.
        """
        with self.store.locked():
            snapshot = self.store.load()
            tables = snapshot.tables
            editor = Editor(tables, snapshot.archive, actor, self.root)
            known = {r["Path"] for r in tables["overlord"]}
            followed = []
            for old, new in renames:
                if old in known and new not in known:
                    editor.execute({"op": "repath", "from": old, "to": new})
                    followed.append(f"{old} -> {new}")
                    known = {r["Path"] for r in tables["overlord"]}
            pace = active_pace(tables, self.store)
            registered: list[str] = []
            touched: list[str] = []
            unknown: list[str] = []
            for path in dict.fromkeys(edited):
                if path not in known and not register_new:
                    unknown.append(path)
                    continue
                editor.execute({"op": "touch", "path": path, "pace": pace["ID"] if pace else ""})
                new = editor.events[-1]["detail"].get("new")
                (registered if new else touched).append(new or path)
            if not editor.events:
                return _summary(followed, registered, touched, unknown, [])
            report = self._validate(snapshot)
            if not report["valid"]:
                return f"pacer: change not recorded: {report['errors'][0]}"
            self._commit(snapshot, editor)
            assets = {r["ID"] for r in tables["overlord"] if r["Path"] in set(edited)}
            # Measured, not presumed: a probe may already have run on the edited files.
            stale = [
                r["ID"]
                for r in tables["organism"]
                if set(refs(r.get("Binds", ""))) & assets
                and freshness(r, tables, self.root) == "STALE"
            ]
            return _summary(followed, registered, touched, unknown, stale)

    def stop(self, actor: str) -> dict:
        """Evaluate the gate and write the durable next action on the active pace."""
        with self.store.locked():
            snapshot = self.store.load()
            decision = stop_decision(self._compiler(snapshot))
            pace = active_pace(snapshot.tables, self.store)
            if pace and pace.get("Next") != decision["next"]:
                pace["Next"] = decision["next"]
                editor = Editor(snapshot.tables, snapshot.archive, actor, self.root)
                editor.event("checkpoint", pace["ID"], {"next": decision["next"]})
                self._commit(snapshot, editor)
            return decision

    def sync(self, actor: str, preview: bool = True) -> dict:
        """Reconcile the asset register with the tree: retire rows whose file is gone."""
        _check_actor(actor)
        with self.store.locked():
            snapshot = self.store.load()
            gone = sorted(
                r["ID"]
                for r in snapshot.tables["overlord"]
                if not (self.root / r["Path"]).is_file()
            )
            result = {"preview": preview, "missing": gone}
            if preview or not gone:
                return result
            editor = Editor(snapshot.tables, snapshot.archive, actor, self.root)
            editor.execute({"op": "archive", "ids": gone, "cascade": True})
            self._commit(snapshot, editor)
            return {**result, "archived": sorted(editor.changed & set(gone))}

    def recover(self) -> dict:
        with self.store.locked():
            return self.store.recover()

    # -- lifecycle -----------------------------------------------------------
    def init(self, name: str = "", tier: str = "prototype") -> dict:
        """Create `.pacer/` with empty registers; never touches an existing one."""
        if self.layout.governed():
            raise ValueError(f"{STATE_DIR}/ already exists here; init never overwrites")
        if migrate.detect(self.root):
            raise ValueError("An older PACER format is present; run `pacer migrate` instead")
        with self.store.locked(create=True):
            for register in REGISTERS:
                data = encode_csv(HEADERS[register], [])
                atomic_write(self.layout.state / register_name(register), data)
            text = render_config(name or self.root.name, tier)
            atomic_write(self.layout.config, text.encode("utf-8"))
            for path, text in self.layout.git_files().items():
                atomic_write(path, text.encode("utf-8"))
            detail = {"format": FORMAT}
            self.store.ledger_append({"actor": "init", "op": "init", "id": "-", "detail": detail})
        notes = [note for note in (migrate.unignore_state(self.root),) if note]
        if self._ignored():
            notes.append(f"{STATE_DIR}/ is git-ignored; registers will not be tracked")
        self.config = read_config(self.root)
        return {"root": str(self.root), "state": STATE_DIR, "notes": notes, **self.validate()}

    def migrate(self, source: str | None = None, *, actor: str, preview: bool = True) -> dict:
        """Bring an older PACER project to the current layout; preview unless told to apply."""
        _check_actor(actor)
        plan = migrate.plan(self.root, source)
        if preview:
            return {"preview": True, **migrate.describe(self.root, plan)}
        result = migrate.apply(self.root, plan, actor)
        self.config = read_config(self.root)
        if result["applied"] and self._ignored():
            result["notes"].append(
                f"{STATE_DIR}/ is still git-ignored; registers will not be tracked"
            )
        return {"preview": False, **result}

    def _ignored(self) -> bool:
        """True when git would ignore the registers, which silently loses project state."""
        try:
            out = subprocess.run(
                ["git", "check-ignore", "-q", f"{STATE_DIR}/{register_name('todo')}"],
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return out.returncode == 0


def _check_actor(actor: str) -> None:
    if not actor.strip() or "\n" in actor or len(actor) > 100:
        raise ValueError("A short single-line actor is required")


def _summary(followed, registered, touched, unknown, stale) -> str:
    parts = []
    if followed:
        parts.append("followed " + "; ".join(followed[:3]) + _more(followed, 3))
    if registered:
        parts.append("registered #unpurposed " + ", ".join(registered[:5]) + _more(registered, 5))
    if touched:
        parts.append("touched " + ", ".join(touched[:5]) + _more(touched, 5))
    if unknown:
        parts.append(f"{len(unknown)} changed path(s) have no asset row")
    if stale:
        parts.append("stale " + ", ".join(stale))
    return "pacer: " + " | ".join(parts) if parts else ""


def _more(items: list, shown: int) -> str:
    return f" (+{len(items) - shown})" if len(items) > shown else ""
