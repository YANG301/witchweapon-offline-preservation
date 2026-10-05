package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func refreshBody(token string) string {
	b, _ := json.Marshal(refreshRequest{RefreshToken: token})
	return string(b)
}

func rememberBody(email, password string) string {
	b, _ := json.Marshal(credentialsRequest{Email: email, Password: password, Remember: true})
	return string(b)
}

func registerRememberTest(t *testing.T, a *app, email string) authResponse {
	t.Helper()
	w := request(a, "POST", "/api/v1/auth/register", "", rememberBody(email, testPassword))
	wantStatus(t, w, 201)
	return decodeAuth(t, w.Body.Bytes())
}

func decodeAuth(t *testing.T, body []byte) authResponse {
	t.Helper()
	var result authResponse
	if err := json.Unmarshal(body, &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Token) != 43 || !validRefreshToken(result.RefreshToken) || result.ExpiresAt.IsZero() || result.RefreshExpiresAt == nil || result.RefreshExpiresAt.IsZero() {
		t.Fatalf("incomplete auth response: %s", body)
	}
	return result
}

func wantLegacyAuthShape(t *testing.T, body []byte) authResponse {
	t.Helper()
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(body, &fields); err != nil {
		t.Fatal(err)
	}
	if len(fields) != 3 || fields["token"] == nil || fields["expiresAt"] == nil || fields["player"] == nil {
		t.Fatalf("legacy auth response changed: %s", body)
	}
	var result authResponse
	if err := json.Unmarshal(body, &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Token) != 43 || result.RefreshToken != "" || result.RefreshExpiresAt != nil {
		t.Fatalf("legacy response issued a refresh token: %s", body)
	}
	return result
}

func TestRememberIsOptInAndLegacyLoginsDoNotEvict(t *testing.T) {
	a, dir, _ := fixture(t)
	w := request(a, "POST", "/api/v1/auth/register", "", authBody("legacy-client@example.com", testPassword))
	wantStatus(t, w, 201)
	legacy := wantLegacyAuthShape(t, w.Body.Bytes())
	refreshFile := filepath.Join(dir, "refresh_sessions.json")
	if _, err := os.Stat(refreshFile); !os.IsNotExist(err) {
		t.Fatalf("legacy registration created refresh state: %v", err)
	}
	w = request(a, "POST", "/api/v1/auth/login", "", rememberBody("legacy-client@example.com", testPassword))
	wantStatus(t, w, 200)
	remembered := decodeAuth(t, w.Body.Bytes())
	for i := 0; i < maxRefreshDevices+2; i++ {
		w = request(a, "POST", "/api/v1/auth/login", "", authBody("legacy-client@example.com", testPassword))
		wantStatus(t, w, 200)
		wantLegacyAuthShape(t, w.Body.Bytes())
	}
	w = request(a, "POST", "/api/v1/auth/login", "", `{"email":"legacy-client@example.com","password":"`+testPassword+`","remember":false}`)
	wantStatus(t, w, 200)
	wantLegacyAuthShape(t, w.Body.Bytes())
	wantStatus(t, request(a, "GET", "/api/v1/me", legacy.Token, ""), 200)
	wantStatus(t, request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(remembered.RefreshToken)), 200)
	var saved refreshDiskState
	if err := json.Unmarshal(mustRead(t, refreshFile), &saved); err != nil {
		t.Fatal(err)
	}
	if len(saved.Tokens) != 1 {
		t.Fatalf("legacy logins occupied refresh slots: %d", len(saved.Tokens))
	}
}

func TestRefreshSurvivesRestartAndRotates(t *testing.T) {
	a, dir, stories := fixture(t)
	at := time.Date(2026, 9, 23, 12, 0, 0, 0, time.UTC)
	a.now = func() time.Time { return at }
	initial := registerRememberTest(t, a, "refresh@example.com")
	if !validRefreshToken(initial.RefreshToken) || !initial.RefreshExpiresAt.Equal(at.Add(refreshLifetime)) {
		t.Fatal("registration did not issue a 30-day refresh token")
	}
	state := mustRead(t, filepath.Join(dir, "state.json"))
	if bytes.Contains(state, []byte(initial.RefreshToken)) || bytes.Contains(state, []byte(initial.Token)) || bytes.Contains(state, []byte(testPassword)) {
		t.Fatal("plaintext credential persisted")
	}
	if bytes.Contains(state, []byte("refreshTokens")) {
		t.Fatal("account state format changed; old binary could not roll back")
	}
	refreshState := mustRead(t, filepath.Join(dir, "refresh_sessions.json"))
	if bytes.Contains(refreshState, []byte(initial.RefreshToken)) || !bytes.Contains(refreshState, []byte(tokenHash(initial.RefreshToken))) {
		t.Fatal("refresh state does not contain only the token digest")
	}
	wantStatus(t, request(a, "PUT", "/api/v1/progress/opening-10001", initial.Token, `{"lastLine":1,"completed":false}`), 200)
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	b.now = func() time.Time { return at.Add(29 * 24 * time.Hour) }
	wantStatus(t, request(b, "GET", "/api/v1/me", initial.Token, ""), 401)
	w := request(b, "POST", "/api/v1/auth/refresh", "", refreshBody(initial.RefreshToken))
	wantStatus(t, w, 200)
	rotated := decodeAuth(t, w.Body.Bytes())
	if rotated.Player.ID != initial.Player.ID || len(rotated.Player.Progress) != 1 || rotated.Player.Progress[0].LastLine != 1 || !rotated.RefreshExpiresAt.Equal(*initial.RefreshExpiresAt) || rotated.RefreshToken == initial.RefreshToken {
		t.Fatal("refresh did not restore the same player with a rotated, bounded token")
	}
	wantStatus(t, request(b, "POST", "/api/v1/auth/refresh", "", refreshBody(initial.RefreshToken)), 401)
	wantStatus(t, request(b, "GET", "/api/v1/me", rotated.Token, ""), 200)
	b.now = func() time.Time { return *initial.RefreshExpiresAt }
	wantStatus(t, request(b, "POST", "/api/v1/auth/refresh", "", refreshBody(rotated.RefreshToken)), 401)
}

func TestLogoutAndRevokeClearWholeDeviceFamily(t *testing.T) {
	a, _, _ := fixture(t)
	initial := registerRememberTest(t, a, "revoke@example.com")
	w := request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(initial.RefreshToken))
	wantStatus(t, w, 200)
	rotated := decodeAuth(t, w.Body.Bytes())
	// An access token issued before rotation can still log out the device.
	wantStatus(t, request(a, "POST", "/api/v1/auth/logout", initial.Token, ""), 204)
	wantStatus(t, request(a, "GET", "/api/v1/me", initial.Token, ""), 401)
	wantStatus(t, request(a, "GET", "/api/v1/me", rotated.Token, ""), 401)
	wantStatus(t, request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(rotated.RefreshToken)), 401)

	newLogin := decodeAuth(t, request(a, "POST", "/api/v1/auth/login", "", rememberBody("revoke@example.com", testPassword)).Body.Bytes())
	a.now = func() time.Time { return newLogin.ExpiresAt }
	wantStatus(t, request(a, "GET", "/api/v1/me", newLogin.Token, ""), 401)
	wantStatus(t, request(a, "POST", "/api/v1/auth/revoke", "", refreshBody(newLogin.RefreshToken)), 204)
	wantStatus(t, request(a, "POST", "/api/v1/auth/revoke", "", refreshBody(newLogin.RefreshToken)), 204)
	wantStatus(t, request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(newLogin.RefreshToken)), 401)
	wantStatus(t, request(a, "POST", "/api/v1/auth/revoke", "", refreshBody(strings.Repeat("A", 43))), 204)
}

func TestRefreshConcurrentReplayAndInputLimits(t *testing.T) {
	a, _, _ := fixture(t)
	initial := registerRememberTest(t, a, "replay@example.com")
	var wg sync.WaitGroup
	results := make(chan int, 10)
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			results <- request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(initial.RefreshToken)).Code
		}()
	}
	wg.Wait()
	close(results)
	success := 0
	for code := range results {
		switch code {
		case 200:
			success++
		case 401:
		default:
			t.Errorf("unexpected concurrent refresh status %d", code)
		}
	}
	if success != 1 {
		t.Fatalf("refresh token issued %d successors", success)
	}
	for _, body := range []string{`{}`, `{"refreshToken":"bad"}`, `{"refreshToken":"bad","userId":"other"}`, `null`} {
		wantStatus(t, request(a, "POST", "/api/v1/auth/revoke", "", body), 400)
	}
	// A separate fixture keeps the malformed-input checks independent.
	b, _, _ := fixture(t)
	wantStatus(t, request(b, "POST", "/api/v1/auth/refresh", "", fmt.Sprintf(`{"refreshToken":%q}`, strings.Repeat("A", 43))), 401)
	wantStatus(t, request(b, "POST", "/api/v1/auth/refresh", "", `{"refreshToken":"`+strings.Repeat("x", requestLimit)+`"}`), 413)
}

func TestRefreshWriteFailureKeepsOldCredential(t *testing.T) {
	a, dir, _ := fixture(t)
	initial := registerRememberTest(t, a, "write-failure@example.com")
	a.store.refreshFile = filepath.Join(t.TempDir(), "missing-directory", "refresh_sessions.json")
	wantStatus(t, request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(initial.RefreshToken)), 500)
	wantStatus(t, request(a, "GET", "/api/v1/me", initial.Token, ""), 200)
	a.store.refreshFile = filepath.Join(dir, "refresh_sessions.json")
	wantStatus(t, request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(initial.RefreshToken)), 200)
	state := mustRead(t, filepath.Join(dir, "refresh_sessions.json"))
	if bytes.Contains(state, []byte(initial.RefreshToken)) {
		t.Fatal("old plaintext token appeared in state")
	}
}

func TestRefreshRevokeWriteFailureAndRegistrationRecovery(t *testing.T) {
	a, dir, _ := fixture(t)
	initial := registerRememberTest(t, a, "revoke-disk@example.com")
	realFile := a.store.refreshFile
	a.store.refreshFile = filepath.Join(t.TempDir(), "missing-directory", "refresh_sessions.json")
	wantStatus(t, request(a, "POST", "/api/v1/auth/revoke", "", refreshBody(initial.RefreshToken)), 500)
	wantStatus(t, request(a, "GET", "/api/v1/me", initial.Token, ""), 200)
	a.store.refreshFile = realFile
	wantStatus(t, request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(initial.RefreshToken)), 200)

	a.store.refreshFile = filepath.Join(t.TempDir(), "missing-directory", "refresh_sessions.json")
	wantStatus(t, request(a, "POST", "/api/v1/auth/register", "", rememberBody("partial@example.com", testPassword)), 500)
	a.store.refreshFile = realFile
	if !bytes.Contains(mustRead(t, filepath.Join(dir, "state.json")), []byte("partial@example.com")) {
		t.Fatal("registration boundary did not persist the account first")
	}
	w := request(a, "POST", "/api/v1/auth/login", "", rememberBody("partial@example.com", testPassword))
	wantStatus(t, w, 200)
	if decodeAuth(t, w.Body.Bytes()).Player.Email != "partial@example.com" {
		t.Fatal("partially registered account could not recover by password login")
	}
}

func TestRefreshRateIsSeparateFromPasswordLogin(t *testing.T) {
	a, _, _ := fixture(t)
	initial := registerRememberTest(t, a, "rate-refresh@example.com")
	for i := 0; i < 21; i++ {
		wantStatus(t, request(a, "POST", "/api/v1/auth/revoke", "", refreshBody(strings.Repeat("A", 43))), 204)
	}
	// This login would fail if lightweight token traffic used the KDF bucket.
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody("rate-refresh@example.com", testPassword)), 200)
	proxy := httptest.NewRequest("POST", "/api/v1/auth/revoke", strings.NewReader(refreshBody(initial.RefreshToken)))
	proxy.Header.Set("Content-Type", "application/json")
	a.mu.Lock()
	a.refreshRates[authRateKey(proxy)] = rateEntry{Count: refreshRatePerMinute, Until: a.now().Add(time.Minute)}
	a.mu.Unlock()
	limited := httptest.NewRecorder()
	a.ServeHTTP(limited, proxy)
	wantStatus(t, limited, 429)
	if limited.Header().Get("Retry-After") != "60" {
		t.Fatal("refresh limit omitted retry hint")
	}
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody("rate-refresh@example.com", testPassword)), 200)
}

func TestRefreshDeviceCapAndLegacyState(t *testing.T) {
	a, dir, stories := fixture(t)
	first := registerRememberTest(t, a, "devices@example.com")
	var last authResponse
	for i := 0; i < maxRefreshDevices; i++ {
		w := request(a, "POST", "/api/v1/auth/login", "", rememberBody("devices@example.com", testPassword))
		wantStatus(t, w, 200)
		last = decodeAuth(t, w.Body.Bytes())
	}
	wantStatus(t, request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(first.RefreshToken)), 401)
	wantStatus(t, request(a, "GET", "/api/v1/me", first.Token, ""), 401)
	wantStatus(t, request(a, "POST", "/api/v1/auth/refresh", "", refreshBody(last.RefreshToken)), 200)
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	// A data directory created by the old server has no refresh file.
	if err := os.Remove(filepath.Join(dir, "refresh_sessions.json")); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	wantStatus(t, request(b, "POST", "/api/v1/auth/login", "", authBody("devices@example.com", testPassword)), 200)
}
