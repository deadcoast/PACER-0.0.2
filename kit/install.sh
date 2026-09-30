#!/usr/bin/env bash
# Install the PACER 3 plugin into Claude Code and/or Codex and put the `pacer` CLI on PATH.
# Usage: ./install.sh [--agent claude|codex|both] [--no-tool]
set -euo pipefail
kit="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
market="$kit/marketplace"
plugin="$market/plugins/pacer"
version="$(tr -d '[:space:]' < "$kit/VERSION")"
agent="both"
tool=1
while [ $# -gt 0 ]; do
  case "$1" in
    --agent) agent="$2"; shift 2 ;;
    --no-tool) tool=0; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
echo "PACER $version kit  /  $kit"
done=()
if [ "$agent" = "both" ] || [ "$agent" = "claude" ]; then
  if command -v claude >/dev/null; then
    if claude plugin marketplace list 2>/dev/null | grep -q pacer3; then claude plugin marketplace update pacer3 >/dev/null
    else claude plugin marketplace add "$market" --scope user >/dev/null; fi
    for dup in $(claude plugin list --json 2>/dev/null | grep -o '"id": *"pacer@[^"]*"' | sed 's/.*"pacer@/pacer@/; s/"//' | grep -v '^pacer@pacer3$' | sort -u); do
      claude plugin uninstall "$dup" --scope user >/dev/null 2>&1 && echo "Claude Code  replaced $dup (one PACER copy per host)"
    done
    if claude plugin list --json 2>/dev/null | grep -q 'pacer@pacer3'; then claude plugin update pacer@pacer3 --scope user >/dev/null
    else claude plugin install pacer@pacer3 --scope user >/dev/null; fi
    done+=("Claude Code")
  elif [ "$agent" = "claude" ]; then echo "claude CLI not found" >&2; exit 1; fi
fi
if [ "$agent" = "both" ] || [ "$agent" = "codex" ]; then
  if command -v codex >/dev/null; then
    codex plugin marketplace list --json 2>/dev/null | grep -q '"pacer3"' || codex plugin marketplace add "$market" >/dev/null
    for m in $(codex plugin marketplace list --json 2>/dev/null | grep -o '"name": *"[^"]*"' | sed 's/.*: *"//; s/"//' | grep -v '^pacer3$' | sort -u); do
      if codex plugin list --marketplace "$m" --json 2>/dev/null | grep -q "\"pluginId\": *\"pacer@$m\""; then
        codex plugin remove "pacer@$m" --json >/dev/null 2>&1 && echo "Codex  replaced pacer@$m (one PACER copy per host)"
      fi
    done
    if codex plugin list --marketplace pacer3 --json 2>/dev/null | grep -q '"installed": *true'; then codex plugin update pacer@pacer3 --json >/dev/null
    else codex plugin add pacer@pacer3 --json >/dev/null; fi
    done+=("Codex")
  elif [ "$agent" = "codex" ]; then echo "codex CLI not found" >&2; exit 1; fi
fi
if [ "$tool" = 1 ]; then
  uv tool install --force --from "$plugin" pacer-mcp >/dev/null
  done+=("pacer CLI (uv tool)")
fi
[ ${#done[@]} -gt 0 ] || { echo "No agent CLI found; install claude or codex." >&2; exit 1; }
echo "Installed: ${done[*]}"
echo "Start a new agent session. In a project: pacer --root . initialize"
