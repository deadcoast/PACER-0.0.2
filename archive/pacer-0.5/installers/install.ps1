#Requires -Version 5.1
<#
.SYNOPSIS
Install or refresh this checkout's PACER plugin for Codex and Claude Code.
.DESCRIPTION
Uses the official plugin CLIs. Full logs are retained under .cache/install/logs.
Prepares the root uv workspace, then uses the official plugin CLIs.
Requires existing uv, the Python version in .python-version and the selected CLIs.
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
$script:interactive = -not $NoAnimation -and ($Host.UI.SupportsVirtualTerminal -or -not [Console]::IsOutputRedirected)
$script:progressLabel = ''
$script:progressPercent = -1
$script:started = [Diagnostics.Stopwatch]::StartNew()
$script:results = @()
$script:workspace = $null

function Write-InstallLog([string]$Kind, [string]$Message) {
    [IO.File]::AppendAllText($logPath, "$(Get-Date -Format o) [$Kind] $Message`n", $utf8)
}

function Clear-InstallProgress {
    if ($script:drawn) {
        $esc = [char]27
        Write-Host "${esc}[2K`r${esc}[1A${esc}[2K`r" -NoNewline
        $script:drawn = $false
    }
}

function Show-InstallProgress([string]$Label, [string]$Current, [int]$Percent = -1) {
    $esc = [char]27
    $width = 115
    try {
        if ($Host.UI.RawUI.WindowSize.Width -gt 10) { $width = $Host.UI.RawUI.WindowSize.Width - 5 }
    } catch { } # Some PowerShell hosts expose output without a console window.
    if ($Percent -ge 0) {
        $filled = [int][Math]::Floor($Percent / 5)
        $bar = ('=' * $filled).PadRight(20, ' ')
        $line = "  [$bar] $($Percent.ToString().PadLeft(3))%  $Label"
    } else {
        # This moving segment means busy; CLI operations expose no percentage.
        $position = [int]($script:started.ElapsedMilliseconds / 120) % 34
        if ($position -gt 17) { $position = 34 - $position }
        $bar = (' ' * $position + '===').PadRight(20, ' ')
        $line = "  [$bar] $Label  $([int]$script:started.Elapsed.TotalSeconds)s"
    }
    if ($line.Length -gt $width) { $line = $line.Substring(0, $width) }
    if ($Current.Length -gt $width - 2) { $Current = '...' + $Current.Substring($Current.Length - ($width - 5)) }
    if ($script:interactive) {
        if ($script:drawn) { Write-Host "${esc}[1A`r" -NoNewline }
        Write-Host "${esc}[2K$line`r`n${esc}[2K  $Current`r" -NoNewline -ForegroundColor DarkGray
        $script:drawn = $true
    } elseif ($Label -ne $script:progressLabel -or ($Percent -eq 100 -and $script:progressPercent -ne 100)) {
        # Keep progress visible without cursor controls in transcripts and plain hosts.
        Write-Host $line -ForegroundColor DarkGray
        Write-Host "  $Current" -ForegroundColor DarkGray
    }
    $script:progressLabel = $Label
    $script:progressPercent = $Percent
}

function Write-InstallMilestone([string]$Message, [ConsoleColor]$Color = 'Cyan') {
    Clear-InstallProgress
    Write-Host "  $Message" -ForegroundColor $Color
    Write-InstallLog 'INFO' $Message
}

function Invoke-InstallCli([string]$Executable, [string[]]$Arguments, [string]$Label,
    [hashtable]$Environment = @{}, [string]$WorkingDirectory = $pacerRoot, [string]$Current = '', [switch]$FollowOutput) {
    $script:step++
    $prefix = Join-Path $logRoot ($script:step.ToString('00'))
    $commandText = $Executable + ' ' + ($Arguments -join ' ')
    Write-InstallLog 'COMMAND' $commandText
    Write-InstallLog 'CWD' $WorkingDirectory
    if (-not $Current) { $Current = $commandText }
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
    $info.WorkingDirectory = $WorkingDirectory
    foreach ($key in $Environment.Keys) {
        if ($null -eq $Environment[$key]) { $info.EnvironmentVariables.Remove($key) }
        else { $info.EnvironmentVariables[$key] = $Environment[$key] }
    }
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
                    if ($FollowOutput -and $line.Trim()) { $Current = $line.Trim() }
                    $stream.Task = $stream.Reader.ReadLineAsync()
                }
            }
            Show-InstallProgress $Label $Current
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
    Write-InstallLog 'DISPLAY' "animated=$script:interactive; host=$($Host.Name); virtualTerminal=$($Host.UI.SupportsVirtualTerminal); outputRedirected=$([Console]::IsOutputRedirected)"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) { throw 'uv is not available on PATH. Make your existing uv installation available, then rerun install.ps1.' }
    $uvVersion = (Invoke-InstallCli $uv.Source @('--version') 'Checking uv').Trim()
    Write-InstallMilestone $uvVersion Gray
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
    $environmentPath = Join-Path $pacerRoot '.venv'
    # Scope routing corrections to child processes; never rewrite the caller's shell.
    $uvEnvironment = @{
        UV_PROJECT_ENVIRONMENT = $environmentPath; UV_PYTHON_DOWNLOADS = 'never'
        VIRTUAL_ENV = $null; UV_PROJECT = $null; UV_WORKING_DIRECTORY = $null
        UV_PYTHON = $null; PYTHONHOME = $null; PYTHONPATH = $null
    }
    foreach ($key in @('VIRTUAL_ENV', 'UV_PROJECT_ENVIRONMENT', 'UV_PROJECT', 'UV_WORKING_DIRECTORY', 'UV_PYTHON', 'PYTHONHOME', 'PYTHONPATH')) {
        if ([Environment]::GetEnvironmentVariable($key)) {
            Write-InstallLog 'ROUTING' "Ignoring inherited $key for workspace setup"
        }
    }
    Write-InstallLog 'ROUTING' "project=$pacerRoot; environment=$environmentPath; Python downloads=never"
    $pythonRequest = (Get-Content -LiteralPath (Join-Path $pacerRoot '.python-version') -Raw).Trim()
    $python = (Invoke-InstallCli $uv.Source @('python', 'find', '--system', '--no-project', '--no-python-downloads', $pythonRequest) "Finding existing Python $pythonRequest" -Environment $uvEnvironment).Trim()
    Write-InstallMilestone "Python $pythonRequest  /  $python" Gray
    $existed = Test-Path -LiteralPath (Join-Path $environmentPath 'pyvenv.cfg')
    $null = Invoke-InstallCli $uv.Source @('sync', '--locked', '--project', $pacerRoot, '--python', $python, '--no-python-downloads') 'Syncing workspace' -Environment $uvEnvironment -Current (Join-Path $pacerRoot 'uv.lock') -FollowOutput
    # Single quotes survive Windows PowerShell's legacy native argument marshalling.
    $probe = 'import json, sys, pacer_mcp, pacer_mcp.cli, pacer_mcp.server; from importlib.metadata import version; print(json.dumps(dict(environment=sys.prefix, python=sys.version.split()[0], source=pacer_mcp.__file__, package=version(''pacer-mcp''), pytest=version(''pytest''), ruff=version(''ruff''))))'
    $verified = @()
    foreach ($project in @($pacerRoot, $pluginRoot)) {
        $label = if ($project -eq $pacerRoot) { 'Checking root runtime' } else { 'Checking plugin runtime' }
        $runtime = Invoke-InstallCli $uv.Source @('run', '--locked', '--no-sync', '--project', $project, 'python', '-c', $probe) $label -Environment $uvEnvironment -Current $project | ConvertFrom-Json
        if ([IO.Path]::GetFullPath($runtime.environment) -ne $environmentPath -or [IO.Path]::GetFullPath($runtime.source) -ne (Join-Path $pluginRoot 'src/pacer_mcp/__init__.py').Replace('/', '\')) {
            throw "Wrong PACER runtime for $project : $($runtime | ConvertTo-Json -Compress)"
        }
        $verified += $runtime
    }
    $script:workspace = [ordered]@{ uv = $uvVersion; python = $verified[0].python; path = $environmentPath; action = $(if ($existed) { 'refreshed' } else { 'created' }); checks = $verified; retired = $null }
    Write-InstallMilestone "Workspace  $($script:workspace.action)  /  Python $($script:workspace.python)" Green
    Write-InstallMilestone "$environmentPath  /  root + plugin verified" DarkGray
    $nested = Join-Path $pluginRoot '.venv'
    if (Test-Path -LiteralPath $nested) {
        $old = Get-Item -LiteralPath $nested -Force
        $retired = [IO.Path]::GetFullPath((Join-Path $pacerRoot ".cache/retired-environments/install-$runId-plugin-venv"))
        # Never follow an environment junction or move anything outside this checkout.
        if (-not $old.PSIsContainer -or ($old.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $old.FullName -ne $nested -or -not $retired.StartsWith($pacerRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Cannot retire the old environment safely: $nested"
        }
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $retired) -Force
        try {
            Move-Item -LiteralPath $old.FullName -Destination $retired
            $script:workspace.retired = $retired
            Write-InstallMilestone 'Old plugin environment  preserved in .cache/retired-environments' Gray
            Write-InstallLog 'RETIRED' "$nested -> $retired"
        } catch {
            Write-InstallLog 'WARNING' ($_ | Format-List * -Force | Out-String)
            Write-InstallMilestone "Old plugin environment remains at $nested; close processes using it and rerun. The verified root environment is ready." Yellow
        }
    }
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
    # Codex backs up an existing cache directory before replacing it. Windows
    # refuses that rename while an agent holds files open, even for identical source.
    # Keep the content fingerprint stable and give each install its own directory.
    # Codex selects the greatest remaining cache version. Put the increasing
    # generation before the fingerprint; 'r' sorts above legacy hex digests.
    $generation = [DateTime]::UtcNow.Ticks
    $version = ($manifest.version -split '\+')[0] + '+local.r' + $generation + '.' + $digest.Substring(0, 16)
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
            # Exactly one PACER copy per host: a copy from another marketplace (for example a kit
            # install) would run the hooks and MCP server twice, so it is replaced here.
            foreach ($other in @(($markets | ConvertFrom-Json).marketplaces | Where-Object { $_.name -ne $market.name })) {
                $otherList = Invoke-InstallCli $cli @('plugin', 'list', '--marketplace', $other.name, '--json') "Checking $($other.name) marketplace" | ConvertFrom-Json
                foreach ($dup in @($otherList.installed | Where-Object { $_.name -eq 'pacer' })) {
                    $null = Invoke-InstallCli $cli @('plugin', 'remove', $dup.pluginId, '--json') "Replacing $($dup.pluginId)"
                    Write-InstallMilestone "Codex  replaced $($dup.pluginId)" Yellow
                }
            }
            $previous = $before.installed | Where-Object { $_.pluginId -eq $pluginId } | Select-Object -First 1
            $protectedFiles = @()
            try {
                if ($previous) {
                    $codexDataRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
                    $previousPath = Join-Path $codexDataRoot "plugins/cache/$($market.name)/pacer"
                    if (Test-Path -LiteralPath $previousPath) {
                        # Codex also prunes older versions after installing. Keep their
                        # files readable/writable but deny deletion during that cleanup,
                        # so a running session does not lose part of its package.
                        foreach ($cachedVersion in (Get-ChildItem -LiteralPath $previousPath -Directory -Force)) {
                            foreach ($file in (Get-ChildItem -LiteralPath $cachedVersion.FullName -Recurse -File -Force)) {
                                $protectedFiles += [IO.File]::Open($file.FullName, 'Open', 'Read', 'ReadWrite')
                            }
                        }
                        Write-InstallLog 'PRESERVE' "$($protectedFiles.Count) files in $previousPath"
                    }
                }
                $install = Invoke-InstallCli $cli @('plugin', 'add', $pluginId, '--json') 'Installing PACER in Codex' | ConvertFrom-Json
            } finally {
                foreach ($stream in $protectedFiles) { $stream.Dispose() }
            }
            if ($install.version -ne $version) { throw 'Codex did not install the current PACER version.' }
            $installedPath = $install.installedPath
        } else {
            $pluginId = 'pacer@' + $claudeMarket.name
            $before = Invoke-InstallCli $cli @('plugin', 'list', '--json') 'Checking Claude installation' | ConvertFrom-Json
            $existing = @($before | Where-Object { $_.id -eq $pluginId -and $_.scope -eq 'user' }).Count -gt 0
            $null = Invoke-InstallCli $cli @('plugin', 'marketplace', 'add', $workRoot, '--scope', 'user') 'Registering Claude marketplace'
            foreach ($dup in @($before | Where-Object { $_.id -like 'pacer@*' -and $_.id -ne $pluginId })) {
                $null = Invoke-InstallCli $cli @('plugin', 'uninstall', $dup.id, '--scope', $dup.scope) "Replacing $($dup.id)"
                Write-InstallMilestone "Claude  replaced $($dup.id)" Yellow
            }
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
    Write-InstallJson (Join-Path $logRoot 'result.json') ([ordered]@{ status = 'complete'; source = $pacerRoot; workspace = $script:workspace; digest = $digest; files = $inventory; installs = $script:results })
    Show-InstallProgress 'Complete' "$($script:results.Count) agent CLI(s)  /  $($files.Count) files  /  $([Math]::Round($script:started.Elapsed.TotalSeconds, 1))s" 100
    if ($script:drawn) { Write-Host ''; $script:drawn = $false }
    Write-InstallLog 'INFO' 'Installation complete'
    Write-Host '  Start a new agent session to load the updated skills and MCP server.' -ForegroundColor Gray
    Write-Host "  Logs: $logRoot`n" -ForegroundColor DarkGray
} catch {
    Clear-InstallProgress
    $details = ($_ | Format-List * -Force | Out-String) + "`n" + $_.ScriptStackTrace
    Write-InstallLog 'ERROR' $details
    Write-InstallJson (Join-Path $logRoot 'result.json') ([ordered]@{ status = 'failed'; source = $pacerRoot; workspace = $script:workspace; installs = $script:results; error = $details })
    Write-Host "`n  PACER / installation failed" -ForegroundColor Red
    Write-Host $details -ForegroundColor Red
    if ($script:results.Count) { Write-Host ('  Completed before failure: ' + (($script:results | ForEach-Object { $_.agent }) -join ', ')) -ForegroundColor Yellow }
    Write-Host "  Full logs: $logRoot`n" -ForegroundColor Yellow
    exit 1
} finally {
    Clear-InstallProgress
}
