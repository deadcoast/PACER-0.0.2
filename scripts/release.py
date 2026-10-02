"""Ship a PACER release from one command.

    python scripts/release.py 3.1.0            version, checks, kit, sync, proof, commit, tag, push
    python scripts/release.py 3.1.0 --dry-run  stop before anything is committed; restore the files
    python scripts/release.py 3.1.0 --no-push  commit and tag, push later
    python scripts/release.py 3.1.0 --matrix   run the tests on every supported Python too

Preconditions, checked first: a clean tree on a branch with an upstream that is
not ahead of it, no such tag yet, and a `## <version>` section in CHANGELOG.md.
The version is written to the four files that carry it and to the lock file.
Then the checks run, the kit is built, every host on this machine is synced from
the tree, the repository's own requirements are proved again, and one commit is
made, tagged `v<version>` and pushed with its tag. `pacer update` on any other
machine finds the tag from then on.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "pacer"

sys.dont_write_bytecode = True
sys.path.insert(0, str(PLUGIN / "src"))

from pacer.display import Journey, Step, StepError  # noqa: E402
from pacer.home import read_state, update_state  # noqa: E402
from pacer.update import parse, run_installer  # noqa: E402

VERSIONED = {
    PLUGIN / "pyproject.toml": (r'^version = "[^"]+"', 'version = "{v}"'),
    PLUGIN / "src" / "pacer" / "__init__.py": (r'^__version__ = "[^"]+"', '__version__ = "{v}"'),
    PLUGIN / ".claude-plugin" / "plugin.json": (r'"version": "[^"]+"', '"version": "{v}"'),
    PLUGIN / ".codex-plugin" / "plugin.json": (r'"version": "[^"]+"', '"version": "{v}"'),
}
EXPECT = {
    "preflight": 2.0,
    "version": 3.0,
    "check": 60.0,
    "kit": 1.0,
    "prove": 70.0,
    "commit": 1.0,
    "tag": 0.5,
    "push": 5.0,
}


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if done.returncode:
        raise StepError(
            f"git {' '.join(args)}: {(done.stderr or done.stdout).strip().splitlines()[-1]}"
        )
    return done.stdout.strip()


def expected(step_id: str) -> float:
    recorded = read_state().get("timings", {}).get(f"release.{step_id}")
    return float(recorded) if isinstance(recorded, (int, float)) else EXPECT[step_id]


def current_version() -> str:
    text = (PLUGIN / "src" / "pacer" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def preflight(version: str) -> str:
    if parse(version) is None:
        raise StepError(f"{version} is not MAJOR.MINOR.PATCH")
    before = current_version()
    if not (parse(version) or ()) > (parse(before) or ()):
        raise StepError(f"{version} is not newer than {before}")
    if git("status", "--porcelain"):
        raise StepError("the tree has uncommitted changes; commit them first")
    branch = git("symbolic-ref", "-q", "--short", "HEAD")
    git("fetch", "--quiet", "--tags", "origin")
    ahead, behind = (
        int(n) for n in git("rev-list", "--left-right", "--count", "HEAD...@{u}").split()
    )
    if behind:
        raise StepError(f"{branch} is {behind} commit(s) behind its upstream; pull first")
    if git("tag", "--list", f"v{version}"):
        raise StepError(f"tag v{version} exists")
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## {re.escape(version)}\b", changelog, flags=re.MULTILINE):
        raise StepError(f"CHANGELOG.md has no `## {version}` section")
    return f"{before} {'->'} {version} on {branch}" + (
        f", {ahead} unpushed commit(s)" if ahead else ""
    )


def write_version(version: str) -> list[Path]:
    touched = []
    for path, (pattern, replacement) in VERSIONED.items():
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(
            pattern, replacement.format(v=version), text, count=1, flags=re.MULTILINE
        )
        if count != 1:
            raise StepError(f"no version to replace in {path.relative_to(REPO)}")
        path.write_text(updated, encoding="utf-8", newline="\n")
        touched.append(path)
    changelog = REPO / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    stamped = re.sub(
        rf"^## {re.escape(version)}\s*$",
        f"## {version} — {today}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if stamped != text:
        changelog.write_text(stamped, encoding="utf-8", newline="\n")
        touched.append(changelog)
    done = subprocess.run(
        ["uv", "lock", "--project", str(PLUGIN)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode:
        raise StepError(f"uv lock: {(done.stderr or done.stdout).strip().splitlines()[-1]}")
    touched.append(PLUGIN / "uv.lock")
    return touched


def run(command: list[str], journey: Journey, keep: dict[str, str], step_id: str) -> str:
    done = subprocess.run(
        command,
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    if done.returncode:
        keep[step_id] = done.stdout
        raise StepError(lines[-1].strip() if lines else f"exit {done.returncode}")
    return lines[-1].strip() if lines else ""


def prove(journey: Journey) -> str:
    """Run every proven requirement's probe again; all must come back CURRENT."""
    from pacer.service import Service

    service = Service(REPO)
    with service.store.locked():
        rows = [
            r
            for r in service.store.load().tables["organism"]
            if r["Status"] == "VALIDATED_COMPLETE"
        ]
    results = []
    for row in rows:
        journey.note(f"probing {row['ID']} {row['Title']}")
        result = service.probe(row["ID"], "release")
        results.append((row["ID"], result["freshness"]))
        if result["freshness"] != "CURRENT":
            raise StepError(f"{row['ID']} came back {result['freshness']}")
    return ", ".join(f"{k} {v}" for k, v in results) or "no proven requirements"


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("version")
    parser.add_argument(
        "--dry-run", action="store_true", help="stop before committing; restore the files"
    )
    parser.add_argument("--no-push", action="store_true", help="commit and tag, do not push")
    parser.add_argument("--matrix", action="store_true", help="tests on every supported Python")
    args = parser.parse_args()
    version = args.version

    plan = ["preflight", "version", "check", "kit"]
    if not args.dry_run:
        plan += ["claude", "codex", "command", "prove", "commit", "tag"]
        if not args.no_push:
            plan.append("push")
    labels = {"claude": "Claude Code", "codex": "Codex"}
    steps = [Step(i, labels.get(i, i), expected(i) if i in EXPECT else 5.0) for i in plan]
    journey = Journey("release", steps, detail=f"v{version}")
    kept: dict[str, str] = {}
    touched: list[Path] = []
    started = time.monotonic()
    python = sys.executable
    with journey:
        with journey.step("preflight") as stage:
            stage.done(preflight(version))
        if journey.ok:
            with journey.step("version") as stage:
                touched = write_version(version)
                stage.done(f"{len(touched)} files")
        if journey.ok:
            check = [
                python,
                "-B",
                str(REPO / "scripts" / "check.py"),
                *(["--matrix"] if args.matrix else []),
            ]
            with journey.step("check", "lint, types, tests, registers, manifests") as stage:
                stage.done(run(check, journey, kept, "check"))
        if journey.ok:
            with journey.step("kit") as stage:
                stage.done(
                    run(
                        [python, "-B", str(REPO / "scripts" / "build_kit.py")], journey, kept, "kit"
                    )
                )
        if journey.ok and not args.dry_run:
            changed, advice, failure = run_installer(REPO, journey, ["--host", "all"])
            if failure:
                journey.plan([Step("install", "install", 1.0)])
                journey.begin("install")
                journey.end("install", "fail", failure)
        if journey.ok and not args.dry_run:
            with journey.step("prove") as stage:
                stage.done(prove(journey))
            with journey.step("commit") as stage:
                git("add", "-A")
                git("commit", "-q", "-m", f"release: PACER {version}")
                stage.done(git("rev-parse", "--short=7", "HEAD"))
            with journey.step("tag") as stage:
                git("tag", "-a", f"v{version}", "-m", f"PACER {version}")
                stage.done(f"v{version}")
            if not args.no_push:
                with journey.step("push") as stage:
                    branch = git("symbolic-ref", "-q", "--short", "HEAD")
                    git("push", "--quiet", "--follow-tags", "origin", branch)
                    stage.done(f"origin/{branch} and v{version}")
        if args.dry_run or not journey.ok:
            for path in touched:
                git("checkout", "--quiet", "--", str(path))
            new_kit = REPO / "releases" / f"pacer-kit-{version}.zip"
            if not git("ls-files", "--", str(new_kit)) and new_kit.exists():
                new_kit.unlink()
        took = time.monotonic() - started
        if not journey.ok:
            failed = next(s.label for s in journey.steps if s.state == "fail")
            hints = ["The tree is as it was before the release."]
            ok = journey.close(f"stopped at {failed}", hints)
        elif args.dry_run:
            ok = journey.close(
                f"dry run clean in {took:.0f}s", ["The tree is as it was; nothing was committed."]
            )
        else:
            where = "pushed" if not args.no_push else "tagged, not pushed"
            ok = journey.close(
                f"v{version} {where} in {took:.0f}s", ["Start a new session to load it."]
            )
    for step_id, text in kept.items():
        print(f"\n── {step_id} ──\n{text.rstrip()}\n")
    update_state(
        lambda s: s.setdefault("timings", {}).update(
            {f"release.{k}": v for k, v in journey.timings().items() if k in EXPECT}
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
