package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

const legacyRoleLimit = 2048

var legacyRoleID = regexp.MustCompile(`^[1-9][0-9]{0,18}$`)

type legacyRoleSummary struct {
	Version int    `json:"version"`
	Exists  bool   `json:"exists"`
	RoleID  string `json:"roleId"`
	Name    string `json:"name"`
	Head    *int   `json:"head"`
	HeadBox *int   `json:"headBox"`
}

// legacyRole exposes only the role belonging to the authenticated account.
// The Java save, rather than the separate Go prototype role, is authoritative
// for the original game's numeric RoleID and nickname.
func (a *app) legacyRole(w http.ResponseWriter, r *http.Request, id string, _ [32]byte) {
	if a.legacy == nil {
		fail(w, 503, "legacy_unavailable", "原协议服务尚未连接。")
		return
	}
	if r.URL.RawQuery != "" {
		fail(w, 400, "invalid_request", "角色摘要不接受查询参数。")
		return
	}
	player, ok := a.store.player(id)
	if !ok {
		fail(w, 401, "unauthorized", "请重新登录。")
		return
	}
	upstreamRequest, err := a.makeLegacyRequest(r, player, "/__role", nil)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法读取角色摘要。")
		return
	}
	response, err := a.legacy.client.Do(upstreamRequest)
	if err != nil {
		fail(w, 502, "legacy_upstream_failed", "原协议服务暂时不可用。")
		return
	}
	defer response.Body.Close()
	if response.StatusCode != 200 || response.ContentLength > legacyRoleLimit ||
		!strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		fail(w, 502, "legacy_role_invalid", "角色摘要暂时不可用。")
		return
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, legacyRoleLimit+1))
	if err != nil || len(data) > legacyRoleLimit {
		fail(w, 502, "legacy_role_invalid", "角色摘要暂时不可用。")
		return
	}
	role, err := parseLegacyRoleSummary(data)
	if err != nil {
		fail(w, 502, "legacy_role_invalid", "角色摘要暂时不可用。")
		return
	}
	// The Android login bridge still consumes the original four-field public
	// schema; cosmetic fields are internal to Java /__role and the chat gateway.
	writeJSON(w, 200, struct {
		Version int    `json:"version"`
		Exists  bool   `json:"exists"`
		RoleID  string `json:"roleId"`
		Name    string `json:"name"`
	}{role.Version, role.Exists, role.RoleID, role.Name})
}

// Shared by the original login summary and settings' public RID lookup. The
// Java summary is authoritative; the separate Go prototype Role is unused.
func parseLegacyRoleSummary(data []byte) (legacyRoleSummary, error) {
	invalid := errors.New("invalid legacy role summary")
	var fields map[string]json.RawMessage
	if json.Unmarshal(data, &fields) != nil || (len(fields) != 4 && len(fields) != 6) {
		return legacyRoleSummary{}, invalid
	}
	for _, key := range []string{"version", "exists", "roleId", "name"} {
		if fields[key] == nil || bytes.Equal(bytes.TrimSpace(fields[key]), []byte("null")) {
			return legacyRoleSummary{}, invalid
		}
	}
	_, hasHead := fields["head"]
	_, hasHeadBox := fields["headBox"]
	if hasHead != hasHeadBox || (hasHead && len(fields) != 6) {
		return legacyRoleSummary{}, invalid
	}
	var role legacyRoleSummary
	decode := json.NewDecoder(strings.NewReader(string(data)))
	decode.DisallowUnknownFields()
	if decode.Decode(&role) != nil || decode.Decode(new(any)) != io.EOF || role.Version != 1 ||
		(hasHead && (role.Head == nil || role.HeadBox == nil || *role.Head < 0 || *role.HeadBox < 0)) ||
		(role.Exists && (!legacyRoleID.MatchString(role.RoleID) || len(role.Name) == 0 || len(role.Name) > 128 || !utf8.ValidString(role.Name))) ||
		(!role.Exists && (role.RoleID != "" || role.Name != "")) {
		return legacyRoleSummary{}, invalid
	}
	if role.Exists {
		if _, err := strconv.ParseInt(role.RoleID, 10, 64); err != nil {
			return legacyRoleSummary{}, invalid
		}
	}
	for _, char := range role.Name {
		if unicode.IsControl(char) || unicode.Is(unicode.Cf, char) {
			return legacyRoleSummary{}, invalid
		}
	}
	return role, nil
}
