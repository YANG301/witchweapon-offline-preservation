[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$TestRoot,
    [string]$JarPath = (Join-Path $PSScriptRoot 'build\witchweapon-legacy.jar'),
    [bool]$ExpectedAllUnlocked = $true
)

$ErrorActionPreference = 'Stop'
$java = 'D:\Environment\Java\jdk8\bin\java.exe'
$jsonJar = 'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'
$fixture = Join-Path $PSScriptRoot 'resources\offline_responses.json'
$jar = (Resolve-Path -LiteralPath $JarPath).Path
$desktop = [IO.Path]::GetFullPath('E:\Desktop').TrimEnd('\')
$testPath = [IO.Path]::GetFullPath($TestRoot).TrimEnd('\')
if (-not $testPath.StartsWith($desktop + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Test root must be below the actual desktop'
}
if (Test-Path -LiteralPath $testPath) { throw 'Refuse to reuse an existing test directory' }
foreach ($file in @($java, $jsonJar, $fixture, $jar)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing dependency: $file" }
}
if (Get-NetTCPConnection -State Listen -LocalPort 19882 -ErrorAction SilentlyContinue) {
    throw 'Isolated test port 19882 is already in use'
}
[IO.Directory]::CreateDirectory($testPath) | Out-Null
$marker = Join-Path $testPath '.campaign-health-isolated-test'
[IO.File]::WriteAllText($marker, 'owned by Test-CampaignHealth.ps1', [Text.UTF8Encoding]::new($false))
$data = Join-Path $testPath 'data'
$classpath = "$jar;$jsonJar"
$arguments = @('-Dfile.encoding=UTF-8', '-cp', ('"' + $classpath + '"'),
    'com.codex.witchweapon.StandaloneServer', '--port', '19882',
    '--data-dir', ('"' + $data + '"'), '--responses', ('"' + $fixture + '"'))
$oldSecret = [Environment]::GetEnvironmentVariable('WW_LEGACY_PROXY_SECRET', 'Process')
$env:WW_LEGACY_PROXY_SECRET = 'local-campaign-health-test-secret-12345'
$process = $null
$passed = $false
try {
    $process = Start-Process -FilePath $java -ArgumentList $arguments -PassThru `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $testPath 'out.log') `
        -RedirectStandardError (Join-Path $testPath 'err.log')
    $health = $null
    for ($i = 0; $i -lt 60; $i++) {
        if ($process.HasExited) { throw 'Isolated game server exited during startup' }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:19882/health' -TimeoutSec 1
            break
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if ($null -eq $health) { throw 'Health request timed out' }
    if ($health.status -ne 'ok' -or $health.mainlineStages -ne 235 -or
        [bool]$health.allMainlineUnlocked -ne $ExpectedAllUnlocked) {
        throw ('Unexpected health response: ' + ($health | ConvertTo-Json -Compress))
    }
    $health | ConvertTo-Json -Compress
    $passed = $true
}
finally {
    if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    [Environment]::SetEnvironmentVariable('WW_LEGACY_PROXY_SECRET', $oldSecret, 'Process')
    if ($passed) {
        $checked = [IO.Path]::GetFullPath($testPath).TrimEnd('\')
        if (-not $checked.StartsWith($desktop + '\', [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $marker -PathType Leaf)) {
            throw 'Refuse unsafe isolated-test cleanup'
        }
        Remove-Item -LiteralPath $checked -Recurse -Force
    }
}
