#Requires -Version 5.1
<#
.SYNOPSIS
Install or refresh this checkout's PACER plugin for Codex and Claude Code.
.DESCRIPTION
Uses the official plugin CLIs. Full logs are retained under .cache/install/logs.
Requires existing Python 3.11+, uv and the selected agent CLIs.
#>
[CmdletBinding()]
param(
    [ValidateSet('All', 'Codex', 'Claude')][string]$Agent = 'All',
    [switch]$NoAnimation
)

$ErrorActionPreference = 'Stop'
$pacerRoot = $PSScriptRoot
$workRoot = Join-Path $pacerRoot '.cache/install'
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + "-$PID"
$logRoot = Join-Path $workRoot "logs/$runId"
$null = New-Item -ItemType Directory -Path $logRoot -Force
$logPath = Join-Path $logRoot 'install.log'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$script:step = 0
$script:drawn = $false
$script:interactive = -not $NoAnimation -and -not [Console]::IsOutputRedirected
$script:started = [Diagnostics.Stopwatch]::StartNew()
$script:results = @()

function Write-InstallLog([string]$Kind, [string]$Message) {
    [IO.File]::AppendAllText($logPath, "$(Get-Date -Format o) [$Kind] $Message`n", $utf8)
}

function Clear-InstallProgress {
    if ($script:drawn) {
        $esc = [char]27
        [Console]::Write("${esc}[2K`r${esc}[1A${esc}[2K`r")
        $script:drawn = $false
    }
}

function Show-InstallProgress([string]$Label, [string]$Current, [int]$Percent = -1) {
    if (-not $script:interactive) { return }
    $esc = [char]27
    $width = [Math]::Max(20, [Console]::WindowWidth - 5)
    if ($Percent -ge 0) {
        $filled = [int][Math]::Floor($Percent / 5)
        $bar = ('=' * $filled).PadRight(20, ' ')
        $line = "  [$bar] $($Percent.ToString().PadLeft(3))%  $Label"
    } else {
        $frame = @('|', '/', '-', '\')[[int]($script:started.ElapsedMilliseconds / 120) % 4]
        $line = "  [$frame] $Label  $([int]$script:started.Elapsed.TotalSeconds)s"
    }
    if ($line.Length -gt $width) { $line = $line.Substring(0, $width) }
    if ($Current.Length -gt $width - 2) { $Current = '...' + $Current.Substring($Current.Length - ($width - 5)) }
    if ($script:drawn) { [Console]::Write("${esc}[1A`r") }
    [Console]::Write("${esc}[2K${esc}[90m$line${esc}[0m`r`n${esc}[2K${esc}[90m  $Current${esc}[0m`r")
    $script:drawn = $true
}

function Write-InstallMilestone([string]$Message, [ConsoleColor]$Color = 'Cyan') {
    Clear-InstallProgress
    Write-Host "  $Message" -ForegroundColor $Color
    Write-InstallLog 'INFO' $Message
}

function Invoke-InstallCli([string]$Executable, [string[]]$Arguments, [string]$Label) {
    $script:step++
    $prefix = Join-Path $logRoot ($script:step.ToString('00'))
    $commandText = $Executable + ' ' + ($Arguments -join ' ')
    Write-InstallLog 'COMMAND' $commandText
    # A child PowerShell supports npm shims; encoded arguments preserve shell metacharacters.
    $quoted = @($Executable) + $Arguments | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }
    $invocation = '$ErrorActionPreference = ''Stop''; $ProgressPreference = ''SilentlyContinue''; [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); try { & ' + ($quoted -join ' ') + '; if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE } } catch { Write-Error ($_ | Out-String) -ErrorAction Continue; exit 1 }'
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($invocation))
    $engine = (Get-Process -Id $PID).Path
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $engine
    $info.Arguments = "-NoProfile -NonInteractive -OutputFormat Text -ExecutionPolicy Bypass -EncodedCommand $encoded"
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.WindowStyle = 'Hidden'
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = $utf8
    $info.StandardErrorEncoding = $utf8
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    $null = $process.Start()
    $streams = @(
        @{ Reader = $process.StandardOutput; Path = "$prefix.stdout.log"; Task = $process.StandardOutput.ReadLineAsync() },
        @{ Reader = $process.StandardError; Path = "$prefix.stderr.log"; Task = $process.StandardError.ReadLineAsync() }
    )
    foreach ($stream in $streams) { [IO.File]::WriteAllText($stream.Path, '', $utf8) }
    try {
        while (-not $process.HasExited -or $streams[0].Task -or $streams[1].Task) {
            foreach ($stream in $streams) {
                while ($stream.Task -and $stream.Task.IsCompleted) {
                    $line = $stream.Task.GetAwaiter().GetResult()
                    if ($null -eq $line) { $stream.Task = $null; break }
                    [IO.File]::AppendAllText($stream.Path, $line + "`n", $utf8)
                    $stream.Task = $stream.Reader.ReadLineAsync()
                }
            }
            Show-InstallProgress $Label $commandText
            Start-Sleep -Milliseconds 120
            $process.Refresh()
        }
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        $stdout = [IO.File]::ReadAllText("$prefix.stdout.log")
        $stderr = [IO.File]::ReadAllText("$prefix.stderr.log")
        Write-InstallLog 'STDOUT' $stdout
        Write-InstallLog 'STDERR' $stderr
        Write-InstallLog 'EXIT' "$exitCode ($Label)"
        Clear-InstallProgress
        if ($exitCode -ne 0) {
            if ($stdout) { Write-Host $stdout -ForegroundColor Yellow }
            if ($stderr) { Write-Host $stderr -ForegroundColor Red }
            throw "$Label failed (exit $exitCode). Command: $commandText"
        }
        foreach ($line in ($stderr -split '\r?\n' | Where-Object { $_ -match '(?i)warning|error' })) {
            Write-InstallMilestone $line Yellow
        }
        return $stdout
    } finally {
        if (-not $process.HasExited) { $process.Kill() }
        $process.Dispose()
    }
}

function Write-InstallJson([string]$Path, $Value) {
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 30) + "`n", $utf8)
    Write-InstallLog 'WRITE' $Path
}

function Get-InstallHash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}

try {
    Write-Host "`n  PACER / install" -ForegroundColor White
    Write-Host "  Current source -> your agent CLIs`n" -ForegroundColor DarkGray
    Write-InstallLog 'START' "source=$pacerRoot; agent=$Agent; PowerShell=$($PSVersionTable.PSVersion); user=$([Environment]::UserName)"
    $null = Get-Command uv -ErrorAction Stop
    $hosts = @()
    foreach ($name in @('Codex', 'Claude')) {
        if ($Agent -ne 'All' -and $Agent -ne $name) { continue }
        $cli = Get-Command $name.ToLowerInvariant() -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $cli) { throw "$name CLI was not found on PATH. Install it first, or select the available host with -Agent Codex or -Agent Claude." }
        $hosts += @{ Name = $name; Path = $cli.Source }
        $version = Invoke-InstallCli $cli.Source @('--version') "Finding $name"
        Write-InstallMilestone "$name  $($version.Trim())" Gray
    }
    $pluginRoot = Join-Path $pacerRoot 'plugins/pacer'
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($pluginRoot)
    $files = @()
    while ($pending.Count) {
        $directory = $pending.Pop()
        foreach ($item in (Get-ChildItem -LiteralPath $directory -Force)) {
            if ($item.PSIsContainer) {
                if ($item.Name -notin @('.venv', '__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', 'dist', '.git') -and $item.Name -notlike '*.egg-info') { $pending.Push($item.FullName) }
            } elseif ($item.Extension -notin @('.pyc', '.pyo')) { $files += $item }
        }
    }
    [string[]]$names = @($files | ForEach-Object { $_.FullName })
    [Array]::Sort($names, [StringComparer]::Ordinal)
    $files = @($names | ForEach-Object { Get-Item -LiteralPath $_ -Force })
    $inventory = @()
    for ($i = 0; $i -lt $files.Count; $i++) {
        $relative = $files[$i].FullName.Substring($pluginRoot.Length + 1).Replace('\', '/')
        Show-InstallProgress 'Reading source' $relative ([int](100 * $i / $files.Count))
        $hash = Get-InstallHash $files[$i].FullName
        $inventory += [ordered]@{ path = $relative; sha256 = $hash }
        Write-InstallLog 'SOURCE' "$hash $relative"
    }
    $hashInput = (($inventory | ForEach-Object { $_.path + ':' + $_.sha256 }) -join "`n") + (Get-InstallHash $PSCommandPath)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = ([BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($hashInput)))).Replace('-', '').ToLowerInvariant() } finally { $sha.Dispose() }
    $manifest = Get-Content -LiteralPath (Join-Path $pluginRoot 'plugin.json') -Raw | ConvertFrom-Json
    $version = ($manifest.version -split '\+')[0] + '+local.' + $digest.Substring(0, 16)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $environmentKey = ([BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($version)))).Replace('-', '').ToLowerInvariant().Substring(0, 16) }
    finally { $sha.Dispose() }
    # Distinct snapshots exclude deleted source files and preserve running older versions.
    $bundleRelative = "builds/$version/pacer"
    $bundle = Join-Path $workRoot $bundleRelative
    for ($i = 0; $i -lt $files.Count; $i++) {
        $relative = $inventory[$i].path
        Show-InstallProgress 'Preparing PACER' $relative ([int](100 * $i / $files.Count))
        $destination = Join-Path $bundle $relative
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force
        Copy-Item -LiteralPath $files[$i].FullName -Destination $destination -Force
        Write-InstallLog 'COPY' "$relative -> $destination"
    }
    Show-InstallProgress 'Preparing PACER' $relative 100
    foreach ($relative in @('plugin.json', '.codex-plugin/plugin.json', '.claude-plugin/plugin.json')) {
        $path = Join-Path $bundle $relative
        $json = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        $json.version = $version
        Write-InstallJson $path $json
    }
    $mcpPath = Join-Path $bundle 'mcp.json'
    $mcp = Get-Content -LiteralPath $mcpPath -Raw | ConvertFrom-Json
    $mcp.mcpServers.pacer.env.UV_PROJECT_ENVIRONMENT = '${PLUGIN_DATA}/venv-' + $environmentKey
    Write-InstallJson $mcpPath $mcp
    $mcpPath = Join-Path $bundle '.mcp.json'
    $mcp = Get-Content -LiteralPath $mcpPath -Raw | ConvertFrom-Json
    $mcp.mcpServers.pacer.env.UV_PROJECT_ENVIRONMENT = '${CLAUDE_PLUGIN_DATA}/venv-' + $environmentKey
    Write-InstallJson $mcpPath $mcp
    $market = Get-Content -LiteralPath (Join-Path $pacerRoot '.agents/plugins/marketplace.json') -Raw | ConvertFrom-Json
    $market.plugins[0].source.path = "./$bundleRelative"
    Write-InstallJson (Join-Path $workRoot '.agents/plugins/marketplace.json') $market
    $claudeMarket = Get-Content -LiteralPath (Join-Path $pacerRoot '.claude-plugin/marketplace.json') -Raw | ConvertFrom-Json
    $claudeMarket.plugins[0].source = "./$bundleRelative"
    Write-InstallJson (Join-Path $workRoot '.claude-plugin/marketplace.json') $claudeMarket
    Write-InstallMilestone "Prepared $($files.Count) files  /  $version"
    foreach ($hostCli in $hosts) {
        $name = $hostCli.Name
        $cli = $hostCli.Path
        $pluginId = 'pacer@' + $market.name
        if ($name -eq 'Codex') {
            $before = Invoke-InstallCli $cli @('plugin', 'list', '--marketplace', $market.name, '--json') 'Checking Codex installation' | ConvertFrom-Json
            $existing = @($before.installed | Where-Object { $_.pluginId -eq $pluginId }).Count -gt 0
            $markets = Invoke-InstallCli $cli @('plugin', 'marketplace', 'list', '--json') 'Checking Codex marketplace'
            $registered = @(($markets | ConvertFrom-Json).marketplaces | Where-Object { $_.name -eq $market.name })
            if ($registered.Count -and $registered[0].root.Replace('\', '/') -ne $workRoot.Replace('\', '/')) {
                # Codex requires removing the old source registration before retargeting it.
                # This command preserves installed versions and their data.
                $null = Invoke-InstallCli $cli @('plugin', 'marketplace', 'remove', $market.name) 'Updating Codex marketplace location'
            }
            $null = Invoke-InstallCli $cli @('plugin', 'marketplace', 'add', $workRoot) 'Registering Codex marketplace'
            $install = Invoke-InstallCli $cli @('plugin', 'add', $pluginId, '--json') 'Installing PACER in Codex' | ConvertFrom-Json
            if ($install.version -ne $version) { throw 'Codex did not install the current PACER version.' }
            $installedPath = $install.installedPath
        } else {
            $pluginId = 'pacer@' + $claudeMarket.name
            $before = Invoke-InstallCli $cli @('plugin', 'list', '--json') 'Checking Claude installation' | ConvertFrom-Json
            $existing = @($before | Where-Object { $_.id -eq $pluginId -and $_.scope -eq 'user' }).Count -gt 0
            $null = Invoke-InstallCli $cli @('plugin', 'marketplace', 'add', $workRoot, '--scope', 'user') 'Registering Claude marketplace'
            if ($existing) {
                $null = Invoke-InstallCli $cli @('plugin', 'marketplace', 'update', $claudeMarket.name) 'Refreshing Claude marketplace'
            }
            $verb = if ($existing) { 'update' } else { 'install' }
            $null = Invoke-InstallCli $cli @('plugin', $verb, $pluginId, '--scope', 'user') 'Installing PACER in Claude'
            $after = Invoke-InstallCli $cli @('plugin', 'list', '--json') 'Locating installed Claude plugin' | ConvertFrom-Json
            $installed = @($after | Where-Object { $_.id -eq $pluginId -and $_.scope -eq 'user' })
            if ($installed.Count -ne 1 -or $installed[0].version -ne $version) { throw 'Claude did not select the current PACER version. See CLI output in the installation log.' }
            if (-not $installed[0].enabled) {
                $null = Invoke-InstallCli $cli @('plugin', 'enable', $pluginId, '--scope', 'user') 'Enabling PACER in Claude'
            }
            $installedPath = $installed[0].installPath
        }
        $action = if ($existing) { 'refreshed' } else { 'installed' }
        $script:results += [ordered]@{ agent = $name; action = $action; version = $version; path = $installedPath }
        Write-InstallMilestone "$name  $action" Green
        Write-InstallMilestone $installedPath DarkGray
    }
    Write-InstallJson (Join-Path $logRoot 'result.json') ([ordered]@{ source = $pacerRoot; digest = $digest; files = $inventory; installs = $script:results })
    Write-InstallMilestone "Complete  /  $([Math]::Round($script:started.Elapsed.TotalSeconds, 1))s" Green
    Write-Host '  Start a new agent session to load the updated skills and MCP server.' -ForegroundColor Gray
    Write-Host "  Logs: $logRoot`n" -ForegroundColor DarkGray
} catch {
    Clear-InstallProgress
    $details = ($_ | Format-List * -Force | Out-String) + "`n" + $_.ScriptStackTrace
    Write-InstallLog 'ERROR' $details
    Write-Host "`n  PACER / installation failed" -ForegroundColor Red
    Write-Host $details -ForegroundColor Red
    if ($script:results.Count) { Write-Host ('  Completed before failure: ' + (($script:results | ForEach-Object { $_.agent }) -join ', ')) -ForegroundColor Yellow }
    Write-Host "  Full logs: $logRoot`n" -ForegroundColor Yellow
    exit 1
} finally {
    Clear-InstallProgress
}
