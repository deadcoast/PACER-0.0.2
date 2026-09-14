"""CLI JSON, refusal exits and lossless CSV round trips are user-visible contracts."""

import json
import subprocess
import sys


def test_cli_query_and_refusal_exit(paced, tmp_path):
    base = [sys.executable, "-m", "pacer_mcp.cli", "--root", str(paced.store.root)]
    result = subprocess.run(
        base + ["query", "todo", "--ready", "--fields", "ID"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["rows"] == [{"ID": "PAC-001"}]
    receipt = paced.onboard()
    commands = tmp_path / "commands.json"
    commands.write_text(json.dumps([{"op": "transition", "id": "PAC-001", "status": "DONE"}]))
    result = subprocess.run(
        base
        + [
            "apply",
            "--file",
            str(commands),
            "--actor",
            "cli-test",
            "--revision",
            receipt["revision"],
            "--onboarding",
            receipt["onboarding"],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and result.stdout == ""
    assert result.stderr.strip() == "REFUSAL: Illegal transition TODO->DONE"


def test_csv_quotes_multiline_unicode_survive_append(paced, apply):
    text = 'Café, "quoted"\n第二行; evidence'
    apply({"op": "append", "id": "PAC-001", "field": "LearningNotes", "text": text})
    row = paced.query("todo", where={"ID": "PAC-001"}, fields=["LearningNotes"])["rows"][0]
    assert row["LearningNotes"] == text
    assert paced.validate()["valid"]
