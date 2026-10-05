[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$TestRoot)
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$java = 'D:\Environment\Java\jdk8\bin\java.exe'
$javac = 'D:\Environment\Java\jdk8\bin\javac.exe'
$jsonJar = 'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'
$python = 'D:\Environment\UnityTools\venv\Scripts\python.exe'
$testPath = [IO.Path]::GetFullPath($TestRoot)
if (Test-Path -LiteralPath $testPath) {
    if (@(Get-ChildItem -LiteralPath $testPath -Force).Count) { throw 'TestRoot must be empty' }
}
[IO.Directory]::CreateDirectory($testPath) | Out-Null
$classes = Join-Path $testPath 'classes'
[IO.Directory]::CreateDirectory($classes) | Out-Null
$jar = Join-Path $PSScriptRoot 'build\witchweapon-legacy.jar'
$responses = Join-Path $PSScriptRoot 'resources\offline_responses.json'
$catalog = Join-Path $PSScriptRoot 'resources\stage_catalog.json'
$classpath = "$classes;$jar;$jsonJar"
$sources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'tests\com\codex\witchweapon') -Filter '*.java' -File | ForEach-Object FullName)
& $javac '-J-Dfile.encoding=UTF-8' '-encoding' 'UTF-8' '-source' '8' '-target' '8' '-cp' "$jar;$jsonJar" '-d' $classes @sources
if ($LASTEXITCODE -ne 0) { throw 'Java test compilation failed' }
foreach ($name in @('MainlineStageSelfTest','NewAccountSelfTest','GuideDrawSelfTest','RestrictedCombatRoleSelfTest','TutorialBattleSelfTest','TutorialTaskSelfTest','StarterStorySelfTest')) {
    $casePath = Join-Path $testPath $name
    [IO.Directory]::CreateDirectory($casePath) | Out-Null
    $caseArgs = if ($name -in @('TutorialTaskSelfTest','StarterStorySelfTest')) { @($responses,$casePath) } else { @($casePath,$responses) }
    if ($name -eq 'MainlineStageSelfTest') { $caseArgs += $catalog }
    & $java '-Dfile.encoding=UTF-8' '-cp' $classpath "com.codex.witchweapon.$name" @caseArgs
    if ($LASTEXITCODE -ne 0) { throw "$name failed" }
}
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
& $python (Join-Path $PSScriptRoot 'tests\test_stage_catalog.py')
if ($LASTEXITCODE -ne 0) { throw 'Stage catalog checks failed' }
$data = Join-Path $testPath 'http-data'
$oldSecret = $env:WW_LEGACY_PROXY_SECRET
$env:WW_LEGACY_PROXY_SECRET = 'local-guide-serial-http-test-secret'
$process = $null
try {
    $arguments = @('-Dfile.encoding=UTF-8','-cp',('"'+$classpath+'"'),'com.codex.witchweapon.StandaloneServer','--port','19879','--data-dir',('"'+$data+'"'),'--responses',('"'+$responses+'"'))
    $process = Start-Process -FilePath $java -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $testPath 'http.out.log') -RedirectStandardError (Join-Path $testPath 'http.err.log')
    $ready = $false
    for ($i=0; $i -lt 60; $i++) {
        if ($process.HasExited) { throw 'Local HTTP server exited' }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:19879/health' -TimeoutSec 1
            if ($health.mainlineStages -eq 235) { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 200
    }
    if (-not $ready) { throw 'Catalog-backed HTTP server did not become ready' }
    foreach ($test in @('guide_serial_http_check.py','mainline_http_check.py')) {
        & $python (Join-Path $PSScriptRoot "tests\$test") --data-dir $data
        if ($LASTEXITCODE -ne 0) { throw "$test failed" }
    }
    'MAINLINE_REGRESSION_PASS'
} finally {
    if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    $env:WW_LEGACY_PROXY_SECRET = $oldSecret
}
