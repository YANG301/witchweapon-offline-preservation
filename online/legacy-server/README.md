# Java原协议与玩法服务

`src` 包含当前玩法代码，`resources` 包含只读定义与目录，`tests` 是自测源码。`Build.ps1` 可从稳定源码完整编译，不需要线上存档。

主要模块包括 `LocalSave`/`LocalEconomy` 事务与持久化、商店与CAPH、任务、邮件、集会所、抽卡分解、升星、战斗结算和迷宫。`StandaloneServer` 是回环HTTP入口，Go网关通过共享秘密代理账号请求。

整理稿的稳定构建去掉未发布石板接线。草稿在根 `experiments/stone-slate`。构建补入 `maze_rules.json` 并默认核对/打包已有战斗布局；石板目录数据保留为原始资料，但没有启用其玩法路由。

`tools` 和 `Test-*.ps1` 保留历史检查与固定二进制构建代码。它们可能需要历史JAR、外部资料或新建隔离测试目录，不是直接运行即可升级正式服的入口。

详细环境和命令见 [构建说明](../../docs/BUILD.md)，功能边界见 [状态](../../docs/STATUS.md)。
