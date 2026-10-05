package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
)

const testProxySecret = "test-only-proxy-secret-with-more-than-32-characters"

func TestLegacyProxyAuthIsolationAndWireCompatibility(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "legacy-alice@example.com")
	bob := registerTest(t, a, "legacy-bob@example.com")
	if result := roleRequest(a, alice.Token, "代理角色"); result.status != 201 {
		t.Fatalf("create role: %+v", result)
	}
	wantStatus(t, request(a, "POST", "/api/v1/legacy/level/startBattle", "", "instanceid=3110001002"), 401)
	wantStatus(t, request(a, "POST", "/api/v1/legacy/level/startBattle", alice.Token, "instanceid=3110001002"), 503)
	for _, path := range []string{"/account/user/login", "/getversion", "/api/v1/legacy/account/user/login", "/api/v1/legacy/game/account/user/login", "/api/v1/legacy/game/getversion", "/api/v1/legacy/game/assets/config.env", "/api/v1/legacy/game/assets/config.mapping", "/api/v1/legacy/not-an-endpoint"} {
		wantStatus(t, request(a, "POST", path, alice.Token, ""), 404)
	}
	if legacyPathAllowed("/level//startBattle") {
		t.Fatal("malformed legacy path accepted")
	}
	if w := request(a, "GET", "/api/v1/me", alice.Token, ""); w.Code != 200 {
		t.Fatalf("existing API stopped working: %s", w.Body.String())
	}

	type seenRequest struct {
		Account, Role, PublicRID, Path, Query, Method, Body, ContentType, Secret, Authorization, Cookie string
	}
	seen := make(chan seenRequest, 3)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		seen <- seenRequest{r.Header.Get("X-WW-Account-ID"), r.Header.Get("X-WW-Role-ID"), r.Header.Get("X-WW-Public-RID"), r.URL.Path, r.URL.RawQuery, r.Method, string(body), r.Header.Get("Content-Type"), r.Header.Get("X-WW-Proxy-Secret"), r.Header.Get("Authorization"), r.Header.Get("Cookie")}
		w.Header().Set("Content-Type", "application/octet-stream")
		w.WriteHeader(206)
		_, _ = w.Write([]byte{0, 1, 2, 255})
	}))
	defer upstream.Close()
	if err := a.configureLegacyProxy(upstream.URL, testProxySecret); err != nil {
		t.Fatal(err)
	}

	send := func(token string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/api/v1/legacy/level/startBattle?round=2&key=x%2Fy", strings.NewReader("instanceid=3110001002&start=1"))
		r.Header.Set("Authorization", "Bearer "+token)
		r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		r.Header.Set("X-WW-Account-ID", "forged-account")
		r.Header.Set("X-WW-Role-ID", "forged-role")
		r.Header.Set("X-WW-Public-RID", "114514")
		r.Header.Set("X-WW-Proxy-Secret", "forged-secret")
		r.Header.Set("Cookie", "forged-cookie=yes")
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		return w
	}
	for _, tc := range []struct {
		token, account string
		role           bool
		publicRID      int
	}{{alice.Token, alice.Player.ID, true, alice.Player.PublicRID}, {bob.Token, bob.Player.ID, false, bob.Player.PublicRID}} {
		w := send(tc.token)
		if w.Code != 206 || w.Header().Get("Content-Type") != "application/octet-stream" || !bytes.Equal(w.Body.Bytes(), []byte{0, 1, 2, 255}) {
			t.Fatalf("proxy changed protobuf wire response: %d %v %x", w.Code, w.Header(), w.Body.Bytes())
		}
		got := <-seen
		if got.Account != tc.account || got.PublicRID != strconv.Itoa(tc.publicRID) || got.Path != "/level/startBattle" || got.Query != "round=2&key=x%2Fy" || got.Method != "POST" || got.Body != "instanceid=3110001002&start=1" || got.ContentType != "application/x-www-form-urlencoded" || got.Secret != testProxySecret || got.Authorization != "" || got.Cookie != "" {
			t.Fatalf("proxy forwarded incorrect identity or wire request: %+v", got)
		}
		if tc.role && got.Role == "" || !tc.role && got.Role != "" {
			t.Fatalf("wrong role header for account %s: %+v", tc.account, got)
		}
	}
	wantStatus(t, send(strings.Repeat("x", 43)), 401)
}

func TestLegacyProxyBoundsAndConfiguration(t *testing.T) {
	a, _, _ := fixture(t)
	user := registerTest(t, a, "legacy-bounds@example.com")
	for _, target := range []string{"http://example.com:19877", "http://localhost:19877", "https://127.0.0.1:19877", "http://127.0.0.1:19877/path", "http://127.0.0.1", "http://admin:pw@127.0.0.1:19877"} {
		if err := a.configureLegacyProxy(target, testProxySecret); err == nil {
			t.Fatalf("unsafe upstream accepted: %s", target)
		}
	}
	if err := a.configureLegacyProxy("127.0.0.1:19877", "short"); err == nil {
		t.Fatal("short internal secret accepted")
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(bytes.Repeat([]byte("X"), legacyResponseLimit+1))
	}))
	defer upstream.Close()
	if err := a.configureLegacyProxy(upstream.URL, testProxySecret); err != nil {
		t.Fatal(err)
	}
	wantStatus(t, request(a, "POST", "/api/v1/legacy/level/startBattle", user.Token, strings.Repeat("a", legacyRequestLimit+1)), 413)
	wantStatus(t, request(a, "GET", "/api/v1/legacy/level/getAllProgress", user.Token, ""), 502)
	// An extra caller-controlled identity field does not alter the account scope
	// of the existing JSON role endpoint.
	wantStatus(t, request(a, "POST", "/api/v1/role", user.Token, `{"nickname":"代理测试","accountId":"forged"}`), 400)
	var persisted diskState
	if err := json.Unmarshal(mustRead(t, a.store.file), &persisted); err != nil {
		t.Fatal(err)
	}
	if len(persisted.Users) != 1 {
		t.Fatal("proxy test unexpectedly mutated account state")
	}
}

func TestLegacyStateMirrorsOnlyApprovedFields(t *testing.T) {
	a, _, _ := fixture(t)
	user := registerTest(t, a, "legacy-state@example.com")
	wantStatus(t, request(a, "GET", "/api/v1/legacy-state", "", ""), 401)
	wantStatus(t, request(a, "GET", "/api/v1/legacy-state", user.Token, ""), 503)
	state := `{"version":1,"name":"测试角色","gold":123,"mazeRound":2,"mazeEnergy_10010001":600,"passwordHash":"must never reach client","items":{"secret":true}}`
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/__state" || r.Method != "GET" || r.Header.Get("X-WW-Account-ID") != user.Player.ID || r.Header.Get("X-WW-Proxy-Secret") != testProxySecret || r.Header.Get("Authorization") != "" {
			w.WriteHeader(403)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_, _ = w.Write([]byte(state))
	}))
	defer upstream.Close()
	if err := a.configureLegacyProxy(upstream.URL, testProxySecret); err != nil {
		t.Fatal(err)
	}
	w := request(a, "GET", "/api/v1/legacy-state", user.Token, "")
	wantStatus(t, w, 200)
	var result map[string]json.RawMessage
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if len(result) != 5 || string(result["mazeEnergy_10010001"]) != "600" || len(result["passwordHash"]) != 0 || len(result["items"]) != 0 {
		t.Fatalf("state whitelist failed: %s", w.Body.String())
	}
	wantStatus(t, request(a, "GET", "/api/v1/legacy-state?accountId=forged", user.Token, ""), 400)
	state = `{"version":1,"name":"","gold":123}`
	wantStatus(t, request(a, "GET", "/api/v1/legacy-state", user.Token, ""), 502)
	state = `{"version":1,"name":"测试角色","gold":{"passwordHash":"secret"}}`
	wantStatus(t, request(a, "GET", "/api/v1/legacy-state", user.Token, ""), 502)
}
