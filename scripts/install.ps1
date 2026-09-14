# Install this repository's PACER plugin using the official Codex CLI.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$pacerRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pacerMarketplace = Join-Path $pacerRoot '.agents/plugins/marketplace.json'
$pacerName = (Get-Content -LiteralPath $pacerMarketplace -Raw | ConvertFrom-Json).name
if ($pacerName -notmatch '^[a-z0-9][a-z0-9_-]*$') {
    throw 'Invalid marketplace name'
}
$null = Get-Command uv -ErrorAction Stop
$pacerCodex = Get-Command codex -ErrorAction Stop

# This is an explicit repository marketplace, separate from the implicit
# user-profile marketplace. Codex owns all configuration and cache mutations.
& $pacerCodex plugin marketplace add $pacerRoot
if ($LASTEXITCODE -ne 0) { throw 'Codex marketplace installation failed' }
& $pacerCodex plugin add "pacer@$pacerName" --json
if ($LASTEXITCODE -ne 0) { throw 'Codex plugin installation failed' }
& $pacerCodex plugin list --marketplace $pacerName --json
if ($LASTEXITCODE -ne 0) { throw 'Codex plugin discovery failed' }
Write-Output 'PACER installed. Start a new Codex thread and invoke $pacer:pacer-onboard.'
