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
	"net"
	"os"
	"strconv"
	"time"
)

const emailCodeLifetime = 30 * time.Minute
const emailCodeAttempts = 5

var emailBeijing = time.FixedZone("Asia/Shanghai", 8*3600)

const emailMonthlyQuotaMessage = "本月验证码邮件额度已用完，请下月再试。"

type emailRateWindow struct {
	Start int64 `json:"start"`
	Count int   `json:"count"`
}

type emailVerificationRecord struct {
	Email           string          `json:"email"`
	RoleID          string          `json:"roleId"`
	CodeHash        string          `json:"codeHash,omitempty"`
	Nonce           string          `json:"nonce,omitempty"`
	ExpiresAt       int64           `json:"expiresAt,omitempty"`
	CodeActive      bool            `json:"codeActive"`
	Attempts        int             `json:"attempts"`
	LastSendAt      int64           `json:"lastSendAt"`
	Hour            emailRateWindow `json:"hour"`
	Day             emailRateWindow `json:"day"`
	Verified        bool            `json:"verified"`
	VerifiedAt      int64           `json:"verifiedAt,omitempty"`
	RewardRequestID string          `json:"rewardRequestId,omitempty"`
	RewardSent      bool            `json:"rewardSent"`
	RewardMailID    string          `json:"rewardMailId,omitempty"`
}

type emailVerificationState struct {
	Version             int                                `json:"version"`
	GlobalHour          emailRateWindow                    `json:"globalHour"`
	GlobalDay           emailRateWindow                    `json:"globalDay"`
	GlobalMonth         emailRateWindow                    `json:"globalMonth"`
	IPDays              map[string]emailRateWindow         `json:"ipDays"`
	MonthlyBlockedUntil int64                              `json:"monthlyBlockedUntil,omitempty"`
	Users               map[string]emailVerificationRecord `json:"users"`
}

type emailRateLimits struct {
	GlobalHour, GlobalDay, Monthly, MonthResetDay int
}

type emailFlowError struct {
	Status       int
	Message      string
	RetrySeconds int
	Reason       string
}

func (e *emailFlowError) Error() string { return e.Message }

func validateEmailVerificationState(state emailVerificationState) error {
	invalid := errors.New("invalid email verification registry")
	validWindow := func(w emailRateWindow, span int64) bool {
		return w.Start >= 0 && w.Start%span == 0 && w.Count >= 0 && w.Count <= 1000000 && (w.Start != 0 || w.Count == 0)
	}
	validDay := func(w emailRateWindow) bool {
		return w.Start >= 0 && (w.Start == 0 && w.Count == 0 || (w.Start+8*3600)%86400 == 0 && w.Count >= 0 && w.Count <= 1000000)
	}
	if (state.Version != 1 && state.Version != 2) || state.Users == nil || !validWindow(state.GlobalHour, 3600) ||
		(state.Version == 1 && !validWindow(state.GlobalDay, 86400)) || (state.Version == 2 && !validDay(state.GlobalDay)) {
		return invalid
	}
	if state.Version == 2 {
		if state.IPDays == nil || !validWindow(state.GlobalMonth, 86400) || state.MonthlyBlockedUntil < 0 ||
			state.MonthlyBlockedUntil != 0 && state.MonthlyBlockedUntil%86400 != 0 {
			return invalid
		}
		for hash, window := range state.IPDays {
			decoded, err := hex.DecodeString(hash)
			if err != nil || len(decoded) != 32 || hex.EncodeToString(decoded) != hash || !validDay(window) || window.Count != 1 {
				return invalid
			}
		}
	} else if state.GlobalMonth != (emailRateWindow{}) || state.MonthlyBlockedUntil != 0 || len(state.IPDays) != 0 {
		return invalid
	}
	for id, record := range state.Users {
		if id == "" || len(id) > 128 || !validEmail(record.Email) || record.Email != normalizeEmail(record.Email) ||
			!legacyRoleID.MatchString(record.RoleID) || record.Attempts < 0 || record.Attempts > emailCodeAttempts ||
			record.LastSendAt < 1 || !validWindow(record.Hour, 3600) ||
			(state.Version == 1 && !validWindow(record.Day, 86400)) || (state.Version == 2 && !validDay(record.Day)) {
			return invalid
		}
		if _, err := strconv.ParseInt(record.RoleID, 10, 64); err != nil {
			return invalid
		}
		if record.CodeHash != "" {
			hash, err := hex.DecodeString(record.CodeHash)
			lifetime := record.ExpiresAt - record.LastSendAt
			if err != nil || len(hash) != 32 || hex.EncodeToString(hash) != record.CodeHash || len(record.Nonce) != 22 ||
				(lifetime != 600 && (state.Version == 1 || lifetime != int64(emailCodeLifetime/time.Second))) || record.Verified {
				return invalid
			}
		} else if record.Nonce != "" || record.ExpiresAt != 0 || record.CodeActive {
			return invalid
		}
		if record.CodeActive && record.Attempts >= emailCodeAttempts {
			return invalid
		}
		if record.Verified {
			if record.VerifiedAt < 1 || !adminMailRequestID.MatchString(record.RewardRequestID) {
				return invalid
			}
		} else if record.VerifiedAt != 0 || record.RewardRequestID != "" || record.RewardSent || record.RewardMailID != "" {
			return invalid
		}
		if record.RewardSent && !legacyRoleID.MatchString(record.RewardMailID) || !record.RewardSent && record.RewardMailID != "" {
			return invalid
		}
	}
	return nil
}

func (s *store) loadEmailVerifications() error {
	f, err := os.Open(s.emailVerificationFile)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer f.Close()
	var state emailVerificationState
	dec := json.NewDecoder(io.LimitReader(f, 64<<20))
	dec.DisallowUnknownFields()
	if dec.Decode(&state) != nil || dec.Decode(new(any)) != io.EOF {
		return errors.New("invalid email verification registry JSON")
	}
	if err := validateEmailVerificationState(state); err != nil {
		return err
	}
	if state.Version == 1 {
		// Keep old challenge hashes and exact expiry. LastSendAt is enough to
		// enforce the new account day; historical client IPs cannot be inferred.
		state.Version, state.IPDays = 2, make(map[string]emailRateWindow)
		latest := int64(0)
		for _, record := range state.Users {
			if record.LastSendAt > latest {
				latest = record.LastSendAt
			}
		}
		if latest > 0 {
			state.GlobalDay = emailRateWindow{Start: emailDayStart(latest), Count: state.GlobalDay.Count}
			month, _ := emailMonthBounds(time.Unix(latest, 0), 1)
			state.GlobalMonth.Start = month
			for id, record := range state.Users {
				if record.LastSendAt >= month {
					state.GlobalMonth.Count += record.Day.Count
				}
				record.Day = emailRateWindow{Start: emailDayStart(record.LastSendAt), Count: 1}
				state.Users[id] = record
			}
		}
	}
	s.emailVerifications = state
	for id, account := range s.state.Users {
		record := state.Users[id]
		account.EmailVerified = record.Verified && record.Email == account.Email
	}
	return nil
}

func (s *store) copyEmailVerifications() emailVerificationState {
	next := s.emailVerifications
	next.Users = make(map[string]emailVerificationRecord, len(s.emailVerifications.Users)+1)
	next.IPDays = make(map[string]emailRateWindow, len(s.emailVerifications.IPDays)+1)
	for hash, window := range s.emailVerifications.IPDays {
		next.IPDays[hash] = window
	}
	for id, record := range s.emailVerifications.Users {
		next.Users[id] = record
	}
	return next
}

func (s *store) persistEmailVerifications(next emailVerificationState) error {
	if err := persistJSON(s.emailVerificationFile, next); err != nil {
		return err
	}
	s.emailVerifications = next
	return nil
}

func (s *store) emailVerification(id string) emailVerificationRecord {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.emailVerifications.Users[id]
}

func emailCodeHash(key []byte, id, email, nonce, code string) string {
	mac := hmac.New(sha256.New, key)
	for _, part := range []string{"witchweapon-email-v1", id, email, nonce, code} {
		_, _ = mac.Write([]byte(part))
		_, _ = mac.Write([]byte{0})
	}
	return hex.EncodeToString(mac.Sum(nil))
}

func emailWindowAt(window emailRateWindow, now, span int64) emailRateWindow {
	start := now / span * span
	if window.Start != start {
		return emailRateWindow{Start: start}
	}
	return window
}

func emailCooldown(record emailVerificationRecord, now int64) int {
	if record.LastSendAt == 0 || emailDayStart(record.LastSendAt) < emailDayStart(now) {
		return 0
	}
	return int(emailDayStart(record.LastSendAt) + 86400 - now)
}

func emailDayStart(unix int64) int64 { return (unix+8*3600)/86400*86400 - 8*3600 }

func emailMonthBounds(now time.Time, resetDay int) (int64, int64) {
	if resetDay < 1 || resetDay > 31 {
		resetDay = 1
	}
	local := now.UTC()
	boundary := func(year int, month time.Month) time.Time {
		lastDay := time.Date(year, month+1, 0, 0, 0, 0, 0, time.UTC).Day()
		day := resetDay
		if day > lastDay {
			day = lastDay
		}
		return time.Date(year, month, day, 0, 0, 0, 0, time.UTC)
	}
	start := boundary(local.Year(), local.Month())
	if now.Before(start) {
		start = boundary(local.Year(), local.Month()-1)
	}
	end := boundary(start.Year(), start.Month()+1)
	return start.Unix(), end.Unix()
}

func emailIPHash(key []byte, ip string) string {
	parsed := net.ParseIP(ip)
	if parsed == nil {
		return ""
	}
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write([]byte("witchweapon-email-ip-v1\x00" + parsed.String()))
	return hex.EncodeToString(mac.Sum(nil))
}

func emailSendRestriction(state emailVerificationState, id, ipHash string, now time.Time, limits emailRateLimits) *emailFlowError {
	unix := now.Unix()
	record := state.Users[id]
	month, nextMonth := emailMonthBounds(now, limits.MonthResetDay)
	if unix < record.LastSendAt || unix < state.GlobalHour.Start || unix < state.GlobalDay.Start || unix < state.GlobalMonth.Start {
		return &emailFlowError{Status: 503, Message: "邮箱服务时间暂时异常，请稍后重试。", Reason: "temporary"}
	}
	if state.MonthlyBlockedUntil > unix || state.GlobalMonth.Start >= month && state.GlobalMonth.Start < nextMonth && state.GlobalMonth.Count >= limits.Monthly {
		if state.MonthlyBlockedUntil > nextMonth {
			nextMonth = state.MonthlyBlockedUntil
		}
		return &emailFlowError{Status: 429, Message: emailMonthlyQuotaMessage, RetrySeconds: int(nextMonth - unix), Reason: "month"}
	}
	if cooldown := emailCooldown(record, unix); cooldown > 0 {
		return &emailFlowError{Status: 429, Message: "该账号今天已发送过验证码，请明天再试（北京时间每日一次）。", RetrySeconds: cooldown, Reason: "day_account"}
	}
	if ipHash == "" {
		return &emailFlowError{Status: 503, Message: "无法确认请求来源，请稍后重试。", Reason: "temporary"}
	}
	day := emailDayStart(unix)
	if window := state.IPDays[ipHash]; window.Start >= day && window.Count > 0 {
		return &emailFlowError{Status: 429, Message: "当前IP今天已发送过验证码，请明天再试（北京时间每日一次）。", RetrySeconds: int(window.Start + 86400 - unix), Reason: "day_ip"}
	}
	if window := emailWindowAt(state.GlobalHour, unix, 3600); window.Count >= limits.GlobalHour {
		return &emailFlowError{Status: 429, Message: "验证码服务暂时繁忙，请稍后再试。", RetrySeconds: int(window.Start + 3600 - unix), Reason: "temporary"}
	}
	if state.GlobalDay.Start == day && state.GlobalDay.Count >= limits.GlobalDay {
		return &emailFlowError{Status: 429, Message: "验证码服务今天已达到发送限额，请明天再试。", RetrySeconds: int(day + 86400 - unix), Reason: "day_service"}
	}
	return nil
}

func (s *store) emailSendRestriction(id, ip string, key []byte, now time.Time, limits emailRateLimits) *emailFlowError {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.sharedEmailSendRestriction(id, emailIPHash(key, ip), now, limits)
}

func (s *store) blockEmailMonth(now time.Time, resetDay int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	next := s.copyEmailVerifications()
	_, until := emailMonthBounds(now, resetDay)
	if until > next.MonthlyBlockedUntil {
		next.MonthlyBlockedUntil = until
	}
	return s.persistEmailVerifications(next)
}

func (s *store) prepareEmailCode(id, email, roleID, ip string, key []byte, now time.Time, limits emailRateLimits) (string, string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	record := s.emailVerifications.Users[id]
	if account := s.state.Users[id]; account == nil || account.Email != email {
		return "", "", errors.New("email account mismatch")
	}
	if record.Email != "" && (record.Email != email || record.RoleID != roleID) {
		return "", "", errors.New("email verification identity mismatch")
	}
	if record.Verified {
		return "", "", &emailFlowError{Status: 409, Message: "该邮箱已经验证。"}
	}
	unix := now.Unix()
	ipHash := emailIPHash(key, ip)
	if flow := s.sharedEmailSendRestriction(id, ipHash, now, limits); flow != nil {
		return "", "", flow
	}
	next := s.copyEmailVerifications()
	record.Hour = emailWindowAt(record.Hour, unix, 3600)
	day := emailDayStart(unix)
	record.Day = emailRateWindow{Start: day}
	next.GlobalHour = emailWindowAt(next.GlobalHour, unix, 3600)
	if next.GlobalDay.Start != day {
		next.GlobalDay = emailRateWindow{Start: day}
	}
	month, endMonth := emailMonthBounds(now, limits.MonthResetDay)
	if next.GlobalMonth.Start != month {
		count := 0
		if next.GlobalMonth.Start >= month && next.GlobalMonth.Start < endMonth {
			count = next.GlobalMonth.Count
		}
		next.GlobalMonth = emailRateWindow{Start: month, Count: count}
	}
	for hash, window := range next.IPDays {
		if window.Start < day {
			delete(next.IPDays, hash)
		}
	}
	next.IPDays[ipHash] = emailRateWindow{Start: day, Count: 1}
	number, err := rand.Int(rand.Reader, big.NewInt(1000000))
	if err != nil {
		return "", "", err
	}
	code := fmt.Sprintf("%06d", number.Int64())
	nonce, err := randomID(16)
	if err != nil {
		return "", "", err
	}
	record.Email, record.RoleID, record.Nonce = email, roleID, nonce
	record.CodeHash = emailCodeHash(key, id, email, nonce, code)
	record.LastSendAt, record.ExpiresAt = unix, unix+int64(emailCodeLifetime/time.Second)
	record.CodeActive, record.Attempts = false, 0
	record.Hour.Count++
	record.Day.Count++
	next.GlobalHour.Count++
	next.GlobalDay.Count++
	next.GlobalMonth.Count++
	next.Users[id] = record
	// Persist quota and an inactive challenge before the external send. A crash
	// cannot restore quota or turn an unconfirmed email into a usable code.
	if err := s.persistEmailVerifications(next); err != nil {
		return "", "", err
	}
	return code, nonce, nil
}

func (s *store) finishEmailCode(id, nonce string, accepted bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	record := s.emailVerifications.Users[id]
	if record.Nonce != nonce || record.Verified {
		return errors.New("email challenge changed")
	}
	record.CodeActive = accepted
	if !accepted {
		record.CodeHash, record.Nonce, record.ExpiresAt = "", "", 0
	}
	next := s.copyEmailVerifications()
	next.Users[id] = record
	return s.persistEmailVerifications(next)
}

func newEmailRewardRequestID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16]), nil
}

func (s *store) verifyEmailCode(id, email, roleID, code string, key []byte, now time.Time) (emailVerificationRecord, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	record := s.emailVerifications.Users[id]
	if record.Email != email || record.RoleID != roleID {
		return record, &emailFlowError{Status: 400, Message: "请先发送邮箱验证码。"}
	}
	if record.Verified {
		return record, nil
	}
	if !record.CodeActive || now.Unix() >= record.ExpiresAt || now.Unix() < record.LastSendAt {
		return record, &emailFlowError{Status: 400, Message: "验证码已失效，请重新发送。"}
	}
	if len(code) != 6 || stringsOnlyDigits(code) == false {
		return record, &emailFlowError{Status: 400, Message: "请输入六位数字验证码。"}
	}
	expected := emailCodeHash(key, id, email, record.Nonce, code)
	matched := hmac.Equal([]byte(expected), []byte(record.CodeHash))
	if !matched {
		record.Attempts++
		if record.Attempts >= emailCodeAttempts {
			record.CodeActive = false
		}
		next := s.copyEmailVerifications()
		next.Users[id] = record
		if err := s.persistEmailVerifications(next); err != nil {
			return record, err
		}
		return record, &emailFlowError{Status: 400, Message: "验证码不正确；多次输错后需要重新发送。"}
	}
	requestID, err := newEmailRewardRequestID()
	if err != nil {
		return record, err
	}
	record.Verified, record.VerifiedAt, record.RewardRequestID = true, now.Unix(), requestID
	record.CodeHash, record.Nonce, record.ExpiresAt, record.Attempts, record.CodeActive = "", "", 0, 0, false
	next := s.copyEmailVerifications()
	next.Users[id] = record
	// Durable outbox: confirmed verification and the one immutable request ID
	// precede any call capable of enqueuing the in-game reward.
	if err := s.persistEmailVerifications(next); err != nil {
		return record, err
	}
	updated := *s.state.Users[id]
	updated.EmailVerified = true
	s.state.Users[id] = &updated
	return record, nil
}

func stringsOnlyDigits(value string) bool {
	for _, ch := range value {
		if ch < '0' || ch > '9' {
			return false
		}
	}
	return true
}

func (s *store) finishEmailReward(id, requestID, mailID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	record := s.emailVerifications.Users[id]
	if !record.Verified || record.RewardRequestID != requestID {
		return errors.New("email reward identity mismatch")
	}
	if record.RewardSent {
		return nil
	}
	record.RewardSent, record.RewardMailID = true, mailID
	next := s.copyEmailVerifications()
	next.Users[id] = record
	return s.persistEmailVerifications(next)
}
