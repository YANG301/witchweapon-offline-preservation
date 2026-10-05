#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$binaryDir = Join-Path $projectRoot 'server\dist'
$dataDir = Join-Path $projectRoot 'data'
$deployDir = Join-Path $projectRoot 'deploy'
$binary = Join-Path $binaryDir 'witchweapon-server-linux-amd64'
if (-not (Test-Path -LiteralPath $binary)) { throw '请先执行 Build.ps1 并通过测试' }
$files = @($binary, (Join-Path $dataDir 'stories.json'), (Join-Path $deployDir 'witchweapon-prototype.service'), (Join-Path $deployDir 'install-first-time.sh'))
$hashLines = $files | ForEach-Object { '{0}  {1}' -f (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant(),(Split-Path -Leaf $_) }
[IO.File]::WriteAllText((Join-Path $deployDir 'SHA256SUMS'),($hashLines -join "`n") + "`n",[Text.UTF8Encoding]::new($false))
$package = Join-Path $deployDir 'witchweapon-prototype-linux-amd64.tar.gz'
& tar -czf $package -C $binaryDir witchweapon-server-linux-amd64 -C $dataDir stories.json -C $deployDir witchweapon-prototype.service install-first-time.sh SHA256SUMS
if ($LASTEXITCODE -ne 0) { throw '打包失败' }
Write-Host "已生成：$package"
Get-FileHash -LiteralPath $package -Algorithm SHA256
