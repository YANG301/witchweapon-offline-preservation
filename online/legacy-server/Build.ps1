[CmdletBinding()]
param(
    [string]$PreservedBattleCatalog,
    [string]$OutputDirectory
)
#requires -Version 7.0
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$javac = 'D:\Environment\Java\jdk8\bin\javac.exe'
$jarTool = 'D:\Environment\Java\jdk8\bin\jar.exe'
$jsonJar = 'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'
$buildRoot = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $PSScriptRoot 'build' }
$classes = Join-Path $buildRoot 'classes'
$outputJar = Join-Path $buildRoot 'witchweapon-legacy.jar'
$stageCatalog = Join-Path $PSScriptRoot 'resources\stage_catalog.json'
$dailyCatalog = Join-Path $PSScriptRoot 'resources\daily_stage_catalog.json'
$furnaceCatalog = Join-Path $PSScriptRoot 'resources\weapon_furnace_catalog.json'
$slateCatalog = Join-Path $PSScriptRoot 'resources\stone_slate_catalog.json'
$giftCatalog = Join-Path $PSScriptRoot 'resources\gift_shop_catalog.json'
$exchangeCatalog = Join-Path $PSScriptRoot 'resources\exchange_shop_catalog.json'
$prayerCatalog = Join-Path $PSScriptRoot 'resources\prayer_shop_catalog.json'
$caphCatalog = Join-Path $PSScriptRoot 'resources\caph_shop_catalog.json'
$progressionCatalog = Join-Path $PSScriptRoot 'resources\progression_tasks_catalog.json'
$storyTaskCatalog = Join-Path $PSScriptRoot 'resources\main_story_tasks_catalog.json'
$resourceShopCatalog = Join-Path $PSScriptRoot 'resources\resource_shop_catalog.json'
$recycleCatalog = Join-Path $PSScriptRoot 'resources\recycle_values.json'
$mazeCatalog = Join-Path $PSScriptRoot 'resources\maze_rules.json'
if (-not $PreservedBattleCatalog) { $PreservedBattleCatalog = Join-Path $PSScriptRoot 'resources\preserved_battle_catalog.json' }
$taskTemp = 'D:\Environment\Java\temp\witch-online-legacy'
foreach ($path in @($javac, $jarTool, $jsonJar)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing portable dependency: $path" }
}
if ($PreservedBattleCatalog) {
    $PreservedBattleCatalog = [IO.Path]::GetFullPath($PreservedBattleCatalog)
    if (-not (Test-Path -LiteralPath $PreservedBattleCatalog -PathType Leaf) -or
        [IO.Path]::GetFileName($PreservedBattleCatalog) -ne 'preserved_battle_catalog.json') {
        throw 'Explicit preserved battle resource is missing or has the wrong filename'
    }
    $preserved = Get-Content -LiteralPath $PreservedBattleCatalog -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($preserved.schemaVersion -ne 1 -or $preserved.mode -ne 'preserved-layouts-v1' -or
        @($preserved.stages.PSObject.Properties).Count -ne 247 -or @($preserved.missingStageIds).Count -ne 50) {
        throw 'Preserved battle candidate membership is invalid'
    }
    foreach ($name in @('stage_catalog.json','daily_stage_catalog.json','weapon_furnace_catalog.json','stone_slate_catalog.json')) {
        $actual = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot "resources\$name") -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $preserved.baseResourceHashes.$name) { throw "Fallback catalog changed: $name" }
    }
}
if (-not (Test-Path -LiteralPath $stageCatalog -PathType Leaf)) { throw 'Stage catalog resource is missing' }
if (-not (Test-Path -LiteralPath $dailyCatalog -PathType Leaf)) { throw 'Daily battle catalog resource is missing' }
if (-not (Test-Path -LiteralPath $furnaceCatalog -PathType Leaf)) { throw 'Weapon furnace catalog resource is missing' }
if (-not (Test-Path -LiteralPath $slateCatalog -PathType Leaf)) { throw 'Stone slate catalog resource is missing' }
if (-not (Test-Path -LiteralPath $giftCatalog -PathType Leaf)) { throw 'Original gift shop catalog resource is missing' }
if (-not (Test-Path -LiteralPath $exchangeCatalog -PathType Leaf)) { throw 'Original exchange shop catalog resource is missing' }
if (-not (Test-Path -LiteralPath $prayerCatalog -PathType Leaf)) { throw 'Prayer exchange shop catalog resource is missing' }
if (-not (Test-Path -LiteralPath $caphCatalog -PathType Leaf)) { throw 'Original CAPH point shop catalog resource is missing' }
if (-not (Test-Path -LiteralPath $progressionCatalog -PathType Leaf)) { throw 'Original permanent task catalog resource is missing' }
if (-not (Test-Path -LiteralPath $storyTaskCatalog -PathType Leaf)) { throw 'Original shared story task catalog resource is missing' }
if (-not (Test-Path -LiteralPath $resourceShopCatalog -PathType Leaf)) { throw 'Original resource shop catalog resource is missing' }
if (-not (Test-Path -LiteralPath $mazeCatalog -PathType Leaf)) { throw 'Maze rules resource is missing' }
if (-not (Test-Path -LiteralPath $recycleCatalog -PathType Leaf)) { throw 'Original recycle values resource is missing' }
$catalog = Get-Content -LiteralPath $stageCatalog -Raw -Encoding UTF8 | ConvertFrom-Json
if ($catalog.schemaVersion -ne 1 -or @($catalog.stages.PSObject.Properties).Count -ne 235) {
    throw 'Stage catalog schema or mainline count is invalid'
}
[IO.Directory]::CreateDirectory($classes) | Out-Null
[IO.Directory]::CreateDirectory($taskTemp) | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$sources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src') -Recurse -Filter '*.java' -File | ForEach-Object FullName)
if ($sources.Count -lt 4) { throw 'Legacy source files missing' }
$compileStarted = [DateTime]::UtcNow
& $javac '-J-Dfile.encoding=UTF-8' '-encoding' 'UTF-8' '-source' '8' '-target' '8' '-cp' $jsonJar '-d' $classes @sources
if ($LASTEXITCODE -ne 0) { throw "javac exited with $LASTEXITCODE" }
$compiled = @(Get-ChildItem -LiteralPath $classes -Recurse -Filter '*.class' -File |
    Where-Object { $_.LastWriteTimeUtc -ge $compileStarted })
if ($compiled.Count -lt $sources.Count) { throw 'Expected class files were not generated' }
$jarArgs = @('cf', $outputJar)
foreach ($classFile in $compiled) {
    $relative = $classFile.FullName.Substring($classes.Length + 1).Replace('\', '/')
    $jarArgs += @('-C', $classes, $relative)
}
$jarArgs += @('-C', (Split-Path -Parent $stageCatalog), 'stage_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $dailyCatalog), 'daily_stage_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $furnaceCatalog), 'weapon_furnace_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $slateCatalog), 'stone_slate_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $giftCatalog), 'gift_shop_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $exchangeCatalog), 'exchange_shop_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $prayerCatalog), 'prayer_shop_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $caphCatalog), 'caph_shop_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $progressionCatalog), 'progression_tasks_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $storyTaskCatalog), 'main_story_tasks_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $resourceShopCatalog), 'resource_shop_catalog.json')
$jarArgs += @('-C', (Split-Path -Parent $recycleCatalog), 'recycle_values.json')
$jarArgs += @('-C', (Split-Path -Parent $mazeCatalog), 'maze_rules.json')
if ($PreservedBattleCatalog) {
    $jarArgs += @('-C', (Split-Path -Parent $PreservedBattleCatalog), 'preserved_battle_catalog.json')
}
& $jarTool @jarArgs
if ($LASTEXITCODE -ne 0) { throw "jar exited with $LASTEXITCODE" }
Get-FileHash -Algorithm SHA256 -LiteralPath $outputJar | Select-Object Path,Hash
