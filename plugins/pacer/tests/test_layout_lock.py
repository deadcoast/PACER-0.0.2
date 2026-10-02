import subprocess
import sys
import textwrap
import time

import pytest

from pacer.layout import Layout, find_root, register_name
from pacer.lock import FileLock, LockTimeout


def test_every_name_is_lowercase_pacer_and_lives_under_one_directory(tmp_path):
    layout = Layout(tmp_path)
    assert register_name("todo") == "todo.pacer.csv"
    paths = [
        layout.config,
        layout.ledger,
        layout.register("overlord"),
        layout.archived("nodule"),
        layout.lock,
        layout.journal,
        layout.hook_state,
        layout.provider_cache,
        layout.probe_dir("OGM-001"),
        *layout.git_files(),
    ]
    assert all(p.is_relative_to(tmp_path / ".pacer") for p in paths)
    assert layout.config.name == "project.pacer.toml"
    assert layout.ledger.name == "ledger.pacer.jsonl"
    assert (
        layout.archived("nodule").relative_to(layout.state).as_posix() == "archive/nodule.pacer.csv"
    )
    assert layout.lock.is_relative_to(layout.run)
    assert not any("PACER" in p.name for p in paths)


def test_find_root_needs_the_project_frame(tmp_path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_root(nested) is None
    (tmp_path / ".pacer").mkdir()
    assert find_root(nested) is None  # a bare directory is not a governed project
    (tmp_path / ".pacer" / "project.pacer.toml").write_text("")
    assert find_root(nested) == tmp_path.resolve()
    assert Layout(tmp_path).governed()


def test_lock_excludes_another_process_and_is_released_on_exit(tmp_path):
    path = tmp_path / "run" / "lock"
    holder = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(__import__("pacer").__path__[0] + "/..")!r})
        from pacer.lock import FileLock
        with FileLock({str(path)!r}):
            print("held", flush=True)
            time.sleep(1.2)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "held"
    started = time.monotonic()
    with pytest.raises(LockTimeout), FileLock(path, timeout=0.3):
        pass
    assert time.monotonic() - started < 1.0
    child.wait(timeout=10)
    with FileLock(path, timeout=2.0):
        pass  # the holder exited, so the lock is free
    with FileLock(path, timeout=2.0):
        pass  # and it can be taken again after a clean release
