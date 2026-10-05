package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
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

type emailTestTransport func(*http.Request) (*http.Response, error)

func (f emailTestTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func configureEmailTest(t *testing.T, a *app) {
	t.Helper()
	t.Setenv("WW_EMAIL_VERIFICATION_ENABLED", "true")
	t.Setenv("WW_CF_EMAIL_ACCOUNT_ID", strings.Repeat("a", 32))
	t.Setenv("WW_CF_EMAIL_API_TOKEN", strings.Repeat("test-token-", 4))
	t.Setenv("WW_CF_EMAIL_API_TOKEN_FILE", "")
	t.Setenv("WW_CF_EMAIL_FROM", "noreply@example.com")
	for _, name := range []string{"WW_EMAIL_ACCOUNT_HOUR_LIMIT", "WW_EMAIL_ACCOUNT_DAY_LIMIT", "WW_EMAIL_GLOBAL_HOUR_LIMIT", "WW_EMAIL_GLOBAL_DAY_LIMIT", "WW_EMAIL_MONTHLY_LIMIT", "WW_EMAIL_MONTH_RESET_DAY"} {
		t.Setenv(name, "")
	}
	if err := a.configureEmailVerificationFromEnv(); err != nil {
		t.Fatal(err)
	}
}

func emailTestCFResponse(body string) *http.Response {
	return &http.Response{StatusCode: 200, Header: http.Header{"Content-Type": {"application/json"}}, Body: io.NopCloser(strings.NewReader(body))}
}

func TestEmailSendLogsOnlySafeAcceptance(t *testing.T) {
	const recipient, code, token = "synthetic-recipient@example.com", "012345", "synthetic-send-token"
	for _, test := range []struct {
		name, messageID, delivered, queued, wantStatus, wantID string
	}{
		{"delivered", "<cf-test-message@example.net>", recipient, "", "delivered", "<cf-test-message@example.net>"},
		{"queued", "cf-test-queued", "", recipient, "queued", "cf-test-queued"},
		{"missing-id", "", "", recipient, "queued", "unavailable"},
		{"log-injection", "unsafe\nprivate-response", "", recipient, "queued", "unavailable"},
		{"recipient-id", "<" + recipient + ">", "", recipient, "queued", "unavailable"},
		{"code-id", "cf-" + code, "", recipient, "queued", "unavailable"},
		{"token-id", token, "", recipient, "queued", "unavailable"},
		{"other-recipient", "cf-not-accepted", "other@example.com", "", "", ""},
	} {
		t.Run(test.name, func(t *testing.T) {
			var output bytes.Buffer
			previous := log.Writer()
			log.SetOutput(&output)
			t.Cleanup(func() { log.SetOutput(previous) })
			config := &emailVerificationConfig{accountID: strings.Repeat("a", 32), token: token, from: "noreply@example.com"}
			config.client = &http.Client{Transport: emailTestTransport(func(r *http.Request) (*http.Response, error) {
				var input struct {
					Subject string `json:"subject"`
					Text    string `json:"text"`
					HTML    string `json:"html"`
				}
				if json.NewDecoder(r.Body).Decode(&input) != nil || input.Subject != "魔女兵器邮箱验证码" ||
					!strings.Contains(input.Text, code) || !strings.Contains(input.HTML, ">"+code+"</td>") {
					t.Error("transactional send payload invalid")
				}
				data, _ := json.Marshal(map[string]any{"success": true, "errors": []any{}, "result": map[string]any{
					"message_id": test.messageID, "delivered": []string{test.delivered}, "queued": []string{test.queued}, "metadata": "private-response",
				}})
				return emailTestCFResponse(string(data)), nil
			})}
			err := config.sendCode(context.Background(), recipient, code)
			if test.wantStatus == "" {
				if err == nil || output.Len() != 0 {
					t.Fatal("unaccepted recipient was logged as accepted")
				}
				return
			}
			if err != nil || !strings.Contains(output.String(), "status="+test.wantStatus) ||
				!strings.Contains(output.String(), "message_id="+fmt.Sprintf("%q", test.wantID)) {
				t.Fatal("safe acceptance correlation was lost")
			}
			for _, sensitive := range []string{recipient, code, token, "private-response", "metadata", "Bearer"} {
				if strings.Contains(output.String(), sensitive) {
					t.Fatalf("acceptance log exposed %q", sensitive)
				}
			}
		})
	}
}

type emailTestMail struct {
	mu              sync.Mutex
	roles           map[string]string
	codes           map[string]string
	sends           int
	revision        int
	rewards         map[string]string
	digest          map[string]string
	failAfterCommit bool
}

func (model *emailTestMail) installCF(t *testing.T, a *app) {
	t.Helper()
	a.emailVerification.client.Transport = emailTestTransport(func(r *http.Request) (*http.Response, error) {
		if r.Method != "POST" || r.URL.Scheme != "https" || r.URL.Host != "api.cloudflare.com" ||
			r.URL.Path != "/client/v4/accounts/"+strings.Repeat("a", 32)+"/email/sending/send" ||
			r.Header.Get("Authorization") != "Bearer "+a.emailVerification.token {
			t.Error("wrong Cloudflare send transport")
		}
		var input struct {
			To      []string `json:"to"`
			From    string   `json:"from"`
			Subject string   `json:"subject"`
			Text    string   `json:"text"`
			HTML    string   `json:"html"`
		}
		if json.NewDecoder(r.Body).Decode(&input) != nil || len(input.To) != 1 || input.From != "noreply@example.com" || input.Subject == "" {
			return nil, errors.New("synthetic request rejected")
		}
		code := regexp.MustCompile(`[0-9]{6}`).FindString(input.Text)
		if code == "" {
			t.Error("mail lacked a six-digit code")
		}
		if !strings.Contains(input.HTML, ">"+code+"</td>") || strings.Contains(input.Subject, code) ||
			!strings.Contains(input.HTML, `href="https://www.witchweapon.wiki/"`) {
			t.Error("mail HTML, subject or wiki link invalid")
		}
		model.mu.Lock()
		model.codes[input.To[0]] = code
		model.sends++
		model.mu.Unlock()
		data, _ := json.Marshal(map[string]any{"success": true, "errors": []any{}, "result": map[string]any{"queued": []string{input.To[0]}, "delivered": []string{}}})
		return emailTestCFResponse(string(data)), nil
	})
}

func (model *emailTestMail) handler(t *testing.T, a *app) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		model.mu.Lock()
		defer model.mu.Unlock()
		id := r.Header.Get("X-WW-Account-ID")
		if model.roles[id] == "" || r.Header.Get("X-WW-Proxy-Secret") != testProxySecret || r.Header.Get("Authorization") != "" {
			w.WriteHeader(403)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/__role":
			if r.Method != "GET" {
				t.Error("role summary mutated")
			}
			fmt.Fprintf(w, `{"version":1,"exists":true,"roleId":%q,"name":"原版角色"}`, model.roles[id])
		case "/__admin/state":
			fmt.Fprintf(w, `{"version":1,"revision":%d,"name":"原版角色","gold":0,"roleCreated":true,"roleId":%q,"exp":0,"wins":0,"attempts":0,"stars":0,"mazeWins":0,"mazeAttempts":0,"mazeStars":0,"mazeRound":1,"active":false}`, model.revision, model.roles[id])
		case "/__admin/mail/send":
			if r.Method != "POST" || r.ParseForm() != nil {
				t.Error("bad reward method")
				w.WriteHeader(400)
				return
			}
			requestID := r.Form.Get("requestId")
			outbox := a.store.emailVerification(id)
			if !outbox.Verified || outbox.RewardRequestID != requestID {
				t.Error("reward was sent before a durable verified outbox")
			}
			var attachments []adminMailAttachment
			if json.Unmarshal([]byte(r.Form.Get("attachments")), &attachments) != nil || len(attachments) != 1 || attachments[0] != (adminMailAttachment{Type: 3, ID: 40350003, Count: 100}) {
				t.Error("wrong email verification gift")
			}
			digest := r.Form.Get("reason") + r.Form.Get("title") + r.Form.Get("sender") + r.Form.Get("content") + r.Form.Get("attachments")
			if previous := model.rewards[requestID]; previous != "" {
				if model.digest[requestID] != digest {
					t.Error("retry changed immutable reward content")
					w.WriteHeader(409)
					return
				}
				fmt.Fprintf(w, `{"id":%q,"revision":"%d","duplicate":true}`, previous, model.revision)
				return
			}
			if r.Form.Get("expectedRevision") != fmt.Sprint(model.revision) {
				w.WriteHeader(409)
				return
			}
			model.rewards[requestID] = "123456789"
			model.digest[requestID] = digest
			model.revision++
			if model.failAfterCommit {
				model.failAfterCommit = false
				w.WriteHeader(500)
				return
			}
			fmt.Fprintf(w, `{"id":"123456789","revision":"%d","duplicate":false}`, model.revision)
		default:
			t.Error("unexpected Java request")
			w.WriteHeader(404)
		}
	})
}

func emailTestFixture(t *testing.T) (*app, authResponse, *emailTestMail, string, string) {
	t.Helper()
	a, dir, stories := fixture(t)
	user := registerTest(t, a, "verification-player@example.com")
	configureEmailTest(t, a)
	model := &emailTestMail{roles: map[string]string{user.Player.ID: "87123456789"}, codes: make(map[string]string), revision: 1, rewards: make(map[string]string), digest: make(map[string]string)}
	java := httptest.NewServer(model.handler(t, a))
	t.Cleanup(java.Close)
	if err := a.configureLegacyProxy(java.URL, testProxySecret); err != nil {
		t.Fatal(err)
	}
	model.installCF(t, a)
	return a, user, model, dir, stories
}

func emailTestRequest(t *testing.T, a *app, token, action, body string, status int) emailVerificationView {
	t.Helper()
	method := "POST"
	if action == "status" {
		method = "GET"
	}
	w := request(a, method, "/api/v1/legacy/role/email/"+action, token, body)
	wantStatus(t, w, status)
	var view emailVerificationView
	if json.Unmarshal(w.Body.Bytes(), &view) != nil || view.RoleID != "87123456789" || view.MaskedEmail != "v***@example.com" || view.Message == "" {
		t.Fatal("email response contract invalid")
	}
	return view
}

func TestEmailVerificationCodeAndRewardEndToEnd(t *testing.T) {
	a, user, model, _, _ := emailTestFixture(t)
	wantStatus(t, request(a, "POST", "/api/v1/legacy/role/email/send", "", "{}"), 401)
	if view := emailTestRequest(t, a, user.Token, "status", "", 200); view.Verified || !view.ServiceReady {
		t.Fatal("incorrect initial email state")
	}
	if view := emailTestRequest(t, a, user.Token, "send", "{}", 200); view.Verified || view.CooldownSeconds < 1 || view.SendAllowed || view.SendBlockedReason != "day_account" ||
		!strings.Contains(view.Message, "已提交发送") || strings.Contains(view.Message, "已发送到") {
		t.Fatal("send confirmed an unverified email")
	}
	model.mu.Lock()
	code := model.codes[user.Player.Email]
	model.mu.Unlock()
	registry := mustRead(t, a.store.emailVerificationFile)
	storedChallenge := a.store.emailVerification(user.Player.ID)
	if bytes.Contains(registry, []byte(`"code"`)) || len(storedChallenge.CodeHash) != 64 || storedChallenge.CodeHash == code {
		t.Fatal("plaintext email code reached the registry")
	}
	bad := "000000"
	if code == bad {
		bad = "111111"
	}
	emailTestRequest(t, a, user.Token, "verify", `{"code":"`+bad+`"}`, 400)
	model.mu.Lock()
	count := len(model.rewards)
	model.mu.Unlock()
	if count != 0 {
		t.Fatal("incorrect email code received a reward")
	}
	view := emailTestRequest(t, a, user.Token, "verify", `{"code":"`+code+`"}`, 200)
	if !view.Verified || !view.RewardSent {
		t.Fatal("verified email did not confirm its reward")
	}
	player, _ := a.store.player(user.Player.ID)
	if !player.EmailVerified || player.Email != user.Player.Email {
		t.Fatal("player projection lost verification or changed login email")
	}
	items, _, _ := a.store.adminAccounts("", "", 100)
	if len(items) != 1 || !items[0].EmailVerified {
		t.Fatal("admin projection lost email verification")
	}
	accountSave := mustRead(t, a.store.file)
	if bytes.Contains(accountSave, []byte("emailVerified")) {
		t.Fatal("verification changed legacy account save schema")
	}
	before := mustRead(t, a.store.emailVerificationFile)
	emailTestRequest(t, a, user.Token, "status", "", 200)
	if !bytes.Equal(before, mustRead(t, a.store.emailVerificationFile)) {
		t.Fatal("status query wrote the registry")
	}
	emailTestRequest(t, a, user.Token, "verify", `{"code":""}`, 200)
	model.mu.Lock()
	count = len(model.rewards)
	sends := model.sends
	model.mu.Unlock()
	if count != 1 || sends != 1 {
		t.Fatal("email or reward was resent after completed verification")
	}
}

func TestEmailRewardRecoversAcrossResponseLossAndRestart(t *testing.T) {
	a, user, model, dir, stories := emailTestFixture(t)
	model.failAfterCommit = true
	emailTestRequest(t, a, user.Token, "send", "{}", 200)
	model.mu.Lock()
	code := model.codes[user.Player.Email]
	model.mu.Unlock()
	view := emailTestRequest(t, a, user.Token, "verify", `{"code":"`+code+`"}`, 503)
	if !view.Verified || view.RewardSent {
		t.Fatal("uncertain reward lost confirmed verification")
	}
	requestID := a.store.emailVerification(user.Player.ID).RewardRequestID
	before := mustRead(t, a.store.emailVerificationFile)
	emailTestRequest(t, a, user.Token, "status", "", 200)
	if !bytes.Equal(before, mustRead(t, a.store.emailVerificationFile)) {
		t.Fatal("status retried a pending reward")
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	configureEmailTest(t, b)
	if err := b.configureLegacyProxy(a.legacy.upstream.String(), testProxySecret); err != nil {
		t.Fatal(err)
	}
	login, err := b.issueAuth(user.Player.ID, false)
	if err != nil {
		t.Fatal(err)
	}
	if !login.Player.EmailVerified {
		t.Fatal("restart lost the verified player projection")
	}
	view = emailTestRequest(t, b, login.Token, "verify", `{"code":""}`, 200)
	if !view.Verified || !view.RewardSent || b.store.emailVerification(user.Player.ID).RewardRequestID != requestID {
		t.Fatal("restart did not recover the same reward outbox")
	}
	model.mu.Lock()
	count := len(model.rewards)
	model.mu.Unlock()
	if count != 1 {
		t.Fatal("response loss produced a duplicate reward")
	}
}

func TestEmailCodeExpiresAndAttemptLimitSurvivesRestart(t *testing.T) {
	a, user, model, dir, stories := emailTestFixture(t)
	emailTestRequest(t, a, user.Token, "send", "{}", 200)
	model.mu.Lock()
	code := model.codes[user.Player.Email]
	model.mu.Unlock()
	bad := "000000"
	if bad == code {
		bad = "111111"
	}
	for i := 0; i < emailCodeAttempts; i++ {
		emailTestRequest(t, a, user.Token, "verify", `{"code":"`+bad+`"}`, 400)
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	configureEmailTest(t, b)
	if err := b.configureLegacyProxy(a.legacy.upstream.String(), testProxySecret); err != nil {
		t.Fatal(err)
	}
	login, err := b.issueAuth(user.Player.ID, false)
	if err != nil {
		t.Fatal(err)
	}
	emailTestRequest(t, b, login.Token, "verify", `{"code":"`+code+`"}`, 400)
	if record := b.store.emailVerification(user.Player.ID); record.Verified || record.Attempts != emailCodeAttempts || record.CodeActive {
		t.Fatal("restart bypassed code attempt limit")
	}
	// Exercise exact expiry without waiting and without any external request.
	now := time.Now().Add(24 * time.Hour)
	generated, nonce, err := b.store.prepareEmailCode(user.Player.ID, user.Player.Email, "87123456789", "192.0.2.1", b.emailVerification.key[:], now, b.emailVerification.limits)
	if err != nil {
		t.Fatal(err)
	}
	if err := b.store.finishEmailCode(user.Player.ID, nonce, true); err != nil {
		t.Fatal(err)
	}
	if _, err := b.store.verifyEmailCode(user.Player.ID, user.Player.Email, "87123456789", generated, b.emailVerification.key[:], now.Add(emailCodeLifetime)); err == nil {
		t.Fatal("expired email code was accepted")
	}
}

func TestEmailPersistentRateLimitsAndConcurrentReservation(t *testing.T) {
	a, dir, stories := fixture(t)
	user := registerTest(t, a, "limits@example.com")
	key := bytes.Repeat([]byte{7}, 32)
	limits := emailRateLimits{GlobalHour: 100, GlobalDay: 500, Monthly: 3000, MonthResetDay: 1}
	now := time.Date(2026, 10, 2, 15, 59, 59, 0, time.UTC)
	var wg sync.WaitGroup
	errs := make(chan error, 12)
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _, err := a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.7", key, now, limits)
			errs <- err
		}()
	}
	wg.Wait()
	close(errs)
	success := 0
	for err := range errs {
		if err == nil {
			success++
		}
	}
	if success != 1 {
		t.Fatal("concurrent sends bypassed persistent cooldown")
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	if _, _, err := b.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "203.0.113.9", key, now, limits); err == nil {
		t.Fatal("restart or another IP bypassed account day limit")
	}
	other := registerTest(t, b, "global-limits@example.com")
	if _, _, err := b.store.prepareEmailCode(other.Player.ID, other.Player.Email, "43", "::ffff:198.51.100.7", key, now, limits); err == nil {
		t.Fatal("restart or mapped IPv6 bypassed IP day limit")
	}
	if bytes.Contains(mustRead(t, b.store.emailVerificationFile), []byte("198.51.100.7")) {
		t.Fatal("IP was persisted in plaintext")
	}
	if _, _, err := b.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.7", key, now.Add(time.Second), limits); err != nil {
		t.Fatal("Beijing midnight did not release account and IP", err)
	}
	if flow := b.store.emailSendRestriction(user.Player.ID, "198.51.100.7", key, now.Add(time.Second), limits); flow == nil || flow.RetrySeconds != 86400 {
		t.Fatal("new day did not return exact next midnight wait")
	}
}

func TestCloudflareOnlyActivatesCodesForAcceptedRecipients(t *testing.T) {
	for _, body := range []string{
		`{"success":false,"errors":[],"result":{"delivered":["verification-player@example.com"]}}`,
		`{"success":true,"errors":[],"result":{"queued":["someone-else@example.com"]}}`,
		`{"success":true,"errors":[],"result":{"delivered":[],"queued":[]}}`,
		`{"success":true,"errors":[],"result":{"delivered":["verification-player@example.com"],"suppressed_recipients":["verification-player@example.com"]}}`,
		`{"success":true,"errors":[{"message":"synthetic-secret-error"}],"result":{"queued":["verification-player@example.com"]}}`,
	} {
		t.Run(fmt.Sprint(len(body)), func(t *testing.T) {
			a, user, _, _, _ := emailTestFixture(t)
			a.emailVerification.client.Transport = emailTestTransport(func(*http.Request) (*http.Response, error) { return emailTestCFResponse(body), nil })
			view := emailTestRequest(t, a, user.Token, "send", "{}", 503)
			if view.Verified || strings.Contains(view.Message, "synthetic-secret-error") {
				t.Fatal("Cloudflare failure leaked data or verified email")
			}
			if record := a.store.emailVerification(user.Player.ID); record.CodeActive || record.CodeHash != "" || record.Day.Count != 1 {
				t.Fatal("failed send activated a code or restored quota")
			}
		})
	}
}

func TestEmailConfigurationTokenRotationAndFilePrecedence(t *testing.T) {
	a, _, _ := fixture(t)
	configureEmailTest(t, a)
	key := a.emailVerification.key
	t.Setenv("WW_CF_EMAIL_API_TOKEN", strings.Repeat("rotated-token-", 3))
	if err := a.configureEmailVerificationFromEnv(); err != nil {
		t.Fatal(err)
	}
	if a.emailVerification.key != key {
		t.Fatal("Cloudflare token rotation changed the code HMAC key")
	}
	tokenPath := filepath.Join(t.TempDir(), "synthetic-email-token")
	if err := os.WriteFile(tokenPath, []byte(strings.Repeat("file-token-", 4)), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("WW_CF_EMAIL_API_TOKEN_FILE", tokenPath)
	if err := a.configureEmailVerificationFromEnv(); err != nil {
		t.Fatal(err)
	}
	if a.emailVerification.token != strings.Repeat("file-token-", 4) {
		t.Fatal("configured token file did not take precedence")
	}
	t.Setenv("WW_CF_EMAIL_API_TOKEN_FILE", filepath.Join(t.TempDir(), "missing-secret"))
	if err := a.configureEmailVerificationFromEnv(); err == nil {
		t.Fatal("missing token file fell back to the environment")
	}
}

func TestEmailDisabledServiceAndUntrustedParameters(t *testing.T) {
	a, user, model, _, _ := emailTestFixture(t)
	a.emailVerification = nil
	if view := emailTestRequest(t, a, user.Token, "status", "", 200); view.ServiceReady || view.Verified {
		t.Fatal("disabled service reported ready or verified")
	}
	emailTestRequest(t, a, user.Token, "send", "{}", 503)
	for _, tc := range []struct{ method, path, body string }{
		{"POST", "/role/email/send", `{"email":"attacker@example.com"}`},
		{"POST", "/role/email/verify", `{"roleId":"999"}`},
		{"GET", "/role/email/status?email=attacker@example.com", ""},
	} {
		w := request(a, tc.method, "/api/v1/legacy"+tc.path, user.Token, tc.body)
		wantStatus(t, w, 400)
		var fields map[string]json.RawMessage
		if json.Unmarshal(w.Body.Bytes(), &fields) != nil || len(fields) != 9 {
			t.Fatal("business error lost the email response contract")
		}
	}
	if _, err := os.Stat(a.store.emailVerificationFile); !os.IsNotExist(err) {
		t.Fatal("read-only or rejected request created verification state")
	}
	model.mu.Lock()
	defer model.mu.Unlock()
	if model.sends != 0 || len(model.rewards) != 0 {
		t.Fatal("disabled service or untrusted parameters triggered an external send")
	}
}
