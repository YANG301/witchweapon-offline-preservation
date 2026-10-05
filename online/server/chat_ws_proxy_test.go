package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"witchweapon.local/prototype-server/internal/chat"
)

func TestRTMCosmeticChangeClosesOnlySuccessfulAccountSockets(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "rtm-icon-alice@example.com")
	bob := registerTest(t, a, "rtm-icon-bob@example.com")
	var aliceHead atomic.Int64
	aliceHead.Store(1)
	var aliceBox atomic.Int64
	aliceBox.Store(1)
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-WW-Proxy-Secret") != legacyTestSecret {
			http.Error(w, "forbidden", 403)
			return
		}
		account := r.Header.Get("X-WW-Account-ID")
		if r.URL.Path == "/__role" {
			w.Header().Set("Content-Type", "application/json")
			switch account {
			case alice.Player.ID:
				_, _ = fmt.Fprintf(w, `{"version":1,"exists":true,"roleId":"101","name":"Alice","head":%d,"headBox":%d}`, aliceHead.Load(), aliceBox.Load())
			case bob.Player.ID:
				_, _ = w.Write([]byte(`{"version":1,"exists":true,"roleId":"202","name":"Bob","head":1,"headBox":1}`))
			default:
				http.Error(w, "forbidden", 403)
			}
			return
		}
		if account != alice.Player.ID || r.Method != http.MethodPost {
			http.Error(w, "forbidden", 403)
			return
		}
		if err := r.ParseForm(); err != nil || r.Form.Get("rid") != "101" {
			http.Error(w, "bad form", 400)
			return
		}
		switch r.URL.Path {
		case "/role/head/change":
			if r.Form.Get("head") != "2" {
				http.Error(w, "locked", 422)
				return
			}
			aliceHead.Store(2)
		case "/role/headbox/change":
			if r.Form.Get("headbox") != "2" {
				http.Error(w, "locked", 422)
				return
			}
			aliceBox.Store(2)
		case "/role/role": // An unrelated success must not refresh chat.
		default:
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/octet-stream")
		_, _ = w.Write([]byte{0x0a, 0x02, 'o', 'k'})
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, legacyTestSecret); err != nil {
		t.Fatal(err)
	}
	observed := make(chan http.Header, 4)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		observed <- r.Header.Clone()
		up := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}
		conn, err := up.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		for {
			kind, data, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if err = conn.WriteMessage(kind, data); err != nil {
				return
			}
		}
	}))
	defer backend.Close()
	if err := a.configureChatProxy(backend.URL, chatTestSecret); err != nil {
		t.Fatal(err)
	}
	public := httptest.NewServer(a)
	defer public.Close()
	wsURL := "ws" + strings.TrimPrefix(public.URL, "http") + "/api/v1/chat/rtm"
	connect := func(token string, wantHead, wantBox string) *websocket.Conn {
		t.Helper()
		headers := http.Header{"Authorization": []string{"Bearer " + token}}
		conn, response, err := (&websocket.Dialer{HandshakeTimeout: 3 * time.Second}).Dial(wsURL, headers)
		if err != nil {
			t.Fatalf("websocket status=%v err=%v", response, err)
		}
		select {
		case got := <-observed:
			if got.Get("X-WW-Role-Head") != wantHead || got.Get("X-WW-Role-Head-Box") != wantBox {
				t.Fatalf("stale avatar in new chat handshake: %v/%v", got.Get("X-WW-Role-Head"), got.Get("X-WW-Role-Head-Box"))
			}
		case <-time.After(time.Second):
			t.Fatal("chat backend did not receive connection")
		}
		return conn
	}
	echo := func(conn *websocket.Conn) {
		t.Helper()
		_ = conn.SetReadDeadline(time.Now().Add(time.Second))
		if err := conn.WriteMessage(websocket.TextMessage, []byte(`{}`)); err != nil {
			t.Fatal(err)
		}
		if _, data, err := conn.ReadMessage(); err != nil || string(data) != `{}` {
			t.Fatalf("unrelated chat connection was closed: %q %v", data, err)
		}
	}
	legacy := func(token, path, form string) int {
		t.Helper()
		req := httptest.NewRequest(http.MethodPost, "/api/v1/legacy"+path, strings.NewReader(form))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		result := httptest.NewRecorder()
		a.ServeHTTP(result, req)
		return result.Code
	}
	aliceSocket := connect(alice.Token, "1", "1")
	defer aliceSocket.Close()
	bobSocket := connect(bob.Token, "1", "1")
	defer bobSocket.Close()
	if code := legacy(alice.Token, "/role/head/change", "rid=101&head=99"); code != 422 {
		t.Fatalf("locked icon status=%d", code)
	}
	if code := legacy(alice.Token, "/role/role", "rid=101"); code != 200 {
		t.Fatalf("unrelated route status=%d", code)
	}
	echo(aliceSocket)
	echo(bobSocket)
	if code := legacy(alice.Token, "/role/head/change", "rid=101&head=2"); code != 200 {
		t.Fatalf("selected icon status=%d", code)
	}
	_ = aliceSocket.SetReadDeadline(time.Now().Add(2 * time.Second))
	if _, _, err := aliceSocket.ReadMessage(); err == nil {
		t.Fatal("old avatar socket stayed connected after icon change")
	}
	echo(bobSocket)
	aliceSocket2 := connect(alice.Token, "2", "1")
	defer aliceSocket2.Close()
	if code := legacy(alice.Token, "/role/headbox/change", "rid=101&headbox=2"); code != 200 {
		t.Fatalf("selected frame status=%d", code)
	}
	_ = aliceSocket2.SetReadDeadline(time.Now().Add(2 * time.Second))
	if _, _, err := aliceSocket2.ReadMessage(); err == nil {
		t.Fatal("old avatar socket stayed connected after frame change")
	}
	echo(bobSocket)
	aliceSocket3 := connect(alice.Token, "2", "2")
	defer aliceSocket3.Close()
	echo(aliceSocket3)
}

func TestRTMCosmeticChangeInvalidatesPendingHandshake(t *testing.T) {
	a, _, _ := fixture(t)
	epoch, ok := a.takeRTMSlot("local-test-account")
	if !ok {
		t.Fatal("slot unavailable")
	}
	defer a.releaseRTMSlot("local-test-account")
	a.refreshRTMCosmetics("local-test-account")
	if a.registerRTMLink("local-test-account", epoch, &rtmLink{}) {
		t.Fatal("pending handshake retained old avatar epoch")
	}
}

func TestRTMProxyAuthenticatesAndBindsServerRole(t *testing.T) {
	a, _, _ := fixture(t)
	player := registerTest(t, a, "rtm-player@example.com")
	var roleExists atomic.Bool
	roleExists.Store(true)
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/__role" || r.Header.Get("X-WW-Proxy-Secret") != legacyTestSecret || r.Header.Get("X-WW-Account-ID") != player.Player.ID {
			http.Error(w, "bad role request", 403)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		if roleExists.Load() {
			_, _ = w.Write([]byte(`{"version":1,"exists":true,"roleId":"1007","name":"真实昵称","head":42,"headBox":7}`))
		} else {
			_, _ = w.Write([]byte(`{"version":1,"exists":false,"roleId":"","name":""}`))
		}
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, legacyTestSecret); err != nil {
		t.Fatal(err)
	}
	observed := make(chan http.Header, 4)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/rtm" {
			http.NotFound(w, r)
			return
		}
		observed <- r.Header.Clone()
		up := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}
		conn, err := up.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		for {
			typ, data, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if err = conn.WriteMessage(typ, data); err != nil {
				return
			}
		}
	}))
	defer backend.Close()
	if err := a.configureChatProxy(backend.URL, chatTestSecret); err != nil {
		t.Fatal(err)
	}
	public := httptest.NewServer(a)
	defer public.Close()
	wsURL := "ws" + strings.TrimPrefix(public.URL, "http") + "/api/v1/chat/rtm"
	connect := func(headers http.Header) (*websocket.Conn, *http.Response, error) {
		d := websocket.Dialer{HandshakeTimeout: 5 * time.Second}
		return d.Dial(wsURL, headers)
	}
	if conn, resp, err := connect(nil); err == nil || resp == nil || resp.StatusCode != 401 {
		if conn != nil {
			_ = conn.Close()
		}
		t.Fatalf("anonymous upgrade: response=%v err=%v", resp, err)
	}
	select {
	case <-observed:
		t.Fatal("anonymous user reached chat backend")
	default:
	}
	roleExists.Store(false)
	missing := http.Header{"Authorization": []string{"Bearer " + player.Token}}
	if conn, resp, err := connect(missing); err == nil || resp == nil || resp.StatusCode != 409 {
		if conn != nil {
			_ = conn.Close()
		}
		t.Fatalf("missing role: response=%v err=%v", resp, err)
	}
	roleExists.Store(true)
	forged := http.Header{}
	forged.Set("Authorization", "Bearer "+player.Token)
	forged.Set("X-WW-Account-ID", "BBBBBBBBBBBBBBBBBBBBBB")
	forged.Set("X-WW-Role-ID", "9999")
	forged.Set("X-WW-Role-Name-B64", base64.RawURLEncoding.EncodeToString([]byte("伪造昵称")))
	forged.Set("X-WW-Role-Head", "999")
	forged.Set("X-WW-Role-Head-Box", "888")
	forged.Set("X-WW-Chat-Secret", "attacker-supplied-secret")
	forged.Set("Cookie", "session=forged")
	conn, resp, err := connect(forged)
	if err != nil {
		t.Fatalf("authorized upgrade: status=%v err=%v", resp, err)
	}
	defer conn.Close()
	var headers http.Header
	select {
	case headers = <-observed:
	case <-time.After(2 * time.Second):
		t.Fatal("backend not reached")
	}
	name, err := base64.RawURLEncoding.DecodeString(headers.Get("X-WW-Role-Name-B64"))
	if err != nil {
		t.Fatal(err)
	}
	if headers.Get("X-WW-Account-ID") != player.Player.ID || headers.Get("X-WW-Role-ID") != "1007" || string(name) != "真实昵称" ||
		headers.Get("X-WW-Role-Head") != "42" || headers.Get("X-WW-Role-Head-Box") != "7" ||
		headers.Get("X-WW-Chat-Secret") != chatTestSecret || headers.Get("Authorization") != "" || headers.Get("Cookie") != "" {
		t.Fatalf("gateway forwarded untrusted WS identity: %+v", headers)
	}
	if err = conn.WriteMessage(websocket.TextMessage, []byte(`{"cmd":"session","op":"open","peerId":"9999","i":1}`)); err != nil {
		t.Fatal(err)
	}
	_, echo, err := conn.ReadMessage()
	if err != nil {
		t.Fatal(err)
	}
	if string(echo) != `{"cmd":"session","op":"open","peerId":"9999","i":1}` {
		t.Fatalf("proxy altered RTM JSON: %s", echo)
	}
	forged.Set("Origin", "https://attacker.example")
	if originConn, originResponse, originErr := connect(forged); originErr == nil || originResponse == nil || originResponse.StatusCode != 403 {
		if originConn != nil {
			_ = originConn.Close()
		}
		t.Fatalf("cross-site websocket allowed: %v %v", originResponse, originErr)
	}
}

func TestRTMConnectionLimit(t *testing.T) {
	a, _, _ := fixture(t)
	player := registerTest(t, a, "rtm-limit@example.com")
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"version":1,"exists":true,"roleId":"1007","name":"真实昵称"}`))
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, legacyTestSecret); err != nil {
		t.Fatal(err)
	}
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		up := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}
		conn, err := up.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		for {
			if _, _, err = conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	defer backend.Close()
	if err := a.configureChatProxy(backend.URL, chatTestSecret); err != nil {
		t.Fatal(err)
	}
	public := httptest.NewServer(a)
	defer public.Close()
	wsURL := "ws" + strings.TrimPrefix(public.URL, "http") + "/api/v1/chat/rtm"
	headers := http.Header{"Authorization": []string{"Bearer " + player.Token}}
	dialer := websocket.Dialer{HandshakeTimeout: 5 * time.Second}
	first, _, err := dialer.Dial(wsURL, headers)
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	second, _, err := dialer.Dial(wsURL, headers)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	third, response, err := dialer.Dial(wsURL, headers)
	if third != nil {
		_ = third.Close()
	}
	if err == nil || response == nil || response.StatusCode != 429 {
		t.Fatalf("third socket status=%v err=%v", response, err)
	}
}

func TestRTMGatewayToIsolatedChatEndToEnd(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "rtm-end-alice@example.com")
	bob := registerTest(t, a, "rtm-end-bob@example.com")
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/__role" || r.Header.Get("X-WW-Proxy-Secret") != legacyTestSecret {
			http.Error(w, "forbidden", 403)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		switch r.Header.Get("X-WW-Account-ID") {
		case alice.Player.ID:
			_, _ = w.Write([]byte(`{"version":1,"exists":true,"roleId":"101","name":"爱丽丝","head":42,"headBox":7}`))
		case bob.Player.ID:
			_, _ = w.Write([]byte(`{"version":1,"exists":true,"roleId":"202","name":"鲍勃"}`))
		default:
			http.Error(w, "forbidden", 403)
		}
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, legacyTestSecret); err != nil {
		t.Fatal(err)
	}
	chatService, err := chat.New(filepath.Join(t.TempDir(), "chat"), chatTestSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer chatService.Close()
	backend := httptest.NewServer(chatService)
	defer backend.Close()
	if err := a.configureChatProxy(backend.URL, chatTestSecret); err != nil {
		t.Fatal(err)
	}
	public := httptest.NewServer(a)
	defer public.Close()
	url := "ws" + strings.TrimPrefix(public.URL, "http") + "/api/v1/chat/rtm?subprotocol=lc.json.*"
	connect := func(token string) *websocket.Conn {
		t.Helper()
		header := http.Header{"Authorization": []string{"Bearer " + token}}
		conn, response, err := (&websocket.Dialer{HandshakeTimeout: 3 * time.Second}).Dial(url, header)
		if err != nil {
			t.Fatalf("RTM gateway dial status=%v: %v", response, err)
		}
		return conn
	}
	left, right := connect(alice.Token), connect(bob.Token)
	defer left.Close()
	defer right.Close()
	request := func(conn *websocket.Conn, frame any) map[string]json.RawMessage {
		t.Helper()
		if err := conn.WriteJSON(frame); err != nil {
			t.Fatal(err)
		}
		_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
		var response map[string]json.RawMessage
		if err := conn.ReadJSON(&response); err != nil {
			t.Fatal(err)
		}
		return response
	}
	for _, sample := range []struct {
		conn *websocket.Conn
		role string
	}{{left, "101"}, {right, "202"}} {
		opened := request(sample.conn, map[string]any{"cmd": "session", "op": "open", "peerId": sample.role, "i": -65535})
		if string(opened["i"]) != "-65535" || string(opened["op"]) != `"opened"` {
			t.Fatalf("session open=%v", opened)
		}
		queried := request(sample.conn, map[string]any{"cmd": "conv", "op": "query", "where": map[string]any{"objectId": "xinfengzhou-world"}, "peerId": sample.role, "i": -65534})
		if string(queried["i"]) != "-65534" || !strings.Contains(string(queried["results"]), "xinfengzhou-world") {
			t.Fatalf("world query=%v", queried)
		}
	}
	ack := request(left, map[string]any{"cmd": "direct", "cid": "xinfengzhou-world", "peerId": "101", "i": -65533,
		"msg": `{"_lctype":2,"ChatContent":"联调成功","ChannelType":0,"Name":"攻击者","idRole":"999","Head":999,"HeadBox":888}`})
	if string(ack["uid"]) != `"world-1"` {
		t.Fatalf("direct ack=%v", ack)
	}
	_ = right.SetReadDeadline(time.Now().Add(3 * time.Second))
	var broadcast map[string]json.RawMessage
	if err := right.ReadJSON(&broadcast); err != nil {
		t.Fatal(err)
	}
	var typedText string
	if err := json.Unmarshal(broadcast["msg"], &typedText); err != nil {
		t.Fatal(err)
	}
	var typed map[string]any
	if err := json.Unmarshal([]byte(typedText), &typed); err != nil || typed["Name"] != "爱丽丝" || typed["idRole"] != "101" ||
		typed["ChatContent"] != "联调成功" || typed["Head"] != float64(42) || typed["HeadBox"] != float64(7) {
		t.Fatalf("gateway/adapter actor mismatch=%v err=%v", typed, err)
	}
}

// This opt-in test uses the exact production HTTP deadlines on both the Go
// gateway and the isolated chat process. The original SDK sends an empty JSON
// heartbeat roughly every 60 seconds; ordinary HTTP timeouts must not kill
// either upgraded WebSocket before the next command.
func TestRTMGatewayAndChatRemainConnectedPastHTTPTimeouts(t *testing.T) {
	if os.Getenv("WW_CHAT_LONG_TEST") != "1" {
		t.Skip("set WW_CHAT_LONG_TEST=1 for 65+ second two-service WebSocket test")
	}
	a, _, _ := fixture(t)
	player := registerTest(t, a, "rtm-long@example.com")
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/__role" || r.Header.Get("X-WW-Proxy-Secret") != legacyTestSecret ||
			r.Header.Get("X-WW-Account-ID") != player.Player.ID {
			http.Error(w, "forbidden", 403)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"version":1,"exists":true,"roleId":"101","name":"测试角色"}`))
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, legacyTestSecret); err != nil {
		t.Fatal(err)
	}
	chatSvc, err := chat.New(filepath.Join(t.TempDir(), "chat"), chatTestSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer chatSvc.Close()
	chatListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	chatHTTP := chat.NewHTTPServer(chatSvc)
	chatDone := make(chan error, 1)
	go func() { chatDone <- chatHTTP.Serve(chatListener) }()
	defer func() { _ = chatHTTP.Close(); <-chatDone }()
	if err := a.configureChatProxy(chatListener.Addr().String(), chatTestSecret); err != nil {
		t.Fatal(err)
	}
	gateListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	gateHTTP := newGatewayHTTPServer(a)
	gateDone := make(chan error, 1)
	go func() { gateDone <- gateHTTP.Serve(gateListener) }()
	defer func() { _ = gateHTTP.Close(); <-gateDone }()
	url := "ws://" + gateListener.Addr().String() + "/api/v1/chat/rtm?subprotocol=lc.json.3"
	header := http.Header{"Authorization": []string{"Bearer " + player.Token}}
	conn, response, err := (&websocket.Dialer{HandshakeTimeout: 3 * time.Second}).Dial(url, header)
	if err != nil {
		t.Fatalf("two-service dial status=%v: %v", response, err)
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
		if string(answer["cmd"]) != `"`+expected+`"` {
			t.Fatalf("expected %s, got %v", expected, answer)
		}
	}
	exchange(map[string]any{"cmd": "session", "op": "open", "peerId": "101", "i": -65535}, "session")
	connectedAt := time.Now()
	timer := time.NewTimer(60 * time.Second)
	defer timer.Stop()
	<-timer.C
	if err := conn.WriteMessage(websocket.TextMessage, []byte(`{}`)); err != nil {
		t.Fatalf("60s gateway heartbeat failed: %v", err)
	}
	time.Sleep(6 * time.Second)
	exchange(map[string]any{"cmd": "logs", "cid": "xinfengzhou-world", "l": 20,
		"peerId": "101", "i": -65534}, "logs")
	exchange(map[string]any{"cmd": "read", "convs": []any{}, "peerId": "101", "i": -65533}, "read")
	if elapsed := time.Since(connectedAt); elapsed < 65*time.Second {
		t.Fatalf("test did not cross requested 65s boundary: %s", elapsed)
	}
}
