package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
)

type emailVerificationConfig struct {
	accountID     string
	token         string
	from          string
	key           [32]byte
	limits        emailRateLimits
	client        *http.Client
	rewardMu      sync.Mutex
	rewarding     map[string]bool
	recoveryWG    sync.WaitGroup
	recoverySlots chan struct{}
}

var cfEmailAccountID = regexp.MustCompile(`^[a-fA-F0-9]{32}$`)
var cfEmailMessageID = regexp.MustCompile(`^[A-Za-z0-9@._:+<>-]{1,256}$`)

func (a *app) emailVerificationReady() bool { return a.emailVerification != nil }

func readEmailSecretFile(path string, maximum int64) ([]byte, error) {
	invalid := errors.New("邮件服务凭据文件不可用")
	if !filepath.IsAbs(path) {
		return nil, invalid
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() > maximum ||
		(runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0) {
		return nil, invalid
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, invalid
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, maximum+1))
	if err != nil || int64(len(data)) > maximum {
		return nil, invalid
	}
	return data, nil
}

func (a *app) configureEmailVerificationFromEnv() error {
	enabled := strings.TrimSpace(os.Getenv("WW_EMAIL_VERIFICATION_ENABLED"))
	if enabled == "" || enabled == "0" || strings.EqualFold(enabled, "false") {
		a.emailVerification = nil
		return nil
	}
	if enabled != "1" && !strings.EqualFold(enabled, "true") {
		return errors.New("WW_EMAIL_VERIFICATION_ENABLED 须为 true 或 false")
	}
	config := &emailVerificationConfig{accountID: os.Getenv("WW_CF_EMAIL_ACCOUNT_ID"), from: os.Getenv("WW_CF_EMAIL_FROM"),
		limits: emailRateLimits{GlobalHour: 100, GlobalDay: 500, Monthly: 3000, MonthResetDay: 1}, rewarding: make(map[string]bool), recoverySlots: make(chan struct{}, 8)}
	if !cfEmailAccountID.MatchString(config.accountID) || !validEmail(config.from) {
		return errors.New("Cloudflare 邮件账号或发件地址配置无效")
	}
	// EnvironmentFile is an alternative for systemd versions without secure
	// credentials support. A supplied token file always takes precedence.
	config.token = strings.TrimSpace(os.Getenv("WW_CF_EMAIL_API_TOKEN"))
	if path := os.Getenv("WW_CF_EMAIL_API_TOKEN_FILE"); path != "" {
		data, err := readEmailSecretFile(path, 2048)
		if err != nil {
			return err
		}
		config.token = strings.TrimSpace(string(data))
	}
	if len(config.token) < 16 || len(config.token) > 1024 || strings.ContainsAny(config.token, " \t\r\n") {
		return errors.New("Cloudflare 邮件发送凭据配置无效")
	}
	for _, limit := range []struct {
		name   string
		target *int
	}{
		{"WW_EMAIL_GLOBAL_HOUR_LIMIT", &config.limits.GlobalHour}, {"WW_EMAIL_GLOBAL_DAY_LIMIT", &config.limits.GlobalDay},
		{"WW_EMAIL_MONTHLY_LIMIT", &config.limits.Monthly},
	} {
		if value := os.Getenv(limit.name); value != "" {
			number, err := strconv.Atoi(value)
			if err != nil || number < 1 || number > 1000000 {
				return errors.New("邮箱验证码限额配置无效")
			}
			*limit.target = number
		}
	}
	if value := os.Getenv("WW_EMAIL_MONTH_RESET_DAY"); value != "" {
		day, err := strconv.Atoi(value)
		if err != nil || day < 1 || day > 31 {
			return errors.New("邮箱月度额度重置日须为1至31")
		}
		config.limits.MonthResetDay = day
	}
	keyPath := filepath.Join(filepath.Dir(a.store.file), "email_verification_key.json")
	var keyRecord struct {
		Version int    `json:"version"`
		Key     string `json:"key"`
	}
	if _, err := os.Lstat(keyPath); errors.Is(err, os.ErrNotExist) {
		if len(a.store.emailVerifications.IPDays) != 0 {
			return errors.New("邮箱验证码密钥缺失，无法恢复已有IP发送限额")
		}
		for _, record := range a.store.emailVerifications.Users {
			if record.CodeHash != "" {
				return errors.New("邮箱验证码密钥缺失，无法恢复已有验证码")
			}
		}
		for _, record := range a.store.passwordRecoveries.Records {
			if record.CodeHash != "" {
				return errors.New("邮箱验证码密钥缺失，无法恢复已有找回验证码")
			}
		}
		if _, err := rand.Read(config.key[:]); err != nil {
			return errors.New("无法创建邮箱验证码密钥")
		}
		keyRecord.Version, keyRecord.Key = 1, hex.EncodeToString(config.key[:])
		if err := persistJSON(keyPath, keyRecord); err != nil {
			return errors.New("无法保存邮箱验证码密钥")
		}
	} else {
		data, err := readEmailSecretFile(keyPath, 512)
		if err != nil {
			return err
		}
		decoder := json.NewDecoder(bytes.NewReader(data))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&keyRecord) != nil || decoder.Decode(new(any)) != io.EOF || keyRecord.Version != 1 {
			return errors.New("邮箱验证码密钥格式无效")
		}
		key, err := hex.DecodeString(keyRecord.Key)
		if err != nil || len(key) != 32 || hex.EncodeToString(key) != keyRecord.Key {
			return errors.New("邮箱验证码密钥格式无效")
		}
		copy(config.key[:], key)
	}
	config.client = &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		Transport: &http.Transport{Proxy: nil, ForceAttemptHTTP2: true, MaxConnsPerHost: 8, MaxIdleConnsPerHost: 4,
			IdleConnTimeout: 30 * time.Second, TLSHandshakeTimeout: 5 * time.Second, ResponseHeaderTimeout: 8 * time.Second,
			DialContext: (&net.Dialer{Timeout: 3 * time.Second}).DialContext}}
	a.emailVerification = config
	return nil
}

func (config *emailVerificationConfig) sendCode(ctx context.Context, email, code string) error {
	plain, html, err := renderEmailVerification(code)
	if err != nil {
		return errors.New("验证码邮件暂时无法发送，请稍后重试。")
	}
	return config.sendTransactionalCode(ctx, email, code, emailVerificationSubject, plain, html)
}

func (config *emailVerificationConfig) sendRecoveryCode(ctx context.Context, email, code string) error {
	plain, html, err := renderPasswordRecoveryEmail(code)
	if err != nil {
		return errors.New("验证码邮件暂时无法发送，请稍后重试。")
	}
	return config.sendTransactionalCode(ctx, email, code, "魔女兵器密码找回验证码", plain, html)
}

func (config *emailVerificationConfig) sendTransactionalCode(ctx context.Context, email, code, subject, plain, html string) error {
	failed := errors.New("验证码邮件暂时无法发送，请稍后重试。")
	body, err := json.Marshal(struct {
		To      []string `json:"to"`
		From    string   `json:"from"`
		Subject string   `json:"subject"`
		Text    string   `json:"text"`
		HTML    string   `json:"html"`
	}{[]string{email}, config.from, subject, plain, html})
	if err != nil {
		return failed
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.cloudflare.com/client/v4/accounts/"+config.accountID+"/email/sending/send", bytes.NewReader(body))
	if err != nil {
		return failed
	}
	request.Header.Set("Authorization", "Bearer "+config.token)
	request.Header.Set("Content-Type", "application/json")
	response, err := config.client.Do(request)
	if err != nil {
		return failed
	}
	defer response.Body.Close()
	if response.ContentLength > 65536 ||
		!strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		return failed
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, 65537))
	if err != nil || len(data) > 65536 {
		return failed
	}
	var result struct {
		Success bool `json:"success"`
		Errors  []struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"errors"`
		Result struct {
			MessageID        string   `json:"message_id"`
			Delivered        []string `json:"delivered"`
			Queued           []string `json:"queued"`
			PermanentBounces []string `json:"permanent_bounces"`
			Suppressed       []string `json:"suppressed_recipients"`
		} `json:"result"`
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	if decoder.Decode(&result) != nil || decoder.Decode(new(any)) != io.EOF {
		return failed
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 || !result.Success || len(result.Errors) != 0 {
		for _, providerError := range result.Errors {
			message := strings.ToLower(providerError.Message)
			// A generic HTTP 429 / "throttled" is not proof of monthly quota.
			if strings.Contains(message, "monthly") && (strings.Contains(message, "quota") || strings.Contains(message, "sending limit") || strings.Contains(message, "monthly_limit")) &&
				(strings.Contains(message, "exceeded") || strings.Contains(message, "exhausted") || strings.Contains(message, "reached")) {
				return &emailFlowError{Status: 429, Message: emailMonthlyQuotaMessage, Reason: "month"}
			}
		}
		return failed
	}
	for _, address := range append(result.Result.PermanentBounces, result.Result.Suppressed...) {
		if normalizeEmail(address) == email {
			return failed
		}
	}
	status := ""
	for _, accepted := range []struct {
		status    string
		addresses []string
	}{{"delivered", result.Result.Delivered}, {"queued", result.Result.Queued}} {
		for _, address := range accepted.addresses {
			if normalizeEmail(address) == email {
				status = accepted.status
				break
			}
		}
		if status != "" {
			break
		}
	}
	if status == "" {
		return failed
	}
	messageID := result.Result.MessageID
	if !cfEmailMessageID.MatchString(messageID) || strings.Contains(strings.ToLower(messageID), strings.ToLower(email)) ||
		strings.Contains(messageID, code) || strings.Contains(messageID, config.token) {
		messageID = "unavailable"
	}
	log.Printf("email_verification_send message_id=%q status=%s", messageID, status)
	return nil
}
