# 构建与验证

## 环境

当前维护环境使用 Windows、PowerShell 7 和 `D:\Environment` 下已有的便携工具，不需要全局安装或修改 PATH。

| 组件 | 环境 |
| --- | --- |
| 在线 Java 玩法服务 | JDK 8；`org.json` 的 `android-json-9.0.0_r61` |
| Go 网关与聊天 | Go 1.27.1；依赖版本以 `online/server/go.mod` 和 `go.sum` 为准 |
| 安卓桥接 | 历史工具使用 JDK、Android API28和 Build Tools35中的 D8；准确输入按脚本固定哈希核对 |
| 资源与补丁工具 | Python 3、UnityPy、Pillow及按工具需要提供的其他库 |
| 原单机工程 | 其历史 README 列出 Python3.13、JDK17和不同版本 Android SDK；不要直接套用在线服务的环境 |

Python 工具并不全部需要同一套依赖：AssetBundle 工具依赖 UnityPy，图像工具依赖 Pillow，部分签名构建依赖 cryptography，原程序分析还使用 capstone/androguard。保留原单机的 `requirements.txt`，在线工具按选用脚本准备环境；本稿不伪造一份已经验证覆盖全部历史脚本的依赖锁。

## Java 稳定服务

从仓库根目录，在 PowerShell 7 中执行：

```powershell
& .\online\legacy-server\Build.ps1
```

默认产物为 `online/legacy-server/build/witchweapon-legacy.jar`。脚本会编译稳定 `src`，打包玩法目录、迷宫规则和已有战斗布局。JDK8与 JSON 库的位置在脚本开头，可按自己的便携环境修改。

```powershell
& .\online\legacy-server\Build.ps1 -OutputDirectory 'D:\Environment\Java\temp\witch-review-build'
```

已有布局文件可用 `-PreservedBattleCatalog` 显式指定。脚本检查247个布局、50个缺失ID和基础目录哈希，避免错配另一版数据。默认构建没有石板实验接线。

启动本机隔离服务前，给当前进程提供自行生成的 `WW_LEGACY_PROXY_SECRET`。再执行：

```powershell
& .\online\legacy-server\Start-LegacyService.ps1 -Port 19877 -DataDirectory 'D:\Project\本地测试存档'
```

`Start-LegacyService.ps1` 使用源码目录的 `offline_responses.json`。测试存档须与实际账号存档隔离。本轮没有启动这条服务。

## Go 网关和聊天

```powershell
. .\online\scripts\GoEnvironment.ps1
Push-Location .\online\server
try {
    & $script:GoExe test ./...
    if ($LASTEXITCODE -ne 0) { throw 'Go tests failed' }
} finally { Pop-Location }
```

这个 module 包含 Go 网关、管理后台资源和 `cmd/chat`。`online/scripts/Build.ps1` 可以测试并构建 Windows/Linux 网关：

```powershell
& .\online\scripts\Build.ps1
```

聊天程序可从 `online/server` 构建 `./cmd/chat`。实际启动时分别提供数据目录、回环上游和各进程共享的私密代理口令。可选邮箱服务通过 `WW_EMAIL_VERIFICATION_ENABLED`、Cloudflare account/from和令牌文件配置，默认不自动发邮件。

**公开稿使用模拟服主内部ID。** 既有正式 RID 注册表不能与该占位配置混用；详见 [审阅说明](REVIEW.md)。

## 签名更新工具

`online/deploy/update-server/main.go` 是独立命令，使用 Go 标准库：

```powershell
. .\online\scripts\GoEnvironment.ps1
& $script:GoExe run .\online\deploy\update-server\main.go --help
```

发布、验证和回退的参数说明见其 [README](../online/deploy/update-server/README.md)。私钥、签名发布目录及公网配置不包含在源码稿。未获得具体发布指令时，不执行 `publish`、`rollback` 或切换发布指针。

## 安卓 APK 与 Lua

`online/android-client/src` 保存 Android 桥接，`lua` 保存Lua修复，`patch_*.py` 处理原始资源或源码。`build_startup_version_v125_apk.py` 是已有v125整合构建的历史入口，依赖固定v124APK、第191版完整资源、签名环境和本地模式脚本。

当前不能仅克隆此仓库就构建完全相同的生产 APK。历史脚本保存了输入校验与转换关系，但仍含旧路径及逐版本依赖。本轮保留其层级，不逐个修改固定哈希、重写整条构建链或补造缺失二进制。

原单机可独立按 [原构建说明](../offline-preservation/README.md) 处理；它的版本状态与后续在线版分开。

## 审阅稿检查

```powershell
& 'D:\Environment\UnityTools\venv\Scripts\python.exe' -X utf8 -B .\tools\verify_review.py
```

检查原单机保留文件、整理来源哈希、JSON/Python语法、本地Markdown链接和禁止纳入的文件类型。它只读仓库，不部署、不访问账号、不生成玩家数据。

Java/Go编译和测试的本轮结果见 [验证记录](VALIDATION.md)。
