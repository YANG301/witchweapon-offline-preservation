package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

const testAdminPassword = "local-test-admin-password-42000000"

func configureAdminTest(t *testing.T, a *app) {
	t.Helper()
	encoded, err := encodeAdminCredential([]byte(testAdminPassword))
	if err != nil {
		t.Fatal(err)
	}
	if err := a.configureAdmin(encoded); err != nil {
		t.Fatal(err)
	}
}

func adminRequest(a *app, method, path, token, body string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, "http://127.0.0.1:18080"+path, strings.NewReader(body))
	r.RemoteAddr = "127.0.0.1:51000"
	r.Host = "127.0.0.1:18080"
	r.Header.Set("Content-Type", "application/json")
	if method != http.MethodGet {
		r.Header.Set("Origin", "http://127.0.0.1:18080")
	}
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	return w
}

func loginAdminTest(t *testing.T, a *app) string {
	t.Helper()
	response := adminRequest(a, http.MethodPost, "/admin/api/login", "", fmt.Sprintf(`{"username":"admin","password":%q}`, testAdminPassword))
	wantStatus(t, response, 200)
	var body struct {
		Token string `json:"token"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if len(body.Token) != 43 {
		t.Fatal("admin token size")
	}
	return body.Token
}

func TestAdminAuthAndAccountProjection(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "alice@example.com")
	bob := registerTest(t, a, "bob@example.com")
	configureAdminTest(t, a)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/accounts", alice.Token, ""), 401)
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/login", "", `{"username":"admin","password":"incorrect-admin-password-123456"}`), 401)
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/login", "", fmt.Sprintf(`{"username":"wrong","password":%q}`, testAdminPassword)), 401)
	adminToken := loginAdminTest(t, a)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/me", adminToken, ""), 200)
	duplicateAuth := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:18080/admin/api/me", nil)
	duplicateAuth.RemoteAddr = "127.0.0.1:51000"
	duplicateAuth.Header.Add("Authorization", "Bearer "+adminToken)
	duplicateAuth.Header.Add("Authorization", "Bearer "+adminToken)
	duplicateResponse := httptest.NewRecorder()
	a.ServeHTTP(duplicateResponse, duplicateAuth)
	wantStatus(t, duplicateResponse, 401)
	wantStatus(t, request(a, http.MethodGet, "/api/v1/me", adminToken, ""), 401)
	response := adminRequest(a, http.MethodGet, "/admin/api/accounts?limit=1", adminToken, "")
	wantStatus(t, response, 200)
	var list struct {
		Items      []adminAccountSummary `json:"items"`
		Total      int                   `json:"total"`
		NextCursor string                `json:"nextCursor"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &list); err != nil {
		t.Fatal(err)
	}
	if list.Total != 2 || len(list.Items) != 1 || list.NextCursor == "" {
		t.Fatalf("unexpected listing %+v", list)
	}
	for _, forbidden := range []string{"passwordHash", "\"salt\"", testPassword, alice.Token, bob.Token, testAdminPassword} {
		if strings.Contains(response.Body.String(), forbidden) {
			t.Fatal("secret leaked from admin listing")
		}
	}
	page2 := adminRequest(a, http.MethodGet, "/admin/api/accounts?limit=1&cursor="+url.QueryEscape(list.NextCursor), adminToken, "")
	wantStatus(t, page2, 200)
	var list2 struct {
		Items []adminAccountSummary `json:"items"`
	}
	if err := json.Unmarshal(page2.Body.Bytes(), &list2); err != nil || len(list2.Items) != 1 || list2.Items[0].ID == list.Items[0].ID {
		t.Fatal("pagination repeated account")
	}
	search := adminRequest(a, http.MethodGet, "/admin/api/accounts?q=ALICE", adminToken, "")
	wantStatus(t, search, 200)
	if !strings.Contains(search.Body.String(), "alice@example.com") || strings.Contains(search.Body.String(), "bob@example.com") {
		t.Fatal("search scope")
	}
	ridSearch := adminRequest(a, http.MethodGet, fmt.Sprintf("/admin/api/accounts?q=%d", alice.Player.PublicRID), adminToken, "")
	wantStatus(t, ridSearch, 200)
	var byRID struct {
		Items []adminAccountSummary `json:"items"`
		Total int                   `json:"total"`
	}
	if err := json.Unmarshal(ridSearch.Body.Bytes(), &byRID); err != nil || byRID.Total != 1 || len(byRID.Items) != 1 ||
		byRID.Items[0].ID != alice.Player.ID || byRID.Items[0].PublicRID != alice.Player.PublicRID {
		t.Fatal("public RID search did not return its account")
	}
	if _, err := a.store.createRole(bob.Player.ID, Role{ID: "unity-test-role", Nickname: "试验昵称", Level: 1, CreatedAt: time.Now().UTC()}); err != nil {
		t.Fatal(err)
	}
	nameSearch := adminRequest(a, http.MethodGet, "/admin/api/accounts?q="+url.QueryEscape("试验昵称"), adminToken, "")
	wantStatus(t, nameSearch, 200)
	if !strings.Contains(nameSearch.Body.String(), "\"total\":0") {
		t.Fatal("account search unexpectedly matched a Unity-only role nickname")
	}
	detail := adminRequest(a, http.MethodGet, "/admin/api/accounts/"+alice.Player.ID, adminToken, "")
	wantStatus(t, detail, 200)
	if !strings.Contains(detail.Body.String(), "\"available\":false") || strings.Contains(detail.Body.String(), "passwordHash") {
		t.Fatal("detail projection")
	}
	for _, path := range []string{"/admin/api/accounts?limit=201", "/admin/api/accounts?cursor=../", "/admin/api/accounts?q=x&q=y"} {
		wantStatus(t, adminRequest(a, http.MethodGet, path, adminToken, ""), 400)
	}
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/logout", adminToken, ""), 204)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/me", adminToken, ""), 401)
}

func TestAdminLoopbackOriginAndProxyBoundary(t *testing.T) {
	a, _, _ := fixture(t)
	configureAdminTest(t, a)
	makeRequest := func(host, remote, origin string, forwarded bool) *httptest.ResponseRecorder {
		r := httptest.NewRequest(http.MethodPost, "http://"+host+"/admin/api/login",
			strings.NewReader(fmt.Sprintf(`{"username":"admin","password":%q}`, testAdminPassword)))
		r.RemoteAddr = remote
		r.Host = host
		r.Header.Set("Content-Type", "application/json")
		if origin != "" {
			r.Header.Set("Origin", origin)
		}
		if forwarded {
			r.Header.Set("X-Real-IP", "198.51.100.44")
		}
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		return w
	}
	for _, response := range []*httptest.ResponseRecorder{
		makeRequest("212.192.15.11:18443", "127.0.0.1:50000", "http://212.192.15.11:18443", true),
		makeRequest("127.0.0.1:18080", "203.0.113.4:50000", "http://127.0.0.1:18080", false),
		makeRequest("127.0.0.1:18080", "127.0.0.1:50000", "", false),
		makeRequest("127.0.0.1:18080", "127.0.0.1:50000", "http://evil.example", false),
		makeRequest("127.0.0.1:18080", "127.0.0.1:50000", "http://127.0.0.1:18080", true),
	} {
		wantStatus(t, response, 404)
	}
	forwardedPort := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:18080/admin/", nil)
	forwardedPort.RemoteAddr = "127.0.0.1:50000"
	forwardedPort.Header.Set("X-Forwarded-Port", "18443")
	forwardedPortResponse := httptest.NewRecorder()
	a.ServeHTTP(forwardedPortResponse, forwardedPort)
	wantStatus(t, forwardedPortResponse, 404)
	wantStatus(t, makeRequest("127.0.0.1:18080", "127.0.0.1:50000", "http://127.0.0.1:18080", false), 200)
}

func TestAdminPublicOriginExactBoundary(t *testing.T) {
	a, _, _ := fixture(t)
	configureAdminTest(t, a)
	const origin = "https://203.0.113.80:18444"
	makeRequest := func(method, host, remote, requestOrigin, forwardHeader string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, "http://127.0.0.1:18080/admin/api/login",
			strings.NewReader(fmt.Sprintf(`{"username":"admin","password":%q}`, testAdminPassword)))
		r.Host = host
		r.RemoteAddr = remote
		r.Header.Set("Content-Type", "application/json")
		if requestOrigin != "" {
			r.Header.Set("Origin", requestOrigin)
		}
		if forwardHeader != "" {
			r.Header.Set("X-Forwarded-For", forwardHeader)
		}
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		return w
	}
	wantStatus(t, makeRequest(http.MethodPost, "203.0.113.80:18444", "127.0.0.1:51000", origin, ""), 404)
	for _, invalid := range []string{
		"http://203.0.113.80:18444", "https://203.0.113.80:18444/",
		"https://203.0.113.80:18444/admin/", "https://203.0.113.80:18444?x=1",
		"https://witchweapon.wiki:18444", "https://127.0.0.1:18444", "https://203.0.113.80",
		"https://0.0.0.0:18444",
	} {
		if err := a.configureAdminPublicOrigin(invalid); err == nil {
			t.Fatalf("accepted invalid public origin %q", invalid)
		}
	}
	if err := a.configureAdminPublicOrigin(origin); err != nil {
		t.Fatal(err)
	}
	for _, response := range []*httptest.ResponseRecorder{
		makeRequest(http.MethodPost, "203.0.113.80:18443", "127.0.0.1:51000", origin, ""),
		makeRequest(http.MethodPost, "witchweapon.wiki:18444", "127.0.0.1:51000", origin, ""),
		makeRequest(http.MethodPost, "203.0.113.80:18444", "198.51.100.2:51000", origin, ""),
		makeRequest(http.MethodPost, "203.0.113.80:18444", "127.0.0.1:51000", "", ""),
		makeRequest(http.MethodPost, "203.0.113.80:18444", "127.0.0.1:51000", "https://203.0.113.80:18443", ""),
		makeRequest(http.MethodPost, "203.0.113.80:18444", "127.0.0.1:51000", origin, "198.51.100.2"),
	} {
		wantStatus(t, response, 404)
	}
	wantStatus(t, makeRequest(http.MethodPost, "203.0.113.80:18444", "127.0.0.1:51000", origin, ""), 200)
	asset := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:18080/admin/", nil)
	asset.Host = "203.0.113.80:18444"
	asset.RemoteAddr = "127.0.0.1:51000"
	w := httptest.NewRecorder()
	a.ServeHTTP(w, asset)
	wantStatus(t, w, 200)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/", "", ""), 200)
}

func TestAdminPublicAndSSHRateBucketsIndependent(t *testing.T) {
	a, _, _ := fixture(t)
	configureAdminTest(t, a)
	if err := a.configureAdminPublicOrigin("https://203.0.113.80:18444"); err != nil {
		t.Fatal(err)
	}
	public := func() *httptest.ResponseRecorder {
		r := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:18080/admin/api/login", strings.NewReader("{"))
		r.RemoteAddr = "127.0.0.1:51000"
		r.Host = "203.0.113.80:18444"
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Origin", "https://203.0.113.80:18444")
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		return w
	}
	for i := 0; i < 60; i++ {
		wantStatus(t, public(), 400)
	}
	wantStatus(t, public(), 429)
	for i := 0; i < 5; i++ {
		wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/login", "", "{"), 400)
	}
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/login", "", "{"), 429)
}

func TestAdminKDFConcurrencyBoundAndOldSecretDisabled(t *testing.T) {
	t.Setenv("WW_ADMIN_SECRET", "obsolete-test-only-secret-no-longer-accepted")
	t.Setenv(adminCredentialEnvName, "")
	a, _, _ := fixture(t)
	if err := a.configureAdmin(os.Getenv(adminCredentialEnvName)); err != nil || a.admin != nil {
		t.Fatal("old admin secret unexpectedly enabled admin auth")
	}
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/login", "", `{"secret":"obsolete-test-only-secret-no-longer-accepted"}`), 404)
	configureAdminTest(t, a)
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/login", "", `{"secret":"obsolete-test-only-secret-no-longer-accepted"}`), 400)
	a.kdfSlots <- struct{}{}
	a.kdfSlots <- struct{}{}
	defer func() { <-a.kdfSlots; <-a.kdfSlots }()
	body := fmt.Sprintf(`{"username":"admin","password":%q}`, testAdminPassword)
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/login", "", body), 429)
}

func TestAdminLegacyWhitelistedPatchAndIsolation(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "alice@example.com")
	bob := registerTest(t, a, "bob@example.com")
	configureAdminTest(t, a)
	adminToken := loginAdminTest(t, a)
	revisions := map[string]int64{alice.Player.ID: 5, bob.Player.ID: 12}
	names := map[string]string{alice.Player.ID: "本地玩家", bob.Player.ID: "另一个角色"}
	golds := map[string]int64{alice.Player.ID: 1000, bob.Player.ID: 5000}
	patches := 0
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-WW-Account-ID")
		if r.Header.Get("X-WW-Proxy-Secret") != strings.Repeat("x", 40) || revisions[id] == 0 {
			t.Error("invalid service identity")
			w.WriteHeader(403)
			return
		}
		if r.URL.Path != "/__admin/state" && r.URL.Path != "/__admin/patch" {
			t.Error("unexpected Java path")
			w.WriteHeader(404)
			return
		}
		if id == bob.Player.ID && r.URL.Path == "/__admin/state" {
			w.WriteHeader(404)
			return
		}
		if r.URL.Path == "/__admin/patch" {
			patches++
			if r.Header.Get("Content-Type") != "application/x-www-form-urlencoded" {
				t.Error("wrong content type")
			}
			_ = r.ParseForm()
			expected, _ := strconv.ParseInt(r.Form.Get("expectedRevision"), 10, 64)
			if expected != revisions[id] {
				w.WriteHeader(409)
				return
			}
			if r.Form.Get("reason") != "修复测试存档的金币数值" {
				t.Error("missing reason")
			}
			if name := r.Form.Get("name"); name != "" {
				names[id] = name
			}
			if gold := r.Form.Get("gold"); gold != "" {
				golds[id], _ = strconv.ParseInt(gold, 10, 64)
			}
			revisions[id]++
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		fmt.Fprintf(w, `{"version":1,"revision":%d,"name":%q,"gold":%d,"roleCreated":true,"roleId":"42","exp":0,"wins":1,"attempts":1,"stars":3,"mazeWins":0,"mazeAttempts":0,"mazeStars":0,"mazeRound":1,"active":false}`,
			revisions[id], names[id], golds[id])
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, strings.Repeat("x", 40)); err != nil {
		t.Fatal(err)
	}
	wantStatus(t, request(a, http.MethodGet, "/api/v1/legacy/__admin/state", alice.Token, ""), 404)
	wantStatus(t, request(a, http.MethodPost, "/api/v1/legacy/__admin/patch", alice.Token, "expectedRevision=5&gold=9999"), 404)
	detail := adminRequest(a, http.MethodGet, "/admin/api/accounts/"+alice.Player.ID, adminToken, "")
	wantStatus(t, detail, 200)
	if !strings.Contains(detail.Body.String(), "\"revision\":\"5\"") || !strings.Contains(detail.Body.String(), "\"gold\":1000") {
		t.Fatalf("unexpected Java summary: %s", detail.Body.String())
	}
	unstarted := adminRequest(a, http.MethodGet, "/admin/api/accounts/"+bob.Player.ID, adminToken, "")
	wantStatus(t, unstarted, 200)
	if !strings.Contains(unstarted.Body.String(), "\"reason\":\"not_started\"") || strings.Contains(unstarted.Body.String(), "\"passwordHash\"") {
		t.Fatalf("unstarted account result invalid: %s", unstarted.Body.String())
	}
	path := "/admin/api/accounts/" + alice.Player.ID + "/legacy"
	for _, body := range []string{
		`{"expectedRevision":"5","changes":{"gold":-1},"reason":"修复测试存档的金币数值"}`,
		`{"expectedRevision":"5","changes":{"gold":1000000001},"reason":"修复测试存档的金币数值"}`,
		`{"expectedRevision":"5","changes":{"rmb":99},"reason":"修复测试存档的金币数值"}`,
		`{"expectedRevision":"5","changes":{"name":"x"},"reason":"修复测试存档的金币数值"}`,
		`{"expectedRevision":"5","changes":{"gold":999},"reason":"x"}`,
	} {
		wantStatus(t, adminRequest(a, http.MethodPatch, path, adminToken, body), 400)
	}
	if patches != 0 {
		t.Fatal("invalid patch reached Java")
	}
	body := `{"expectedRevision":"5","changes":{"name":"新角色","gold":3000},"reason":"修复测试存档的金币数值"}`
	result := adminRequest(a, http.MethodPatch, path, adminToken, body)
	wantStatus(t, result, 200)
	if patches != 1 || golds[alice.Player.ID] != 3000 || names[alice.Player.ID] != "新角色" ||
		golds[bob.Player.ID] != 5000 || !strings.Contains(result.Body.String(), "\"revision\":\"6\"") {
		t.Fatalf("patch result invalid: %s", result.Body.String())
	}
	wantStatus(t, adminRequest(a, http.MethodPatch, path, adminToken, body), 409)
	if patches != 2 || golds[alice.Player.ID] != 3000 {
		t.Fatal("stale patch changed state")
	}
}

func TestAdminLegacyRejectsUnexpectedSensitiveFields(t *testing.T) {
	body := []byte(`{"version":1,"revision":1,"name":"角色","gold":10,"roleCreated":false,"roleId":"","exp":0,"wins":0,"attempts":0,"stars":0,"mazeWins":0,"mazeAttempts":0,"mazeStars":0,"mazeRound":1,"active":false,"passwordHash":"secret"}`)
	if _, err := parseAdminLegacy(body); err == nil {
		t.Fatal("unexpected Java field accepted")
	}
	missing := []byte(`{"version":1,"revision":1,"name":"角色","gold":10,"roleCreated":false,"roleId":"","exp":0,"wins":0,"attempts":0,"stars":0,"mazeWins":0,"mazeAttempts":0,"mazeStars":0,"mazeRound":1}`)
	if _, err := parseAdminLegacy(missing); err == nil {
		t.Fatal("missing Java field accepted")
	}
}

func TestAdminLegacySettlementTimestampUsesMilliseconds(t *testing.T) {
	seconds := int64(1789800000)
	view := adminLegacyView(adminLegacySummary{LastSettlementAt: &seconds})
	state, ok := view["state"].(map[string]any)
	if !ok || state["lastSettlementAt"] != seconds*1000 {
		t.Fatal("Java seconds were not converted for browser display")
	}
}

func TestAdminAssetsDisabledAndSessionExpiry(t *testing.T) {
	a, _, _ := fixture(t)
	for _, path := range []string{"/admin/", "/admin/style.css", "/admin/app.js"} {
		wantStatus(t, adminRequest(a, http.MethodGet, path, "", ""), 404)
	}
	configureAdminTest(t, a)
	for path, contentType := range map[string]string{
		"/admin/":          "text/html; charset=utf-8",
		"/admin/style.css": "text/css; charset=utf-8",
		"/admin/app.js":    "text/javascript; charset=utf-8",
	} {
		response := adminRequest(a, http.MethodGet, path, "", "")
		wantStatus(t, response, 200)
		if response.Header().Get("Content-Type") != contentType ||
			!strings.Contains(response.Header().Get("Content-Security-Policy"), "script-src 'self'") ||
			response.Header().Get("Cache-Control") != "no-store" {
			t.Fatalf("admin asset headers %q: %+v", path, response.Header())
		}
	}
	start := time.Date(2026, 9, 23, 8, 0, 0, 0, time.UTC)
	a.now = func() time.Time { return start }
	token := loginAdminTest(t, a)
	a.now = func() time.Time { return start.Add(adminSessionLifetime) }
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/me", token, ""), 401)
}
