package main

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"os"
	"strings"
	"time"
)

// The sidecar preserves rollback compatibility with state.json and the
// existing mailbox-verification registry. No code or password is stored.
type passwordRecoveryState struct {
	Version int                               `json:"version"`
	Records map[string]passwordRecoveryRecord `json:"records"`
}

type passwordRecoveryRecord struct {
	UserID           string `json:"userId,omitempty"`
	Email            string `json:"email,omitempty"`
	CredentialDigest string `json:"credentialDigest,omitempty"`
	CodeHash         string `json:"codeHash,omitempty"`
	Nonce            string `json:"nonce,omitempty"`
	ExpiresAt        int64  `json:"expiresAt,omitempty"`
	Active           bool   `json:"active"`
	Attempts         int    `json:"attempts"`
	LastSendAt       int64  `json:"lastSendAt"`
}

var errInvalidRecoveryCode = errors.New("invalid password recovery code")

func (s *store) loadPasswordRecoveries() error {
	f, err := os.Open(s.passwordRecoveryFile)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer f.Close()
	var state passwordRecoveryState
	dec := json.NewDecoder(io.LimitReader(f, 64<<20))
	dec.DisallowUnknownFields()
	if dec.Decode(&state) != nil || dec.Decode(new(any)) != io.EOF || state.Version != 1 || state.Records == nil {
		return errors.New("invalid password recovery registry")
	}
	for key, r := range state.Records {
		if r.LastSendAt <= 0 || r.Attempts < 0 || r.Attempts > emailCodeAttempts || r.Active && r.Attempts >= emailCodeAttempts {
			return errors.New("invalid password recovery record")
		}
		if r.UserID == "" {
			digest, err := hex.DecodeString(strings.TrimPrefix(key, "missing:"))
			if !strings.HasPrefix(key, "missing:") || err != nil || len(digest) != 32 || hex.EncodeToString(digest) != strings.TrimPrefix(key, "missing:") || r.Email != "" || r.CodeHash != "" {
				return errors.New("invalid anonymous recovery record")
			}
		} else if key != "account:"+r.UserID || len(r.UserID) > 128 || !validEmail(r.Email) || r.Email != normalizeEmail(r.Email) {
			return errors.New("invalid recovery identity")
		}
		if r.CodeHash != "" {
			if !canonicalHash(r.CodeHash) || !canonicalHash(r.CredentialDigest) || len(r.Nonce) != 22 || r.ExpiresAt-r.LastSendAt != int64(emailCodeLifetime/time.Second) {
				return errors.New("invalid recovery challenge")
			}
		} else if r.Active || r.Nonce != "" || r.CredentialDigest != "" || r.ExpiresAt != 0 {
			return errors.New("invalid empty recovery challenge")
		}
	}
	s.passwordRecoveries = state
	return nil
}

func canonicalHash(value string) bool {
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == 32 && hex.EncodeToString(decoded) == value
}

func (s *store) copyPasswordRecoveries() passwordRecoveryState {
	next := passwordRecoveryState{Version: 1, Records: make(map[string]passwordRecoveryRecord, len(s.passwordRecoveries.Records)+1)}
	for key, record := range s.passwordRecoveries.Records {
		next.Records[key] = record
	}
	return next
}

func (s *store) persistPasswordRecoveries(next passwordRecoveryState) error {
	if err := persistJSON(s.passwordRecoveryFile, next); err != nil {
		return err
	}
	s.passwordRecoveries = next
	return nil
}

func recoveryHash(key []byte, parts ...string) string {
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write([]byte("witchweapon-password-recovery-v1\x00"))
	for _, part := range parts {
		_, _ = mac.Write([]byte(part))
		_, _ = mac.Write([]byte{0})
	}
	return hex.EncodeToString(mac.Sum(nil))
}

// Called under s.mu. Sharing counters does not overwrite Verified, rewards or
// any active binding challenge. A recovery reservation also blocks binding
// email sends for the same account until the next Beijing day.
func (s *store) sharedEmailSendRestriction(id, ipHash string, now time.Time, limits emailRateLimits) *emailFlowError {
	state := s.emailVerifications
	record := state.Users[id]
	if recovery := s.passwordRecoveries.Records["account:"+id]; recovery.LastSendAt > record.LastSendAt {
		record.LastSendAt = recovery.LastSendAt
	}
	state.Users = map[string]emailVerificationRecord{id: record}
	return emailSendRestriction(state, id, ipHash, now, limits)
}

func (s *store) preparePasswordCode(email, ip string, key []byte, now time.Time, limits emailRateLimits) (string, string, string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	id := s.emails[email]
	recordKey := "account:" + id
	if id == "" {
		recordKey = "missing:" + recoveryHash(key, "address", email)
	}
	old := s.passwordRecoveries.Records[recordKey]
	ipHash := emailIPHash(key, ip)
	if flow := s.sharedEmailSendRestriction(id, ipHash, now, limits); flow != nil {
		return "", "", "", flow
	}
	if now.Unix() < old.LastSendAt {
		return "", "", "", &emailFlowError{Status: 503, Reason: "temporary", Message: "邮箱服务时间暂时异常，请稍后重试。"}
	}
	if cooldown := emailCooldown(emailVerificationRecord{LastSendAt: old.LastSendAt}, now.Unix()); cooldown > 0 {
		return "", "", "", &emailFlowError{Status: 429, Reason: "day_account", RetrySeconds: cooldown}
	}
	next := s.copyPasswordRecoveries()
	day := emailDayStart(now.Unix())
	// Synthetic addresses are retained only for today's rate limit. The
	// existing global hourly request limiter bounds their allocation.
	for k, r := range next.Records {
		if r.UserID == "" && r.LastSendAt < day {
			delete(next.Records, k)
		}
	}
	record := passwordRecoveryRecord{UserID: id, LastSendAt: now.Unix()}
	code, nonce := "", ""
	if id != "" {
		account := s.state.Users[id]
		if account == nil || account.Email != email {
			return "", "", "", errors.New("recovery identity changed")
		}
		number, err := rand.Int(rand.Reader, big.NewInt(1000000))
		if err != nil {
			return "", "", "", err
		}
		code = fmt.Sprintf("%06d", number.Int64())
		nonce, err = randomID(16)
		if err != nil {
			return "", "", "", err
		}
		record.Email, record.Nonce = email, nonce
		record.CredentialDigest = hex.EncodeToString(account.Hash)
		record.CodeHash = recoveryHash(key, "code", id, email, nonce, record.CredentialDigest, code)
		record.ExpiresAt = now.Add(emailCodeLifetime).Unix()
	}
	next.Records[recordKey] = record
	// Persist an inactive challenge before reserving shared counters. If the
	// second save fails or the process crashes, no email is sent and no code
	// can be verified. A same-account retry remains limited for the day.
	if err := s.persistPasswordRecoveries(next); err != nil {
		return "", "", "", err
	}
	quota := s.copyEmailVerifications()
	for hash, window := range quota.IPDays {
		if window.Start < day {
			delete(quota.IPDays, hash)
		}
	}
	quota.IPDays[ipHash] = emailRateWindow{Start: day, Count: 1}
	if id != "" {
		quota.GlobalHour = emailWindowAt(quota.GlobalHour, now.Unix(), 3600)
		if quota.GlobalDay.Start != day {
			quota.GlobalDay = emailRateWindow{Start: day}
		}
		month, end := emailMonthBounds(now, limits.MonthResetDay)
		if quota.GlobalMonth.Start != month {
			count := 0
			if quota.GlobalMonth.Start >= month && quota.GlobalMonth.Start < end {
				count = quota.GlobalMonth.Count
			}
			quota.GlobalMonth = emailRateWindow{Start: month, Count: count}
		}
		quota.GlobalHour.Count++
		quota.GlobalDay.Count++
		quota.GlobalMonth.Count++
	}
	if err := s.persistEmailVerifications(quota); err != nil {
		return "", "", "", err
	}
	return id, code, nonce, nil
}

func (s *store) finishPasswordCode(id, nonce string, accepted bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	r := s.passwordRecoveries.Records["account:"+id]
	if r.Nonce != nonce || r.CodeHash == "" {
		return errors.New("password recovery challenge changed")
	}
	r.Active = accepted
	if !accepted {
		r.CodeHash, r.Nonce, r.CredentialDigest, r.ExpiresAt = "", "", "", 0
	}
	next := s.copyPasswordRecoveries()
	next.Records["account:"+id] = r
	return s.persistPasswordRecoveries(next)
}

func (s *store) validatePasswordCode(email, code string, key []byte, now time.Time) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	id := s.emails[email]
	user := s.state.Users[id]
	r := s.passwordRecoveries.Records["account:"+id]
	if user == nil || r.UserID != id || r.Email != email || !r.Active || now.Unix() < r.LastSendAt || now.Unix() >= r.ExpiresAt || r.Attempts >= emailCodeAttempts || !hmac.Equal([]byte(r.CredentialDigest), []byte(hex.EncodeToString(user.Hash))) {
		return "", errInvalidRecoveryCode
	}
	expected := recoveryHash(key, "code", id, email, r.Nonce, r.CredentialDigest, code)
	if !hmac.Equal([]byte(expected), []byte(r.CodeHash)) {
		r.Attempts++
		if r.Attempts >= emailCodeAttempts {
			r.Active = false
		}
		next := s.copyPasswordRecoveries()
		next.Records["account:"+id] = r
		if err := s.persistPasswordRecoveries(next); err != nil {
			return "", err
		}
		return "", errInvalidRecoveryCode
	}
	return id, nil
}

// Called with app.credentialMu held exclusively. Clear durable refresh
// grants before changing the password. A crash after state.json replacement
// cannot reuse the code: its credential digest is bound to the old password.
func (s *store) commitRecoveredPassword(id string, salt, hash []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	user := s.state.Users[id]
	if user == nil {
		return errors.New("missing recovery account")
	}
	refresh := s.copyRefreshState()
	for key, grant := range refresh.Tokens {
		if grant.UserID == id {
			delete(refresh.Tokens, key)
		}
	}
	if err := s.persistRefresh(refresh); err != nil {
		return err
	}
	s.refreshState = refresh
	updated := *user
	updated.Salt, updated.Hash, updated.Iterations = salt, hash, passwordIterations
	next := s.copyState()
	next.Users[id] = &updated
	if err := s.persist(next); err != nil {
		return err
	}
	s.state = next
	return nil
}
