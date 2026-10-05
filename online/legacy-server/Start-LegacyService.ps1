[CmdletBinding()]
param([ValidateRange(1,65535)][int]$Port=19877,[string]$DataDirectory='')
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
if ([string]::IsNullOrWhiteSpace($env:WW_LEGACY_PROXY_SECRET)) { throw 'WW_LEGACY_PROXY_SECRET is required in this process' }
$java = 'D:\Environment\Java\jdk8\bin\java.exe'
$jsonJar = 'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'
$serviceJar = Join-Path $PSScriptRoot 'build\witchweapon-legacy.jar'
if (-not (Test-Path -LiteralPath $serviceJar -PathType Leaf)) { & (Join-Path $PSScriptRoot 'Build.ps1') }
if ([string]::IsNullOrWhiteSpace($DataDirectory)) { $DataDirectory = Join-Path $PSScriptRoot 'data' }
$taskTemp = 'D:\Environment\Java\temp\witch-online-legacy'
[IO.Directory]::CreateDirectory($taskTemp) | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$classpath = "$serviceJar;$jsonJar"
& $java '-Dfile.encoding=UTF-8' "-Djava.io.tmpdir=$taskTemp" '-cp' $classpath 'com.codex.witchweapon.StandaloneServer' '--port' "$Port" '--data-dir' ([IO.Path]::GetFullPath($DataDirectory)) '--responses' (Join-Path $PSScriptRoot 'resources\offline_responses.json')
if ($LASTEXITCODE -ne 0) { throw "Legacy service exited with $LASTEXITCODE" }
