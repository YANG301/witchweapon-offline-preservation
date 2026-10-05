#requires -Version 7.0
param(
    [int]$LocalPort = 18765,
    [string]$SshTarget = 'root@212.192.15.11'
)

$ErrorActionPreference = 'Stop'
if ($LocalPort -lt 1024 -or $LocalPort -gt 65535) { throw '本机端口应为 1024 至 65535。' }
if ($SshTarget -notmatch '^[a-zA-Z0-9_.-]+@[a-zA-Z0-9.-]+$') { throw 'SSH 地址格式不正确。' }

$projectRoot = Split-Path -Parent $PSScriptRoot
$knownHosts = Join-Path $projectRoot '.local\known_hosts'
if (-not (Test-Path -LiteralPath $knownHosts -PathType Leaf)) {
    throw '缺少已核对的 SSH 主机记录，请先核对服务器指纹。'
}

$url = "http://127.0.0.1:$LocalPort/admin/"
Write-Host "保持此窗口开启，然后在外置 Google Chrome 打开：$url"
Write-Host 'SSH 密码只在终端输入；后台管理密钥在网页输入。按 Ctrl+C 关闭隧道。'
& ssh -o "UserKnownHostsFile=$knownHosts" -o StrictHostKeyChecking=yes `
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 `
    -N -L "127.0.0.1:${LocalPort}:127.0.0.1:18080" $SshTarget
if ($LASTEXITCODE -ne 0) { throw '管理后台 SSH 隧道未建立或已中断。' }
