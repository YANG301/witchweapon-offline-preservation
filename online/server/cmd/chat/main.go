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

	"witchweapon.local/prototype-server/internal/chat"
)

func main() {
	listen := flag.String("listen", "127.0.0.1:18081", "loopback IP:port")
	data := flag.String("data", "./chat-storage", "chat data directory; separate from account saves")
	guildMembershipUpstream := flag.String("guild-membership-upstream", "", "optional numeric loopback Java legacy service, e.g. 127.0.0.1:19877")
	flag.Parse()
	host, _, err := net.SplitHostPort(*listen)
	if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		fmt.Fprintln(os.Stderr, "chat service must listen on a numeric loopback IP")
		os.Exit(1)
	}
	svc, err := chat.New(*data, os.Getenv("WW_CHAT_PROXY_SECRET"))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer svc.Close()
	if err := svc.ConfigureGuildMembership(*guildMembershipUpstream, os.Getenv("WW_LEGACY_PROXY_SECRET")); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	listener, err := net.Listen("tcp", *listen)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	server := chat.NewHTTPServer(svc)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	select {
	case err = <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err = server.Shutdown(shutdown); err != nil {
			_ = server.Close()
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
}
