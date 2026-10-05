#requires -Version 7.0
param([switch]$Validate, [switch]$BuildWindows, [switch]$Play, [string]$ServerUrl = 'http://127.0.0.1:18080')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$client = Join-Path $projectRoot 'client'
$unityRoot = 'D:\Environment\Unity'
$editor = Join-Path $unityRoot 'Editors\6000.3.24f1\Editor\Unity.exe'
if (-not (Test-Path -LiteralPath $editor)) { throw '尚未安装指定官方编辑器，先完成 docs\Unity官方安装方案.md 中的安装与授权。' }
$env:UPM_CACHE_ROOT = Join-Path $unityRoot 'cache\UPM'
$env:UPM_MAX_CACHE_SIZE = '5000000000'
$env:BEE_CACHE_DIRECTORY = Join-Path $unityRoot 'cache\Bee'
$env:ASSETSTORE_CACHE_PATH = Join-Path $unityRoot 'cache\AssetStore'
$giCache = Join-Path $unityRoot 'cache\GI'
$env:TEMP = Join-Path $unityRoot 'temp'
$env:TMP = $env:TEMP
$env:UNITY_NO_CLI_INVOKED_TELEMETRY = '1'
$env:WITCH_SERVER_URL = $ServerUrl
$logDir = Join-Path $client 'Logs'
if ($Play) { $env:WITCH_CAPTURE_PATH = Join-Path $logDir 'preview.png' }
New-Item -ItemType Directory -Force -Path $env:UPM_CACHE_ROOT,$env:BEE_CACHE_DIRECTORY,$env:ASSETSTORE_CACHE_PATH,$giCache,$env:TEMP,$logDir | Out-Null
$start = [Diagnostics.ProcessStartInfo]::new($editor)
$start.UseShellExecute = $false
$start.WorkingDirectory = $client
$start.ArgumentList.Add('-projectPath')
$start.ArgumentList.Add($client)
$start.ArgumentList.Add('-giCustomCacheLocation')
$start.ArgumentList.Add($giCache)
$start.ArgumentList.Add('-logFile')
$start.ArgumentList.Add((Join-Path $logDir $(if ($BuildWindows) {'build.log'} elseif ($Validate) {'validation.log'} else {'editor.log'})))
if ($Validate -or $BuildWindows) {
    foreach ($arg in @('-batchmode','-nographics','-quit','-executeMethod')) { $start.ArgumentList.Add($arg) }
    $start.ArgumentList.Add($(if ($BuildWindows) {'WitchWeapon.Online.Editor.ProjectSetup.BuildWindows'} else {'WitchWeapon.Online.Editor.ProjectSetup.ValidateProject'}))
} elseif ($Play) {
    $start.ArgumentList.Add('-executeMethod')
    $start.ArgumentList.Add('WitchWeapon.Online.Editor.PrototypePreview.OpenAndCheck')
}
$process = [Diagnostics.Process]::Start($start)
if ($Validate -or $BuildWindows) {
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Unity 校验或构建失败（$($process.ExitCode)），请查看 client\Logs。" }
    Write-Host 'Unity 进程已成功结束，请同时核对日志中的 ONLINE_CLIENT_VALIDATION_OK / ONLINE_CLIENT_BUILD_OK。'
} else {
    Write-Host "Unity 已启动，进程 $($process.Id)。"
}
