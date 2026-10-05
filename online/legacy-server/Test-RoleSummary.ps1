[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$javac = 'D:\Environment\Java\jdk8\bin\javac.exe'
$java = 'D:\Environment\Java\jdk8\bin\java.exe'
$jsonJar = 'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'
$jar = Join-Path $PSScriptRoot 'build\witchweapon-legacy.jar'
$buildRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'build'))
$testRoot = [IO.Path]::GetFullPath((Join-Path $buildRoot ('role-summary-' + [Guid]::NewGuid().ToString('N'))))
if (-not $testRoot.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Test path escaped build directory'
}
& (Join-Path $PSScriptRoot 'Build.ps1') | Out-Null
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
try {
    $classes = Join-Path $testRoot 'classes'
    $data = Join-Path $testRoot 'data'
    [IO.Directory]::CreateDirectory($classes) | Out-Null
    [IO.Directory]::CreateDirectory($data) | Out-Null
    $testSource = Join-Path $PSScriptRoot 'tests\com\codex\witchweapon\RoleSummarySelfTest.java'
    & $javac '-J-Dfile.encoding=UTF-8' '-encoding' 'UTF-8' '-source' '8' '-target' '8' '-cp' "$jar;$jsonJar" '-d' $classes $testSource
    if ($LASTEXITCODE -ne 0) { throw "javac test failed: $LASTEXITCODE" }
    & $java '-Dfile.encoding=UTF-8' '-cp' "$classes;$jar;$jsonJar" 'com.codex.witchweapon.RoleSummarySelfTest' $data
    if ($LASTEXITCODE -ne 0) { throw "role summary test failed: $LASTEXITCODE" }
}
finally {
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
