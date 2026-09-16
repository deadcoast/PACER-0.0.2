# Compatibility entry point; the root installer owns installation and refresh.
[CmdletBinding()]
param(
    [ValidateSet('All', 'Codex', 'Claude')][string]$Agent = 'All',
    [switch]$NoAnimation
)
& (Join-Path $PSScriptRoot '../install.ps1') @PSBoundParameters
