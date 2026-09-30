from pathlib import Path

import pytest
from pacer_mcp import schema


@pytest.fixture
def registers(tmp_path: Path) -> Path:
    for name in schema.REGISTERS:
        (tmp_path / f"{name}.PACER.csv").write_text(
            ",".join(schema.HEADERS[name]) + "\n", encoding="utf-8"
        )
    (tmp_path / "README.md").write_text("Fixture project\n", encoding="utf-8")
    return tmp_path
