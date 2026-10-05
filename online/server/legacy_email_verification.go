package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type emailVerificationView struct {
	RoleID            string `json:"roleId"`
	MaskedEmail       string `json:"maskedEmail"`
	Verified          bool   `json:"verified"`
	RewardSent        bool   `json:"rewardSent"`
	ServiceReady      bool   `json:"serviceReady"`
	Message           string `json:"message"`
	CooldownSeconds   int    `json:"cooldownSeconds"`
	SendAllowed       bool   `json:"sendAllowed"`
	SendBlockedReason string `json:"sendBlockedReason"`
}

func maskedVerificationEmail(email string) string {
	parts := strings.SplitN(email, "@", 2)
	if len(parts) != 2 || parts[0] == "" {
		return "***"
	}
	runes := []rune(parts[0])
	return string(runes[0]) + "***@" + parts[1]
}

func (a *app) writeEmailVerification(w http.ResponseWriter, r *http.Request, player Player, roleID string, status int, message string, cooldown int) {
	record := a.store.emailVerification(player.ID)
	verified := record.Verified && record.Email == player.Email && (roleID == "" || record.RoleID == roleID)
	allowed, reason := false, "service"
	if verified {
		reason = "verified"
	} else if config := a.emailVerification; config != nil {
		if flow := a.store.emailSendRestriction(player.ID, authRateKey(r), config.key[:], a.now(), config.limits); flow != nil {
			reason = flow.Reason
			if flow.RetrySeconds > cooldown {
				cooldown = flow.RetrySeconds
			}
		} else {
			allowed, reason = true, ""
		}
	}
	if remaining := emailCooldown(record, a.now().Unix()); !record.Verified && remaining > cooldown {
		cooldown = remaining
	}
	if cooldown > 0 {
		w.Header().Set("Retry-After", strconv.Itoa(cooldown))
	}
	writeJSON(w, status, emailVerificationView{RoleID: roleID, MaskedEmail: maskedVerificationEmail(player.Email),
		Verified: verified, RewardSent: verified && record.RewardSent, ServiceReady: a.emailVerificationReady(),
		Message: message, CooldownSeconds: cooldown, SendAllowed: allowed, SendBlockedReason: reason})
}

func readEmailVerificationInput(w http.ResponseWriter, r *http.Request, send bool) (string, error) {
	r.Body = http.MaxBytesReader(w, r.Body, 256)
	body, err := io.ReadAll(r.Body)
	if err != nil {
		return "", &emailFlowError{Status: 400, Message: "邮箱请求内容无效。"}
	}
	if len(bytes.TrimSpace(body)) == 0 {
		return "", nil
	}
	contentType := strings.ToLower(strings.TrimSpace(strings.Split(r.Header.Get("Content-Type"), ";")[0]))
	if contentType == "application/json" {
		var fields map[string]json.RawMessage
		if json.Unmarshal(body, &fields) != nil || fields == nil || len(fields) > 1 || send && len(fields) != 0 {
			return "", &emailFlowError{Status: 400, Message: "邮箱请求包含未知参数。"}
		}
		for key := range fields {
			if key != "code" {
				return "", &emailFlowError{Status: 400, Message: "邮箱请求包含未知参数。"}
			}
		}
		var input struct {
			Code string `json:"code"`
		}
		decoder := json.NewDecoder(bytes.NewReader(body))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&input) != nil || decoder.Decode(new(any)) != io.EOF {
			return "", &emailFlowError{Status: 400, Message: "验证码格式无效。"}
		}
		if fields["code"] != nil && bytes.Equal(bytes.TrimSpace(fields["code"]), []byte("null")) {
			return "", &emailFlowError{Status: 400, Message: "验证码格式无效。"}
		}
		return input.Code, nil
	}
	if contentType == "application/x-www-form-urlencoded" {
		form, err := url.ParseQuery(string(body))
		if err != nil || len(form) > 1 || send && len(form) != 0 {
			return "", &emailFlowError{Status: 400, Message: "邮箱请求包含未知参数。"}
		}
		for key, values := range form {
			if key != "code" || len(values) != 1 {
				return "", &emailFlowError{Status: 400, Message: "邮箱请求包含未知参数。"}
			}
		}
		return form.Get("code"), nil
	}
	return "", &emailFlowError{Status: 415, Message: "请使用 JSON 格式提交邮箱请求。"}
}

func (a *app) legacyEmailVerification(w http.ResponseWriter, r *http.Request, player Player, path string) {
	roleID := ""
	respond := func(status int, message string, cooldown int) {
		a.writeEmailVerification(w, r, player, roleID, status, message, cooldown)
	}
	statusOnly := path == "/role/email/status"
	wanted := http.MethodPost
	if statusOnly {
		wanted = http.MethodGet
	}
	if r.Method != wanted {
		w.Header().Set("Allow", wanted)
		respond(405, "邮箱接口请求方式无效。", 0)
		return
	}
	if r.URL.RawQuery != "" || r.URL.ForceQuery {
		respond(400, "邮箱接口不接受查询参数。", 0)
		return
	}
	code := ""
	if statusOnly {
		if r.ContentLength > 0 || len(r.TransferEncoding) > 0 {
			respond(400, "邮箱状态查询不接受请求内容。", 0)
			return
		}
		if body, err := io.ReadAll(io.LimitReader(r.Body, 1)); err != nil || len(body) != 0 {
			respond(400, "邮箱状态查询不接受请求内容。", 0)
			return
		}
	} else {
		var err error
		code, err = readEmailVerificationInput(w, r, path == "/role/email/send")
		if err != nil {
			var flow *emailFlowError
			errors.As(err, &flow)
			respond(flow.Status, flow.Message, flow.RetrySeconds)
			return
		}
	}
	if a.legacy == nil {
		respond(503, "游戏角色服务暂时不可用。", 0)
		return
	}
	role, err := a.readLegacyRoleSummary(r, player)
	if err != nil {
		respond(502, "角色摘要暂时不可用。", 0)
		return
	}
	if !role.Exists {
		respond(409, "请先创建游戏角色。", 0)
		return
	}
	roleID = role.RoleID
	record := a.store.emailVerification(player.ID)
	if record.Email != "" && (record.Email != player.Email || record.RoleID != roleID) {
		respond(503, "邮箱验证身份不一致，请到测试群反馈。", 0)
		return
	}
	if statusOnly {
		message := "验证注册邮箱后可领取100张祈愿塔罗牌。"
		if !a.emailVerificationReady() {
			message = "邮箱验证服务暂未开放，请稍后再试。"
		} else if !record.Verified {
			config := a.emailVerification
			if flow := a.store.emailSendRestriction(player.ID, authRateKey(r), config.key[:], a.now(), config.limits); flow != nil {
				message = flow.Message
			}
		}
		if record.Verified {
			message = "邮箱已验证，奖励邮件正在等待重试。"
			if record.RewardSent {
				message = "邮箱已验证，100张祈愿塔罗牌奖励已发送到游戏邮件。"
			}
		}
		respond(200, message, 0)
		return
	}
	if !a.emailVerificationReady() {
		respond(503, "邮箱验证服务暂未开放，请稍后再试。", 0)
		return
	}
	config := a.emailVerification
	if path == "/role/email/send" {
		if record.Verified {
			respond(200, "该邮箱已经验证，无需再次发送验证码。", 0)
			return
		}
		generated, nonce, err := a.store.prepareEmailCode(player.ID, player.Email, roleID, authRateKey(r), config.key[:], a.now(), config.limits)
		if err != nil {
			var flow *emailFlowError
			if errors.As(err, &flow) {
				respond(flow.Status, flow.Message, flow.RetrySeconds)
			} else {
				respond(503, "验证码状态暂时无法保存，请稍后重试。", 0)
			}
			return
		}
		sendErr := config.sendCode(r.Context(), player.Email, generated)
		accepted := sendErr == nil
		var sendFlow *emailFlowError
		if errors.As(sendErr, &sendFlow) && sendFlow.Reason == "month" {
			if err := a.store.blockEmailMonth(a.now(), config.limits.MonthResetDay); err != nil {
				respond(503, "月度邮件额度状态暂时无法保存，请稍后重试。", 0)
				return
			}
		}
		if err := a.store.finishEmailCode(player.ID, nonce, accepted); err != nil {
			respond(503, "验证码状态暂时无法保存，今日发送次数已使用，请明天再试。", 0)
			return
		}
		if !accepted {
			if sendFlow != nil && sendFlow.Reason == "month" {
				respond(429, emailMonthlyQuotaMessage, 0)
			} else {
				respond(503, "验证码邮件发送未确认，今日发送次数已使用，请明天再试。", 0)
			}
			return
		}
		respond(200, "验证码邮件已提交发送，30分钟内有效，请检查收件箱及垃圾邮件；今天不能再次发送。", 0)
		return
	}
	record, err = a.store.verifyEmailCode(player.ID, player.Email, roleID, code, config.key[:], a.now())
	if err != nil {
		var flow *emailFlowError
		if errors.As(err, &flow) {
			respond(flow.Status, flow.Message, flow.RetrySeconds)
		} else {
			respond(503, "邮箱验证状态暂时无法保存，请稍后重试。", 0)
		}
		return
	}
	if record.RewardSent {
		respond(200, "邮箱已验证，奖励已发送到游戏邮件。", 0)
		return
	}
	config.rewardMu.Lock()
	if config.rewarding[player.ID] {
		config.rewardMu.Unlock()
		respond(200, "邮箱已验证，奖励邮件正在发送，请稍后重试。", 0)
		return
	}
	config.rewarding[player.ID] = true
	config.rewardMu.Unlock()
	defer func() { config.rewardMu.Lock(); delete(config.rewarding, player.ID); config.rewardMu.Unlock() }()
	mailID, err := a.deliverEmailVerificationReward(r, player.ID, record)
	if err != nil {
		respond(503, "邮箱已验证，奖励邮件暂未发送；请点击验证重试。", 0)
		return
	}
	if err := a.store.finishEmailReward(player.ID, record.RewardRequestID, mailID); err != nil {
		respond(503, "邮箱已验证，奖励邮件发送结果等待确认；请点击验证重试。", 0)
		return
	}
	respond(200, "邮箱验证成功！100张祈愿塔罗牌已发送到游戏邮件。", 0)
}

func (a *app) deliverEmailVerificationReward(r *http.Request, id string, record emailVerificationRecord) (string, error) {
	failed := errors.New("email verification reward unavailable")
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()
	trusted := r.Clone(ctx)
	attachments, _ := json.Marshal([]adminMailAttachment{{Type: 3, ID: 40350003, Count: 100}})
	for attempt := 0; attempt < 2; attempt++ {
		summary, err := a.adminLegacyState(trusted, id)
		if err != nil || !summary.RoleCreated || summary.RoleID != record.RoleID {
			return "", failed
		}
		form := url.Values{"expectedRevision": {summary.Revision}, "requestId": {record.RewardRequestID},
			"reason": {"发放首次验证注册邮箱奖励"}, "title": {"邮箱验证奖励"}, "sender": {"系统"},
			"content": {"感谢您验证注册邮箱！100张祈愿塔罗牌已附在本邮件中，请及时领取。"}, "attachments": {string(attachments)}}
		response, err := a.adminJavaRequest(trusted, id, http.MethodPost, "/__admin/mail/send", strings.NewReader(form.Encode()))
		if err != nil {
			return "", failed
		}
		if response.StatusCode == http.StatusConflict {
			response.Body.Close()
			continue
		}
		if response.StatusCode != http.StatusOK || response.ContentLength > adminMailResponseLimit || !strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
			response.Body.Close()
			return "", failed
		}
		body, err := io.ReadAll(io.LimitReader(response.Body, adminMailResponseLimit+1))
		response.Body.Close()
		if err != nil || len(body) > adminMailResponseLimit {
			return "", failed
		}
		var result struct {
			ID        string `json:"id"`
			Revision  string `json:"revision"`
			Duplicate bool   `json:"duplicate"`
		}
		decoder := json.NewDecoder(bytes.NewReader(body))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&result) != nil || decoder.Decode(new(any)) != io.EOF || !legacyRoleID.MatchString(result.ID) {
			return "", failed
		}
		if _, err := strconv.ParseInt(result.ID, 10, 64); err != nil {
			return "", failed
		}
		if revision, err := strconv.ParseUint(result.Revision, 10, 63); err != nil || strconv.FormatUint(revision, 10) != result.Revision {
			return "", failed
		}
		return result.ID, nil
	}
	return "", failed
}
