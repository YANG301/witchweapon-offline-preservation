package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func validateListen(address string) error {
	host, port, err := net.SplitHostPort(address)
	if err != nil || port == "" {
		return errors.New("监听地址必须包含本机回环 IP 和端口")
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return errors.New("本原型仅允许回环 IP，例如 127.0.0.1:18080；远程访问请配置 HTTPS 反向代理或 SSH 转发")
	}
	return nil
}

func run() error {
	listen := flag.String("listen", "127.0.0.1:18080", "loopback IP:port")
	data := flag.String("data", "./storage", "single-process writable data directory")
	stories := flag.String("stories", "../data/stories.json", "read-only story JSON file")
	legacyUpstream := flag.String("legacy-upstream", "", "optional loopback Java legacy protocol service, e.g. 127.0.0.1:19877")
	chatUpstream := flag.String("chat-upstream", "", "optional loopback chat service, e.g. 127.0.0.1:18081")
	adminSetPassword := flag.Bool("admin-set-password", false, "interactively create or rotate the admin password")
	adminCredentialEnv := flag.String("admin-credential-env", "", "root-only systemd EnvironmentFile to write in -admin-set-password mode")
	flag.Parse()
	if *adminSetPassword {
		return runAdminSetPassword(*adminCredentialEnv)
	}
	if *adminCredentialEnv != "" {
		return errors.New("-admin-credential-env 仅可与 -admin-set-password 一起使用")
	}
	if err := validateListen(*listen); err != nil {
		return err
	}
	a, err := newApp(*data, *stories)
	if err != nil {
		return fmt.Errorf("无法读取剧情或存档配置: %w", err)
	}
	defer a.Close()
	if err := a.configureLegacyProxy(*legacyUpstream, os.Getenv("WW_LEGACY_PROXY_SECRET")); err != nil {
		return fmt.Errorf("无法配置原协议代理: %w", err)
	}
	if err := a.configureChatProxy(*chatUpstream, os.Getenv("WW_CHAT_PROXY_SECRET")); err != nil {
		return fmt.Errorf("无法配置聊天代理: %w", err)
	}
	if err := a.configureAdmin(os.Getenv(adminCredentialEnvName)); err != nil {
		return fmt.Errorf("无法配置管理后台: %w", err)
	}
	if err := a.configureAdminPublicOrigin(os.Getenv("WW_ADMIN_PUBLIC_ORIGIN")); err != nil {
		return fmt.Errorf("无法配置管理后台公网来源: %w", err)
	}
	if err := a.configureEmailVerificationFromEnv(); err != nil {
		return fmt.Errorf("无法配置邮箱验证服务: %w", err)
	}
	listener, err := net.Listen("tcp", *listen)
	if err != nil {
		return err
	}
	a.startAdminMailWorker()
	server := newGatewayHTTPServer(a)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	fmt.Printf("在线服务已启动：http://%s；邮箱验证服务已配置：%t。\n", listener.Addr(), a.emailVerificationReady())
	select {
	case err := <-done:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdown); err != nil {
			_ = server.Close()
			return err
		}
		return nil
	}
}

func newGatewayHTTPServer(handler http.Handler) *http.Server {
	return &http.Server{Handler: handler, ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second,
		IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
