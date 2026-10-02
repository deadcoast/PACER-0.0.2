"""Build the PACER kit: the marketplace, the plugin and the installer in one archive.

    python scripts/build_kit.py            write releases/pacer-kit-<version>.zip
    python scripts/build_kit.py --check    fail when that file is not what the sources build

The kit is the distributable part of this repository in the same layout, so the
installer and both marketplace manifests work unchanged from an unpacked copy.
Only files git knows about are packed. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = "plugins/pacer"
# Paths git is asked for, and the part of them the kit leaves out.
INCLUDE = (
    "README.md",
    "CHANGELOG.md",
    "MIVIM.pipeline",
    "install.py",
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
    PLUGIN,
)
EXCLUDE = (f"{PLUGIN}/tests/",)
# Fixed entry metadata: the same sources always give the same archive listing.
ENTRY_TIME = (1980, 1, 1, 0, 0, 0)
ENTRY_MODE = 0o644 << 16


def version() -> str:
    text = (REPO / PLUGIN / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["project"]["version"]


def sources() -> list[str]:
    """Tracked and not-yet-committed files under the included paths; never ignored ones."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *INCLUDE],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    paths = {p for p in listed.split("\0") if p and not p.startswith(EXCLUDE)}
    return sorted(p for p in paths if (REPO / p).is_file())


def contents(prefix: str) -> dict[str, bytes]:
    return {f"{prefix}/{path}": (REPO / path).read_bytes() for path in sources()}


def digests(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


def write(target: Path, files: dict[str, bytes]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in files.items():
            entry = zipfile.ZipInfo(name, ENTRY_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = ENTRY_MODE
            archive.writestr(entry, data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    args = parser.parse_args()
    name = f"pacer-kit-{version()}"
    target = REPO / "releases" / f"{name}.zip"
    files = contents(name)
    if not args.check:
        write(target, files)
        size = target.stat().st_size
        print(f"{target.relative_to(REPO).as_posix()}  {len(files)} files  {size} bytes")
        return 0
    if not target.is_file():
        print(f"{target.relative_to(REPO).as_posix()} is missing; run scripts/build_kit.py")
        return 1
    with zipfile.ZipFile(target) as archive:
        packed = digests({item.filename: archive.read(item) for item in archive.infolist()})
    built = digests(files)
    changed = sorted(n for n in packed.keys() | built.keys() if packed.get(n) != built.get(n))
    if changed:
        print(
            f"{target.name} is out of date ({len(changed)} files differ); run scripts/build_kit.py"
        )
        for item in changed[:10]:
            print(f"  {item}")
        return 1
    print(f"{target.name} matches the sources ({len(built)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
