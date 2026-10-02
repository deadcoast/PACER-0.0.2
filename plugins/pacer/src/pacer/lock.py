"""Inter-process file lock on the standard library alone.

The hook path runs on every edit and must not need an environment to be built,
so the runtime carries no third-party dependency. The operating system releases
the lock if the holder dies, which is the property the writer relies on.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import IO

# `sys.platform` rather than `os.name`: type checkers narrow on it, so each branch
# is checked against the modules that exist on its own platform.
if sys.platform == "win32":
    import msvcrt

    def _acquire(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _release(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class LockTimeout(Exception):
    """The lock stayed held past the caller's deadline."""


class FileLock:
    """Exclusive advisory lock; not re-entrant, one holder per file."""

    def __init__(self, path: Path, timeout: float = 5.0, poll: float = 0.02):
        self.path, self.timeout, self.poll = Path(path), timeout, poll
        self._handle: IO[bytes] | None = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        handle = open(self.path, "a+b")  # noqa: SIM115 - held for the lock's lifetime
        while True:
            try:
                _acquire(handle)
                self._handle = handle
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise LockTimeout(str(self.path)) from None
                time.sleep(self.poll)

    def __exit__(self, *exc) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                _release(handle)
            finally:
                handle.close()
