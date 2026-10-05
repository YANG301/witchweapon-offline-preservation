[CmdletBinding()]
param([string]$JarPath = '', [string]$TestRoot = '')
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$root = $PSScriptRoot
$java = 'D:\Environment\Java\jdk8\bin\java.exe'
$jar = if ($JarPath) { (Resolve-Path -LiteralPath $JarPath).Path } else { Join-Path $root 'build\witchweapon-legacy.jar' }
$json = 'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'
$testRoot = if ($TestRoot) { [IO.Path]::GetFullPath($TestRoot) } else { Join-Path $root 'build\account-isolation-test' }
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
$stdout = Join-Path $testRoot 'server.out.log'
$stderr = Join-Path $testRoot 'server.err.log'
$data = Join-Path $testRoot 'data'
$env:WW_LEGACY_PROXY_SECRET = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$classpath = "$jar;$json"
$arguments = @('-Dfile.encoding=UTF-8','-cp',('"'+$classpath+'"'),'com.codex.witchweapon.StandaloneServer','--port','19877','--data-dir',('"'+$data+'"'),'--responses',('"'+(Join-Path $root 'resources\offline_responses.json')+'"'))
$process = Start-Process -FilePath $java -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
try {
    $health = $null
    for ($i=0; $i -lt 60; $i++) {
        try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:19877/health' -TimeoutSec 1; break }
        catch { Start-Sleep -Milliseconds 200 }
    }
    if ($null -eq $health -or $health.mode -ne 'account-isolated' -or $health.responseEntries -ne 241) { throw 'Legacy service did not become ready with the original response set' }
    $a = 'AAAAAAAAAAAAAAAAAAAAAA'
    $b = 'BBBBBBBBBBBBBBBBBBBBBB'
    $c = 'CCCCCCCCCCCCCCCCCCCCCC'
    $headersA = @{ 'X-WW-Account-ID'=$a; 'X-WW-Proxy-Secret'=$env:WW_LEGACY_PROXY_SECRET }
    $headersB = @{ 'X-WW-Account-ID'=$b; 'X-WW-Proxy-Secret'=$env:WW_LEGACY_PROXY_SECRET }
    $headersC = @{ 'X-WW-Account-ID'=$c; 'X-WW-Proxy-Secret'=$env:WW_LEGACY_PROXY_SECRET }
    $base = 'http://127.0.0.1:19877'
    $unauth = Invoke-WebRequest -Uri "$base/role/role" -Method Post -SkipHttpErrorCheck
    if ($unauth.StatusCode -ne 403) { throw "Unauthenticated route returned $($unauth.StatusCode)" }
    $unknown = Invoke-WebRequest -Uri "$base/combat/does-not-exist" -Method Post -Headers $headersC -SkipHttpErrorCheck
    if ($unknown.StatusCode -ne 404 -or (Test-Path -LiteralPath (Join-Path $data "users\$c"))) { throw 'Unknown route created account data' }
    $createA = Invoke-WebRequest -Uri "$base/role/create" -Method Post -Headers $headersA -ContentType 'application/x-www-form-urlencoded' -Body 'name=Alice' -SkipHttpErrorCheck
    $createB = Invoke-WebRequest -Uri "$base/role/create" -Method Post -Headers $headersB -ContentType 'application/x-www-form-urlencoded' -Body 'name=Bob' -SkipHttpErrorCheck
    if ($createA.StatusCode -ne 200 -or $createB.StatusCode -ne 200) { throw 'Role creation failed' }
    $savePathA = Join-Path $data "users\$a\offline_save_v1.json"
    $savePathB = Join-Path $data "users\$b\offline_save_v1.json"
    $beforeDrawA = (Get-FileHash -Algorithm SHA256 -LiteralPath $savePathA).Hash
    $drawKey = [Guid]::NewGuid().ToString()
    $realDraw = Invoke-WebRequest -Uri "$base/draw/gold/single" -Method Post -Headers $headersA -ContentType 'application/x-www-form-urlencoded' -Body "idempotency=$drawKey" -SkipHttpErrorCheck
    $afterDrawA = (Get-FileHash -Algorithm SHA256 -LiteralPath $savePathA).Hash
    $drawReplay = Invoke-WebRequest -Uri "$base/draw/gold/single" -Method Post -Headers $headersA -ContentType 'application/x-www-form-urlencoded' -Body "idempotency=$drawKey" -SkipHttpErrorCheck
    if ($realDraw.StatusCode -ne 200 -or $drawReplay.StatusCode -ne 200 -or
        $afterDrawA -eq $beforeDrawA -or (Get-FileHash -Algorithm SHA256 -LiteralPath $savePathA).Hash -ne $afterDrawA) {
        throw 'Free starter draw or persistent replay protection failed'
    }
    $saveA = Get-Content -LiteralPath (Join-Path $data "users\$a\offline_save_v1.json") -Encoding UTF8 -Raw | ConvertFrom-Json
    $saveB = Get-Content -LiteralPath (Join-Path $data "users\$b\offline_save_v1.json") -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($saveA.name -ne 'Alice' -or $saveB.name -ne 'Bob' -or $saveA.drawCount -ne 1 -or
        $saveA.gold -ne 1000 -or $saveB.gold -ne 1000) {
        throw 'Accounts did not retain independent names and beginner balances'
    }
    $beforeFakeA = (Get-FileHash -Algorithm SHA256 -LiteralPath $savePathA).Hash
    $beforeFakeB = (Get-FileHash -Algorithm SHA256 -LiteralPath $savePathB).Hash
    $fakeUnauthorized = Invoke-WebRequest -Uri "$base/draw/fake" -Method Post -ContentType 'application/x-www-form-urlencoded' -Body 'fakeid=123' -SkipHttpErrorCheck
    $fakeGet = Invoke-WebRequest -Uri "$base/draw/fake" -Method Get -Headers $headersA -SkipHttpErrorCheck
    $fakeInvalid = Invoke-WebRequest -Uri "$base/draw/fake" -Method Post -Headers $headersA -ContentType 'application/x-www-form-urlencoded' -Body 'fakeid=invalid' -SkipHttpErrorCheck
    $fakeUnknown = Invoke-WebRequest -Uri "$base/draw/fake/unknown" -Method Post -Headers $headersC -ContentType 'application/x-www-form-urlencoded' -Body 'fakeid=123' -SkipHttpErrorCheck
    $fake = Invoke-WebRequest -Uri "$base/draw/fake" -Method Post -Headers $headersA -ContentType 'application/x-www-form-urlencoded' -Body 'fakeid=123' -SkipHttpErrorCheck
    $fakeBytes = if ($fake.Content -is [byte[]]) { $fake.Content } else { [Text.Encoding]::UTF8.GetBytes([string]$fake.Content) }
    if ($fakeUnauthorized.StatusCode -ne 403 -or $fakeGet.StatusCode -ne 405 -or $fakeInvalid.StatusCode -ne 400 -or $fakeUnknown.StatusCode -ne 404 -or
        $fake.StatusCode -ne 200 -or [Convert]::ToBase64String($fakeBytes) -ne 'CgJvaxIA') { throw 'Fake draw routing or CommonInfo response is invalid' }
    $afterFakeA = (Get-FileHash -Algorithm SHA256 -LiteralPath $savePathA).Hash
    $afterFakeB = (Get-FileHash -Algorithm SHA256 -LiteralPath $savePathB).Hash
    $afterFakeSaveA = Get-Content -LiteralPath $savePathA -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($afterFakeA -ne $beforeFakeA -or $afterFakeB -ne $beforeFakeB -or
        $afterFakeSaveA.drawCount -ne $saveA.drawCount -or (Test-Path -LiteralPath (Join-Path $data "users\$c"))) {
        throw 'Fake draw changed rewards, draw count, or another account save'
    }
    $mirrorA = Invoke-RestMethod -Uri "$base/__state" -Method Get -Headers $headersA
    $mirrorB = Invoke-RestMethod -Uri "$base/__state" -Method Get -Headers $headersB
    if ($mirrorA.name -ne 'Alice' -or $mirrorB.name -ne 'Bob' -or $mirrorA.PSObject.Properties.Name -contains 'items') { throw 'Safe state mirror is not account-isolated' }
    $startKey = [Guid]::NewGuid().ToString()
    $start = Invoke-WebRequest -Uri "$base/level/startBattle" -Method Post -Headers $headersA -ContentType 'application/x-www-form-urlencoded' -Body "instanceid=3130001026&idempotency=$startKey" -SkipHttpErrorCheck
    if ($start.StatusCode -ne 200) { throw 'Maze start failed' }
    $settlementBody = "instanceid=3130001026&pass=1&stars=3&hp=0.4&energyStartKey=$startKey&mazeEnergy_100=250"
    $settle = Invoke-WebRequest -Uri "$base/level/pushMainLineProgress" -Method Post -Headers $headersA -ContentType 'application/x-www-form-urlencoded' -Body $settlementBody -SkipHttpErrorCheck
    if ($settle.StatusCode -ne 200) { throw 'Maze settlement failed' }
    $after = Invoke-RestMethod -Uri "$base/__state" -Method Get -Headers $headersA
    if ($after.mazeHP -lt 0.39 -or $after.mazeHP -gt 0.71 -or $after.mazeEnergy_100 -lt 250 -or $after.mazeEnergy_100 -gt 550) { throw 'Maze HP/energy carry was not persisted' }
    $repeat = Invoke-WebRequest -Uri "$base/level/pushMainLineProgress" -Method Post -Headers $headersA -ContentType 'application/x-www-form-urlencoded' -Body $settlementBody -SkipHttpErrorCheck
    $afterRepeat = Invoke-RestMethod -Uri "$base/__state" -Method Get -Headers $headersA
    if ($repeat.StatusCode -ne 200 -or $afterRepeat.gold -ne $after.gold -or $afterRepeat.mazeRound -ne $after.mazeRound) { throw 'Duplicate settlement changed reward or maze round' }
    $otherAfter = Invoke-RestMethod -Uri "$base/__state" -Method Get -Headers $headersB
    if ($otherAfter.gold -ne $mirrorB.gold) { throw 'Maze reward crossed account boundary' }
    $traversal = Invoke-WebRequest -Uri "$base/role/role" -Method Post -Headers @{'X-WW-Account-ID'='../outside';'X-WW-Proxy-Secret'=$env:WW_LEGACY_PROXY_SECRET} -SkipHttpErrorCheck
    if ($traversal.StatusCode -ne 403) { throw 'Invalid account ID was not rejected' }
    [pscustomobject]@{Status='PASS';Health=$health.mode;Unauthorized=$unauth.StatusCode;Unknown=$unknown.StatusCode;FakeDraw=$fake.StatusCode;FakeDrawUnchanged=($afterFakeA -eq $beforeFakeA -and $afterFakeB -eq $beforeFakeB);InvalidAccount=$traversal.StatusCode;AccountA=$saveA.name;AccountB=$saveB.name;MazeRound=$after.mazeRound;MazeHP=$after.mazeHP;MazeEnergy=$after.mazeEnergy_100;DuplicateGold=$afterRepeat.gold;ResponseEntries=$health.responseEntries} | ConvertTo-Json -Compress
}
finally {
    if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    Remove-Item Env:\WW_LEGACY_PROXY_SECRET -ErrorAction SilentlyContinue
}
