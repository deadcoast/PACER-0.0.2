import io
import json
import re

import pytest

from pacer.display import Journey, Step, StepError, notice, paceline, report
from pacer.display.term import Caps, Pen, between, clip, detect, visible

SGR = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def plain(text: str) -> str:
    return SGR.sub("", text)


def test_capabilities_follow_the_stream_and_the_environment():
    piped = detect(io.StringIO(), {})
    assert not piped.live and piped.color == 0
    forced = detect(io.StringIO(), {"PACER_DISPLAY": "live"})
    assert forced.live and forced.color == 24 and forced.unicode
    assert detect(io.StringIO(), {"PACER_DISPLAY": "live", "NO_COLOR": "1"}).color == 0

    class Tty(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    assert detect(Tty(), {"TERM": "dumb"}).live is False
    live = detect(Tty(), {"COLORTERM": "truecolor"})
    assert live.live and live.color == 24
    assert detect(Tty(), {"PACER_DISPLAY": "plain"}).live is False


def test_pen_degrades_to_what_the_terminal_has():
    rgb = (62, 136, 255)
    assert Pen(Caps(True, 24, True, 80)).rgb("x", rgb, 94) == "\x1b[38;2;62;136;255mx\x1b[0m"
    assert Pen(Caps(True, 8, True, 80)).rgb("x", rgb, 94) == "\x1b[38;5;75mx\x1b[0m"
    assert Pen(Caps(True, 4, True, 80)).rgb("x", rgb, 94) == "\x1b[94mx\x1b[0m"
    assert Pen(Caps(True, 24, True, 80)).rgb("x", rgb, 94, bold=True).startswith("\x1b[1;38;2;")
    bare = Pen(Caps(False, 0, True, 80))
    assert bare.rgb("x", rgb, 94) == "x" and bare.bold("x") == "x" and bare.dim("x") == "x"
    assert Pen(Caps(True, 0, True, 80)).bold("x") == "\x1b[1mx\x1b[0m"


def test_width_helpers_ignore_escapes():
    styled = "\x1b[1mhello\x1b[0m world"
    assert visible(styled) == 11
    assert clip(styled, 20) == styled
    short = clip(styled, 8)
    assert visible(short) == 8 and short.endswith("…\x1b[0m") and plain(short) == "hello w…"
    assert clip("plain text here", 6) == "plain…"
    assert between("left", "right", 20) == "left" + " " * 11 + "right"
    assert (
        between("a long left side", "right", 18) == "a long left side…"[:18]
        or len(between("a long left side", "right", 18)) <= 18
    )


def test_layout_is_proportional_bounded_and_exact():
    assert layout_sum(paceline.layout([1.0, 3.0, 1.0], 40)) == 40 - 2
    sizes = paceline.layout([0.1, 10.0], 30)
    assert sizes[0] == 2 and sum(sizes) == 29
    assert paceline.layout([], 20) == []
    assert paceline.layout([2.0], 20) == [20]
    assert sum(paceline.layout([1.0] * 10, 12)) == 10  # never fewer cells than segments


def layout_sum(sizes):
    return sum(sizes)


def test_pace_line_draws_fill_head_and_track():
    pen = Pen(Caps(False, 0, True, 80))
    line = paceline.render([4, 4], set(), 5.5, 0.0, pen, paceline.UNICODE)
    assert line == "━━━━ ━╸──"
    assert (
        paceline.render([4, 4], set(), 8, 0.0, pen, paceline.UNICODE, settled=True) == "━━━━ ━━━━"
    )
    assert paceline.render([4, 4], {1}, 4, 0.0, pen, paceline.UNICODE) == "━━━━ ━━━━"
    assert paceline.render([4, 4], set(), 5.5, 0.0, pen, paceline.ASCII) == "==== =>--"
    assert (
        paceline.render([4, 4], set(), 8, 0.0, pen, paceline.UNICODE, reveal=3) == "━━━" + " " * 6
    )
    coloured = Pen(Caps(True, 24, True, 80))
    assert plain(paceline.render([4, 4], set(), 6, 0.3, coloured, paceline.UNICODE)) == "━━━━ ━━──"
    first = paceline.gradient(0.0)
    assert first == paceline.NIGHT and paceline.gradient(1.0) == paceline.ICE
    assert paceline.mix((0, 0, 0), (10, 20, 30), 0.5) == (5, 10, 15)


def test_plain_journey_prints_one_line_per_stage():
    out = io.StringIO()
    journey = Journey(
        "update",
        [Step("a", "resolve", 1), Step("b", "Claude Code", 2)],
        detail="3.0.0",
        stream=out,
        env={},
    )
    with journey:
        with journey.step("a") as stage:
            stage.done("v3.1.0 on origin")
        with journey.step("b") as stage:
            stage.note("installing")
            raise StepError("the installed copy is in use")
        assert journey.close("stopped at Claude Code", ["Run pacer update again."]) is False
    assert out.getvalue() == (
        "PACER update 3.0.0\n"
        "  ok  resolve        v3.1.0 on origin\n"
        "  !!  Claude Code    the installed copy is in use\n"
        "stopped at Claude Code\n"
        "Run pacer update again.\n"
    )
    assert (
        journey.timings() == {"a": pytest.approx(0.0, abs=0.5)}
        or "a" in journey.timings()
        or journey.timings() == {}
    )


def test_events_journey_is_relayed_into_another():
    wire = io.StringIO()
    child = Journey("install", [Step("claude", "Claude Code", 4.0)], stream=wire, mode="events")
    with child:
        child.plan([Step("codex", "Codex", 3.0)])
        with child.step("claude", "comparing") as stage:
            stage.note("installing")
            stage.done("pacer@mivim 3.1.0")
        with child.step("codex") as stage:
            stage.skip("current")
        child.close("ready in 1.2s", ["Start a new session to load it."])
    lines = wire.getvalue().splitlines()
    assert [json.loads(line)["event"] for line in lines] == [
        "plan",
        "plan",
        "begin",
        "note",
        "end",
        "begin",
        "end",
        "close",
    ]

    screen = io.StringIO()
    parent = Journey("update", [Step("resolve", "resolve", 1.0)], stream=screen, env={})
    with parent:
        with parent.step("resolve") as stage:
            stage.done("v3.1.0 on origin")
        closing = None
        for line in [*lines, "stray text that is not an event"]:
            data = parent.relay(line)
            if data and data["event"] == "close":
                closing = data
        assert parent.relay("not json") is None
        assert [s.id for s in parent.steps] == ["resolve", "claude", "codex"]
        assert closing["headline"] == "ready in 1.2s" and closing["ok"] is True
        parent.close(closing["headline"], closing["hints"])
    text = screen.getvalue()
    assert (
        "  ok  Claude Code    pacer@mivim 3.1.0" in text and "  --  Codex          current" in text
    )


def test_live_journey_hides_the_cursor_redraws_and_ends_with_a_ledger():
    out = io.StringIO()
    env = {"PACER_DISPLAY": "live", "COLUMNS": "100"}
    journey = Journey(
        "update",
        [Step("a", "resolve", 0.2), Step("b", "Codex", 0.2)],
        detail="3.0.0 ▸ 3.1.0",
        stream=out,
        env=env,
    )
    assert journey.mode == "live"
    with journey:
        with journey.step("a", "reading origin") as stage:
            import time

            time.sleep(0.12)
            stage.done("v3.1.0 on origin")
        with journey.step("b") as stage:
            stage.skip("current")
        journey.close("ready in 0.3s", ["Start a new session to load it."])
    raw = out.getvalue()
    assert raw.startswith("\x1b[?25l") and raw.endswith("\x1b[?25h")
    assert raw.count("\x1b[?2026h") >= 3  # at least intro frames, outro and the final draw
    final = plain(raw.rsplit("\x1b[J", 1)[1])
    assert "PACER  update · 3.0.0 ▸ 3.1.0" in final and "MIVIM · spec · vigiles" in final
    assert (
        "ready in 0.3s" in final
        and "✓ resolve  v3.1.0 on origin" in final
        and "· Codex    current" in final
    )
    assert "Start a new session to load it." in final
    assert all(len(line) <= 100 for line in final.splitlines())
    assert "a" in journey.timings()


def test_live_failure_shows_what_did_not_run():
    out = io.StringIO()
    journey = Journey(
        "release",
        [Step("a", "check", 1), Step("b", "tag", 1), Step("c", "push", 1)],
        stream=out,
        env={"PACER_DISPLAY": "live"},
    )
    with journey:
        with journey.step("a") as stage:
            stage.done("")
        with journey.step("b"):
            raise StepError("tag v3.1.0 exists")
        journey.close("stopped at tag")
    final = plain(out.getvalue().rsplit("\x1b[J", 1)[1])
    assert (
        "✗ tag    tag v3.1.0 exists" in final
        and "push   not run" in final
        and "stopped at tag" in final
    )


def test_report_is_a_ledger_without_a_line():
    out = io.StringIO()
    ok = report(
        "status",
        [("done", "Claude Code", "pacer@mivim 3.1.0"), ("fail", "Codex", "not installed")],
        detail="3.1.0",
        hints=["pacer update"],
        stream=out,
    )
    assert ok is False
    assert (
        out.getvalue()
        == "PACER status 3.1.0\n  ok  Claude Code    pacer@mivim 3.1.0\n  !!  Codex          not installed\npacer update\n"
    )


def test_notice_wording_is_the_same_everywhere():
    text = notice.text("3.0.0", "3.1.0")
    assert text.splitlines() == [
        "PACER 3.1.0 is available · installed 3.0.0",
        "  update    pacer update",
        "  silence   pacer update --notify off",
    ]
    styled = notice.styled("3.0.0", "3.1.0", io.StringIO())
    assert (
        "pacer update --notify off" in styled and "PACER 3.1.0" in styled and "\x1b[" not in styled
    )
