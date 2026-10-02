"""Run PACER as `python -m pacer` or by path: `python <plugin>/src/pacer/__main__.py`.

Hooks start PACER by path so nothing has to be installed first: everything
outside the MCP server uses the standard library only. Started that way, Python
puts this package directory on `sys.path`; it is swapped for the parent so
`pacer` imports as a package and no module here can shadow a standard one.
"""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - reached only by interpreters too old to import us
    sys.stderr.write("pacer needs Python 3.11 or newer\n")
    raise SystemExit(2)

if not __package__:
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    same = os.path.normcase(here)
    sys.path[:] = [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) != same]
    sys.path.insert(0, os.path.dirname(here))

from pacer.cli import main  # noqa: E402

raise SystemExit(main())
