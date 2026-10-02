"""Fixtures build projects through the same Service every caller uses."""

import subprocess
import sys
from pathlib import Path

import pytest

from pacer.service import Service

PASS = f'"{sys.executable}" -c "raise SystemExit(0)"'
FAIL = f'"{sys.executable}" -c "raise SystemExit(3)"'

# One area, one phase, three paces, three assets, one requirement, two decisions.
SEED = [
    {
        "op": "add",
        "register": "overlord",
        "row": {"ID": "OVR-001", "Path": "src/a.py", "Purpose": "entry"},
    },
    {
        "op": "add",
        "register": "overlord",
        "row": {"ID": "OVR-002", "Path": "src/b.py", "Purpose": "second"},
    },
    {
        "op": "add",
        "register": "overlord",
        "row": {"ID": "OVR-003", "Path": "src/c.py", "Purpose": "third", "Tier": "protected"},
    },
    {
        "op": "pace",
        "nodule": {
            "ID": "NDL-001",
            "Name": "boot",
            "Lane": "main",
            "Request": "make it boot",
            "Intent": "boot path",
            "Exit": "boots",
        },
        "tasks": [
            {
                "ID": "PAC-001",
                "Kind": "AREA",
                "Pos": "A1",
                "Title": "Core",
                "Status": "ACTIVE",
                "Tier": "prototype",
            },
            {
                "ID": "PAC-002",
                "Kind": "PHASE",
                "Pos": "A1.P1",
                "Title": "Boot",
                "Status": "ACTIVE",
                "Tier": "prototype",
                "Exit": "boots",
                "Binds": "OGM-001",
            },
            {
                "ID": "PAC-003",
                "Kind": "PACE",
                "Pos": "A1.P1.01",
                "Title": "Load",
                "Produce": "loader",
                "In": "OVR-001",
                "Out": "src/new.py",
            },
            {
                "ID": "PAC-004",
                "Kind": "PACE",
                "Pos": "A1.P1.02",
                "Title": "Wire",
                "Produce": "wiring",
                "In": "OVR-002",
            },
            {
                "ID": "PAC-005",
                "Kind": "PACE",
                "Pos": "A1.P1.03",
                "Title": "Far",
                "Produce": "far away",
                "In": "OVR-003",
            },
        ],
        "requirements": [
            {
                "ID": "OGM-001",
                "Title": "Boots",
                "Authority": "USER",
                "Origin": "make it boot",
                "Requirement": "boots",
                "Binds": "OVR-001",
                "Probe": PASS,
            },
        ],
        "decisions": [
            {
                "ID": "DEC-001",
                "Kind": "LATCH",
                "Subject": "OVR-001",
                "Question": "sync?",
                "Chosen": "sync",
                "Authority": "USER",
                "Latched": "true",
            },
            {
                "ID": "DEC-002",
                "Kind": "LESSON",
                "Subject": "PAC-002",
                "Why": "boot order matters",
                "Authority": "OBSERVED",
            },
        ],
    },
    {"op": "status", "id": "PAC-003", "status": "ACTIVE"},
]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Every test gets its own PACER home; none may reach the network or the real hosts."""
    monkeypatch.setenv("PACER_HOME", str(tmp_path_factory.mktemp("home")))
    monkeypatch.setenv("PACER_NO_UPDATE_CHECK", "1")
    monkeypatch.setenv("PACER_DISPLAY", "plain")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A bare source tree with three files and no PACER state."""
    (tmp_path / "src").mkdir()
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / "src" / name).write_text("x = 1\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def project(root: Path) -> Service:
    """An initialised, empty project."""
    service = Service(root)
    service.init(name="demo")
    return service


@pytest.fixture
def seeded(project: Service) -> Service:
    """The standard web with PAC-003 active."""
    project.write(SEED, "tester")
    return project


@pytest.fixture
def git(root: Path):
    """Run git in the fixture tree with a throwaway identity."""

    def run(*args: str) -> str:
        base = [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "-c",
            "core.autocrlf=false",
        ]
        out = subprocess.run([*base, *args], cwd=root, capture_output=True, text=True, check=True)
        return out.stdout

    run("init", "-q")
    return run


def tables(service: Service) -> dict:
    with service.store.locked():
        return service.store.load().tables


def archived(service: Service) -> dict:
    with service.store.locked():
        return service.store.load().archive


def row(service: Service, key: str) -> dict:
    for rows in tables(service).values():
        for item in rows:
            if item["ID"] == key:
                return item
    raise KeyError(key)
