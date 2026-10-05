package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const legacyRequestLimit = 1 << 20
const legacyResponseLimit = 8 << 20
const legacyStateLimit = 64 << 10
const legacyPrefix = "/api/v1/legacy"

var mazeEnergyField = regexp.MustCompile(`^mazeEnergy_[0-9]{1,32}$`)
var mirroredFields = map[string]bool{
	"version": true, "name": true, "gold": true, "rmb": true,
	"stamina": true, "activityStamina": true, "inventoryRevision": true,
	"collectionRevision": true, "mazeRound": true, "mazeHP": true,
	"active": true, "activeStage": true, "battleMazeRound": true,
	"startKey": true,
}

// The first path segments come from the preservation project's offline
// response set. The proxy does not assume every route has dynamic logic.
var legacySegments = map[string]bool{
	"achievement": true, "activity": true, "ap": true,
	"backpack": true, "challenge": true, "combat": true, "csc": true,
	"draw": true, "evnInfo": true, "fashion": true, "game": true,
	"guide": true, "guild": true, "hello": true,
	"level": true, "login": true, "mail": true,
	"mini": true, "mirror": true, "misc": true, "Notice": true,
	"phone": true, "redeemcode": true, "resource": true, "role": true,
	"servant": true, "shop": true, "story": true, "task": true,
	"test": true, "time": true, "timer": true, "vip": true,
}

type legacyProxy struct {
	upstream url.URL
	secret   string
	client   *http.Client
}

func legacyPathAllowed(path string) bool {
	if !strings.HasPrefix(path, "/") || strings.Contains(path, "\\") || strings.Contains(path, "//") || strings.Contains(path, "..") {
		return false
	}
	check := path
	if strings.HasPrefix(check, "/game/") {
		check = strings.TrimPrefix(check, "/game")
	}
	if strings.HasPrefix(check, "/account/") || check == "/account" || check == "/getversion" || check == "/m.version" || strings.HasSuffix(strings.ToLower(check), ".env") || strings.HasSuffix(strings.ToLower(check), ".mapping") {
		return false
	}
	first, _, _ := strings.Cut(strings.TrimPrefix(path, "/"), "/")
	return legacySegments[first]
}

func parseLegacyUpstream(raw string) (url.URL, error) {
	if raw == "" {
		return url.URL{}, errors.New("missing upstream")
	}
	if !strings.Contains(raw, "://") {
		raw = "http://" + raw
	}
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "http" || u.User != nil || (u.Path != "" && u.Path != "/") || u.RawQuery != "" || u.Fragment != "" {
		return url.URL{}, errors.New("上游必须是没有路径或凭据的 HTTP 回环地址")
	}
	host, port, err := net.SplitHostPort(u.Host)
	if err != nil || port == "" {
		return url.URL{}, errors.New("上游地址必须包含端口")
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return url.URL{}, errors.New("上游只允许数字形式的回环 IP")
	}
	return *u, nil
}

// configureLegacyProxy must run before ServeHTTP is used. The shared secret is
// injected only into the Go-to-Java hop, never accepted from an outside caller.
func (a *app) configureLegacyProxy(upstream, secret string) error {
	if upstream == "" {
		return nil
	}
	if len(secret) < 32 || len(secret) > 256 || strings.TrimSpace(secret) != secret || strings.ContainsAny(secret, "\r\n") {
		return errors.New("WW_LEGACY_PROXY_SECRET 须设置为 32 至 256 字符的随机密钥")
	}
	u, err := parseLegacyUpstream(upstream)
	if err != nil {
		return err
	}
	transport := &http.Transport{
		Proxy:                 nil,
		MaxIdleConnsPerHost:   4,
		IdleConnTimeout:       30 * time.Second,
		ResponseHeaderTimeout: 20 * time.Second,
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			if address != u.Host {
				return nil, errors.New("unexpected upstream address")
			}
			return (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, network, address)
		},
	}
	a.legacy = &legacyProxy{upstream: u, secret: secret, client: &http.Client{Transport: transport, Timeout: 25 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
	return nil
}

func (a *app) legacyRoute(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodPost {
		w.Header().Set("Allow", "GET, POST")
		fail(w, 405, "method_not_allowed", "原协议只接受 GET 或 POST。")
		return
	}
	originalPath := strings.TrimPrefix(r.URL.Path, legacyPrefix)
	if !legacyPathAllowed(originalPath) || r.URL.EscapedPath() != r.URL.Path {
		fail(w, 404, "not_found", "没有找到该接口。")
		return
	}
	a.auth(func(w http.ResponseWriter, r *http.Request, id string, _ [32]byte) {
		a.forwardLegacy(w, r, id, originalPath)
	})(w, r)
}

func (a *app) forwardLegacy(w http.ResponseWriter, r *http.Request, id, originalPath string) {
	player, ok := a.store.player(id)
	if !ok {
		fail(w, 401, "unauthorized", "请重新登录。")
		return
	}
	if originalPath == "/role/publicRid" {
		a.legacyPublicRID(w, r, player)
		return
	}
	if originalPath == "/role/email/status" || originalPath == "/role/email/send" || originalPath == "/role/email/verify" {
		a.legacyEmailVerification(w, r, player, originalPath)
		return
	}
	if a.legacy == nil {
		fail(w, 503, "legacy_unavailable", "原协议服务尚未连接。")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, legacyRequestLimit)
	body, err := io.ReadAll(r.Body)
	if err != nil {
		var large *http.MaxBytesError
		if errors.As(err, &large) {
			fail(w, 413, "request_too_large", "请求内容过长。")
		} else {
			fail(w, 400, "invalid_request", "请求内容无法读取。")
		}
		return
	}
	upstreamRequest, err := a.makeLegacyRequest(r, player, originalPath, body)
	if err != nil {
		fail(w, 400, "invalid_request", "请求路径无效。")
		return
	}
	response, err := a.legacy.client.Do(upstreamRequest)
	if err != nil {
		fail(w, 502, "legacy_upstream_failed", "原协议服务暂时不可用。")
		return
	}
	defer response.Body.Close()
	if response.ContentLength > legacyResponseLimit {
		fail(w, 502, "legacy_response_too_large", "原协议响应超出限制。")
		return
	}
	responseBody, err := io.ReadAll(io.LimitReader(response.Body, legacyResponseLimit+1))
	if err != nil || len(responseBody) > legacyResponseLimit {
		fail(w, 502, "legacy_response_invalid", "原协议响应无法读取。")
		return
	}
	if contentType := response.Header.Get("Content-Type"); contentType != "" {
		w.Header().Set("Content-Type", contentType)
	}
	w.Header().Set("Content-Length", fmt.Sprint(len(responseBody)))
	if r.Method == http.MethodPost && response.StatusCode == http.StatusOK &&
		(originalPath == "/role/head/change" || originalPath == "/role/headbox/change") {
		a.refreshRTMCosmetics(id)
	}
	w.WriteHeader(response.StatusCode)
	_, _ = w.Write(responseBody)
}

func (a *app) makeLegacyRequest(r *http.Request, player Player, path string, body []byte) (*http.Request, error) {
	target := a.legacy.upstream
	target.Path = path
	if path != "/__state" && path != "/__role" {
		target.RawQuery = r.URL.RawQuery
	}
	request, err := http.NewRequestWithContext(r.Context(), r.Method, target.String(), bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	// Only these fields cross the trust boundary. In particular, caller-supplied
	// X-WW-*, Authorization and Cookie headers are never copied to Java.
	if contentType := r.Header.Get("Content-Type"); contentType != "" && path != "/__state" && path != "/__role" {
		request.Header.Set("Content-Type", contentType)
	}
	if accept := r.Header.Get("Accept"); accept != "" && path != "/__state" && path != "/__role" {
		request.Header.Set("Accept", accept)
	}
	request.Header.Set("X-WW-Account-ID", player.ID)
	request.Header.Set("X-WW-Public-RID", strconv.Itoa(player.PublicRID))
	if player.Role != nil {
		request.Header.Set("X-WW-Role-ID", player.Role.ID)
	}
	request.Header.Set("X-WW-Proxy-Secret", a.legacy.secret)
	return request, nil
}

// legacyState mirrors only the author Lua scripts' expected local-save fields.
// It filters a second time even though Java /__state itself uses a whitelist.
func (a *app) legacyState(w http.ResponseWriter, r *http.Request, id string, _ [32]byte) {
	if a.legacy == nil {
		fail(w, 503, "legacy_unavailable", "原协议服务尚未连接。")
		return
	}
	if r.URL.RawQuery != "" {
		fail(w, 400, "invalid_request", "状态镜像不接受查询参数。")
		return
	}
	player, ok := a.store.player(id)
	if !ok {
		fail(w, 401, "unauthorized", "请重新登录。")
		return
	}
	upstreamRequest, err := a.makeLegacyRequest(r, player, "/__state", nil)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法读取游戏状态。")
		return
	}
	response, err := a.legacy.client.Do(upstreamRequest)
	if err != nil {
		fail(w, 502, "legacy_upstream_failed", "原协议服务暂时不可用。")
		return
	}
	defer response.Body.Close()
	if response.StatusCode != 200 || response.ContentLength > legacyStateLimit || !strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		fail(w, 502, "legacy_state_invalid", "游戏状态镜像暂时不可用。")
		return
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, legacyStateLimit+1))
	if err != nil || len(data) > legacyStateLimit {
		fail(w, 502, "legacy_state_invalid", "游戏状态镜像暂时不可用。")
		return
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil || raw == nil {
		fail(w, 502, "legacy_state_invalid", "游戏状态镜像暂时不可用。")
		return
	}
	var version int
	var name string
	if err := json.Unmarshal(raw["version"], &version); err != nil || version != 1 {
		fail(w, 502, "legacy_state_invalid", "游戏状态镜像版本无效。")
		return
	}
	if err := json.Unmarshal(raw["name"], &name); err != nil || name == "" {
		fail(w, 502, "legacy_state_invalid", "游戏状态镜像角色无效。")
		return
	}
	filtered := make(map[string]json.RawMessage)
	for key, value := range raw {
		if mirroredFields[key] || mazeEnergyField.MatchString(key) {
			if !validMirrorScalar(key, value) {
				fail(w, 502, "legacy_state_invalid", "游戏状态镜像字段无效。")
				return
			}
			filtered[key] = value
		}
	}
	writeJSON(w, 200, filtered)
}

func validMirrorScalar(key string, value json.RawMessage) bool {
	switch key {
	case "name", "startKey":
		var text string
		return json.Unmarshal(value, &text) == nil && len(text) <= 128
	case "active":
		var active bool
		return json.Unmarshal(value, &active) == nil
	case "mazeHP":
		var hp float64
		return json.Unmarshal(value, &hp) == nil && !math.IsNaN(hp) && hp >= 0 && hp <= 1
	}
	if mazeEnergyField.MatchString(key) {
		var energy float64
		return json.Unmarshal(value, &energy) == nil && !math.IsNaN(energy) && energy >= 0 && energy <= 1000
	}
	var integer int64
	return json.Unmarshal(value, &integer) == nil && integer >= 0
}
