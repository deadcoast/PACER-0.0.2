import pytest

from pacer.frames import Compiler
from pacer.gates import edit_decision, effective_tier, stop_decision
from pacer.provider import NullProvider
from pacer.rank import rank
from tests.conftest import FAIL, row, tables


class Uses:
    """Provider stub: src/a.py is used by two files."""

    name = "stub"

    def users(self, path):
        return ["src/main.py", "src/b.py"] if path == "src/a.py" else []

    def deps(self, path):
        return []


def compiler(service, provider=None):
    return Compiler(
        tables(service), service.root, service.store, provider or NullProvider(), service.config
    )


def test_rank_is_distance_over_typed_edges(seeded):
    distance = {key: d for d, key in rank(tables(seeded), NullProvider(), ["PAC-003"])}
    assert distance["PAC-003"] == 0
    assert distance["OVR-001"] == distance["PAC-002"] == distance["PAC-004"] == 1
    assert distance["NDL-001"] == 1 and distance["OGM-001"] == 2 and distance["DEC-001"] == 2
    assert distance["OVR-003"] > distance["OVR-001"]


def test_session_frame_spine_then_relevance(seeded):
    lines = seeded.frame("session").splitlines()
    assert lines[0] == "PACER demo tier=prototype pace=PAC-003"
    assert lines[1:6] == [
        "PAC PAC-001 A1 ACTIVE prototype | Title: Core",
        "PAC PAC-002 A1.P1 ACTIVE prototype | Title: Boot | Binds: OGM-001 | Exit: boots",
        "PAC PAC-003 A1.P1.01 ACTIVE | Produce: loader | In: OVR-001 | Out: src/new.py",
        "DEC DEC-002 LESSON OBSERVED | Subject: PAC-002 | Why: boot order matters",
        "DEC DEC-001 LATCH USER latched | Subject: OVR-001 | Question: sync? | Chosen: sync",
    ]
    assert (
        lines[6].startswith("OGM OGM-001 SCAFFOLD USER | Requirement: boots")
        and "Evidence: UNBOUND" in lines[6]
    )
    assert lines[7].startswith("PAC PAC-004") and lines[8].startswith("PAC PAC-005")
    assert "OVR OVR-001 src/a.py | Purpose: entry | bound-by: OGM-001 | latch: DEC-001" in lines
    assert len(lines) == len(set(lines))


def test_budget_keeps_the_spine_and_counts_the_rest(seeded):
    seeded.config["budgets"]["session"] = 256
    lines = seeded.frame("session").splitlines()
    assert [line.split()[1] for line in lines[1:6]] == [
        "PAC-001",
        "PAC-002",
        "PAC-003",
        "DEC-002",
        "DEC-001",
    ]
    assert lines[-1] == "+7 more: pacer_q PAC-003"


def test_frame_never_renders_a_card_it_drops(seeded, monkeypatch):
    seeded.config["budgets"]["session"] = 256
    rendered = []
    original = Compiler.render
    monkeypatch.setattr(
        Compiler,
        "render",
        lambda self, key, flags=(): rendered.append(key) or original(self, key, flags),
    )
    seeded.frame("session")
    assert len(rendered) == 6  # five spine cards and the first one that did not fit


def test_idle_frames_say_what_to_do(seeded):
    seeded.write([{"op": "status", "id": "PAC-003", "status": "TODO"}], "t")
    lines = seeded.frame("session").splitlines()
    assert lines[0].endswith("pace=none")
    assert "no active pace: 3 open; start one with op status <PAC> ACTIVE" in lines
    assert any(line.startswith("PAC PAC-003") for line in lines)


def test_open_work_is_whatever_is_not_done(seeded):
    """Integrated paces are still open; finished ones are history and leave the frame."""
    seeded.write(
        [
            {"op": "status", "id": "PAC-003", "status": "DONE"},
            {"op": "status", "id": "PAC-004", "status": "INTEGRATED"},
            {"op": "status", "id": "PAC-002", "status": "INTEGRATED"},
            {"op": "status", "id": "PAC-001", "status": "INTEGRATED"},
        ],
        "t",
    )
    lines = seeded.frame("session").splitlines()
    assert lines[0] == "PACER demo tier=prototype pace=none"
    assert lines[1].startswith("PAC PAC-001 A1 INTEGRATED") and lines[2].startswith(
        "PAC PAC-002 A1.P1"
    )
    assert "no active pace: 2 open; start one with op status <PAC> ACTIVE" in lines
    assert any(line.startswith("PAC PAC-004 A1.P1.02 INTEGRATED") for line in lines)
    assert not any(line.startswith("PAC PAC-003") for line in lines)
    assert not any(
        line.startswith("PAC PAC-003") for line in seeded.frame("edit", "src/a.py").splitlines()
    )
    assert seeded.q("PAC-003").startswith("PAC PAC-003 A1.P1.01 DONE")  # still reachable by ID
    done = [{"op": "status", "id": key, "status": "DONE"} for key in ("PAC-004", "PAC-005")]
    seeded.write(done, "t")
    assert "no open work: pace the next request with op pace" in seeded.frame("session")


def test_empty_project_frame(project):
    assert project.frame("session").splitlines() == [
        "PACER demo tier=prototype pace=none",
        "empty registers: pace the first request with pacer_write op pace (skill: pacer)",
    ]
    assert project.frame("prompt", "anything at all") == ""
    assert project.frame("stop") == "PACER stop tier=prototype pace=none next=implement"


def test_edit_frame_delivers_the_constraints_on_a_file(seeded):
    text = compiler(seeded, Uses()).edit("src/a.py")
    lines = text.splitlines()
    assert (
        lines[1]
        == "OVR OVR-001 src/a.py | Purpose: entry | bound-by: OGM-001 | latch: DEC-001 | used-by: src/b.py, src/main.py"
    )
    assert lines[2].startswith("OGM OGM-001") and lines[3].startswith(
        "DEC DEC-001 LATCH USER latched"
    )
    assert lines[4].startswith("PAC PAC-003") and "OFF-PACE" not in text
    assert "| OFF-PACE" in compiler(seeded).edit("src/b.py").splitlines()[1]
    planned = compiler(seeded, Uses()).edit("src/new.py").splitlines()
    assert planned[1] == "OVR - src/new.py unregistered"
    (seeded.root / "src" / "c.py").unlink()
    assert compiler(seeded).edit("src/c.py").splitlines()[1].endswith("| missing | OFF-PACE")


def test_prompt_frame_answers_only_what_is_named(seeded):
    assert seeded.frame("prompt", "hello there") == ""
    text = seeded.frame("prompt", "look at OGM-001 and src/b.py, also PAC-999")
    assert [line.split()[1] for line in text.splitlines()] == ["OGM-001", "OVR-002"]
    seeded.write([{"op": "set", "id": "OVR-003", "fields": {"Tags": "#auth"}}], "t")
    assert seeded.frame("prompt", "anything tagged #auth").startswith("OVR OVR-003")
    (seeded.root / "app.config.json").write_text("{}")
    (seeded.root / "Makefile").write_text("all:\n")
    seeded.write(
        [
            {
                "op": "add",
                "register": "overlord",
                "row": {"Path": "app.config.json", "Purpose": "settings"},
            },
            {"op": "add", "register": "overlord", "row": {"Path": "Makefile", "Purpose": "build"}},
        ],
        "t",
    )
    named = seeded.frame("prompt", "Check app.config.json, then the Makefile.")
    assert [line.split()[1] for line in named.splitlines()] == ["OVR-004", "OVR-005"]
    with pytest.raises(ValueError, match="holds PACER state"):
        seeded.write(
            [
                {
                    "op": "add",
                    "register": "overlord",
                    "row": {"Path": ".pacer/project.pacer.toml", "Purpose": "x"},
                }
            ],
            "t",
        )


def test_a_superseded_decision_is_not_delivered(seeded):
    seeded.write(
        [
            {
                "op": "add",
                "register": "decision",
                "row": {
                    "ID": "DEC-003",
                    "Kind": "LATCH",
                    "Subject": "OVR-001",
                    "Chosen": "async",
                    "Authority": "USER",
                    "Latched": "true",
                    "Supersedes": "DEC-001",
                },
            }
        ],
        "t",
    )
    text = seeded.frame("edit", "src/a.py")
    assert "DEC DEC-003" in text and "DEC DEC-001" not in text and "latch: DEC-003" in text


def test_tier_is_inherited_and_only_raised(seeded):
    t = tables(seeded)
    pace, phase = t["todo"][2], t["todo"][1]
    assert effective_tier(pace, t, seeded.config) == "prototype"
    phase["Tier"] = "release"
    assert effective_tier(pace, t, seeded.config) == "release"
    pace["Tier"] = "sketch"
    assert effective_tier(pace, t, seeded.config) == "release"
    pace["Tier"] = "protected"
    assert effective_tier(pace, t, seeded.config) == "protected"
    assert effective_tier(None, t, {"tier": "integrated"}) == "integrated"


def test_stop_matrix(seeded):
    def decide():
        return stop_decision(compiler(seeded))

    assert decide()["block"] is False and decide()["next"] == "implement"
    seeded.write([{"op": "set", "id": "OGM-001", "fields": {"Probe": FAIL}}], "t")
    seeded.probe("OGM-001", "t")
    assert decide()["block"] is False  # prototype never blocks
    seeded.write([{"op": "set", "id": "PAC-002", "fields": {"Tier": "integrated"}}], "t")
    blocked = decide()
    assert (
        blocked["block"]
        and blocked["reasons"] == ["probe failed: OGM-001"]
        and blocked["next"] == "verify"
    )
    assert blocked["text"].splitlines() == [
        "PACER stop tier=integrated pace=PAC-003 next=verify",
        "OGM-001: FAIL",
    ]
    seeded.write(
        [
            {
                "op": "set",
                "id": "OGM-001",
                "fields": {"Probe": row(seeded, "OGM-001")["Probe"].replace("(3)", "(0)")},
            }
        ],
        "t",
    )
    seeded.probe("OGM-001", "t")
    (seeded.root / "src" / "a.py").write_text("x = 2\n")
    assert decide()["block"] is False  # integrated tolerates stale evidence
    seeded.write([{"op": "set", "id": "PAC-002", "fields": {"Tier": "release"}}], "t")
    assert decide()["reasons"] == ["evidence stale: OGM-001"]
    seeded.probe("OGM-001", "t")
    assert decide()["block"] is False
    seeded.write(
        [
            {
                "op": "add",
                "register": "decision",
                "row": {
                    "ID": "DEC-009",
                    "Kind": "LATCH",
                    "Subject": "PAC-003",
                    "Question": "delete old data?",
                },
            }
        ],
        "t",
    )
    asked = decide()
    assert asked["block"] and asked["open_latches"] == ["DEC-009"] and asked["next"] == "inspect"
    assert (
        "DEC DEC-009 LATCH INFERRED open | Subject: PAC-003 | Question: delete old data?"
        in asked["text"]
    )


def test_stop_writes_the_checkpoint(seeded):
    seeded.record(["src/a.py"], [], "hook", register_new=True)
    assert seeded.stop("hook")["next"] == "integrate"
    assert row(seeded, "PAC-003")["Next"] == "integrate"
    assert seeded.log("PAC-003", 1)[0]["op"] == "checkpoint"
    events = len(seeded.log(None, 100))
    seeded.stop("hook")
    assert len(seeded.log(None, 100)) == events  # unchanged next action writes nothing


def test_protected_assets_need_a_user_latch(seeded):
    assert edit_decision(compiler(seeded), "src/b.py") == {"deny": False, "reason": ""}
    denied = edit_decision(compiler(seeded), "src/c.py")
    assert denied["deny"] and "src/c.py is protected" in denied["reason"]
    seeded.write(
        [
            {
                "op": "add",
                "register": "decision",
                "row": {
                    "Kind": "LATCH",
                    "Subject": "OVR-003",
                    "Question": "may edit c?",
                    "Chosen": "yes",
                    "Authority": "USER",
                    "Latched": "true",
                },
            }
        ],
        "t",
    )
    assert edit_decision(compiler(seeded), "src/c.py")["deny"] is False
