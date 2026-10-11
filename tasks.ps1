param(
    [ValidateSet('Install', 'Remove', 'Status')][string]$Action = 'Status',
    [string]$AppDir = $PSScriptRoot,
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'config.json'),
    [string]$Executable = (Join-Path $PSScriptRoot 'RockMerchantQQ.exe'),
    [string]$ScriptPath = '',
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$appPath = (Resolve-Path -LiteralPath $AppDir).Path
$hash = [Security.Cryptography.SHA256]::Create()
try { $digest = $hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($appPath.ToLowerInvariant())) }
finally { $hash.Dispose() }
$taskName = 'RockMerchantQQ-' + ([BitConverter]::ToString($digest).Replace('-', '').Substring(0, 12).ToLowerInvariant())
if ($Action -eq 'Install') {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw 'Executable not found.' }
    $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $targets = @($config.qq.target_ids) + @($config.qq.target_id) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
    if ($targets.Count -eq 0) { throw 'Set at least one receiver QQ or group number.' }
    foreach ($target in $targets) { if ([string]$target -notmatch '^[1-9]\d{4,11}$') { throw 'Invalid receiver QQ or group number.' } }
    if ($config.qq.target_type -notin @('private', 'group')) { throw 'Invalid target type.' }
    $uri = [Uri]$config.qq.base_url
    if ($uri.Scheme -notin @('http', 'https') -or -not $uri.Host) { throw 'Invalid HTTP URL.' }
    $taskArguments = '--config "' + $ConfigPath + '" --once'
    if ($ScriptPath) {
        if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) { throw 'Python entry point not found.' }
        $taskArguments = '"' + $ScriptPath + '" ' + $taskArguments
    }
    if ($ValidateOnly) { Write-Output "Validation passed: $taskName"; exit 0 }
    $taskAction = New-ScheduledTaskAction -Execute $Executable -Argument $taskArguments -WorkingDirectory $appPath
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -Hidden -Priority 7 -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Settings $settings -Principal $principal -Description 'Merchant reminder for this installation' -Force | Out-Null
    Write-Output "Enabled: $taskName"
} elseif ($Action -eq 'Remove') {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Write-Output "Disabled: $taskName"
} else {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) { Write-Output 'Not installed.' }
    else { Write-Output ($task | Select-Object TaskName, State | ConvertTo-Json -Compress) }
}
