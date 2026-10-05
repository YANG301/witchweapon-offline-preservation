#requires -Version 7.0
param([int]$Port = 18080)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$serverExe = Join-Path $projectRoot 'server\dist\witchweapon-server-windows-amd64.exe'
if (-not (Test-Path -LiteralPath $serverExe)) { & "$PSScriptRoot\Build.ps1" }
if ($Port -lt 1024 -or $Port -gt 65535) { throw '端口须在 1024–65535 之间' }
Write-Host "服务端运行在 http://127.0.0.1:$Port；保持窗口开启，Ctrl+C 停止。"
& $serverExe -listen "127.0.0.1:$Port" -data (Join-Path $projectRoot 'server\state') -stories (Join-Path $projectRoot 'data\stories.json')
if ($LASTEXITCODE -ne 0) { throw "服务端退出：$LASTEXITCODE" }
