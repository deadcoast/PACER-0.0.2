# Exercise the real installer and both native plugin CLIs in disposable profiles.
# No model calls, authentication changes or live user-profile writes.
[CmdletBinding()]
param([string]$Engine = (Get-Process -Id $PID).Path)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$trial = Join-Path $root ('.cache/install-tests/' + [guid]::NewGuid().ToString('N'))
$fixture = Join-Path $trial "source with spaces and 'quote"
$null = New-Item -ItemType Directory -Path $fixture -Force
$codexProfile = Join-Path $trial 'codex'
$claudeProfile = Join-Path $trial 'claude'
$null = New-Item -ItemType Directory -Path $codexProfile, $claudeProfile
$utf8 = New-Object Text.UTF8Encoding($false)
$checks = @()

function Assert-Install($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:checks += $Message
}

function Run-Installer([string]$Label, [string]$ExtraPath = '', [string]$ScriptPath = '', [hashtable]$Environment = @{}) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Engine
    if (-not $ScriptPath) { $ScriptPath = Join-Path $fixture 'install.ps1' }
    $info.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $ScriptPath + '"'
    if ($Label -notin @('initial', 'renderer')) { $info.Arguments += ' -NoAnimation' }
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.WindowStyle = 'Hidden'
    $info.WorkingDirectory = $trial # The installer must use its own root from any cwd.
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.EnvironmentVariables['CODEX_HOME'] = $codexProfile
    $info.EnvironmentVariables['CLAUDE_CONFIG_DIR'] = $claudeProfile
    foreach ($key in $Environment.Keys) { $info.EnvironmentVariables[$key] = $Environment[$key] }
    if ($ExtraPath) { $info.EnvironmentVariables['PATH'] = $ExtraPath + ';' + $env:PATH }
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    $null = $process.Start()
    $out = $process.StandardOutput.ReadToEndAsync()
    $err = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(180000)) { $process.Kill(); throw "Timed out: $Label" }
    $stdout = $out.GetAwaiter().GetResult()
    $stderr = $err.GetAwaiter().GetResult()
    [IO.File]::WriteAllText((Join-Path $trial "$Label.stdout.log"), $stdout, $utf8)
    [IO.File]::WriteAllText((Join-Path $trial "$Label.stderr.log"), $stderr, $utf8)
    $code = $process.ExitCode
    $process.Dispose()
    return @{ exit = $code; stdout = $stdout; stderr = $stderr }
}

function Read-InstallResult {
    $latest = Get-ChildItem -LiteralPath (Join-Path $fixture '.cache/install/logs') -Directory | Sort-Object Name | Select-Object -Last 1
    return Get-Content -LiteralPath (Join-Path $latest.FullName 'result.json') -Raw | ConvertFrom-Json
}

$pending = New-Object 'System.Collections.Generic.Stack[string]'
$pending.Push((Join-Path $root 'plugins/pacer'))
$sources = @((Join-Path $root 'install.ps1'), (Join-Path $root '.agents/plugins/marketplace.json'), (Join-Path $root '.claude-plugin/marketplace.json'))
foreach ($relative in @('pyproject.toml', 'uv.lock', '.python-version', 'README.md')) { $sources += Join-Path $root $relative }
while ($pending.Count) {
    foreach ($item in (Get-ChildItem -LiteralPath $pending.Pop() -Force)) {
        if ($item.PSIsContainer) {
            if ($item.Name -notin @('.venv', '__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', 'dist', '.git') -and $item.Name -notlike '*.egg-info') { $pending.Push($item.FullName) }
        } elseif ($item.Extension -notin @('.pyc', '.pyo')) { $sources += $item.FullName }
    }
}
foreach ($source in $sources) {
    $destination = Join-Path $fixture $source.Substring($root.Length + 1)
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force
    Copy-Item -LiteralPath $source -Destination $destination
}
$marker = Join-Path $fixture 'plugins/pacer/refresh-marker.txt'
$obsolete = Join-Path $fixture 'plugins/pacer/removed-marker.txt'
[IO.File]::WriteAllText($marker, 'before', $utf8)
[IO.File]::WriteAllText($obsolete, 'obsolete', $utf8)
$oldEnvironment = Join-Path $fixture 'plugins/pacer/.venv'
$null = New-Item -ItemType Directory -Path $oldEnvironment
[IO.File]::WriteAllText((Join-Path $oldEnvironment 'preserve.txt'), 'old environment', $utf8)
$outsideEnvironment = Join-Path $trial 'unrelated-environment'
$null = New-Item -ItemType Directory -Path $outsideEnvironment
[IO.File]::WriteAllText((Join-Path $outsideEnvironment 'preserve.txt'), 'unrelated', $utf8)
$routing = @{ VIRTUAL_ENV = $oldEnvironment; UV_PROJECT_ENVIRONMENT = $outsideEnvironment; UV_PROJECT = $trial; UV_WORKING_DIRECTORY = $trial; UV_PYTHON = '0.0' }
$lockHashes = @('uv.lock', 'plugins/pacer/uv.lock') | ForEach-Object { Get-FileHash -LiteralPath (Join-Path $fixture $_) }
$first = Run-Installer 'initial' -Environment $routing
Assert-Install ($first.exit -eq 0) "Initial installation succeeds (logs: $trial)"
Assert-Install ($first.stdout -match '\[[= ]{20}\].*Reading source') 'Default output includes the source progress bar'
Assert-Install ($first.stdout -match '\[[= ]{20}\].*Installing PACER in Codex' -and $first.stdout -match '\[[= ]{20}\].*Installing PACER in Claude') 'Both CLI installations display a bar while working'
Assert-Install ($first.stdout -match '\[={20}\]\s+100%\s+Complete') 'The completed bar remains in default output'
$initial = Read-InstallResult
Assert-Install ($initial.workspace.action -eq 'created' -and $initial.workspace.path -eq (Join-Path $fixture '.venv')) 'First install creates the root environment despite conflicting caller routing'
Assert-Install ($initial.workspace.checks.Count -eq 2 -and @($initial.workspace.checks | Where-Object environment -ne $initial.workspace.path).Count -eq 0) 'Root and member load PACER from the shared environment'
Assert-Install ($first.stdout -match '\[[= ]{20}\].*Syncing workspace' -and $first.stdout.IndexOf('root + plugin verified') -lt $first.stdout.IndexOf('Reading source')) 'uv progress and verification precede plugin preparation'
Assert-Install (-not (Test-Path -LiteralPath $oldEnvironment) -and [IO.File]::ReadAllText((Join-Path $initial.workspace.retired 'preserve.txt')) -eq 'old environment') 'The obsolete nested environment is retired intact'
Assert-Install (@(Get-ChildItem -LiteralPath $outsideEnvironment -Force).Count -eq 1 -and [IO.File]::ReadAllText((Join-Path $outsideEnvironment 'preserve.txt')) -eq 'unrelated') 'An inherited external environment remains untouched'
Assert-Install (@($lockHashes | Where-Object { (Get-FileHash -LiteralPath $_.Path).Hash -ne $_.Hash }).Count -eq 0) 'Workspace setup preserves both lockfiles'
Assert-Install (@($initial.installs | Where-Object action -ne 'installed').Count -eq 0) 'Both absent plugins are installed'
$originalFiles = @{}
foreach ($install in $initial.installs) {
    $originalFiles[$install.agent] = @(Get-ChildItem -LiteralPath $install.path -Recurse -File -Force | Get-FileHash)
}
[IO.File]::WriteAllText($marker, 'after', $utf8)
Remove-Item -LiteralPath $obsolete
$second = Run-Installer 'refresh'
Assert-Install ($second.exit -eq 0) 'Refresh succeeds'
Assert-Install ($second.stdout -match '\[={20}\]\s+100%\s+Complete' -and -not $second.stdout.Contains([string][char]27)) 'NoAnimation retains a completed bar without cursor controls'
$refreshed = Read-InstallResult
Assert-Install ($refreshed.workspace.action -eq 'refreshed' -and $refreshed.workspace.path -eq $initial.workspace.path -and -not (Test-Path -LiteralPath $oldEnvironment)) 'Refresh reuses the root environment without recreating the nested environment'
Assert-Install ($initial.digest -ne $refreshed.digest) 'Changed and removed files select a new version'
foreach ($install in $refreshed.installs) {
    Assert-Install ($install.action -eq 'refreshed') "$($install.agent) detects the existing installation"
    Assert-Install ([IO.File]::ReadAllText((Join-Path $install.path 'refresh-marker.txt')) -eq 'after') "$($install.agent) receives changed contents"
    Assert-Install (-not (Test-Path -LiteralPath (Join-Path $install.path 'removed-marker.txt'))) "$($install.agent) drops removed contents"
    foreach ($skill in @('pacer-onboard', 'pacer-develop', 'pacer-audit')) {
        Assert-Install (Test-Path -LiteralPath (Join-Path $install.path "skills/$skill/SKILL.md")) "$($install.agent) installs $skill"
    }
    $originalFiles[$install.agent] += @(Get-ChildItem -LiteralPath $install.path -Recurse -File -Force | Get-FileHash)
}
$heldFiles = @()
try {
    foreach ($install in $refreshed.installs) {
        $heldFiles += [IO.File]::Open((Join-Path $install.path 'src/pacer_mcp/commands.py'), 'Open', 'Read', 'Read')
    }
    $repeat = Run-Installer 'repeat'
    Assert-Install ($repeat.exit -eq 0) "An unchanged refresh succeeds while installed files are open (logs: $trial)"
    $repeated = Read-InstallResult
    Assert-Install ($repeated.digest -eq $refreshed.digest) 'Unchanged source keeps the same content fingerprint'
    foreach ($install in $repeated.installs) {
        $previous = $refreshed.installs | Where-Object agent -eq $install.agent
        Assert-Install ($install.version -ne $previous.version -and $install.path -ne $previous.path) "$($install.agent) refresh uses a fresh cache version"
        Assert-Install ([IO.File]::ReadAllText((Join-Path $previous.path 'refresh-marker.txt')) -eq 'after') "$($install.agent) preserves the old installed contents"
        $unchanged = $true
        foreach ($file in $originalFiles[$install.agent]) {
            if (-not (Test-Path -LiteralPath $file.Path) -or (Get-FileHash -LiteralPath $file.Path).Hash -ne $file.Hash) { $unchanged = $false }
        }
        Assert-Install $unchanged "$($install.agent) preserves every file in both previous installations"
        $mcpFile = if ($install.agent -eq 'Codex') { 'mcp.json' } else { '.mcp.json' }
        $oldMcp = Get-Content -LiteralPath (Join-Path $previous.path $mcpFile) -Raw | ConvertFrom-Json
        $newMcp = Get-Content -LiteralPath (Join-Path $install.path $mcpFile) -Raw | ConvertFrom-Json
        Assert-Install ($oldMcp.mcpServers.pacer.env.UV_PROJECT_ENVIRONMENT -ne $newMcp.mcpServers.pacer.env.UV_PROJECT_ENVIRONMENT) "$($install.agent) refresh selects a separate Python environment"
    }
    Assert-Install (@($heldFiles | Where-Object { -not $_.CanRead }).Count -eq 0) 'Open handles remain usable throughout refresh'
} finally {
    foreach ($stream in $heldFiles) { $stream.Dispose() }
}
$fake = Join-Path $trial 'failing-cli'
$null = New-Item -ItemType Directory -Path $fake
[IO.File]::WriteAllText((Join-Path $fake 'codex.ps1'), "[Console]::Out.WriteLine('stdout diagnostic'); [Console]::Error.WriteLine('specific CLI error: test failure'); exit 23", $utf8)
$failure = Run-Installer 'failure' $fake
Assert-Install ($failure.exit -ne 0) 'A failed CLI exits nonzero'
Assert-Install ($failure.stdout.Contains('stdout diagnostic') -and $failure.stdout.Contains('specific CLI error: test failure') -and $failure.stdout.Contains('exit 23')) 'Failure displays stdout, stderr and the original exit code'
$latest = Get-ChildItem -LiteralPath (Join-Path $fixture '.cache/install/logs') -Directory | Sort-Object Name | Select-Object -Last 1
Assert-Install ((Get-Content -LiteralPath (Join-Path $latest.FullName 'install.log') -Raw).Contains('specific CLI error: test failure')) 'The full failure is retained in the durable log'
Assert-Install ((Read-InstallResult).status -eq 'failed') 'A failed run retains a structured result'
$projectPath = Join-Path $fixture 'pyproject.toml'
$projectText = [IO.File]::ReadAllText($projectPath)
[IO.File]::WriteAllText($projectPath, $projectText.Replace('version = "0.1.0"', 'version = "0.1.1"'), $utf8)
try {
    $lockFailure = Run-Installer 'stale-lock'
    Assert-Install ($lockFailure.exit -ne 0 -and $lockFailure.stdout.Contains('Syncing workspace failed') -and $lockFailure.stdout.Contains('lockfile')) 'A stale lock stops setup and displays the complete uv failure'
    Assert-Install (@((Read-InstallResult).installs).Count -eq 0 -and -not $lockFailure.stdout.Contains('Registering Codex marketplace')) 'uv failure stops before agent installation changes'
    Assert-Install (@($lockHashes | Where-Object { (Get-FileHash -LiteralPath $_.Path).Hash -ne $_.Hash }).Count -eq 0) 'A failed locked sync does not rewrite either lockfile'
} finally { [IO.File]::WriteAllText($projectPath, $projectText, $utf8) }
$pythonVersionPath = Join-Path $fixture '.python-version'
$pythonVersionText = [IO.File]::ReadAllText($pythonVersionPath)
[IO.File]::WriteAllText($pythonVersionPath, '999.0', $utf8)
try {
    $pythonFailure = Run-Installer 'missing-python'
    Assert-Install ($pythonFailure.exit -ne 0 -and $pythonFailure.stdout.Contains('Finding existing Python 999.0 failed') -and $pythonFailure.stdout.Contains('--no-python-downloads')) 'An unavailable Python version fails with downloads explicitly disabled'
    Assert-Install (@((Read-InstallResult).installs).Count -eq 0) 'Missing Python stops before agent installation changes'
} finally { [IO.File]::WriteAllText($pythonVersionPath, $pythonVersionText, $utf8) }
$probe = @'
$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot "source with spaces and 'quote/install.ps1"
$ast = [Management.Automation.Language.Parser]::ParseFile($installer, [ref]$null, [ref]$null)
foreach ($function in ($ast.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.FunctionDefinitionAst] -and $_.Name -in @('Show-InstallProgress', 'Clear-InstallProgress') })) {
    . ([scriptblock]::Create($function.Extent.Text))
}
$script:interactive = $true
$script:drawn = $false
$script:progressLabel = ''
$script:progressPercent = -1
$script:started = [Diagnostics.Stopwatch]::StartNew()
$messages = @(& {
    Show-InstallProgress 'Preparing PACER' 'src/pacer_mcp/commands.py' 25
    Show-InstallProgress 'Preparing PACER' 'skills/pacer-develop/SKILL.md' 75
    Show-InstallProgress 'Installing PACER in Codex' 'codex plugin add pacer@personal --json'
    Clear-InstallProgress
    Show-InstallProgress 'Complete' '2 agent CLIs' 100
} 6>&1)
$frames = @($messages | Where-Object { $_.MessageData.ForegroundColor -eq 'DarkGray' } | ForEach-Object { $_.ToString() })
if ($frames.Count -ne 4) { throw 'Expected four subdued frames through the host information stream' }
if ($frames[0] -notmatch '\[={5} {15}\].*25%' -or $frames[0] -notmatch 'commands.py') { throw 'First file frame was not rendered' }
if ($frames[1] -notmatch '\[={15} {5}\].*75%' -or $frames[1] -notmatch 'SKILL.md') { throw 'The current file did not change with progress' }
if ($frames[2] -notmatch '\[[= ]{20}\].*Installing PACER in Codex') { throw 'CLI work did not render a full bar' }
if ($frames[3] -notmatch '\[={20}\].*100%') { throw 'Completion did not render' }
@{ passed = $true; engine = $PSVersionTable.PSVersion.ToString(); frames = $frames; events = @($messages | ForEach-Object { $_.ToString() }) } | ConvertTo-Json -Depth 6
'@
$probePath = Join-Path $trial 'renderer.ps1'
[IO.File]::WriteAllText($probePath, $probe, $utf8)
$rendered = Run-Installer 'renderer' '' $probePath
Assert-Install ($rendered.exit -eq 0) "Animated rendering updates the bar and file in subdued host output (logs: $trial)"
$report = @{ passed = $true; engine = $Engine; checks = $checks; trial = $trial }
[IO.File]::WriteAllText((Join-Path $trial 'report.json'), ($report | ConvertTo-Json -Depth 10), $utf8)
$report | ConvertTo-Json -Depth 10
