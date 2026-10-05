# 安装包与官网

官网：<https://witchweapon.wiki/>。官网下载和 GitHub Releases 提供同一份 v125 安卓测试包，官网其他平台下载保持原样。

## v125 安卓测试版

发布页：<https://github.com/YANG301/witchweapon-offline-preservation/releases/tag/v125>。

| 项目 | 内容 |
| --- | --- |
| 文件 | `witchweapon-online-local-v125-test.apk` |
| 版本名 | `2.0.1.20043125` |
| 版本码 | `20043125` |
| 包名 | `com.codex.witchweapon.online.originalui.test` |
| 最低系统 | Android 7.0 / API 24 |
| 大小 | 1,781,298,897 字节，约 1.66 GiB |
| 内置资源 | 第 191 版签名资源，共 121 项 |
| SHA-256 | `6c03fa14f8152d0e14d019ce98c11a0663d4127e82b080f7180541aa80c23c7b` |
| 签名证书 SHA-256 | `cddd2e10d32647d55a92df15d38b3b41675414f7c41bc3c50874989bdc34d218` |

本包整合已有客户端更新、在线／本地服务器切换及首次启动资源检查修复。后续兼容资源补丁仍使用游戏原版更新流程。本次仅新增 GitHub 分发与官网链接，没有重新构建 APK，也没有改动游戏服务器、官网服务或玩家数据。

在线区服选择“新丰洲”；选择“本地模式”前需运行电脑端本地服务，并配置设备与电脑的连接。它不是完全脱离电脑服务的手机单机包。

发布前重新核对了完整文件 SHA-256、实际 Android 版本与 APK v2/v3 签名。此前已验证清装和首次启动；完整玩法、保留数据升级及不同设备和网络仍需要玩家测试反馈。

Release 同时提供 `SHA256SUMS.txt`。下载后可通过 PowerShell `Get-FileHash -Algorithm SHA256` 核对安装包；不需要卸载旧包来查看校验值。
