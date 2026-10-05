package main

import (
	"context"
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"errors"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const passwordRecoveryAcceptedMessage = "如果该邮箱已注册，找回验证码将发送到该邮箱；30分钟内有效。每个账号和IP每天只能发送一次，请检查收件箱及垃圾邮件。"
const passwordRecoveryInvalidMessage = "邮箱或验证码不正确，或验证码已失效；请确认使用密码找回邮件中的六位验证码。"

func renderPasswordRecoveryEmail(code string) (string, string, error) {
	plain, html, err := renderEmailVerification(code)
	if err != nil {
		return "", "", err
	}
	replacements := strings.NewReplacer(
		"魔女兵器邮箱验证", "魔女兵器密码找回",
		"您的邮箱验证码：", "您的密码找回验证码：",
		"验证你的邮箱", "找回你的密码",
		"完成当前注册邮箱的验证", "重置当前账号的登录密码",
		"返回游戏个人中心", "返回游戏登录页",
		"设置 → 个人中心", "登录 → 忘记密码",
		"输入这 6 位验证码，完成当前注册邮箱的验证", "输入这 6 位验证码并设置新密码",
		"输入验证码并完成验证", "输入验证码并设置新密码",
		"如果这不是您本人的操作，请忽略本邮件。", "重置成功后，该账号的旧登录会话将失效。如果这不是您本人的操作，请忽略本邮件。",
	)
	return replacements.Replace(plain), replacements.Replace(html), nil
}

func (a *app) passwordRecoveryInput(w http.ResponseWriter, r *http.Request, input any) bool {
	if !a.allowAuth(w, r) {
		return false
	}
	if r.URL.RawQuery != "" || r.URL.ForceQuery {
		fail(w, 400, "invalid_request", "密码找回接口不接受查询参数。")
		return false
	}
	return decodeRequest(w, r, input)
}

func (a *app) sendPasswordRecovery(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Email string `json:"email"`
	}
	if !a.passwordRecoveryInput(w, r, &input) {
		return
	}
	input.Email = normalizeEmail(input.Email)
	if !validEmail(input.Email) {
		fail(w, 400, "invalid_request", "请输入有效的注册邮箱。")
		return
	}
	config := a.emailVerification
	if config == nil {
		fail(w, 503, "email_unavailable", "邮箱找回服务暂未开放，请稍后再试。")
		return
	}
	select {
	case config.recoverySlots <- struct{}{}:
	default:
		fail(w, 429, "server_busy", "邮件服务暂时繁忙，请稍后再试。")
		return
	}
	id, code, nonce, err := a.store.preparePasswordCode(input.Email, authRateKey(r), config.key[:], a.now(), config.limits)
	if err != nil {
		<-config.recoverySlots
		var flow *emailFlowError
		if !errors.As(err, &flow) {
			fail(w, 503, "email_unavailable", "验证码请求暂时无法保存，请稍后再试。")
			return
		}
		if flow.Reason != "day_account" && flow.Reason != "day_ip" {
			if flow.RetrySeconds > 0 {
				w.Header().Set("Retry-After", strconv.Itoa(flow.RetrySeconds))
			}
			fail(w, flow.Status, "email_limited", flow.Message)
			return
		}
	} else if id == "" {
		<-config.recoverySlots // Unknown addresses never consume provider sends.
	} else {
		// Both known and unknown addresses respond immediately. A real provider
		// round trip must not reveal whether a private account exists.
		config.recoveryWG.Add(1)
		go func() {
			defer config.recoveryWG.Done()
			defer func() { <-config.recoverySlots }()
			ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
			defer cancel()
			sendErr := config.sendRecoveryCode(ctx, input.Email, code)
			var flow *emailFlowError
			if errors.As(sendErr, &flow) && flow.Reason == "month" {
				if a.store.blockEmailMonth(a.now(), config.limits.MonthResetDay) != nil {
					log.Print("password_recovery_month_save_failed")
				}
			}
			if a.store.finishPasswordCode(id, nonce, sendErr == nil) != nil {
				log.Print("password_recovery_challenge_save_failed")
			}
			if sendErr != nil {
				log.Print("password_recovery_email_not_confirmed")
			}
		}()
	}
	cooldown := int(emailDayStart(a.now().Unix()) + 86400 - a.now().Unix())
	writeJSON(w, http.StatusAccepted, map[string]any{"message": passwordRecoveryAcceptedMessage, "cooldownSeconds": cooldown})
}

func (a *app) resetPasswordRecovery(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Email    string `json:"email"`
		Code     string `json:"code"`
		Password string `json:"password"`
	}
	if !a.passwordRecoveryInput(w, r, &input) {
		return
	}
	input.Email = normalizeEmail(input.Email)
	if !validRecoveryPassword(input.Password) {
		fail(w, 400, "invalid_password", "密码须为 12 至 128 个字符，首尾不能有空白，且不能含控制字符。")
		return
	}
	if !validEmail(input.Email) || len(input.Code) != 6 || !stringsOnlyDigits(input.Code) {
		fail(w, 400, "invalid_recovery_code", passwordRecoveryInvalidMessage)
		return
	}
	config := a.emailVerification
	if config == nil {
		fail(w, 503, "email_unavailable", "邮箱找回服务暂未开放，请稍后再试。")
		return
	}
	select {
	case a.kdfSlots <- struct{}{}:
	default:
		fail(w, 429, "server_busy", "正在处理其他登录请求，请稍后再试。")
		return
	}
	defer func() { <-a.kdfSlots }()
	a.credentialMu.Lock()
	defer a.credentialMu.Unlock()
	id, err := a.store.validatePasswordCode(input.Email, input.Code, config.key[:], a.now())
	if errors.Is(err, errInvalidRecoveryCode) {
		fail(w, 400, "invalid_recovery_code", passwordRecoveryInvalidMessage)
		return
	}
	if err != nil {
		fail(w, 503, "storage_error", "验证码状态暂时无法保存，请稍后重试。")
		return
	}
	salt := make([]byte, 32)
	if _, err := rand.Read(salt); err != nil {
		fail(w, 500, "internal_error", "暂时无法重置密码。")
		return
	}
	hash, err := pbkdf2.Key(sha256.New, input.Password, salt, passwordIterations, 32)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法重置密码。")
		return
	}
	if err := a.store.commitRecoveredPassword(id, salt, hash); err != nil {
		fail(w, 503, "storage_error", "密码重置暂时无法保存，请稍后重试。")
		return
	}
	a.mu.Lock()
	for key, current := range a.sessions {
		if current.UserID == id {
			delete(a.sessions, key)
		}
	}
	a.mu.Unlock()
	// Reuse the account socket invalidation primitive so old logged-in chat
	// connections close immediately rather than waiting for the 30s watcher.
	a.refreshRTMCosmetics(id)
	writeJSON(w, 200, map[string]string{"message": "密码已重置，请使用新密码重新登录。"})
}

func validRecoveryPassword(password string) bool {
	if !utf8.ValidString(password) || strings.TrimSpace(password) != password || utf8.RuneCountInString(password) < 12 || utf8.RuneCountInString(password) > 128 {
		return false
	}
	for _, ch := range password {
		if unicode.IsControl(ch) {
			return false
		}
	}
	return true
}
