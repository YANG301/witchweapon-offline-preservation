[CmdletBinding()]
param([int]$Port = 19987)
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Invalid test port' }
$root = $PSScriptRoot
$buildRoot = [IO.Path]::GetFullPath((Join-Path $root 'build'))
$testRoot = [IO.Path]::GetFullPath((Join-Path $buildRoot ('role-http-' + [Guid]::NewGuid().ToString('N'))))
if (-not $testRoot.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Test directory escaped project build'
}
$java = 'D:\Environment\Java\jdk8\bin\java.exe'
$jar = Join-Path $root 'build\witchweapon-legacy.jar'
$json = 'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'
& (Join-Path $root 'Build.ps1') | Out-Null
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
$env:WW_LEGACY_PROXY_SECRET = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$accountA = 'AAAAAAAAAAAAAAAAAAAAAA'
$accountB = 'BBBBBBBBBBBBBBBBBBBBBB'
$headersA = @{'X-WW-Account-ID'=$accountA;'X-WW-Proxy-Secret'=$env:WW_LEGACY_PROXY_SECRET}
$headersB = @{'X-WW-Account-ID'=$accountB;'X-WW-Proxy-Secret'=$env:WW_LEGACY_PROXY_SECRET}
$arguments = @('-Dfile.encoding=UTF-8','-cp',('"'+$jar+';'+$json+'"'),
    'com.codex.witchweapon.StandaloneServer','--port',"$Port",'--data-dir',
    ('"'+(Join-Path $testRoot 'data')+'"'),'--responses',
    ('"'+(Join-Path $root 'resources\offline_responses.json')+'"'))
$process = $null
try {
    $process = Start-Process -FilePath $java -ArgumentList $arguments -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $testRoot 'stdout.log') `
        -RedirectStandardError (Join-Path $testRoot 'stderr.log')
    $base = "http://127.0.0.1:$Port"
    $ready = $false
    for ($i=0; $i -lt 50; $i++) {
        try { $null = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 1; $ready = $true; break }
        catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $ready) { throw 'Legacy service did not start' }
    $unauth = Invoke-WebRequest -Uri "$base/__role" -Method Get -SkipHttpErrorCheck
    if ($unauth.StatusCode -ne 403) { throw 'Role summary leaked without proxy secret/account' }
    $freshA = Invoke-RestMethod -Uri "$base/__role" -Method Get -Headers $headersA
    $freshB = Invoke-RestMethod -Uri "$base/__role" -Method Get -Headers $headersB
    if ($freshA.exists -or $freshB.exists -or $freshA.roleId -ne '' -or $freshB.roleId -ne '') {
        throw 'Fresh account was reported as having a role'
    }
    $createdA = Invoke-WebRequest -Uri "$base/role/create" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body '' -SkipHttpErrorCheck
    $createdB = Invoke-WebRequest -Uri "$base/role/create" -Method Post -Headers $headersB `
        -ContentType 'application/x-www-form-urlencoded' -Body 'name=Bob' -SkipHttpErrorCheck
    if ($createdA.StatusCode -ne 200 -or $createdB.StatusCode -ne 200) { throw 'Role creation failed' }
    $roleA = Invoke-RestMethod -Uri "$base/__role" -Method Get -Headers $headersA
    $roleB = Invoke-RestMethod -Uri "$base/__role" -Method Get -Headers $headersB
    if (-not $roleA.exists -or -not $roleB.exists -or $roleA.roleId -eq $roleB.roleId `
        -or $roleA.roleId -notmatch '^[1-9][0-9]{0,18}$' -or $roleB.roleId -notmatch '^[1-9][0-9]{0,18}$' `
        -or $roleA.name -ne '本地玩家' -or $roleB.name -ne 'Bob') {
        throw 'Account-bound role summaries are inconsistent'
    }
    $icon = Invoke-WebRequest -Uri "$base/role/head/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "enc=test&idempotency=test&hwid=test&roleid=$($roleA.roleId)&head=1&time=test&sign=test" -SkipHttpErrorCheck
    $frame = Invoke-WebRequest -Uri "$base/role/headbox/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "enc=test&idempotency=test&hwid=test&roleid=$($roleA.roleId)&headbox=1&time=test&sign=test" -SkipHttpErrorCheck
    foreach ($reply in @($icon,$frame)) {
        if ($reply.StatusCode -ne 200 -or [Convert]::ToHexString($reply.RawContentStream.ToArray()) -ne '0A026F6B') {
            throw 'Cosmetic change did not return CommonInfo Result=ok'
        }
    }
    $crossAccount = Invoke-WebRequest -Uri "$base/role/head/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "roleid=$($roleB.roleId)&head=1" -SkipHttpErrorCheck
    $lockedIcon = Invoke-WebRequest -Uri "$base/role/head/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "roleid=$($roleA.roleId)&head=2" -SkipHttpErrorCheck
    $unknownFrame = Invoke-WebRequest -Uri "$base/role/headbox/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "roleid=$($roleA.roleId)&headbox=20" -SkipHttpErrorCheck
    $queryChange = Invoke-WebRequest -Uri "$base/role/head/change?head=1" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "roleid=$($roleA.roleId)&head=1" -SkipHttpErrorCheck
    $unauthChange = Invoke-WebRequest -Uri "$base/role/head/change" -Method Post `
        -ContentType 'application/x-www-form-urlencoded' -Body "roleid=$($roleA.roleId)&head=1" -SkipHttpErrorCheck
    $missingField = Invoke-WebRequest -Uri "$base/role/head/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "roleid=$($roleA.roleId)&date=test" -SkipHttpErrorCheck
    $wrongRoleKey = Invoke-WebRequest -Uri "$base/role/head/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "rid=$($roleA.roleId)&head=1" -SkipHttpErrorCheck
    $duplicateField = Invoke-WebRequest -Uri "$base/role/head/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "roleid=$($roleA.roleId)&head=1&head=1" -SkipHttpErrorCheck
    $unknownField = Invoke-WebRequest -Uri "$base/role/head/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body "roleid=$($roleA.roleId)&head=1&accountId=forged" -SkipHttpErrorCheck
    $oversizedField = Invoke-WebRequest -Uri "$base/role/head/change" -Method Post -Headers $headersA `
        -ContentType 'application/x-www-form-urlencoded' -Body ("roleid=$($roleA.roleId)&head=1&sign=" + ('x' * 1048576)) -SkipHttpErrorCheck
    if ($crossAccount.StatusCode -ne 422 -or $lockedIcon.StatusCode -ne 422 -or $unknownFrame.StatusCode -ne 422 `
        -or $queryChange.StatusCode -ne 405 -or $unauthChange.StatusCode -ne 403 `
        -or $missingField.StatusCode -ne 400 -or $wrongRoleKey.StatusCode -ne 400 `
        -or $duplicateField.StatusCode -ne 400 -or $unknownField.StatusCode -ne 400 `
        -or $oversizedField.StatusCode -ne 413) {
        throw 'Cosmetic change validation did not reject an unsafe request'
    }
    $afterA = Invoke-RestMethod -Uri "$base/__role" -Method Get -Headers $headersA
    $afterB = Invoke-RestMethod -Uri "$base/__role" -Method Get -Headers $headersB
    if ($afterA.head -ne 1 -or $afterA.headBox -ne 1 -or $afterB.head -ne 1 -or $afterB.headBox -ne 1) {
        throw 'Rejected cosmetic requests changed account data'
    }
    $readonly = Invoke-WebRequest -Uri "$base/__role" -Method Post -Headers $headersA -SkipHttpErrorCheck
    $query = Invoke-WebRequest -Uri "$base/__role?accountId=$accountB" -Method Get -Headers $headersA -SkipHttpErrorCheck
    if ($readonly.StatusCode -ne 405 -or $query.StatusCode -ne 405) {
        throw 'Role summary accepted method or query override'
    }
    'ROLE_SUMMARY_HTTP_PASS'
}
finally {
    if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    Remove-Item Env:\WW_LEGACY_PROXY_SECRET -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
