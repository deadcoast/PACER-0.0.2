"""Run every check the repository has. Standard library only; start it with any Python >= 3.11.

    python scripts/check.py            lint, format, types, tests, manifests, registers, kit
    python scripts/check.py --matrix   also run the tests on every supported Python
    python scripts/check.py --fix      apply lint fixes and formatting first

The product directory is copied verbatim by plugin hosts, so nothing here may
write into it: the environment lives in `.venv/` at the repository root and
every cache under `.cache/`.
"""

from __future__ import annotations

import argparse
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


def uv(
    *args: str, venv: Path = REPO / ".venv", python: str | None = None
) -> tuple[list[str], dict[str, str]]:
    """A command inside the plugin's locked environment, and the environment to run it with."""
    command = ["uv", "run", "--locked", "--project", str(PLUGIN)]
    if python:
        command += ["--python", python]
    return [*command, *args], environment(venv)


def pytest(tag: str) -> tuple[str, ...]:
    # Outside the repository: it is itself a governed project, and the tests need bare ones.
    base = Path(tempfile.gettempdir()) / "pacer-check" / f"pytest-{tag}"
    base.parent.mkdir(parents=True, exist_ok=True)
    return ("python", "-m", "pytest", str(PLUGIN / "tests"), "-q", f"--basetemp={base}")


def step(name: str, command: list[str], env: dict[str, str] | None = None) -> bool:
    print(f"\n== {name}", flush=True)
    env = env or environment(REPO / ".venv")
    done = subprocess.run(command, cwd=REPO, env=env, stdin=subprocess.DEVNULL, check=False)
    if done.returncode:
        print(f"-- {name}: FAILED (exit {done.returncode})", flush=True)
    return done.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matrix", action="store_true", help="test on every supported Python")
    parser.add_argument("--fix", action="store_true", help="apply lint fixes and formatting")
    args = parser.parse_args()
    if shutil.which("uv") is None:
        print("uv is required: https://docs.astral.sh/uv/", file=sys.stderr)
        return 2
    CACHE.mkdir(exist_ok=True)
    scripts = [str(REPO / "scripts"), str(REPO / "install.py")]
    targets = [str(PLUGIN), *scripts]
    results = []
    if args.fix:
        results.append(step("ruff format", *uv("ruff", "format", *targets)))
        results.append(step("ruff fix", *uv("ruff", "check", "--fix", *targets)))
    source = PLUGIN / "src" / "pacer"
    pacer = [sys.executable, str(source / "__main__.py"), "--root", str(REPO)]
    results += [
        step("ruff check", *uv("ruff", "check", *targets)),
        step("ruff format --check", *uv("ruff", "format", "--check", *targets)),
        step(
            "mypy",
            *uv("mypy", "--config-file", str(PLUGIN / "pyproject.toml"), str(source), *scripts),
        ),
        step("pytest", *uv(*pytest("default"))),
        step("registers", [*pacer, "validate"]),
        step("kit", [sys.executable, str(REPO / "scripts" / "build_kit.py"), "--check"]),
    ]
    if shutil.which("claude"):
        results.append(
            step("claude plugin validate", ["claude", "plugin", "validate", str(PLUGIN)])
        )
        results.append(
            step(
                "claude marketplace validate",
                ["claude", "plugin", "validate", str(REPO)],
            )
        )
    else:
        print("\n== claude plugin validate: skipped (claude is not on PATH)")
    if args.matrix:
        for version in PYTHONS:
            venv = CACHE / f"venv-{version}"
            results.append(
                step(
                    f"pytest on Python {version}",
                    *uv(*pytest(version), venv=venv, python=version),
                )
            )
    failed = results.count(False)
    print(f"\n{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
