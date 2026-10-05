# 签名资源更新服务

本目录只提供独立Go工具源码，不带正式发布目录或私钥。游戏网关、Java玩法和玩家存档不参与其资源发布流程。

## 协议

- `GET /updates/stable/manifest.json`：不缓存的签名清单原始字节。
- `GET /updates/stable/manifest.sig`：对相同原始字节的RSA SHA-256签名。
- `GET /updates/stable/blobs/<sha256>`：内容寻址的只读资源，支持Range。
- `GET /updates/health`：当前发布序号的只读检查。

客户端使用内置公钥验证清单，再验证每项路径、版本、大小与SHA-256。清单必须包含相对固定自举APK的**最终完整覆盖集**，不能仅比较前一补丁的差异。DEX、原生代码和不能从覆盖目录加载的资源仍需APK更新。

## 工具入口

从仓库根目录，用现有便携Go查看命令参数：

```powershell
. .\online\scripts\GoEnvironment.ps1
& $script:GoExe run .\online\deploy\update-server\main.go --help
```

子命令包含 `publish`、`verify`、`serve`、`rollback`。发布先写不可变发布目录与blobs，验证后原子切换 `current`。回退将目标旧资源重新签成更高序号；不能让客户端接受倒退序号。

两个清单请求可能跨过发布切换，客户端要整组有限重试，不能跳过验签。资源服务可在回环地址无TLS运行供独立HTTPS反代，也支持明确提供证书的隔离测试。

发布者的签名私钥只留本机。资源主机需要公钥、已签名资源和程序；没有必要接触玩家存档或签名私钥。本次不执行发布或切换。
