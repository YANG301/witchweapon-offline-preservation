#requires -Version 7.0
param([switch]$SkipTests)
. "$PSScriptRoot\GoEnvironment.ps1"
$projectRoot = Split-Path -Parent $PSScriptRoot
$serverRoot = Join-Path $projectRoot 'server'
$dist = Join-Path $serverRoot 'dist'
New-Item -ItemType Directory -Force -Path $dist | Out-Null
Push-Location $serverRoot
try {
    $env:CGO_ENABLED = '0'
    $env:GOOS = 'windows'
    $env:GOARCH = 'amd64'
    if (-not $SkipTests) {
        & $script:GoExe test ./...
        if ($LASTEXITCODE -ne 0) { throw '服务端测试未通过' }
    }
    & $script:GoExe build -trimpath -o (Join-Path $dist 'witchweapon-server-windows-amd64.exe') .
    if ($LASTEXITCODE -ne 0) { throw 'Windows 构建失败' }
    $env:GOOS = 'linux'
    & $script:GoExe build -trimpath -o (Join-Path $dist 'witchweapon-server-linux-amd64') .
    if ($LASTEXITCODE -ne 0) { throw 'Linux 构建失败' }
    Write-Host "构建完成：$dist"
} finally { Pop-Location }
