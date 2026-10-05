package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"
)

type recoveryTestProvider struct {
	mu    sync.Mutex
	codes map[string]string
	sends int
	fail  bool
}

func (p *recoveryTestProvider) install(t *testing.T, a *app) {
	t.Helper()
	a.emailVerification.client.Transport = emailTestTransport(func(r *http.Request) (*http.Response, error) {
		var input struct {
			To      []string `json:"to"`
			Subject string   `json:"subject"`
			Text    string   `json:"text"`
			HTML    string   `json:"html"`
		}
		if json.NewDecoder(r.Body).Decode(&input) != nil || len(input.To) != 1 || input.Subject != "魔女兵器密码找回验证码" || strings.Contains(input.HTML, "设置 → 个人中心") || !strings.Contains(input.HTML, "密码") || !strings.Contains(input.HTML, "https://www.witchweapon.wiki/assets/spring.png") {
			t.Error("wrong recovery email content")
		}
		code := regexp.MustCompile(`[0-9]{6}`).FindString(input.Text)
		if code == "" {
			t.Error("missing recovery code")
		}
		p.mu.Lock()
		defer p.mu.Unlock()
		if p.codes == nil {
			p.codes = make(map[string]string)
		}
		p.codes[input.To[0]] = code
		p.sends++
		if p.fail {
			return nil, errors.New("synthetic transport failure")
		}
		data, _ := json.Marshal(map[string]any{"success": true, "errors": []any{}, "result": map[string]any{"message_id": "synthetic-reset", "queued": input.To}})
		return &http.Response{StatusCode: 200, Header: http.Header{"Content-Type": {"application/json"}}, Body: io.NopCloser(bytes.NewReader(data))}, nil
	})
}

func recoveryRequest(a *app, path, email, code, password, ip string) *httptest.ResponseRecorder {
	input := map[string]string{"email": email}
	if strings.HasSuffix(path, "/reset") {
		input["code"], input["password"] = code, password
	}
	body, _ := json.Marshal(input)
	r := httptest.NewRequest("POST", path, bytes.NewReader(body))
	r.RemoteAddr = ip + ":1234"
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	return w
}

func recoveryCode(t *testing.T, a *app, p *recoveryTestProvider, email, ip string) string {
	t.Helper()
	w := recoveryRequest(a, "/api/v1/auth/password/send", email, "", "", ip)
	wantStatus(t, w, 202)
	a.emailVerification.recoveryWG.Wait()
	p.mu.Lock()
	defer p.mu.Unlock()
	code := p.codes[normalizeEmail(email)]
	if len(code) != 6 {
		t.Fatal("mock provider did not receive a code")
	}
	return code
}

func TestPasswordRecoveryPreservesBindingAndRevokesSessions(t *testing.T) {
	a, dir, stories := fixture(t)
	configureEmailTest(t, a)
	now := time.Date(2026, 10, 4, 8, 0, 0, 0, time.UTC)
	a.now = func() time.Time { return now }
	user := registerTest(t, a, "recover@example.com")
	other := registerTest(t, a, "other@example.com")
	w := request(a, "POST", "/api/v1/auth/login", "", `{"email":"recover@example.com","password":"  correct-password-42  ","remember":true}`)
	wantStatus(t, w, 200)
	var remembered authResponse
	_ = json.Unmarshal(w.Body.Bytes(), &remembered)
	wantStatus(t, request(a, "PUT", "/api/v1/progress/opening-10001", user.Token, `{"lastLine":2,"completed":true}`), 200)
	code, nonce, err := a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.1", a.emailVerification.key[:], now.Add(-24*time.Hour), a.emailVerification.limits)
	if err != nil {
		t.Fatal(err)
	}
	if err = a.store.finishEmailCode(user.Player.ID, nonce, true); err != nil {
		t.Fatal(err)
	}
	if _, err = a.store.verifyEmailCode(user.Player.ID, user.Player.Email, "42", code, a.emailVerification.key[:], now.Add(-24*time.Hour)); err != nil {
		t.Fatal(err)
	}
	if err = a.store.finishEmailReward(user.Player.ID, a.store.emailVerification(user.Player.ID).RewardRequestID, "123"); err != nil {
		t.Fatal(err)
	}
	bindingBefore := a.store.emailVerification(user.Player.ID)
	p := &recoveryTestProvider{}
	p.install(t, a)
	resetCode := recoveryCode(t, a, p, " RECOVER@EXAMPLE.COM ", "198.51.100.2")
	const newPassword = "new-test-password-43"
	wantStatus(t, recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, resetCode, newPassword, "198.51.100.2"), 200)
	for _, token := range []string{user.Token, remembered.Token} {
		wantStatus(t, request(a, "GET", "/api/v1/me", token, ""), 401)
	}
	wantStatus(t, request(a, "POST", "/api/v1/auth/refresh", "", `{"refreshToken":"`+remembered.RefreshToken+`"}`), 401)
	wantStatus(t, request(a, "GET", "/api/v1/me", other.Token, ""), 200)
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody(user.Player.Email, testPassword)), 401)
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody(user.Player.Email, newPassword)), 200)
	if a.store.emailVerification(user.Player.ID) != bindingBefore {
		t.Fatal("recovery altered binding/reward state")
	}
	wantStatus(t, recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, resetCode, "another-test-password", "198.51.100.3"), 400)
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	configureEmailTest(t, b)
	b.now = a.now
	wantStatus(t, request(b, "POST", "/api/v1/auth/login", "", authBody(user.Player.Email, newPassword)), 200)
	wantStatus(t, recoveryRequest(b, "/api/v1/auth/password/reset", user.Player.Email, resetCode, "another-test-password", "198.51.100.3"), 400)
	player, _ := b.store.player(user.Player.ID)
	if !player.EmailVerified || len(player.Progress) != 1 || !player.Progress[0].Completed {
		t.Fatal("player progress or binding was lost")
	}
}

func TestPasswordRecoveryDoesNotEnumerateAccounts(t *testing.T) {
	a, _, _ := fixture(t)
	configureEmailTest(t, a)
	user := registerTest(t, a, "private@example.com")
	now := time.Date(2026, 10, 4, 8, 0, 0, 0, time.UTC)
	a.now = func() time.Time { return now }
	p := &recoveryTestProvider{}
	p.install(t, a)
	known := recoveryRequest(a, "/api/v1/auth/password/send", user.Player.Email, "", "", "198.51.100.1")
	missing := recoveryRequest(a, "/api/v1/auth/password/send", "missing@example.com", "", "", "198.51.100.2")
	repeated := recoveryRequest(a, "/api/v1/auth/password/send", user.Player.Email, "", "", "198.51.100.3")
	a.emailVerification.recoveryWG.Wait()
	if known.Code != 202 || known.Code != missing.Code || known.Body.String() != missing.Body.String() || known.Body.String() != repeated.Body.String() {
		t.Fatal("send response exposed account existence or send history")
	}
	if p.sends != 1 || a.store.emailVerifications.GlobalMonth.Count != 1 {
		t.Fatal("unknown/repeated addresses consumed real sends or monthly quota")
	}
	badKnown := recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, "999999", "another-test-password", "198.51.100.3")
	badMissing := recoveryRequest(a, "/api/v1/auth/password/reset", "missing@example.com", "999999", "another-test-password", "198.51.100.3")
	if badKnown.Code != 400 || badKnown.Body.String() != badMissing.Body.String() {
		t.Fatal("reset response enumerated account")
	}
	if known.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatal("recovery unexpectedly enabled CORS")
	}
}

func TestPasswordRecoverySharesBindingQuotasAndPurposeIsolation(t *testing.T) {
	a, _, _ := fixture(t)
	configureEmailTest(t, a)
	user := registerTest(t, a, "purpose@example.com")
	second := registerTest(t, a, "second@example.com")
	now := time.Date(2026, 10, 4, 8, 0, 0, 0, time.UTC)
	key, limits := a.emailVerification.key[:], a.emailVerification.limits
	bindingCode, _, err := a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.1", key, now, limits)
	if err != nil {
		t.Fatal(err)
	}
	_, _, _, err = a.store.preparePasswordCode(user.Player.Email, "198.51.100.2", key, now, limits)
	var flow *emailFlowError
	if !errors.As(err, &flow) || flow.Reason != "day_account" {
		t.Fatal("binding send failed to limit same-account recovery")
	}
	_, _, _, err = a.store.preparePasswordCode(second.Player.Email, "198.51.100.1", key, now, limits)
	if !errors.As(err, &flow) || flow.Reason != "day_ip" {
		t.Fatal("binding send failed to limit same-IP recovery")
	}
	id, resetCode, nonce, err := a.store.preparePasswordCode(user.Player.Email, "198.51.100.1", key, now.Add(24*time.Hour), limits)
	if err != nil {
		t.Fatal(err)
	}
	if err = a.store.finishPasswordCode(id, nonce, true); err != nil {
		t.Fatal(err)
	}
	_, _, err = a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.2", key, now.Add(24*time.Hour), limits)
	if !errors.As(err, &flow) || flow.Reason != "day_account" {
		t.Fatal("recovery failed to limit binding account")
	}
	_, _, err = a.store.prepareEmailCode(second.Player.ID, second.Player.Email, "42", "198.51.100.1", key, now.Add(24*time.Hour), limits)
	if !errors.As(err, &flow) || flow.Reason != "day_ip" {
		t.Fatal("recovery failed to limit binding IP")
	}
	r := a.store.passwordRecoveries.Records["account:"+id]
	if r.CodeHash == emailCodeHash(key, id, user.Player.Email, nonce, resetCode) {
		t.Fatal("recovery/binding hash domain not isolated")
	}
	// Force a deterministic different code when a random collision occurs.
	if bindingCode == resetCode {
		bindingCode = "000000"
		if bindingCode == resetCode {
			bindingCode = "000001"
		}
	}
	if _, err := a.store.validatePasswordCode(user.Player.Email, bindingCode, key, now.Add(24*time.Hour)); !errors.Is(err, errInvalidRecoveryCode) {
		t.Fatal("binding code authorized password reset")
	}
}

func TestPasswordRecoveryExpiryAttemptLimitAndFailedDelivery(t *testing.T) {
	a, _, _ := fixture(t)
	configureEmailTest(t, a)
	user := registerTest(t, a, "attempts@example.com")
	now := time.Date(2026, 10, 4, 8, 0, 0, 0, time.UTC)
	a.now = func() time.Time { return now }
	p := &recoveryTestProvider{}
	p.install(t, a)
	code := recoveryCode(t, a, p, user.Player.Email, "198.51.100.1")
	wrong := "000000"
	if wrong == code {
		wrong = "000001"
	}
	for i := 0; i < emailCodeAttempts; i++ {
		wantStatus(t, recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, wrong, "another-test-password", "198.51.100.1"), 400)
	}
	wantStatus(t, recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, code, "another-test-password", "198.51.100.1"), 400)
	now = now.Add(24 * time.Hour)
	code = recoveryCode(t, a, p, user.Player.Email, "198.51.100.1")
	now = now.Add(emailCodeLifetime)
	wantStatus(t, recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, code, "another-test-password", "198.51.100.1"), 400)
	now = now.Add(24 * time.Hour)
	p.fail = true
	recoveryCode(t, a, p, user.Player.Email, "198.51.100.1")
	r := a.store.passwordRecoveries.Records["account:"+user.Player.ID]
	if r.Active || r.CodeHash != "" || r.Nonce != "" {
		t.Fatal("failed delivery left a usable recovery code")
	}
}

func TestPasswordRecoveryMonthlyQuotaAndInputValidation(t *testing.T) {
	a, _, _ := fixture(t)
	configureEmailTest(t, a)
	user := registerTest(t, a, "quota@example.com")
	now := time.Date(2026, 10, 4, 8, 0, 0, 0, time.UTC)
	a.now = func() time.Time { return now }
	p := &recoveryTestProvider{}
	p.install(t, a)
	a.emailVerification.limits.Monthly = 1
	recoveryCode(t, a, p, user.Player.Email, "198.51.100.1")
	limited := recoveryRequest(a, "/api/v1/auth/password/send", "missing@example.com", "", "", "198.51.100.2")
	if limited.Code != 429 || !strings.Contains(limited.Body.String(), emailMonthlyQuotaMessage) || limited.Header().Get("Retry-After") == "" {
		t.Fatal("monthly exhausted prompt missing")
	}
	for _, test := range []struct {
		method, path, body, media string
		status                    int
	}{
		{"POST", "/api/v1/auth/password/send", `{"email":"quota@example.com","code":"000000"}`, "application/json", 400},
		{"POST", "/api/v1/auth/password/send?email=quota@example.com", `{}`, "application/json", 400},
		{"POST", "/api/v1/auth/password/send", `{"email":"quota@example.com"}`, "text/plain", 415},
		{"POST", "/api/v1/auth/password/reset", `{"email":"quota@example.com","code":"000000","password":"short"}`, "application/json", 400},
		{"GET", "/api/v1/auth/password/send", "", "application/json", 404},
	} {
		r := httptest.NewRequest(test.method, test.path, strings.NewReader(test.body))
		r.Header.Set("Content-Type", test.media)
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		wantStatus(t, w, test.status)
	}
}

func TestPasswordRecoveryConcurrentResetAndStorageFailure(t *testing.T) {
	a, _, _ := fixture(t)
	configureEmailTest(t, a)
	user := registerTest(t, a, "race@example.com")
	now := time.Date(2026, 10, 4, 8, 0, 0, 0, time.UTC)
	a.now = func() time.Time { return now }
	p := &recoveryTestProvider{}
	p.install(t, a)
	code := recoveryCode(t, a, p, user.Player.Email, "198.51.100.1")
	var wg sync.WaitGroup
	statuses := make(chan int, 2)
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			statuses <- recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, code, "concurrent-new-password", "198.51.100.1").Code
		}()
	}
	wg.Wait()
	close(statuses)
	success, rejected := 0, 0
	for status := range statuses {
		if status == 200 {
			success++
		}
		if status == 400 {
			rejected++
		}
	}
	if success != 1 || rejected != 1 {
		t.Fatal("same code reset the account more than once")
	}
	now = now.Add(24 * time.Hour)
	code = recoveryCode(t, a, p, user.Player.Email, "198.51.100.1")
	original := a.store.refreshFile
	a.store.refreshFile = filepath.Join(t.TempDir(), "missing", "refresh.json")
	wantStatus(t, recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, code, "failure-new-password", "198.51.100.1"), 503)
	a.store.refreshFile = original
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody(user.Player.Email, "concurrent-new-password")), 200)
	stateBytes, err := os.ReadFile(a.store.file)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(stateBytes, []byte("failure-new-password")) || bytes.Contains(stateBytes, []byte(code)) {
		t.Fatal("state exposed password or recovery code")
	}
}

func TestPasswordRecoveryRejectsPasswordsNativeLoginCannotUse(t *testing.T) {
	a, _, _ := fixture(t)
	configureEmailTest(t, a)
	user := registerTest(t, a, "native-password@example.com")
	now := time.Date(2026, 10, 4, 8, 0, 0, 0, time.UTC)
	a.now = func() time.Time { return now }
	p := &recoveryTestProvider{}
	p.install(t, a)
	code := recoveryCode(t, a, p, user.Player.Email, "198.51.100.1")
	before := mustRead(t, a.store.file)
	challenge := a.store.passwordRecoveries.Records["account:"+user.Player.ID]
	for _, password := range []string{
		" valid-password-12", "valid-password-12 ", "\tvalid-password-12", "valid-password-12\n",
		"\u00a0valid-password-12", "valid-password-12\u2003",
		"valid\x00password-12", "valid\npassword-12", "valid\tpassword-12", "valid\x7fpassword-12", "valid\u0085password-12",
		strings.Repeat("x", 11), strings.Repeat("x", 129),
	} {
		w := recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, code, password, "198.51.100.1")
		if w.Code != 400 || !strings.Contains(w.Body.String(), `"code":"invalid_password"`) {
			t.Fatal("unusable native-login password was accepted")
		}
	}
	if !bytes.Equal(before, mustRead(t, a.store.file)) || challenge != a.store.passwordRecoveries.Records["account:"+user.Player.ID] {
		t.Fatal("invalid password altered the account or consumed the valid challenge")
	}
	for _, valid := range []string{strings.Repeat("x", 12), strings.Repeat("x", 128), "valid middle spaces-12", "这是可以登录的十二个字符密码"} {
		if !validRecoveryPassword(valid) {
			t.Fatal("usable native-login password was rejected")
		}
	}
	// A rejected password must not consume the code: an immediately corrected
	// usable password still resets and authenticates in the same session.
	const usable = "valid middle spaces-12"
	wantStatus(t, recoveryRequest(a, "/api/v1/auth/password/reset", user.Player.Email, code, usable, "198.51.100.2"), 200)
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody(user.Player.Email, usable)), 200)
}
