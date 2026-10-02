"""Who PACER is and where it comes from.

The lineage is declared once, in `MIVIM.pipeline` at the repository root: the
parent organisation, the category beneath it, and the spec this agent is
assigned to. A test holds these constants to that file, so the runtime, the
display signature and the user-level home can never drift from it.
"""

ORG = "MIVIM"
CATEGORY = "spec"
SPEC = "vigiles"
AGENT = "PACER"
LINEAGE = (ORG, CATEGORY, SPEC)

MARKET = "mivim"
PLUGIN = "pacer"
PLUGIN_ID = f"{PLUGIN}@{MARKET}"
REPOSITORY = "https://github.com/deadcoast/PACER-0.0.2"
