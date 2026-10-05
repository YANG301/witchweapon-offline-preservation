package main

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"
)

// This settings-only lookup is handled at the authenticated gateway. It never
// changes a game save or grants rewards, and needs no new Java server route.
func (a *app) legacyPublicRID(w http.ResponseWriter, r *http.Request, player Player) {
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", http.MethodGet)
		fail(w, 405, "method_not_allowed", "玩家 RID 查询只接受 GET。")
		return
	}
	if r.URL.RawQuery != "" || r.URL.ForceQuery || r.ContentLength > 0 || len(r.TransferEncoding) > 0 {
		fail(w, 400, "invalid_request", "玩家 RID 查询不接受参数或请求内容。")
		return
	}
	if r.Body != nil {
		body, err := io.ReadAll(io.LimitReader(r.Body, 1))
		if err != nil || len(body) != 0 {
			fail(w, 400, "invalid_request", "玩家 RID 查询不接受参数或请求内容。")
			return
		}
	}
	if a.legacy == nil {
		fail(w, 503, "legacy_unavailable", "原协议服务尚未连接。")
		return
	}
	if player.PublicRID < publicRIDMin || player.PublicRID > publicRIDMax {
		fail(w, 503, "public_rid_unavailable", "玩家 RID 暂时不可用。")
		return
	}
	role, err := a.readLegacyRoleSummary(r, player)
	if err != nil {
		fail(w, 502, "legacy_role_invalid", "角色摘要暂时不可用。")
		return
	}
	if !role.Exists {
		fail(w, 409, "role_required", "请先创建游戏角色。")
		return
	}
	writeJSON(w, 200, struct {
		RID               int    `json:"rid"`
		RoleID            string `json:"roleId"`
		EmailRewardCards  int    `json:"emailRewardCards"`
		EmailServiceReady bool   `json:"emailServiceReady"`
	}{player.PublicRID, role.RoleID, 100, a.emailVerificationReady()})
}

func (a *app) readLegacyRoleSummary(r *http.Request, player Player) (legacyRoleSummary, error) {
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	lookup := r.Clone(ctx)
	lookup.Method = http.MethodGet
	request, err := a.makeLegacyRequest(lookup, player, "/__role", nil)
	if err != nil {
		return legacyRoleSummary{}, err
	}
	response, err := a.legacy.client.Do(request)
	if err != nil {
		return legacyRoleSummary{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK || response.ContentLength > legacyRoleLimit ||
		!strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		return legacyRoleSummary{}, errors.New("invalid role response")
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, legacyRoleLimit+1))
	if err != nil || len(data) > legacyRoleLimit {
		return legacyRoleSummary{}, errors.New("invalid role response size")
	}
	return parseLegacyRoleSummary(data)
}
