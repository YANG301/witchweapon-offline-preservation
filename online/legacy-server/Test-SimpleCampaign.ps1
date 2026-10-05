[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$TestRoot,
    [string]$JarPath = (Join-Path $PSScriptRoot 'build\witchweapon-legacy.jar')
)

$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$java = 'D:\Environment\Java\jdk8\bin\java.exe'
$jsonJar = 'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'
$python = 'D:\Environment\UnityTools\venv\Scripts\python.exe'
$fixture = Join-Path $PSScriptRoot 'resources\offline_responses.json'
$script = Join-Path $PSScriptRoot 'tests\simple_campaign_http_check.py'
$jar = (Resolve-Path -LiteralPath $JarPath).Path
$desktop = [IO.Path]::GetFullPath('E:\Desktop').TrimEnd('\')
$testPath = [IO.Path]::GetFullPath($TestRoot).TrimEnd('\')
if (-not $testPath.StartsWith($desktop + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The isolated test root must be under the actual desktop'
}
if (Test-Path -LiteralPath $testPath) { throw 'Refuse to reuse an existing test directory' }
foreach ($file in @($java, $jsonJar, $python, $fixture, $script, $jar)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing test dependency: $file" }
}
if (Get-NetTCPConnection -State Listen -LocalPort 19881 -ErrorAction SilentlyContinue) {
    throw 'Isolated test port 19881 is already in use'
}
[IO.Directory]::CreateDirectory($testPath) | Out-Null
$marker = Join-Path $testPath '.simple-campaign-isolated-test'
[IO.File]::WriteAllText($marker, 'owned by Test-SimpleCampaign.ps1', [Text.UTF8Encoding]::new($false))
$data = Join-Path $testPath 'data'
$classpath = "$jar;$jsonJar"
$arguments = @('-Dfile.encoding=UTF-8', '-cp', ('"' + $classpath + '"'),
    'com.codex.witchweapon.StandaloneServer', '--port', '19881',
    '--data-dir', ('"' + $data + '"'), '--responses', ('"' + $fixture + '"'))
$previousSecret = [Environment]::GetEnvironmentVariable('WW_LEGACY_PROXY_SECRET', 'Process')
$previousPyEncoding = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$previousPyBytecode = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', 'Process')
$env:WW_LEGACY_PROXY_SECRET = 'local-simple-campaign-http-test-secret'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$process = $null
$passed = $false

function Start-IsolatedServer([int]$run) {
    $out = Join-Path $testPath "server-$run.out.log"
    $err = Join-Path $testPath "server-$run.err.log"
    $started = Start-Process -FilePath $java -ArgumentList $arguments -PassThru `
        -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    try {
        for ($i = 0; $i -lt 80; $i++) {
            if ($started.HasExited) { throw 'Isolated game server exited during startup' }
            try {
                $health = Invoke-RestMethod 'http://127.0.0.1:19881/health' -TimeoutSec 1
                if ($health.mainlineStages -eq 235 -and $health.playableMainlineStages -eq 235) {
                    return $started
                }
            } catch { }
            Start-Sleep -Milliseconds 200
        }
        throw 'The isolated server did not load all 235 playable stages'
    } finally {
        if (-not $started.HasExited -and
            ($null -eq $health -or $health.playableMainlineStages -ne 235)) {
            Stop-Process -Id $started.Id -Force
        }
    }
}

try {
    $process = Start-IsolatedServer 1
    & $python $script --data-dir $data --phase traverse
    if ($LASTEXITCODE -ne 0) { throw '235-stage HTTP traversal failed' }
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    $process = $null
    $process = Start-IsolatedServer 2
    & $python $script --data-dir $data --phase reload
    if ($LASTEXITCODE -ne 0) { throw '235-stage persistence check failed' }
    $passed = $true
    'SIMPLE_CAMPAIGN_HTTP_PASS'
}
finally {
    if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    [Environment]::SetEnvironmentVariable('WW_LEGACY_PROXY_SECRET', $previousSecret, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', $previousPyEncoding, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', $previousPyBytecode, 'Process')
    if ($passed) {
        $checked = [IO.Path]::GetFullPath($testPath).TrimEnd('\')
        if (-not $checked.StartsWith($desktop + '\', [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $marker -PathType Leaf)) {
            throw 'Refuse unsafe isolated-test cleanup'
        }
        Remove-Item -LiteralPath $checked -Recurse -Force
    }
}
