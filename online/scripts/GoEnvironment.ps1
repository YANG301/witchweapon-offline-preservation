#requires -Version 7.0
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$script:GoExe = 'D:\Environment\Go\sdk\bin\go.exe'
if (-not (Test-Path -LiteralPath $script:GoExe)) { throw "找不到既有 Go：$script:GoExe" }
$env:GOROOT = 'D:\Environment\Go\sdk'
$env:GOPATH = 'D:\Environment\Go\包工作目录'
$env:GOCACHE = 'D:\Environment\Go\编译缓存'
$env:GOMODCACHE = 'D:\Environment\Go\模块缓存'
$env:GOTMPDIR = 'D:\Environment\Go\临时文件'
$env:GOTOOLCHAIN = 'local'
$env:GOENV = 'off'
$env:TEMP = $env:GOTMPDIR
$env:TMP = $env:GOTMPDIR
New-Item -ItemType Directory -Force -Path $env:GOPATH,$env:GOCACHE,$env:GOMODCACHE,$env:GOTMPDIR | Out-Null
