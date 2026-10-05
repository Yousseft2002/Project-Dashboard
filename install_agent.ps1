#requires -Version 5.1
[CmdletBinding()]
param([string]$ConfigPath, [switch]$Uninstall)
$ErrorActionPreference = 'Stop'
if (-not $ConfigPath) { $ConfigPath = Join-Path $PSScriptRoot 'collector.config.json' }
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
if (-not $config.device_id) { throw 'Pair this computer with setup_collector.ps1 first.' }
$taskName = 'Project Dashboard Agent - ' + $config.installation_id
if ($Uninstall) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
    Write-Host 'Automatic startup removed. Pairing and local queue retained.'
    exit 0
}
$pythonCandidates = @('python', (Join-Path $env:LOCALAPPDATA 'Python\bin\python.exe'))
$pythonRoot = Join-Path $env:LOCALAPPDATA 'Python'
if (Test-Path -LiteralPath $pythonRoot) {
    $pythonCandidates += @(Get-ChildItem -LiteralPath $pythonRoot -Directory | ForEach-Object { Join-Path $_.FullName 'python.exe' })
}
$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
    try {
        & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonExe = (& $candidate -c 'import sys; print(sys.executable)').Trim(); break }
    } catch { continue }
}
if (-not $pythonExe) { throw 'Python 3.11+ is required for the initial MVP.' }
Push-Location -LiteralPath $PSScriptRoot
try {
    # Validate the exact allowlist without reading source contents or uploading.
    & $pythonExe -m agent preview --config $ConfigPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Workspace validation failed. Run python -m agent preview for details.' }
} finally { Pop-Location }
$pythonwExe = Join-Path (Split-Path -Parent $pythonExe) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwExe)) { throw 'pythonw.exe is required for hidden background startup.' }
$userName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonwExe -Argument ('-m agent run --config "' + $ConfigPath + '"') -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userName
$principal = New-ScheduledTaskPrincipal -UserId $userName -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Approved repository metadata only; offline queue; no remote shell.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host 'Project Dashboard Agent installed and started for this Windows user.'
Write-Host 'It starts at sign-in, uses the existing protected pairing, and runs without a terminal window.'
Write-Host 'Diagnostics: python -m agent diagnostics'
