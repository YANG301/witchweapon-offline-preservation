# 双区服本地模式

这里保存本地/在线服务器列表、选区持久化和Android桥接源码，以及已有整合APK的构建与补丁工具。

`LocalModeBridge.java` 负责本地桥接，`patch_server_list_mode.py`、`patch_server_list_assets.py` 与相关构建脚本恢复原版服务器列表的两项选择。本地模式入口放在服务器列表中，原游客图标和描述已隐藏。

在线版的v125构建还导入这里的 `build_preserved_battle_v111_apk`、`build_server_list_v110_apk` 和 `patch_local_mode_bridge`。原绝对路径关系暂保留，后续公开构建要参数化。

电脑本地服务程序与实际本地存档没有复制。玩法实现收录于根 `online/legacy-server`。本次不更改已安装APK或重新测试本地服务。
