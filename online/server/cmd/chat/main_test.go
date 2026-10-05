package main

import (
	"encoding/base64"
	"encoding/json"
	"net"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"witchweapon.local/prototype-server/internal/chat"
)

// Run explicitly with WW_CHAT_LONG_TEST=1. It uses the exact production
// http.Server configuration and waits past both its 30s read and 35s write
// limits before testing the original SDK's 60s empty-JSON heartbeat.
func TestRTMStaysConnectedPastHTTPTimeouts(t *testing.T) {
	if os.Getenv("WW_CHAT_LONG_TEST") != "1" {
		t.Skip("set WW_CHAT_LONG_TEST=1 for 65+ second WebSocket integration test")
	}
	const secret = "chat-65-second-integration-secret-0123456789"
	svc, err := chat.New(t.TempDir(), secret)
	if err != nil {
		t.Fatal(err)
	}
	defer svc.Close()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := chat.NewHTTPServer(svc)
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	defer func() {
		_ = server.Close()
		<-done
	}()
	header := http.Header{}
	header.Set("X-WW-Chat-Secret", secret)
	header.Set("X-WW-Account-ID", strings.Repeat("A", 22))
	header.Set("X-WW-Role-ID", "101")
	header.Set("X-WW-Role-Name-B64", base64.RawURLEncoding.EncodeToString([]byte("测试角色")))
	conn, response, err := (&websocket.Dialer{HandshakeTimeout: 3 * time.Second}).Dial(
		"ws://"+listener.Addr().String()+"/rtm?subprotocol=lc.json.3", header)
	if err != nil {
		t.Fatalf("dial status=%v: %v", response, err)
	}
	defer conn.Close()
	exchange := func(frame any, expected string) {
		t.Helper()
		if err := conn.WriteJSON(frame); err != nil {
			t.Fatal(err)
		}
		_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
		var answer map[string]json.RawMessage
		if err := conn.ReadJSON(&answer); err != nil {
			t.Fatal(err)
		}
		_ = conn.SetReadDeadline(time.Time{})
		var cmd string
		if err := json.Unmarshal(answer["cmd"], &cmd); err != nil || cmd != expected {
			t.Fatalf("unexpected %s response: %v %v", expected, answer, err)
		}
	}
	exchange(map[string]any{"cmd": "session", "op": "open", "peerId": "101", "i": -65535}, "session")
	connectedAt := time.Now()
	timer := time.NewTimer(60 * time.Second)
	defer timer.Stop()
	<-timer.C
	if err := conn.WriteMessage(websocket.TextMessage, []byte(`{}`)); err != nil {
		t.Fatalf("60s heartbeat failed: %v", err)
	}
	time.Sleep(6 * time.Second)
	exchange(map[string]any{"cmd": "logs", "cid": "xinfengzhou-world", "l": 20,
		"peerId": "101", "i": -65534}, "logs")
	exchange(map[string]any{"cmd": "read", "convs": []any{}, "peerId": "101", "i": -65533}, "read")
	if elapsed := time.Since(connectedAt); elapsed < 65*time.Second {
		t.Fatalf("test did not cross requested 65s boundary: %s", elapsed)
	}
}
