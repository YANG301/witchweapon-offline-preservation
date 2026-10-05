package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestLegacyRoleUsesAuthenticatedJavaAccount(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "legacy-role-alice@example.com")
	bob := registerTest(t, a, "legacy-role-bob@example.com")
	wantStatus(t, request(a, "GET", "/api/v1/legacy-role", "", ""), 401)
	wantStatus(t, request(a, "GET", "/api/v1/legacy-role", alice.Token, ""), 503)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.URL.Path != "/__role" || r.URL.RawQuery != "" ||
			r.Header.Get("X-WW-Proxy-Secret") != testProxySecret ||
			r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" ||
			r.Header.Get("X-WW-Account-ID") == "forged" || r.Header.Get("X-WW-Role-ID") != "" {
			w.WriteHeader(403)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		switch r.Header.Get("X-WW-Account-ID") {
		case alice.Player.ID:
			_, _ = w.Write([]byte(`{"version":1,"exists":true,"roleId":"87123456789","name":"Alice","head":2,"headBox":3}`))
		case bob.Player.ID:
			_, _ = w.Write([]byte(`{"version":1,"exists":false,"roleId":"","name":"","head":0,"headBox":0}`))
		default:
			w.WriteHeader(403)
		}
	}))
	defer upstream.Close()
	if err := a.configureLegacyProxy(upstream.URL, testProxySecret); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		token  string
		exists bool
		id     string
	}{{alice.Token, true, "87123456789"}, {bob.Token, false, ""}} {
		w := request(a, "GET", "/api/v1/legacy-role", tc.token, "")
		wantStatus(t, w, 200)
		var got struct {
			Version int    `json:"version"`
			Exists  bool   `json:"exists"`
			RoleID  string `json:"roleId"`
			Name    string `json:"name"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil || got.Version != 1 ||
			got.Exists != tc.exists || got.RoleID != tc.id {
			t.Fatalf("wrong account role summary: %d %s", w.Code, w.Body.String())
		}
		var publicFields map[string]json.RawMessage
		if err := json.Unmarshal(w.Body.Bytes(), &publicFields); err != nil || len(publicFields) != 4 ||
			publicFields["head"] != nil || publicFields["headBox"] != nil {
			t.Fatalf("public role schema changed: %s", w.Body.String())
		}
	}
	wantStatus(t, request(a, "GET", "/api/v1/legacy-role?accountId=forged", alice.Token, ""), 400)
	wantStatus(t, request(a, "POST", "/api/v1/legacy-role", alice.Token, ""), 404)
}

func TestLegacyRoleRejectsInvalidUpstream(t *testing.T) {
	a, _, _ := fixture(t)
	user := registerTest(t, a, "legacy-role-invalid@example.com")
	var response atomic.Value
	response.Store(`{"version":1,"exists":true,"roleId":"1","name":"Valid"}`)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(response.Load().(string)))
	}))
	defer upstream.Close()
	if err := a.configureLegacyProxy(upstream.URL, testProxySecret); err != nil {
		t.Fatal(err)
	}
	wantStatus(t, request(a, "GET", "/api/v1/legacy-role", user.Token, ""), 200)
	for _, invalid := range []string{
		`{"version":1,"exists":true,"roleId":"0","name":"Bad"}`,
		`{"version":1,"exists":true,"roleId":"9223372036854775808","name":"Bad"}`,
		`{"version":1,"exists":false,"roleId":"1","name":"Bad"}`,
		`{"version":1,"roleId":"","name":""}`,
		`{"version":1,"exists":true,"roleId":"1","name":"Bad","accountId":"leak"}`,
		`{"version":1,"exists":true,"roleId":"1","name":"Bad","head":1}`,
		`{"version":1,"exists":true,"roleId":"1","name":"Bad","head":null,"headBox":1}`,
		`{"version":1,"exists":true,"roleId":"1","name":"Bad","head":"1","headBox":1}`,
		`{"version":1,"exists":true,"roleId":"1","name":"Bad","head":-1,"headBox":1}`,
		`{"version":1,"exists":true,"roleId":"1","name":"Bad","head":1,"headBox":1,"accountId":"leak"}`,
		strings.Repeat("x", legacyRoleLimit+1),
	} {
		response.Store(invalid)
		wantStatus(t, request(a, "GET", "/api/v1/legacy-role", user.Token, ""), 502)
	}
}
