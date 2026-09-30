# PACER 3 project frame. Copy to the project root. Everything here has a default.

[project]
name = "my-project"
# sketch | prototype | playable | integrated | release | protected
tier = "prototype"

[provider]
# auto (codegraph when .codegraph/ exists, else builtin ast scan) | codegraph | builtin | none
name = "auto"

[frames]
# byte budgets per frame; the spine always fits, the rest fills by relevance
session = 4000
prompt = 2000
edit = 1500
stop = 1000
