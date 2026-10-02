"""Install PACER into Claude Code and Codex from this directory.

    uv run install.py                  every host found, plus the `pacer` command
    uv run install.py --host claude    one host: claude or codex
    uv run install.py --no-cli         leave the `pacer` command alone
    uv run install.py --status         report what each host runs; exit 0 when it is this copy
    uv run install.py --uninstall      remove PACER from every host

This directory is a plugin marketplace named `mivim`: a repository checkout or an
unpacked kit, the layout is the same. The installer registers it with each host,
installs `pacer@mivim`, removes any other installed copy so a host never runs
two, and makes `pacer` an editable command that runs this directory. Afterwards
`pacer update` does all of this again, from the latest version, in one go.

Standard library only; needs uv, git and Python 3.11 or newer.
"""

import sys
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036 - reached only by interpreters too old to import us
    sys.stderr.write("PACER needs Python 3.11 or newer\n")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "plugins" / "pacer" / "src"))

from pacer.update import install_main  # noqa: E402

raise SystemExit(install_main(ROOT))
