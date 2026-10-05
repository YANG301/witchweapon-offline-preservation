package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const adminMailRequestLimit = 8192
const adminMailResponseLimit = 2048
const adminMailCatalogLimit = 131072

var adminMailRequestID = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

type adminMailAttachment struct {
	Type  int   `json:"type"`
	ID    int64 `json:"id"`
	Count int64 `json:"count"`
}

type adminMailInput struct {
	ExpectedRevision string                `json:"expectedRevision"`
	RequestID        string                `json:"requestId"`
	Reason           string                `json:"reason"`
	Title            string                `json:"title"`
	Sender           string                `json:"sender"`
	Content          string                `json:"content"`
	Attachments      []adminMailAttachment `json:"attachments"`
}

type adminCatalogEntry struct {
	Type     int    `json:"type"`
	ID       int64  `json:"id"`
	Name     string `json:"name"`
	MaxCount int64  `json:"maxCount"`
}

func decodeAdminMail(w http.ResponseWriter, r *http.Request, target *adminMailInput) bool {
	if strings.TrimSpace(strings.Split(r.Header.Get("Content-Type"), ";")[0]) != "application/json" {
		fail(w, 415, "invalid_request", "请使用 JSON 格式提交邮件。")
		return false
	}
	r.Body = http.MaxBytesReader(w, r.Body, adminMailRequestLimit)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	err := decoder.Decode(target)
	if err == nil {
		if tailErr := decoder.Decode(new(any)); tailErr != io.EOF {
			if tailErr == nil {
				err = errors.New("multiple JSON values")
			} else {
				err = tailErr
			}
		}
	}
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			fail(w, 413, "request_too_large", "邮件内容过长。")
		} else {
			fail(w, 400, "invalid_request", "邮件格式不正确或包含未知字段。")
		}
		return false
	}
	return true
}

func adminMailText(value string, minRunes, maxRunes, maxBytes int, allowNewline bool) bool {
	if !utf8.ValidString(value) || len(value) > maxBytes ||
		utf8.RuneCountInString(value) < minRunes || utf8.RuneCountInString(value) > maxRunes ||
		strings.TrimSpace(value) != value {
		return false
	}
	for _, ch := range value {
		if ch == '<' || ch == '>' || unicode.Is(unicode.Cf, ch) ||
			(unicode.IsControl(ch) && !(allowNewline && ch == '\n')) {
			return false
		}
	}
	return true
}

func validateAdminMail(input adminMailInput) bool {
	revision, err := strconv.ParseUint(input.ExpectedRevision, 10, 63)
	if err != nil || strconv.FormatUint(revision, 10) != input.ExpectedRevision ||
		!adminMailRequestID.MatchString(input.RequestID) ||
		!adminMailText(input.Reason, 8, 200, 512, false) ||
		!adminMailText(input.Title, 1, 60, 256, false) ||
		!adminMailText(input.Sender, 1, 24, 128, false) ||
		!adminMailText(input.Content, 1, 1000, 4096, true) ||
		len(input.Attachments) > 5 {
		return false
	}
	seen := make(map[[2]int64]struct{}, len(input.Attachments))
	for _, attachment := range input.Attachments {
		maximum := int64(0)
		switch attachment.Type {
		case 13:
			if attachment.ID != 0 {
				return false
			}
			maximum = 1000000
		case 98:
			if attachment.ID != 0 {
				return false
			}
			maximum = 100000
		case 3, 2:
			if attachment.ID <= 0 {
				return false
			}
			maximum = 999
		default:
			return false
		}
		if attachment.Count <= 0 || attachment.Count > maximum {
			return false
		}
		key := [2]int64{int64(attachment.Type), attachment.ID}
		if _, duplicate := seen[key]; duplicate {
			return false
		}
		seen[key] = struct{}{}
	}
	return true
}

func (a *app) adminSendMail(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		fail(w, 400, "invalid_request", "邮件路径无效。")
		return
	}
	id := r.PathValue("id")
	if !adminAccountID.MatchString(id) {
		fail(w, 404, "not_found", "没有找到该账号。")
		return
	}
	if _, found := a.store.player(id); !found {
		fail(w, 404, "not_found", "没有找到该账号。")
		return
	}
	var input adminMailInput
	if !decodeAdminMail(w, r, &input) {
		return
	}
	if !validateAdminMail(input) {
		fail(w, 400, "invalid_request", "邮件、物资或操作原因无效。")
		return
	}
	attachments, err := json.Marshal(input.Attachments)
	if err != nil {
		fail(w, 500, "internal_error", "邮件暂时无法发送。")
		return
	}
	form := url.Values{
		"expectedRevision": {input.ExpectedRevision},
		"requestId":        {input.RequestID},
		"reason":           {input.Reason},
		"title":            {input.Title},
		"sender":           {input.Sender},
		"content":          {input.Content},
		"attachments":      {string(attachments)},
	}
	response, err := a.adminJavaRequest(r, id, http.MethodPost, "/__admin/mail/send", strings.NewReader(form.Encode()))
	if err != nil {
		fail(w, 502, "legacy_unavailable", "游戏邮件服务暂时不可用；请使用相同请求编号重试。")
		return
	}
	defer response.Body.Close()
	switch response.StatusCode {
	case http.StatusNotFound:
		fail(w, 409, "save_not_started", "该账号尚未创建游戏角色。")
		return
	case http.StatusConflict:
		fail(w, 409, "save_conflict", "存档已变化或请求编号被占用，请刷新后核对。")
		return
	case http.StatusUnprocessableEntity, http.StatusBadRequest:
		fail(w, 422, "invalid_mail", "邮件或附件未通过游戏存档校验。")
		return
	case http.StatusOK:
	default:
		fail(w, 502, "legacy_unavailable", "游戏邮件服务暂时不可用；请使用相同请求编号重试。")
		return
	}
	if response.ContentLength > adminMailResponseLimit ||
		!strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		fail(w, 502, "legacy_unavailable", "游戏邮件响应无效；请使用相同请求编号重试。")
		return
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, adminMailResponseLimit+1))
	if err != nil || len(body) > adminMailResponseLimit {
		fail(w, 502, "legacy_unavailable", "游戏邮件响应无效；请使用相同请求编号重试。")
		return
	}
	var result struct {
		ID        string `json:"id"`
		Revision  string `json:"revision"`
		Duplicate bool   `json:"duplicate"`
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&result) != nil || decoder.Decode(new(any)) != io.EOF ||
		result.ID == "" || result.Revision == "" {
		fail(w, 502, "legacy_unavailable", "游戏邮件响应无效；请使用相同请求编号重试。")
		return
	}
	writeJSON(w, 200, result)
}

func (a *app) adminMailCatalog(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		fail(w, 400, "invalid_request", "物资目录路径无效。")
		return
	}
	id := r.PathValue("id")
	if !adminAccountID.MatchString(id) {
		fail(w, 404, "not_found", "没有找到该账号。")
		return
	}
	if _, found := a.store.player(id); !found {
		fail(w, 404, "not_found", "没有找到该账号。")
		return
	}
	response, err := a.adminJavaRequest(r, id, http.MethodGet, "/__admin/mail/catalog", nil)
	if err != nil {
		fail(w, 502, "legacy_unavailable", "游戏物资目录暂时不可用。")
		return
	}
	defer response.Body.Close()
	if response.StatusCode != 200 || response.ContentLength > adminMailCatalogLimit ||
		!strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		fail(w, 502, "legacy_unavailable", "游戏物资目录暂时不可用。")
		return
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, adminMailCatalogLimit+1))
	if err != nil || len(body) > adminMailCatalogLimit {
		fail(w, 502, "legacy_unavailable", "游戏物资目录暂时不可用。")
		return
	}
	var catalog struct {
		Version int                 `json:"version"`
		Entries []adminCatalogEntry `json:"entries"`
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&catalog) != nil || decoder.Decode(new(any)) != io.EOF ||
		catalog.Version != 1 || len(catalog.Entries) < 2 || len(catalog.Entries) > 2000 {
		fail(w, 502, "legacy_unavailable", "游戏物资目录格式无效。")
		return
	}
	seen := make(map[[2]int64]struct{}, len(catalog.Entries))
	for _, entry := range catalog.Entries {
		if len(entry.Name) == 0 || len(entry.Name) > 96 || !utf8.ValidString(entry.Name) ||
			entry.MaxCount < 1 || entry.MaxCount > 1000000 ||
			(entry.Type != 2 && entry.Type != 3 && entry.Type != 13 && entry.Type != 98) ||
			((entry.Type == 13 || entry.Type == 98) && entry.ID != 0) ||
			((entry.Type == 2 || entry.Type == 3) && entry.ID <= 0) {
			fail(w, 502, "legacy_unavailable", "游戏物资目录格式无效。")
			return
		}
		key := [2]int64{int64(entry.Type), entry.ID}
		if _, duplicate := seen[key]; duplicate {
			fail(w, 502, "legacy_unavailable", "游戏物资目录格式无效。")
			return
		}
		seen[key] = struct{}{}
	}
	namesJSON, err := adminAssets.ReadFile("admin/mail_catalog_names.json")
	if err != nil {
		fail(w, 500, "internal_error", "物资名称暂时不可用。")
		return
	}
	var names map[string]string
	if json.Unmarshal(namesJSON, &names) != nil {
		fail(w, 500, "internal_error", "物资名称暂时不可用。")
		return
	}
	for i := range catalog.Entries {
		entry := &catalog.Entries[i]
		if name := names[strconv.Itoa(entry.Type)+":"+strconv.FormatInt(entry.ID, 10)]; name != "" && len(name) <= 96 && utf8.ValidString(name) {
			entry.Name = name
		}
	}
	writeJSON(w, 200, catalog)
}
