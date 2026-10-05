package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestLegacyPublicRIDUsesAuthenticatedAccountAndJavaRole(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "public-rid-alice@example.com")
	bob := registerTest(t, a, "public-rid-bob@example.com")
	const route = "/api/v1/legacy/role/publicRid"
	wantStatus(t, request(a, "GET", route, "", ""), 401)
	wantStatus(t, request(a, "GET", route, alice.Token, ""), 503)
	if alice.Player.Role != nil {
		t.Fatal("test needs an original-client account without a Go prototype role")
	}
	if _, err := a.store.createRole(bob.Player.ID, Role{ID: "unused-go-prototype", Nickname: "试验昵称",
		Level: 1, CreatedAt: time.Now().UTC()}); err != nil {
		t.Fatal(err)
	}
	if err := a.store.add(publicRIDTestAccount(ownerPublicRIDAccount)); err != nil {
		t.Fatal(err)
	}
	owner, err := a.issueAuth(ownerPublicRIDAccount, false)
	if err != nil {
		t.Fatal(err)
	}
	roles := map[string]string{alice.Player.ID: "87123456789", bob.Player.ID: "87123456790",
		ownerPublicRIDAccount: "87123456791"}
	rids := map[string]int{alice.Player.ID: alice.Player.PublicRID, bob.Player.ID: bob.Player.PublicRID,
		ownerPublicRIDAccount: ownerPublicRID}
	var calls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		accountID := r.Header.Get("X-WW-Account-ID")
		body, _ := io.ReadAll(r.Body)
		if r.Method != "GET" || r.URL.Path != "/__role" || r.URL.RawQuery != "" || len(body) != 0 ||
			roles[accountID] == "" || r.Header.Get("X-WW-Public-RID") != strconv.Itoa(rids[accountID]) ||
			r.Header.Get("X-WW-Proxy-Secret") != testProxySecret || r.Header.Get("Authorization") != "" ||
			r.Header.Get("Cookie") != "" {
			w.WriteHeader(403)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_, _ = io.WriteString(w, `{"version":1,"exists":true,"roleId":"`+roles[accountID]+`","name":"原版角色","head":1,"headBox":1}`)
	}))
	defer upstream.Close()
	if err := a.configureLegacyProxy(upstream.URL, testProxySecret); err != nil {
		t.Fatal(err)
	}
	stateBefore := mustRead(t, a.store.file)
	registryBefore := mustRead(t, a.store.publicRIDFile)
	for _, user := range []authResponse{alice, bob, owner} {
		r := httptest.NewRequest("GET", route, nil)
		r.Header.Set("Authorization", "Bearer "+user.Token)
		r.Header.Set("X-WW-Account-ID", "forged-account")
		r.Header.Set("X-WW-Role-ID", "forged-role")
		r.Header.Set("X-WW-Public-RID", "999999")
		r.Header.Set("Cookie", "forged=yes")
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		wantStatus(t, w, 200)
		var got struct {
			RID               int    `json:"rid"`
			RoleID            string `json:"roleId"`
			EmailRewardCards  int    `json:"emailRewardCards"`
			EmailServiceReady bool   `json:"emailServiceReady"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil || got.RID != rids[user.Player.ID] ||
			got.RoleID != roles[user.Player.ID] || got.EmailRewardCards != 100 || got.EmailServiceReady {
			t.Fatal("public RID lookup used the wrong identity or email service state")
		}
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(w.Body.Bytes(), &fields); err != nil || len(fields) != 4 {
			t.Fatal("public RID response leaked extra fields")
		}
	}
	for _, tc := range []struct {
		method, path, body string
		status             int
	}{
		{"POST", route, "", 405},
		{"GET", route + "?rid=114514", "", 400},
		{"GET", route + "?", "", 400},
		{"GET", route, "rid=114514", 400},
	} {
		wantStatus(t, request(a, tc.method, tc.path, alice.Token, tc.body), tc.status)
	}
	if calls.Load() != 3 {
		t.Fatal("invalid request reached Java or public RID lookup used another route")
	}
	if !bytes.Equal(stateBefore, mustRead(t, a.store.file)) ||
		!bytes.Equal(registryBefore, mustRead(t, a.store.publicRIDFile)) {
		t.Fatal("public RID lookup mutated account state or granted a reward")
	}
}

func TestLegacyPublicRIDRejectsMissingAndMalformedJavaRoles(t *testing.T) {
	a, _, _ := fixture(t)
	user := registerTest(t, a, "public-rid-invalid@example.com")
	var response atomic.Value
	response.Store(`{"version":1,"exists":true,"roleId":"1","name":"Valid"}`)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, response.Load().(string))
	}))
	defer upstream.Close()
	if err := a.configureLegacyProxy(upstream.URL, testProxySecret); err != nil {
		t.Fatal(err)
	}
	const route = "/api/v1/legacy/role/publicRid"
	for _, tc := range []struct {
		body   string
		status int
	}{
		{`{"version":1,"exists":false,"roleId":"","name":""}`, 409},
		{`{"version":1,"exists":true,"roleId":"0","name":"Bad"}`, 502},
		{`{"version":1,"exists":true,"roleId":"9223372036854775808","name":"Bad"}`, 502},
		{`{"version":1,"exists":true,"name":"Bad"}`, 502},
		{`{"version":1,"exists":null,"roleId":"","name":""}`, 502},
		{`{"version":1,"exists":true,"roleId":"1","name":"Bad","head":1}`, 502},
		{`{"version":1,"exists":true,"roleId":"1","name":"Bad","accountId":"leak"}`, 502},
		{strings.Repeat("x", legacyRoleLimit+1), 502},
	} {
		response.Store(tc.body)
		wantStatus(t, request(a, "GET", route, user.Token, ""), tc.status)
	}
}
