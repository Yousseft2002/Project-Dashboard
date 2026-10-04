#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ConfigPath,
    [string]$DeviceName,
    [string]$ServerUrl,
    [string[]]$Workspaces,
    [string]$TestProject,
    [switch]$LocalDevelopment,
    [switch]$NoRun
)
$ErrorActionPreference = 'Stop'
if (-not $ConfigPath) { $ConfigPath = Join-Path $PSScriptRoot 'collector.config.json' }
Write-Host 'PROJECT PLANNER COLLECTOR SETUP'
Write-Host 'Your browser password is not used. Approve a pairing code in Settings -> Integrations, or use a separate collector token.'

$pythonCandidates = @('python', 'py', (Join-Path $env:LOCALAPPDATA 'Python\bin\python.exe'))
$pythonRoot = Join-Path $env:LOCALAPPDATA 'Python'
if (Test-Path -LiteralPath $pythonRoot) {
    $pythonCandidates += @(Get-ChildItem -LiteralPath $pythonRoot -Directory | ForEach-Object { Join-Path $_.FullName 'python.exe' })
}
$pythonExe = $null
$pythonPrefix = @()
foreach ($candidate in $pythonCandidates) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
    $candidatePrefix = @()
    if ($candidate -eq 'py') { $candidatePrefix = @('-3') }
    try {
        & $candidate @candidatePrefix -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonExe = $candidate; $pythonPrefix = $candidatePrefix; break }
    } catch { continue }
}
if (-not $pythonExe) { throw 'Install Python 3.11 or newer from python.org, then run setup again.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows, then run setup again. The first verification requires a real Git repository.' }
$collectorScript = Join-Path $PSScriptRoot 'collector.py'
$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
$configDirectory = Split-Path -Parent $ConfigPath
$previous = $null
if (Test-Path -LiteralPath $ConfigPath) { $previous = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json }
if (-not $ServerUrl) {
    $defaultServer = 'https://project-dashboard-0d02.onrender.com'
    if ($env:PROJECT_PLANNER_URL) { $defaultServer = $env:PROJECT_PLANNER_URL }
    elseif ($previous -and $previous.server) { $defaultServer = $previous.server }
    $answer = Read-Host "Server URL [$defaultServer]"
    $ServerUrl = if ($answer) { $answer } else { $defaultServer }
}
if (-not $DeviceName) {
    $defaultDevice = $env:COMPUTERNAME
    if ($previous -and $previous.device_name) { $defaultDevice = $previous.device_name }
    $answer = Read-Host "Device name [$defaultDevice]"
    $DeviceName = if ($answer) { $answer } else { $defaultDevice }
}
if ($DeviceName -notmatch '^[\w .-]{1,80}$') { throw 'Device name must contain 1-80 letters, numbers, spaces, dots, dashes or underscores.' }
if (-not $Workspaces) {
    Write-Host 'Suggested folders (nothing is scanned/uploaded until you select them):'
    $suggestionJson = & $pythonExe @pythonPrefix $collectorScript suggest
    if ($LASTEXITCODE -ne 0) { throw 'Workspace suggestions failed.' }
    $suggestions = @($suggestionJson | ConvertFrom-Json)
    for ($i = 0; $i -lt $suggestions.Count; $i++) { Write-Host "$($i+1). $($suggestions[$i].path) [$($suggestions[$i].source)]" }
    $selected = Read-Host 'Select folder numbers, separated by commas (blank selects none)'
    $chosen = @()
    if ($selected) {
        foreach ($part in $selected.Split(',')) {
            $number = 0
            if (-not [int]::TryParse($part.Trim(), [ref]$number) -or $number -lt 1 -or $number -gt $suggestions.Count) { throw 'Invalid folder selection.' }
            $chosen += $suggestions[$number-1].path
        }
    }
    do {
        $extra = Read-Host 'Additional workspace folder (blank to finish)'
        if ($extra) { $chosen += $extra }
    } while ($extra)
    $Workspaces = @($chosen | Select-Object -Unique)
}
if (-not $Workspaces.Count) { throw 'Select at least one workspace folder.' }
foreach ($folder in $Workspaces) { if (-not (Test-Path -LiteralPath $folder -PathType Container)) { throw "Workspace folder is unavailable: $folder" } }

$installationId = [guid]::NewGuid().ToString()
if ($previous -and $previous.installation_id) { $installationId = $previous.installation_id }
$tokenFile = Join-Path $configDirectory 'collector.token.dpapi'
$reuse = $false
if ((Test-Path -LiteralPath $tokenFile) -and $previous -and $previous.server -eq $ServerUrl) {
    $reuse = (Read-Host 'Reuse this computer''s protected collector token? [Y/n]') -notmatch '^[nN]'
}
$usePairing = $false
if (-not $reuse) {
    $method = Read-Host 'Approve a browser pairing code (P), or enter an existing collector token (T)? [P]'
    if ($method -match '^[tT]') {
        $collectorSecret = Read-Host 'Collector token (generated for this computer on the production dashboard)' -AsSecureString
        if ($collectorSecret.Length -lt 20) { throw 'Collector token is missing or too short. Do not use your browser password.' }
        New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
        ConvertFrom-SecureString -SecureString $collectorSecret | Set-Content -LiteralPath $tokenFile -Encoding ASCII
    } else { $usePairing = $true }
}
$config = [ordered]@{ server = $ServerUrl.TrimEnd('/'); device_name = $DeviceName; installation_id = $installationId; token_file = $tokenFile; workspaces = @($Workspaces); sync_seconds = 300; heartbeat_seconds = 60; max_depth = 5; ai_metadata = $false; ignore = @() }
if ($previous -and $previous.device_id -and $previous.server -eq $ServerUrl) { $config.device_id = $previous.device_id }
$config | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
$developmentArgs = @()
if ($LocalDevelopment) { $developmentArgs = @('--local-development') }
if ($usePairing) {
    Write-Host 'Requesting pairing. Approve the exact code shown next in your signed-in dashboard.'
    & $pythonExe @pythonPrefix $collectorScript pair --config $ConfigPath @developmentArgs
    if ($LASTEXITCODE -ne 0) { throw 'Pairing failed. No project data was uploaded.' }
}
Write-Host 'Testing HTTPS, registration and heartbeat FIRST...'
& $pythonExe @pythonPrefix $collectorScript test --config $ConfigPath --heartbeat-only @developmentArgs
if ($LASTEXITCODE -ne 0) { throw 'Heartbeat verification failed. No project data was uploaded. Correct the reported error and rerun setup.' }
Write-Host "Open $ServerUrl/#/integrations and confirm this device is online."
if ((Read-Host 'Does the dashboard show this device online? [y/N]') -notmatch '^[yY]') { throw 'Stopped before project ingestion. Verify the production dashboard/device connection first.' }

if (-not $TestProject) { $TestProject = Read-Host 'Path to ONE real Git repository (must contain at least one commit)' }
Write-Host 'Testing ONE repository...'
& $pythonExe @pythonPrefix $collectorScript test --config $ConfigPath --project $TestProject @developmentArgs
if ($LASTEXITCODE -ne 0) { throw 'One-project verification failed. Full-workspace synchronization was not started.' }
if ((Read-Host 'Refresh the dashboard. Is the real project and its commit visible? [y/N]') -notmatch '^[yY]') { throw 'Stopped before full sync. Verify project rendering first.' }
Write-Host 'Synchronizing selected workspace folders...'
& $pythonExe @pythonPrefix $collectorScript --config $ConfigPath --once @developmentArgs
if ($LASTEXITCODE -ne 0) { throw 'Workspace sync failed. Previous server data is retained.' }
Write-Host "Project Planner: $ServerUrl"
Write-Host 'Setup complete. Configuration is non-secret; the token is protected with Windows DPAPI.'
if (-not $NoRun) {
    Write-Host 'Collector running. Keep this window open; Ctrl+C stops it.'
    & $pythonExe @pythonPrefix $collectorScript --config $ConfigPath @developmentArgs
    exit $LASTEXITCODE
}
