"""Where PACER lives in a project.

Everything PACER owns sits in one directory, `.pacer/`, so a governed project
gains a single entry and nothing collides with the project's own tree:

    .pacer/
      project.pacer.toml      project frame; its presence marks the project root
      todo.pacer.csv          work tree        (PAC)
      overlord.pacer.csv      source assets    (OVR)
      organism.pacer.csv      requirements     (OGM)
      nodule.pacer.csv        scoped intake    (NDL)
      decision.pacer.csv      decisions        (DEC)
      ledger.pacer.jsonl      append-only event history
      archive/<register>.pacer.csv   retired rows, same columns as the live register
      .gitignore              ignores run/
      .gitattributes          no end-of-line conversion: state is byte-exact everywhere
      run/                    lock, journal, probe output, caches; never tracked

File names follow `<name>.pacer.<ext>`. This module is the only place those
names are spelled; every other module asks a Layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FORMAT = "3.0"
STATE_DIR = ".pacer"
CONFIG_NAME = "project.pacer.toml"
LEDGER_NAME = "ledger.pacer.jsonl"
REGISTER_SUFFIX = ".pacer.csv"
ARCHIVE_DIR = "archive"
RUN_DIR = "run"
# Git settings the state directory carries with it, so they hold in every clone.
GIT_FILES = {
    ".gitignore": "# PACER runtime state: lock, journal, probe output, caches.\nrun/\n",
    ".gitattributes": (
        "# PACER state is byte-exact: no end-of-line conversion on any platform.\n* -text\n"
    ),
}


def register_name(register: str) -> str:
    """File name of a register, e.g. `todo.pacer.csv`."""
    return f"{register}{REGISTER_SUFFIX}"


@dataclass(frozen=True)
class Layout:
    """Resolve every PACER path of one project from its root."""

    root: Path

    @property
    def state(self) -> Path:
        return self.root / STATE_DIR

    @property
    def config(self) -> Path:
        return self.state / CONFIG_NAME

    @property
    def ledger(self) -> Path:
        return self.state / LEDGER_NAME

    @property
    def archive(self) -> Path:
        return self.state / ARCHIVE_DIR

    def git_files(self) -> dict[Path, str]:
        """The git settings files of the state directory and their content."""
        return {self.state / name: text for name, text in GIT_FILES.items()}

    @property
    def run(self) -> Path:
        return self.state / RUN_DIR

    @property
    def lock(self) -> Path:
        return self.run / "lock"

    @property
    def journal(self) -> Path:
        return self.run / "transaction.json"

    @property
    def hook_state(self) -> Path:
        return self.run / "hook.json"

    @property
    def provider_cache(self) -> Path:
        return self.run / "provider-cache.json"

    def register(self, register: str) -> Path:
        return self.state / register_name(register)

    def archived(self, register: str) -> Path:
        return self.archive / register_name(register)

    def probe_dir(self, row_id: str) -> Path:
        return self.run / "probes" / row_id

    def governed(self) -> bool:
        return self.config.is_file()

    def relative(self, path: Path) -> str:
        """Project-relative POSIX form, the only form stored or shown."""
        return path.resolve().relative_to(self.root.resolve()).as_posix()


def find_root(start: Path) -> Path | None:
    """Nearest ancestor that PACER governs; None means stay silent."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / STATE_DIR / CONFIG_NAME).is_file():
            return candidate
    return None
