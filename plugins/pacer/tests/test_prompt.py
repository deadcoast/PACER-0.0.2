"""The prompts: keys, the chooser on rails, the path field; and their silence off a terminal."""

import io
from pathlib import Path

import pytest

from pacer.display import keys
from pacer.display.keys import DOWN, ENTER, ESC, TAB, UP, Scripted
from pacer.display.prompt import Field, Option, Scan, _window, ask_path, choose
from pacer.display.term import SGR

LIVE = {"PACER_DISPLAY": "live"}
OPTIONS = [
    Option("claude", "Claude Code", "3.1.0 installed"),
    Option("codex", "Codex", "not installed"),
    Option("all", "both"),
]


class Tty(io.StringIO):
    encoding = "utf-8"

    def isatty(self):
        return True


def frames(stream: io.StringIO) -> list[str]:
    """Each frame drawn, escapes removed."""
    return [SGR.sub("", f).replace("\r", "") for f in stream.getvalue().split("\x1b[?2026h")[1:]]


def test_scripted_keys_end_by_cancelling():
    source = Scripted([None, "a", DOWN])
    assert [source.read(0.1) for _ in range(5)] == [None, "a", DOWN, ESC, ESC]
    assert keys._continues(b"\xc3") and not keys._continues(b"\xc3\xa9")
    assert not keys._continues(b"a")


def test_chooser_moves_wraps_and_answers():
    out = Tty()
    script = Scripted([None, UP, DOWN, ENTER])  # up wraps to the end, down wraps back to the start
    assert (
        choose("update", "where?", OPTIONS, default=0, stream=out, keys=script, env=LIVE)
        == "claude"
    )
    drawn = frames(out)
    assert len(drawn) == 5  # four reads, then the closing frame
    first, last = drawn[0], drawn[-1]
    assert "PACER  update · where?" in first and "MIVIM · spec · vigiles" in first
    assert "▸ ━━━━━━━  Claude Code  3.1.0 installed" in first
    assert "───────  Codex        not installed" in first
    assert "↑↓ or 1–3" in first
    assert "✓ Claude Code" in last and "Codex" not in last
    assert out.getvalue().startswith("\x1b[?25l") and out.getvalue().endswith("\x1b[?25h")

    out = Tty()
    assert (
        choose("update", "where?", OPTIONS, stream=out, keys=Scripted(["2"]), env=LIVE) == "codex"
    )
    assert "✓ Codex" in frames(out)[-1]


def test_chooser_cancels_and_is_silent_off_a_terminal():
    out = Tty()
    assert (
        choose("update", "where?", OPTIONS, default=2, stream=out, keys=Scripted([ESC]), env=LIVE)
        is None
    )
    assert "· cancelled" in frames(out)[-1]
    quiet = io.StringIO()
    assert choose("update", "where?", OPTIONS, default=2, stream=quiet, env={}) == "all"
    assert quiet.getvalue() == ""
    plain = Tty()
    assert (
        choose("update", "where?", OPTIONS, default=1, stream=plain, env={"PACER_DISPLAY": "plain"})
        == "codex"
    )
    assert plain.getvalue() == ""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for name in ("alpha", "alps", "beta"):
        (tmp_path / name).mkdir()
    (tmp_path / "alpha" / "deep").mkdir()
    (tmp_path / "note.txt").write_text("x")
    return tmp_path


def scan(path: Path | None) -> Scan:
    if path is None:
        return Scan("good", ["the default"])
    if not path.exists():
        return Scan("bad", ["does not exist"])
    return Scan("warn", ["exists", path.name])


def test_field_edits_completes_and_scans(tree: Path):
    prefix = str(tree) + "/"
    # "al" completes to the shared "alp"; "h" makes it unique; the second tab finishes it.
    script = Scripted([*prefix, *"al", TAB, "h", TAB, ENTER])
    out = Tty()
    chosen = ask_path("init", "where?", default=tree, scan=scan, stream=out, keys=script, env=LIVE)
    assert chosen == tree / "alpha"
    drawn = frames(out)
    assert "▏" + str(tree)[:16] in drawn[0]  # the caret, then the default dim behind it
    assert any("2 match: alpha, alps" in f for f in drawn)
    assert "✓ " in drawn[-1] and drawn[-1].rstrip().endswith(str(tree / "alpha")[-30:])


def test_field_refuses_a_bad_path_until_fixed(tree: Path):
    field = Field("init", "where?", tree, scan, stream=Tty(), env=LIVE)
    for char in str(tree / "nowhere"):
        field.handle(char)
    assert field.result.state == "bad"
    assert field.handle(ENTER) is None and field.flash == "does not exist"
    for _ in range(len("nowhere")):
        field.handle(keys.BACKSPACE)
    assert field.result.state == "warn"
    assert field.handle(ENTER) == "accept" and field.chosen() == tree
    field.handle("\x17")  # ctrl-w drops the last component
    assert field.chosen() == tree.parent
    field.handle("\x15")  # ctrl-u starts over
    assert field.text == "" and field.result.notes == ["the default"]


def test_field_returns_the_default_off_a_terminal(tmp_path: Path):
    quiet = io.StringIO()
    assert ask_path("init", "where?", default=tmp_path, scan=scan, stream=quiet, env={}) == tmp_path
    assert quiet.getvalue() == ""
    out = Tty()
    assert (
        ask_path(
            "init",
            "where?",
            default=tmp_path,
            scan=scan,
            stream=out,
            keys=Scripted([ESC]),
            env=LIVE,
        )
        is None
    )
    assert "· cancelled" in frames(out)[-1]


def test_window_keeps_the_cursor_in_view():
    assert _window("short", 3, 20) == ("short", 3)
    text = "abcdefghijklmnopqrstuvwxyz"
    shown, at = _window(text, len(text), 12)
    assert shown.startswith("…") and shown.endswith("z") and len(shown) <= 12 and at == len(shown)
    shown, at = _window(text, 0, 12)
    assert shown.startswith("a") and shown.endswith("…") and at == 0
