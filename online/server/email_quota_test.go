package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestEmailIPTrustAndNormalization(t *testing.T) {
	key := bytes.Repeat([]byte{9}, 32)
	for _, test := range []struct{ peer, header, want string }{
		{"127.0.0.1:32000", "::ffff:198.51.100.9", "198.51.100.9"},
		{"[::ffff:127.0.0.1]:32000", "198.51.100.9", "198.51.100.9"},
		{"[::ffff:203.0.113.4]:32000", "198.51.100.9", "203.0.113.4"},
		{"203.0.113.4:32000", "198.51.100.9", "203.0.113.4"},
		{"[::1]:32000", "2001:0db8:0:0:0:0:0:7", "2001:db8::7"},
	} {
		r := httptest.NewRequest("POST", "/role/email/send", nil)
		r.RemoteAddr = test.peer
		r.Header.Set("X-Real-IP", test.header)
		if got := authRateKey(r); got != test.want || emailIPHash(key, got) != emailIPHash(key, test.want) {
			t.Fatal("mail IP trust or normalization diverged from authentication")
		}
	}
	if emailIPHash(key, "198.51.100.9") != emailIPHash(key, "::ffff:198.51.100.9") || emailIPHash(key, "invalid") != "" {
		t.Fatal("IP hash accepted an invalid address or split a mapped address")
	}
}

func TestEmailConcurrentAccountsCannotReuseIPDay(t *testing.T) {
	a, _, _ := fixture(t)
	users := []authResponse{registerTest(t, a, "ip-first@example.com"), registerTest(t, a, "ip-second@example.com")}
	key := bytes.Repeat([]byte{9}, 32)
	limits := emailRateLimits{GlobalHour: 100, GlobalDay: 500, Monthly: 3000, MonthResetDay: 1}
	now := time.Date(2026, 10, 2, 8, 0, 0, 0, time.UTC)
	var wg sync.WaitGroup
	errs := make(chan error, 2)
	for i, user := range users {
		wg.Add(1)
		go func(i int, user authResponse) {
			defer wg.Done()
			ip := "198.51.100.7"
			if i == 1 {
				ip = "::ffff:198.51.100.7"
			}
			_, _, err := a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", ip, key, now, limits)
			errs <- err
		}(i, user)
	}
	wg.Wait()
	close(errs)
	success := 0
	for err := range errs {
		if err == nil {
			success++
		} else {
			var flow *emailFlowError
			if !errors.As(err, &flow) || flow.Reason != "day_ip" {
				t.Fatal("unexpected shared IP rejection", err)
			}
		}
	}
	if success != 1 || len(a.store.emailVerifications.IPDays) != 1 || a.store.emailVerifications.GlobalMonth.Count != 1 {
		t.Fatal("concurrent different accounts bypassed the IP reservation")
	}
}

func TestEmailMonthlyLimitAndReset(t *testing.T) {
	a, dir, stories := fixture(t)
	user := registerTest(t, a, "monthly@example.com")
	key := bytes.Repeat([]byte{8}, 32)
	limits := emailRateLimits{GlobalHour: 100, GlobalDay: 500, Monthly: 2, MonthResetDay: 1}
	now := time.Date(2026, 10, 1, 18, 0, 0, 0, time.UTC)
	for _, at := range []time.Time{now, now.Add(24 * time.Hour)} {
		if _, _, err := a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.7", key, at, limits); err != nil {
			t.Fatal(err)
		}
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	blocked := now.Add(48 * time.Hour)
	before := mustRead(t, b.store.emailVerificationFile)
	flow := b.store.emailSendRestriction(user.Player.ID, "198.51.100.7", key, blocked, limits)
	_, end := emailMonthBounds(blocked, 1)
	if flow == nil || flow.Reason != "month" || flow.Message != emailMonthlyQuotaMessage || flow.RetrySeconds != int(end-blocked.Unix()) {
		t.Fatal("persistent monthly quota did not clearly wait for next month")
	}
	if !bytes.Equal(before, mustRead(t, b.store.emailVerificationFile)) {
		t.Fatal("quota status mutated registry")
	}
	if _, _, err := b.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "203.0.113.7", key, blocked, limits); err == nil {
		t.Fatal("another IP bypassed monthly quota")
	}
	nextMonth := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	if _, _, err := b.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.7", key, nextMonth, limits); err != nil {
		t.Fatal("UTC month boundary did not reset quota", err)
	}
	if b.store.emailVerifications.GlobalMonth.Count != 1 {
		t.Fatal("new month retained the exhausted count")
	}
	start, end := emailMonthBounds(time.Date(2026, 2, 28, 0, 0, 0, 0, time.UTC), 31)
	if time.Unix(start, 0).UTC().Day() != 28 || time.Unix(end, 0).UTC().Day() != 31 {
		t.Fatal("billing reset day did not clamp a short month")
	}
}

func TestEmailMonthlyUTCResetDoesNotReleaseAtBeijingMidnight(t *testing.T) {
	a, _, _ := fixture(t)
	user := registerTest(t, a, "utc-monthly@example.com")
	key := bytes.Repeat([]byte{8}, 32)
	limits := emailRateLimits{GlobalHour: 100, GlobalDay: 500, Monthly: 1, MonthResetDay: 19}
	sent := time.Date(2026, 10, 19, 0, 0, 0, 0, time.UTC)
	if _, _, err := a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.7", key, sent, limits); err != nil {
		t.Fatal(err)
	}
	beijingMidnight := time.Date(2026, 11, 19, 0, 0, 0, 0, emailBeijing)
	flow := a.store.emailSendRestriction(user.Player.ID, "198.51.100.7", key, beijingMidnight, limits)
	if flow == nil || flow.Reason != "month" || flow.RetrySeconds != 8*3600 {
		t.Fatal("Beijing midnight prematurely reset UTC billing quota")
	}
	if _, _, err := a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.7", key, beijingMidnight.Add(8*time.Hour-time.Second), limits); err == nil {
		t.Fatal("quota reopened before UTC billing boundary")
	}
	if _, _, err := a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", "198.51.100.7", key, beijingMidnight.Add(8*time.Hour), limits); err != nil {
		t.Fatal("UTC billing midnight did not reset quota", err)
	}
	if a.store.emailVerifications.GlobalMonth.Start != time.Date(2026, 11, 19, 0, 0, 0, 0, time.UTC).Unix() || a.store.emailVerifications.GlobalMonth.Count != 1 {
		t.Fatal("UTC monthly ledger has the wrong boundary or count")
	}
	if err := validateEmailVerificationState(a.store.emailVerifications); err != nil {
		t.Fatal("UTC billing state cannot restart", err)
	}
	if err := a.store.blockEmailMonth(beijingMidnight.Add(8*time.Hour), 19); err != nil {
		t.Fatal(err)
	}
	if until := a.store.emailVerifications.MonthlyBlockedUntil; until != time.Date(2026, 12, 19, 0, 0, 0, 0, time.UTC).Unix() {
		t.Fatal("provider monthly block is not aligned to UTC billing")
	}
	if err := validateEmailVerificationState(a.store.emailVerifications); err != nil {
		t.Fatal("UTC monthly block cannot restart", err)
	}
}

func TestEmailNewChallengeRemainsValidForThirtyMinutes(t *testing.T) {
	a, _, _ := fixture(t)
	users := []authResponse{registerTest(t, a, "thirty-valid@example.com"), registerTest(t, a, "thirty-expired@example.com")}
	key := bytes.Repeat([]byte{8}, 32)
	limits := emailRateLimits{GlobalHour: 100, GlobalDay: 500, Monthly: 3000, MonthResetDay: 1}
	now := time.Date(2026, 10, 2, 8, 0, 0, 0, time.UTC)
	for i, user := range users {
		ip := "198.51.100.1"
		if i == 1 {
			ip = "198.51.100.2"
		}
		code, nonce, err := a.store.prepareEmailCode(user.Player.ID, user.Player.Email, "42", ip, key, now, limits)
		if err != nil {
			t.Fatal(err)
		}
		if err := a.store.finishEmailCode(user.Player.ID, nonce, true); err != nil {
			t.Fatal(err)
		}
		if record := a.store.emailVerification(user.Player.ID); record.ExpiresAt != now.Unix()+1800 {
			t.Fatal("new challenge did not receive exactly thirty minutes")
		}
		at := now.Add(1799 * time.Second)
		if i == 1 {
			at = now.Add(1800 * time.Second)
		}
		_, err = a.store.verifyEmailCode(user.Player.ID, user.Player.Email, "42", code, key, at)
		if (i == 0 && err != nil) || (i == 1 && err == nil) {
			t.Fatal("thirty-minute acceptance/expiry boundary was incorrect", err)
		}
	}
}

func TestEmailMonthlyBlockedSendStillAllowsVerification(t *testing.T) {
	a, user, model, _, _ := emailTestFixture(t)
	a.emailVerification.limits.Monthly = 1
	emailTestRequest(t, a, user.Token, "send", "{}", 200)
	before := mustRead(t, a.store.emailVerificationFile)
	view := emailTestRequest(t, a, user.Token, "status", "", 200)
	if view.SendAllowed || view.SendBlockedReason != "month" || view.Message != emailMonthlyQuotaMessage || !view.ServiceReady || view.CooldownSeconds < 1 {
		t.Fatal("status did not expose monthly send-only restriction")
	}
	if !bytes.Equal(before, mustRead(t, a.store.emailVerificationFile)) {
		t.Fatal("monthly status wrote state")
	}
	emailTestRequest(t, a, user.Token, "send", "{}", 429)
	model.mu.Lock()
	code := model.codes[user.Player.Email]
	model.mu.Unlock()
	view = emailTestRequest(t, a, user.Token, "verify", `{"code":"`+code+`"}`, 200)
	if !view.Verified || !view.RewardSent {
		t.Fatal("send quota blocked an existing code or reward")
	}
}

func TestEmailProviderMonthlyQuotaIsDistinctFromThrottling(t *testing.T) {
	for _, test := range []struct {
		message string
		monthly bool
	}{
		{"email.sending.error.monthly_quota_exceeded", true},
		{"Monthly sending quota exhausted", true},
		{"email.sending.error.throttled", false},
		{"email.sending.error.daily_limit_exceeded", false},
		{"email.sending.error.authentication.forbidden", false},
	} {
		t.Run(test.message, func(t *testing.T) {
			a, user, _, dir, stories := emailTestFixture(t)
			a.emailVerification.client.Transport = emailTestTransport(func(*http.Request) (*http.Response, error) {
				data, _ := json.Marshal(map[string]any{"success": false, "errors": []any{map[string]any{"code": 10004, "message": test.message}}, "result": nil})
				response := emailTestCFResponse(string(data))
				response.StatusCode = 429
				return response, nil
			})
			status := 503
			if test.monthly {
				status = 429
			}
			view := emailTestRequest(t, a, user.Token, "send", "{}", status)
			if test.monthly {
				if view.Message != emailMonthlyQuotaMessage || view.SendBlockedReason != "month" || a.store.emailVerifications.MonthlyBlockedUntil <= a.now().Unix() {
					t.Fatal("explicit provider monthly quota was not persisted")
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
				if flow := b.store.emailSendRestriction(user.Player.ID, "203.0.113.5", b.emailVerification.key[:], a.now(), b.emailVerification.limits); flow == nil || flow.Reason != "month" {
					t.Fatal("restart bypassed provider monthly block")
				}
			} else if view.SendBlockedReason == "month" || strings.Contains(view.Message, "下月") || a.store.emailVerifications.MonthlyBlockedUntil != 0 {
				t.Fatal("ordinary throttling was mislabeled as monthly exhaustion")
			}
		})
	}
}

func TestEmailVersionOneMigrationPreservesOldCodeExpiry(t *testing.T) {
	a, dir, stories := fixture(t)
	users := []authResponse{registerTest(t, a, "old-valid@example.com"), registerTest(t, a, "old-expired@example.com")}
	configureEmailTest(t, a)
	key := a.emailVerification.key
	last := time.Date(2026, 10, 2, 18, 0, 0, 0, time.UTC)
	state := emailVerificationState{Version: 1, GlobalHour: emailRateWindow{Start: last.Unix() / 3600 * 3600, Count: 2}, GlobalDay: emailRateWindow{Start: last.Unix() / 86400 * 86400, Count: 2}, Users: make(map[string]emailVerificationRecord)}
	const nonce, code = "0123456789012345678901", "012345"
	for _, user := range users {
		state.Users[user.Player.ID] = emailVerificationRecord{Email: user.Player.Email, RoleID: "42", CodeHash: emailCodeHash(key[:], user.Player.ID, user.Player.Email, nonce, code), Nonce: nonce, ExpiresAt: last.Unix() + 600, CodeActive: true, LastSendAt: last.Unix(), Hour: state.GlobalHour, Day: state.GlobalDay}
	}
	if err := persistJSON(a.store.emailVerificationFile, state); err != nil {
		t.Fatal(err)
	}
	before := mustRead(t, a.store.emailVerificationFile)
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal("old registry prevented startup", err)
	}
	defer b.Close()
	configureEmailTest(t, b)
	if !bytes.Equal(before, mustRead(t, b.store.emailVerificationFile)) {
		t.Fatal("loading migration rewrote registry before a mutation")
	}
	if b.store.emailVerifications.Version != 2 || len(b.store.emailVerifications.IPDays) != 0 {
		t.Fatal("legacy migration fabricated IP history")
	}
	if flow := b.store.emailSendRestriction(users[0].Player.ID, "198.51.100.7", key[:], last.Add(time.Second), b.emailVerification.limits); flow == nil || flow.Reason != "day_account" {
		t.Fatal("legacy LastSendAt escaped the Beijing day limit")
	}
	if record := b.store.emailVerification(users[0].Player.ID); record.ExpiresAt != last.Unix()+600 {
		t.Fatal("migration extended an old challenge")
	}
	if _, err := b.store.verifyEmailCode(users[1].Player.ID, users[1].Player.Email, "42", code, key[:], last.Add(600*time.Second)); err == nil {
		t.Fatal("old 10-minute code gained the new lifetime")
	}
	if _, err := b.store.verifyEmailCode(users[0].Player.ID, users[0].Player.Email, "42", code, key[:], last.Add(599*time.Second)); err != nil {
		t.Fatal("old unexpired code was invalidated", err)
	}
	if err := validateEmailVerificationState(b.store.emailVerifications); err != nil {
		t.Fatal("migrated registry cannot restart", err)
	}
}
