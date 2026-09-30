#Requires -Version 5.1
<#
.SYNOPSIS
  Install the PACER 3 plugin into Claude Code and/or Codex and put the `pacer` CLI on PATH.
.PARAMETER Agent
  Claude, Codex or Both (default: every CLI found).
.PARAMETER NoTool
  Skip `uv tool install` of the pacer CLI.
#>
[CmdletBinding()]
param(
    [ValidateSet('Both', 'Claude', 'Codex')] [string] $Agent = 'Both',
    [switch] $NoTool
)
$ErrorActionPreference = 'Stop'
$kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$market = Join-Path $kit 'marketplace'
$plugin = Join-Path $market 'plugins\pacer'
$version = (Get-Content (Join-Path $kit 'VERSION') -Raw).Trim()

function Find-Cli([string] $name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

Write-Host "PACER $version kit  /  $kit"
$uv = Find-Cli 'uv'
if (-not $uv) { throw 'uv is required: https://docs.astral.sh/uv/getting-started/installation/' }

$done = @()
if ($Agent -in @('Both', 'Claude')) {
    $claude = Find-Cli 'claude'
    if ($claude) {
        Write-Host "Claude Code  $(& $claude --version 2>$null | Select-Object -First 1)"
        $listed = & $claude plugin marketplace list 2>$null | Out-String
        if ($listed -match 'pacer3') { & $claude plugin marketplace update pacer3 | Out-Null }
        else { & $claude plugin marketplace add $market --scope user | Out-Null }
        $installed = & $claude plugin list --json 2>$null | Out-String
        if ($installed -match 'pacer@pacer3') { & $claude plugin update pacer@pacer3 --scope user | Out-Null }
        else { & $claude plugin install pacer@pacer3 --scope user | Out-Null }
        $done += 'Claude Code'
    } elseif ($Agent -eq 'Claude') { throw 'claude CLI not found on PATH' }
}
if ($Agent -in @('Both', 'Codex')) {
    $codex = Find-Cli 'codex'
    if ($codex) {
        Write-Host "Codex  $(& $codex --version 2>$null | Select-Object -First 1)"
        $markets = & $codex plugin marketplace list --json 2>$null | Out-String
        if ($markets -notmatch '"pacer3"') { & $codex plugin marketplace add $market | Out-Null }
        $plugins = & $codex plugin list --marketplace pacer3 --json 2>$null | Out-String
        if ($plugins -match '"installed":\s*true') { & $codex plugin update pacer@pacer3 --json | Out-Null }
        else { & $codex plugin add pacer@pacer3 --json | Out-Null }
        $done += 'Codex'
    } elseif ($Agent -eq 'Codex') { throw 'codex CLI not found on PATH' }
}
if (-not $NoTool) {
    & $uv tool install --force --from $plugin pacer-mcp | Out-Null
    $done += 'pacer CLI (uv tool)'
}
if ($done.Count -eq 0) { throw 'No agent CLI found; install claude or codex, or pass -NoTool to only stage the marketplace.' }
Write-Host "Installed: $($done -join ', ')"
Write-Host 'Start a new agent session. In a project: pacer --root . initialize'
