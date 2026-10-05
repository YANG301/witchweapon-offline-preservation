# Go账号网关、后台与聊天

本module提供账号注册登录、认证会话、公开RID、原游戏协议代理、管理后台、邮箱验证码/绑定奖励、密码找回及邮件限额。`cmd/chat` 与 `internal/chat` 实现独立聊天进程。

后台的静态页面与名称目录由 `admin_assets.go` 使用 `go:embed` 打包。`go.mod`/`go.sum` 为实际依赖入口；模块要求Go1.27.1。

```powershell
. ..\scripts\GoEnvironment.ps1
& $script:GoExe test ./...
```

实际服务启动参数见 `main.go`，聊天参数见 `cmd/chat/main.go`。默认只监听回环地址，生产HTTPS反代与凭据须由部署者另行配置。本稿没有真实账号数据库或运营一次性发信工具。

邮件真实发送采用Cloudflare服务，验证码绑定和密码找回都有代码。配置开启前不会自动发送。默认还检查账号/IP日限额、全局限额与月额度，真实令牌通过私密环境或文件提供。

公开稿中 `store.go` 使用模拟服主内部ID，保留RID114514规则。不要用这个占位配置读取当前生产RID注册表。参见 [审阅说明](../../docs/REVIEW.md)。
