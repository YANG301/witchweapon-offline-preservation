#requires -Version 7.0
param([string]$SshTarget = 'root@212.192.15.11', [int]$LocalPort = 18081)
$ErrorActionPreference = 'Stop'
if ($SshTarget -notmatch '^[a-zA-Z0-9_.-]+@[a-zA-Z0-9.-]+$') { throw 'SSH 地址格式不正确' }
if ($LocalPort -lt 1024 -or $LocalPort -gt 65535) { throw '本机端口不正确' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$sshDir = Join-Path $projectRoot '.local'
$knownHosts = Join-Path $sshDir 'known_hosts'
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
$hostCheck = if (Test-Path -LiteralPath $knownHosts) { 'yes' } else { 'ask' }
Write-Host '使用项目独立的 SSH 主机记录；首次连接请核对主机指纹。SSH 密码只在终端输入。'
Write-Host "连接成功后，将 Unity 中的服务地址改为 http://127.0.0.1:$LocalPort。"
Write-Host '隧道需保持窗口开启，Ctrl+C 停止。'
& ssh -o "UserKnownHostsFile=$knownHosts" -o "StrictHostKeyChecking=$hostCheck" -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -N -L "127.0.0.1:${LocalPort}:127.0.0.1:18080" $SshTarget
if ($LASTEXITCODE -ne 0) { throw 'SSH 隧道未建立或已中断' }
