from pathlib import Path

import pytest
from pacer_mcp import schema
from pacer_mcp.service import Service


@pytest.fixture
def registers(tmp_path: Path) -> Path:
    for name in schema.REGISTERS:
        (tmp_path / f"{name}.PACER.csv").write_text(
            ",".join(schema.HEADERS[name]) + "\n", encoding="utf-8"
        )
    (tmp_path / "README.md").write_text("Fixture project\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def project(registers: Path) -> Service:
    (registers / "src").mkdir(exist_ok=True)
    (registers / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    return Service(registers)
