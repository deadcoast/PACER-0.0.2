"""Run every check the repository has, as one journey.

    python scripts/check.py                lint, format, types, tests, registers, kit, manifests
    python scripts/check.py --matrix       also run the tests on every supported Python
    python scripts/check.py --fix          apply lint fixes and formatting first
    python scripts/check.py --tests EXPR   only the tests matching EXPR (a pytest -k expression)

Standard library only; start it with any Python 3.11 or newer. Plugin hosts copy
the product directory verbatim or run it in place, so nothing here may write
into it: the environment lives in `.venv/` at the repository root and every
cache under `.cache/`. Output a stage produced is shown only when it failed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "pacer"
CACHE = REPO / ".cache"
PYTHONS = ("3.11", "3.12", "3.13", "3.14")

sys.dont_write_bytecode = True
sys.path.insert(0, str(PLUGIN / "src"))

from pacer.display import Journey, Step, StepError  # noqa: E402
from pacer.home import read_state, update_state  # noqa: E402

EXPECT = {
    "fix": 3.0,
    "lint": 2.0,
    "format": 2.0,
    "types": 8.0,
    "tests": 25.0,
    "registers": 1.0,
    "kit": 1.0,
    "plugin": 2.0,
    "marketplace": 2.0,
}


def environment(venv: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env.update(
        UV_PROJECT_ENVIRONMENT=str(venv),
        PYTHONPYCACHEPREFIX=str(CACHE / "pycache"),
        RUFF_CACHE_DIR=str(CACHE / "ruff"),
        MYPY_CACHE_DIR=str(CACHE / "mypy"),
    )
    return env


def uv(*args: str, venv: Path = REPO / ".venv", python: str | None = None) -> list[str]:
    """A command inside the plugin's locked environment."""
    command = ["uv", "run", "--locked", "--project", str(PLUGIN)]
    if python:
        command += ["--python", python]
    return [*command, *args]


def pytest(tag: str, expression: str = "") -> list[str]:
    # Outside the repository: it is itself a governed project, and the tests need bare ones.
    base = Path(tempfile.gettempdir()) / "pacer-check" / f"pytest-{tag}"
    base.parent.mkdir(parents=True, exist_ok=True)
    selected = ["-k", expression] if expression else []
    return ["python", "-m", "pytest", str(PLUGIN / "tests"), "-q", f"--basetemp={base}", *selected]


def expected(step_id: str) -> float:
    recorded = read_state().get("timings", {}).get(f"check.{step_id}")
    return float(recorded) if isinstance(recorded, (int, float)) else EXPECT.get(step_id, 3.0)


class Checks:
    def __init__(self) -> None:
        self.output: dict[str, str] = {}

    def run(
        self, journey: Journey, step_id: str, command: list[str], venv: Path | None = None
    ) -> None:
        """One stage: a captured command; its last line is the stage's text."""
        with journey.step(step_id) as stage:
            done = subprocess.run(
                command,
                cwd=REPO,
                env=environment(venv or REPO / ".venv"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            lines = [line for line in done.stdout.splitlines() if line.strip()]
            summary = lines[-1].strip() if lines else ""
            if done.returncode:
                self.output[step_id] = done.stdout
                raise StepError(summary or f"exit {done.returncode}")
            stage.done(_summary(step_id, lines))


def _summary(step_id: str, lines: list[str]) -> str:
    """The one line worth keeping from a tool's output."""
    if step_id == "registers":
        try:
            report = json.loads("\n".join(lines))
            return f"valid, {len(report.get('warnings', []))} warning(s)"
        except ValueError:
            return lines[-1].strip() if lines else ""
    for line in reversed(lines):
        if step_id == "tests" and ("passed" in line or "failed" in line):
            return line.strip()
        if step_id == "types" and line.startswith("Success"):
            return "no issues"
        if step_id == "kit" and "matches" in line:
            return line.strip()
    return {"lint": "clean", "format": "clean", "plugin": "valid", "marketplace": "valid"}.get(
        step_id, lines[-1].strip() if lines else ""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--matrix", action="store_true", help="test on every supported Python")
    parser.add_argument("--fix", action="store_true", help="apply lint fixes and formatting")
    parser.add_argument(
        "--tests", metavar="EXPR", help="only the tests matching a pytest -k expression"
    )
    args = parser.parse_args()
    if shutil.which("uv") is None:
        print("uv is required: https://docs.astral.sh/uv/", file=sys.stderr)
        return 2
    CACHE.mkdir(exist_ok=True)
    targets = [str(PLUGIN), str(REPO / "scripts"), str(REPO / "install.py")]
    source = PLUGIN / "src" / "pacer"
    pacer = [sys.executable, "-B", str(source / "__main__.py"), "--root", str(REPO)]
    claude = shutil.which("claude")

    mypy = uv("mypy", "--config-file", str(PLUGIN / "pyproject.toml"), str(source), *targets[1:])
    build_kit = [sys.executable, "-B", str(REPO / "scripts" / "build_kit.py"), "--check"]
    fixes = ["--fix"] if args.fix else []
    plan: list[tuple[str, str, list[str], Path | None]] = []
    if args.tests:
        plan.append(("tests", f"tests {args.tests}", uv(*pytest("select", args.tests)), None))
    else:
        if args.fix:
            plan.append(("fix", "fix", uv("ruff", "format", *targets), None))
        plan += [
            ("lint", "lint", uv("ruff", "check", *fixes, *targets), None),
            ("format", "format", uv("ruff", "format", "--check", *targets), None),
            ("types", "types", mypy, None),
            ("tests", "tests", uv(*pytest("default")), None),
            ("registers", "registers", [*pacer, "validate"], None),
            ("kit", "kit", build_kit, None),
        ]
        if claude:
            plan.append(
                ("plugin", "plugin manifest", [claude, "plugin", "validate", str(PLUGIN)], None)
            )
            plan.append(
                ("marketplace", "marketplace", [claude, "plugin", "validate", str(REPO)], None)
            )
        if args.matrix:
            for version in PYTHONS:
                venv: Path | None = CACHE / f"venv-{version}"
                label = f"tests on {version}"
                plan.append((f"py{version}", label, uv(*pytest(version), python=version), venv))

    journey = Journey("check", [Step(i, label, expected(i)) for i, label, _, _ in plan])
    checks = Checks()
    with journey:
        for step_id, _, command, venv in plan:
            checks.run(journey, step_id, command, venv)
        failed = [s.label for s in journey.steps if s.state == "fail"]
        ok = journey.close(
            "clean" if not failed else f"{len(failed)} failed",
            [] if not failed else ["output of each failed stage follows"],
        )
    for step_id, text in checks.output.items():
        label = next(s.label for s in journey.steps if s.id == step_id)
        print(f"\n── {label} ──\n{text.rstrip()}\n")
    update_state(
        lambda s: s.setdefault("timings", {}).update(
            {f"check.{k}": v for k, v in journey.timings().items()}
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
