import csv
import io
import json

import pytest

from pacer import migrate
from pacer.hook import run
from pacer.service import Service
from tests.conftest import archived, row, tables


def write_csv(path, columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stream.getvalue(), encoding="utf-8", newline="")


TODO_05 = [
    "ID",
    "Phase",
    "Title",
    "Status",
    "DoD",
    "OVRRefs",
    "OGMRefs",
    "BlockedBy",
    "DependencyType",
    "NextAction",
    "PreviousAttempts",
    "LearningNotes",
    "ApprovalState",
    "ApprovalEvidence",
    "Tags",
]
OVR_05 = ["ID", "Path", "Symbol", "AssetType", "Purpose", "OGMRefs", "Tags"]
OGM_05 = ["ID", "Title", "Status", "Authority", "OriginText", "Requirement", "OVRRefs", "Tags"]
NDL_05 = [
    "ID",
    "NoduleName",
    "Status",
    "Lane",
    "UserRequest",
    "Intent",
    "TargetOVR",
    "NewAssets",
    "OGMTargets",
    "SpawnedPACs",
    "AbsorptionCriteria",
    "Tags",
]


@pytest.fixture
def profile_05(root):
    """A profile 0.5 project: upper-case file names, one vanished file, one absorbed nodule."""
    write_csv(
        root / "todo.PACER.csv",
        TODO_05,
        [
            {
                "ID": "PAC-001",
                "Phase": "BUILD",
                "Title": "Load config",
                "Status": "DONE",
                "DoD": "Config loads. Then more prose that is not the product.",
                "OVRRefs": "OVR-001;OVR-002",
                "OGMRefs": "OGM-001",
                "LearningNotes": "toml beats ini here",
            },
            {
                "ID": "PAC-002",
                "Phase": "BUILD",
                "Title": "Wire it",
                "Status": "DOING",
                "DoD": "Wired",
                "OVRRefs": "OVR-001",
                "BlockedBy": "PAC-001;PAC-003",
                "DependencyType": "hard;soft",
                "NextAction": "review",
                "PreviousAttempts": "tried globals; broke tests",
            },
            {
                "ID": "PAC-003",
                "Phase": "PROPOSAL",
                "Title": "Drop the cache",
                "Status": "TODO",
                "DoD": "Cache removed",
                "ApprovalState": "PENDING",
            },
        ],
    )
    write_csv(
        root / "overlord.PACER.csv",
        OVR_05,
        [
            {
                "ID": "OVR-001",
                "Path": "src/a.py",
                "AssetType": "FILE",
                "Purpose": "entry",
                "OGMRefs": "OGM-001",
            },
            {
                "ID": "OVR-002",
                "Path": "src/deleted.py",
                "AssetType": "FILE",
                "Purpose": "gone",
                "Tags": "#dead",
            },
            {"ID": "OVR-003", "Path": "src/b.py", "AssetType": "FILE", "Purpose": ""},
        ],
    )
    write_csv(
        root / "organism.PACER.csv",
        OGM_05,
        [
            {
                "ID": "OGM-001",
                "Title": "Boots",
                "Status": "VALIDATED_COMPLETE",
                "Authority": "USER",
                "OriginText": "make it boot",
                "Requirement": "it boots",
                "OVRRefs": "OVR-002",
            },
        ],
    )
    write_csv(
        root / "nodule.PACER.csv",
        NDL_05,
        [
            {
                "ID": "NDL-002",
                "NoduleName": "wire",
                "Status": "ACTIVE",
                "Lane": "wire",
                "UserRequest": "wire it up",
                "Intent": "wiring",
                "TargetOVR": "OVR-001;OVR-002",
                "SpawnedPACs": "PAC-002",
                "AbsorptionCriteria": "wired",
            },
        ],
    )
    write_csv(
        root / "archive" / "nodules" / "NDL-001.PACER.csv",
        NDL_05,
        [
            {
                "ID": "NDL-001",
                "NoduleName": "config",
                "Status": "ABSORBED",
                "Lane": "config",
                "UserRequest": "load config",
                "Intent": "config",
                "SpawnedPACs": "PAC-001",
                "AbsorptionCriteria": "loads",
            },
        ],
    )
    (root / ".gitignore").write_text(".venv/\n.pacer/\n")
    return root


def test_profile_05_import(profile_05):
    assert migrate.detect(profile_05) == "0.5"
    service = Service(profile_05)
    preview = service.migrate(actor="t", preview=True)
    assert (
        preview["source"] == "0.5" and preview["validation"]["valid"] and "applied" not in preview
    )
    assert not (profile_05 / ".pacer").exists()  # a preview writes nothing
    result = service.migrate(actor="t", preview=False)
    assert result["applied"] and result["live"] == {
        "todo": 6,
        "overlord": 2,
        "organism": 1,
        "nodule": 1,
        "decision": 3,
    }
    assert result["archived"] == {"overlord": 1, "nodule": 1}

    live = tables(service)
    assert [(r["ID"], r["Kind"], r["Pos"], r["Status"]) for r in live["todo"]] == [
        ("PAC-004", "AREA", "A1", "ACTIVE"),
        ("PAC-005", "PHASE", "A1.P1", "ACTIVE"),
        ("PAC-001", "PACE", "A1.P1.01", "DONE"),
        ("PAC-002", "PACE", "A1.P1.02", "ACTIVE"),
        ("PAC-006", "PHASE", "A1.P2", "ACTIVE"),
        ("PAC-003", "PACE", "A1.P2.01", "TODO"),
    ]
    assert row(service, "PAC-001")["Produce"] == "Config loads."  # the product, not the prose
    assert (
        row(service, "PAC-001")["In"] == "OVR-001"
    )  # the vanished asset is dropped from live rows
    assert (
        row(service, "PAC-002")["Needs"] == "PAC-001"
        and row(service, "PAC-002")["Next"] == "integrate"
    )
    assert (
        row(service, "OGM-001")["Status"] == "PACED_REQUIREMENT"
    )  # an old acceptance is not a probe
    assert row(service, "OGM-001")["Binds"] == "OVR-001"
    assert row(service, "OVR-003")["Tags"] == "#unpurposed"
    assert [(d["Kind"], d["Subject"], d["Latched"]) for d in live["decision"]] == [
        ("LESSON", "PAC-001", ""),
        ("FAILED", "PAC-002", ""),
        ("LATCH", "PAC-003", "false"),
    ]
    assert row(service, "NDL-002")["In"] == "OVR-001"
    gone = archived(service)
    assert [r["Path"] for r in gone["overlord"]] == ["src/deleted.py"] and gone["overlord"][0][
        "Tags"
    ] == ""
    assert [r["ID"] for r in gone["nodule"]] == ["NDL-001"]

    kept = profile_05 / ".pacer" / "archive" / "import-0.5"
    assert sorted(p.relative_to(kept).as_posix() for p in kept.rglob("*") if p.is_file()) == [
        "nodule.PACER.csv",
        "nodules/NDL-001.PACER.csv",
        "organism.PACER.csv",
        "overlord.PACER.csv",
        "todo.PACER.csv",
    ]
    assert sorted(p.name for p in profile_05.iterdir()) == [".gitignore", ".pacer", "src"]
    assert (profile_05 / ".gitignore").read_text() == ".venv/\n"
    assert service.validate()["valid"]
    assert service.log(None, 1)[0]["op"] == "migrate"
    # The pending approval is an open latch on PAC-003; it gates that pace, not the active one.
    assert service.stop("hook")["open_latches"] == []
    service.write([{"op": "status", "id": "PAC-002", "status": "INTEGRATED"}], "t")
    service.write([{"op": "status", "id": "PAC-003", "status": "ACTIVE"}], "t")
    assert service.stop("hook")["open_latches"] == ["DEC-003"]
    with pytest.raises(ValueError, match="already uses the current PACER layout"):
        service.migrate(actor="t", preview=True)


V2_PLAN = """PACER::TODO v2.0.0
PROJECT "demo" maturity=playable
GLOBAL G1 "Engine" state=active
  SOURCE "src/a.py" role="entry point"
  SOURCE "src/missing.py" role="planned"
  PHASE P1 "Boot" state=active
    PACE boot-loader "Load the level" state=done
    PACE boot-wire "Wire the input" state=active
    EXIT coherent="player can move"
    :nodule NDL-001 "input rework"
    +approved boot-wire
GLOBAL G2 "Polish" state=todo
  PHASE P1 "Juice"
    PACE juice-shake "Screen shake"
"""


def test_v2_plan_import(root):
    (root / "TODO.pacer").write_text(V2_PLAN, encoding="utf-8")
    assert migrate.detect(root) == "2.0"
    service = Service(root)
    result = service.migrate(actor="t", preview=False)
    assert result["applied"] and result["archived"] == {"overlord": 1}
    assert service.config["tier"] == "playable" and service.config["project"] == root.name
    live = tables(service)
    assert [(r["Pos"], r["Kind"], r["Status"]) for r in live["todo"]] == [
        ("A1", "AREA", "ACTIVE"),
        ("A1.P1", "PHASE", "ACTIVE"),
        ("A1.P1.01", "PACE", "DONE"),
        ("A1.P1.02", "PACE", "ACTIVE"),
        ("A2", "AREA", "TODO"),
        ("A2.P1", "PHASE", "TODO"),
        ("A2.P1.01", "PACE", "TODO"),
    ]
    assert live["todo"][1]["Exit"] == "player can move" and live["todo"][3]["Tags"] == "#boot-wire"
    assert [(r["Path"], r["Purpose"]) for r in live["overlord"]] == [("src/a.py", "entry point")]
    assert live["nodule"][0]["Spawned"] == "PAC-003" and live["decision"][0]["Subject"] == "PAC-002"
    assert (root / ".pacer" / "archive" / "import-2.0" / "TODO.pacer").read_text(
        encoding="utf-8"
    ) == V2_PLAN
    assert service.frame("session").startswith(f"PACER {root.name} tier=playable pace=PAC-004")


TODO_3R = [
    "ID",
    "Kind",
    "Pos",
    "Title",
    "Status",
    "Tier",
    "Produce",
    "In",
    "Out",
    "Binds",
    "Needs",
    "Latch",
    "Probe",
    "Exit",
    "Next",
    "Tags",
]
OVR_3R = ["ID", "Path", "Symbol", "Kind", "Purpose", "Binds", "Latch", "Tier", "Tags"]
OGM_3R = [
    "ID",
    "Title",
    "Status",
    "Authority",
    "Origin",
    "Requirement",
    "Binds",
    "Probe",
    "Evidence",
    "Tier",
    "Tags",
]
NDL_3R = [
    "ID",
    "Name",
    "Status",
    "Lane",
    "Request",
    "Intent",
    "In",
    "Out",
    "Targets",
    "Spawned",
    "Exit",
    "Tags",
]
DEC_3R = [
    "ID",
    "Kind",
    "Subject",
    "Question",
    "Chosen",
    "Rejected",
    "Why",
    "Authority",
    "Latched",
    "Supersedes",
    "Tags",
]


@pytest.fixture
def root_layout(root):
    """Pre-baseline 3.0: registers and ledger in the project root, config named .MIVIM.spec."""
    write_csv(
        root / "todo.pacer.csv",
        TODO_3R,
        [
            {"ID": "PAC-001", "Kind": "AREA", "Pos": "A1", "Title": "Core", "Status": "ACTIVE"},
            {
                "ID": "PAC-002",
                "Kind": "PHASE",
                "Pos": "A1.P1",
                "Title": "Boot",
                "Status": "ACTIVE",
                "Exit": "boots",
            },
            {
                "ID": "PAC-003",
                "Kind": "PACE",
                "Pos": "A1.P1.01",
                "Title": "Load",
                "Status": "ACTIVE",
                "Produce": "loader",
                "In": "OVR-001",
                "Latch": "DEC-001",
            },
        ],
    )
    write_csv(
        root / "overlord.pacer.csv",
        OVR_3R,
        [
            {
                "ID": "OVR-001",
                "Path": "src/a.py",
                "Kind": "FILE",
                "Purpose": "entry",
                "Binds": "OGM-001",
                "Latch": "DEC-001",
            },
            {"ID": "OVR-002", "Path": "src/b.py", "Kind": "FILE", "Purpose": "second"},
        ],
    )
    write_csv(
        root / "organism.pacer.csv",
        OGM_3R,
        [
            {
                "ID": "OGM-001",
                "Title": "Boots",
                "Status": "SCAFFOLD",
                "Authority": "USER",
                "Requirement": "boots",
                "Binds": "OVR-002",
            },
        ],
    )
    write_csv(
        root / "nodule.pacer.csv",
        NDL_3R,
        [
            {
                "ID": "NDL-002",
                "Name": "done",
                "Status": "ABSORBED",
                "Lane": "x",
                "Request": "r",
                "Intent": "i",
                "Exit": "e",
            },
        ],
    )
    write_csv(
        root / "decision.pacer.csv",
        DEC_3R,
        [
            {
                "ID": "DEC-001",
                "Kind": "LATCH",
                "Subject": "OVR-002",
                "Question": "sync?",
                "Chosen": "sync",
                "Authority": "USER",
                "Latched": "true",
            },
        ],
    )
    write_csv(
        root / "archive" / "nodules" / "NDL-001.pacer.csv",
        NDL_3R,
        [
            {
                "ID": "NDL-001",
                "Name": "old",
                "Status": "ABSORBED",
                "Lane": "y",
                "Request": "r",
                "Intent": "i",
                "Exit": "e",
            },
        ],
    )
    (root / "ledger.pacer.jsonl").write_text(
        '{"at":"2026-09-29T00:00:00Z","actor":"a","op":"add","id":"PAC-001","detail":{}}\n'
    )
    state = root / ".pacer"
    (state / "probes" / "OGM-001").mkdir(parents=True)
    (state / "probes" / "OGM-001" / "1.txt").write_text("$ probe\n")
    (state / ".MIVIM.spec").write_text(
        '[project]\nname = "legacy"\ntier = "integrated"\n\n[frames]\nsession = 5000\n'
    )
    (state / "hook-seen.json").write_text("{}")
    (state / "notes.md").write_text("mine\n")
    (root / ".gitignore").write_text(".pacer/\ndist/\n")
    return root


def test_root_layout_relocates_without_loss(root_layout):
    assert migrate.detect(root_layout) == "3.0-root"
    service = Service(root_layout)
    result = service.migrate(actor="t", preview=False)
    assert result["applied"] and result["live"] == {
        "todo": 3,
        "overlord": 2,
        "organism": 1,
        "nodule": 0,
        "decision": 1,
    }
    assert result["archived"] == {"nodule": 2}
    assert "left untouched in .pacer/: notes.md" in result["notes"]
    # Relations stored once: the reverse columns fold into the forward ones.
    assert row(service, "OGM-001")["Binds"] == "OVR-002;OVR-001"
    assert row(service, "DEC-001")["Subject"] == "OVR-002;PAC-003;OVR-001"
    assert "Latch" not in row(service, "PAC-003") and "Binds" not in row(service, "OVR-001")
    assert service.config == {**service.config, "project": "legacy", "tier": "integrated"}
    assert (
        service.config["budgets"]["session"] == 5000 and service.config["budgets"]["edit"] == 1500
    )
    state = root_layout / ".pacer"
    assert sorted(p.name for p in state.iterdir()) == [
        ".gitattributes",
        ".gitignore",
        "archive",
        "decision.pacer.csv",
        "ledger.pacer.jsonl",
        "nodule.pacer.csv",
        "notes.md",
        "organism.pacer.csv",
        "overlord.pacer.csv",
        "project.pacer.toml",
        "run",
        "todo.pacer.csv",
    ]
    assert (state / "run" / "probes" / "OGM-001" / "1.txt").is_file()
    assert sorted(p.name for p in root_layout.iterdir()) == [".gitignore", ".pacer", "src"]
    assert (root_layout / ".gitignore").read_text() == "dist/\n"
    events = [e["op"] for e in service.log(None, 5)]
    assert events == ["add", "migrate"]  # the old ledger is carried, then continued
    assert "latch: DEC-001" in service.frame("edit", "src/a.py")


def test_invalid_import_writes_nothing(root_layout):
    rows = [{"ID": "OVR-001", "Path": "../outside.py", "Kind": "FILE", "Purpose": "bad"}]
    write_csv(root_layout / "overlord.pacer.csv", OVR_3R, rows)
    service = Service(root_layout)
    result = service.migrate(actor="t", preview=False)
    assert result["applied"] is False and not result["validation"]["valid"]
    assert (root_layout / "todo.pacer.csv").is_file() and not (
        root_layout / ".pacer" / "todo.pacer.csv"
    ).exists()


def test_nothing_to_migrate_and_explicit_source(root, project):
    with pytest.raises(ValueError, match="already uses the current PACER layout"):
        migrate.plan(root)
    with pytest.raises(ValueError, match="Unknown source"):
        migrate.plan(root, "1.0")


def test_bare_directory_has_nothing_to_migrate(root):
    assert migrate.detect(root) is None
    with pytest.raises(ValueError, match="No older PACER format"):
        Service(root).migrate(actor="t", preview=True)


def test_session_start_names_an_untracked_older_layout(root_layout):
    nested = root_layout / "src"
    code, out = run("session-start", {"cwd": str(nested), "session_id": "s", "source": "startup"})
    assert code == 0 and out.startswith(f"PACER: {root_layout.as_posix()} holds a 3.0-root layout")
    assert run("prompt", {"cwd": str(nested), "prompt": "x"}) == (0, "")
    assert (
        json.loads((root_layout / ".pacer" / "hook-seen.json").read_text()) == {}
    )  # nothing was touched


def test_init_refuses_over_an_older_layout(root_layout):
    with pytest.raises(ValueError, match="run `pacer migrate` instead"):
        Service(root_layout).init()
