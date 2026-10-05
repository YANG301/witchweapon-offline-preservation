package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"witchweapon.local/prototype-server/internal/chat"
)

const chatTestSecret = "chat-proxy-secret-for-unit-testing-0123456789"
const legacyTestSecret = "legacy-secret-for-chat-test-0123456789012"

func TestChatGatewayAuthRoleAndCrossZone(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "chat-alice@example.com")
	bob := registerTest(t, a, "chat-bob@example.com")
	chatService, err := chat.New(filepath.Join(t.TempDir(), "chat"), chatTestSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer chatService.Close()
	chatHTTP := httptest.NewServer(chatService)
	defer chatHTTP.Close()
	if err = a.configureChatProxy(chatHTTP.URL, chatTestSecret); err != nil {
		t.Fatal(err)
	}
	var bobHasRole atomic.Bool
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/__role" || r.Method != "GET" || r.Header.Get("X-WW-Proxy-Secret") != legacyTestSecret {
			http.Error(w, "forbidden", 403)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		switch r.Header.Get("X-WW-Account-ID") {
		case alice.Player.ID:
			_, _ = w.Write([]byte(`{"version":1,"exists":true,"roleId":"101","name":"爱丽丝","head":42,"headBox":7}`))
		case bob.Player.ID:
			if bobHasRole.Load() {
				_, _ = w.Write([]byte(`{"version":1,"exists":true,"roleId":"202","name":"鲍勃"}`))
			} else {
				_, _ = w.Write([]byte(`{"version":1,"exists":false,"roleId":"","name":""}`))
			}
		default:
			http.Error(w, "forbidden", 403)
		}
	}))
	defer java.Close()
	if err = a.configureLegacyProxy(java.URL, legacyTestSecret); err != nil {
		t.Fatal(err)
	}
	path := "/api/v1/chat/world"
	w := request(a, "GET", path+"?after=0&limit=50", "", "")
	wantStatus(t, w, 401)
	w = request(a, "POST", path, alice.Token, `{"content":"hi","clientId":"alice-msg-0001","nickname":"admin"}`)
	wantStatus(t, w, 400)
	w = request(a, "POST", path, alice.Token, `{"content":"hi","clientId":"alice-msg-0001","zone":"other"}`)
	wantStatus(t, w, 400)
	w = request(a, "POST", path, bob.Token, `{"content":"hi","clientId":"bob-msg-00001"}`)
	wantStatus(t, w, 409)
	wantStatus(t, request(a, "GET", path, bob.Token, ""), 409)
	bobHasRole.Store(true)
	w = request(a, "POST", path, alice.Token, `{"content":"hi","clientId":"alice-msg-0001"}`)
	wantStatus(t, w, 201)
	var sent struct {
		Message chat.Message `json:"message"`
	}
	if err = json.Unmarshal(w.Body.Bytes(), &sent); err != nil {
		t.Fatal(err)
	}
	if sent.Message.RoleID != "101" || sent.Message.Nickname != "爱丽丝" || sent.Message.Content != "hi" ||
		sent.Message.Head != 42 || sent.Message.HeadBox != 7 {
		t.Fatalf("wrong trusted identity: %+v", sent.Message)
	}
	if strings.Contains(w.Body.String(), alice.Player.ID) {
		t.Fatal("account ID leaked")
	}
	w = request(a, "POST", path, alice.Token, `{"content":"hi","clientId":"alice-msg-0001"}`)
	wantStatus(t, w, 200)
	w = request(a, "GET", path+"?after=0&limit=50", bob.Token, "")
	wantStatus(t, w, 200)
	var list struct {
		Messages []chat.Message `json:"messages"`
		NextSeq  uint64         `json:"nextSeq"`
	}
	if err = json.Unmarshal(w.Body.Bytes(), &list); err != nil {
		t.Fatal(err)
	}
	if len(list.Messages) != 1 || list.Messages[0].Nickname != "爱丽丝" || list.NextSeq != 1 {
		t.Fatalf("world history: %+v", list)
	}
	w = request(a, "GET", "/api/v1/chat/other?after=0", alice.Token, "")
	wantStatus(t, w, 404)
	w = request(a, "POST", path, alice.Token, fmt.Sprintf(`{"content":%q,"clientId":"alice-msg-0002"}`, strings.Repeat("x", 1025)))
	wantStatus(t, w, 400)
	spoof := httptest.NewRequest("POST", path, strings.NewReader(`{"content":"again","clientId":"alice-msg-0002"}`))
	spoof.Header.Set("Content-Type", "application/json")
	spoof.Header.Set("Authorization", "Bearer "+alice.Token)
	spoof.Header.Set("X-WW-Account-ID", bob.Player.ID)
	spoof.Header.Set("X-WW-Role-ID", "9999")
	spoof.Header.Set("X-WW-Role-Head", "999")
	spoof.Header.Set("X-WW-Role-Head-Box", "888")
	spoof.Header.Set("X-WW-Chat-Secret", chatTestSecret)
	got := httptest.NewRecorder()
	a.ServeHTTP(got, spoof)
	// A valid second send may be rate-limited, but it cannot acquire the spoofed
	// identity. Its eventual actor is always resolved by Bearer + Java /__role.
	if got.Code != 201 && got.Code != 429 {
		t.Fatalf("spoof result=%d %s", got.Code, got.Body.String())
	}
	if got.Code == 201 {
		var second struct {
			Message chat.Message `json:"message"`
		}
		if err = json.Unmarshal(got.Body.Bytes(), &second); err != nil {
			t.Fatal(err)
		}
		if second.Message.RoleID != "101" || second.Message.Nickname != "爱丽丝" ||
			second.Message.Head != 42 || second.Message.HeadBox != 7 {
			t.Fatal("spoofed actor accepted")
		}
	}
}

func TestChatGatewayRequiresConfiguration(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "chat-config@example.com")
	wantStatus(t, request(a, "GET", "/api/v1/chat/world", alice.Token, ""), 503)
	if err := a.configureChatProxy("http://8.8.8.8:1234", chatTestSecret); err == nil {
		t.Fatal("public chat upstream accepted")
	}
	if err := a.configureChatProxy("127.0.0.1:18081", "short"); err == nil {
		t.Fatal("short secret accepted")
	}
}

func TestChatRoleCosmeticLegacyFallback(t *testing.T) {
	for _, tc := range []struct {
		name, cosmetics   string
		wantHead, wantBox int
		wantError         bool
	}{
		{name: "missing", cosmetics: "", wantHead: 1, wantBox: 1},
		{name: "zero", cosmetics: `,"head":0,"headBox":0`, wantHead: 1, wantBox: 1},
		{name: "selected", cosmetics: `,"head":2,"headBox":3`, wantHead: 2, wantBox: 3},
		{name: "invalid", cosmetics: `,"head":-1,"headBox":1`, wantError: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			a, _, _ := fixture(t)
			player := registerTest(t, a, "chat-cosmetic-"+tc.name+"@example.com")
			java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/__role" || r.Header.Get("X-WW-Account-ID") != player.Player.ID {
					http.Error(w, "forbidden", 403)
					return
				}
				w.Header().Set("Content-Type", "application/json")
				_, _ = fmt.Fprintf(w, `{"version":1,"exists":true,"roleId":"101","name":"Tester"%s}`, tc.cosmetics)
			}))
			defer java.Close()
			if err := a.configureLegacyProxy(java.URL, legacyTestSecret); err != nil {
				t.Fatal(err)
			}
			role, err := a.readChatRole(httptest.NewRequest(http.MethodGet, "/api/v1/chat/world", nil), player.Player)
			if (err != nil) != tc.wantError {
				t.Fatalf("role=%+v err=%v", role, err)
			}
			if !tc.wantError && (role.head != tc.wantHead || role.headBox != tc.wantBox) {
				t.Fatalf("cosmetics=%d/%d want=%d/%d", role.head, role.headBox, tc.wantHead, tc.wantBox)
			}
		})
	}
}
