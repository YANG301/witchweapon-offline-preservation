package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const chatBodyLimit = 2048
const chatResponseLimit = 64 << 10

type chatProxy struct {
	upstream url.URL
	secret   string
	client   *http.Client
}

type chatRole struct {
	id      string
	name    string
	head    int
	headBox int
}

// configureChatProxy must run before the HTTP server starts. No client-supplied
// identity, Authorization or X-WW-* header is forwarded to the chat process.
func (a *app) configureChatProxy(upstream, secret string) error {
	if upstream == "" {
		return nil
	}
	if len(secret) < 32 || len(secret) > 256 || strings.TrimSpace(secret) != secret || strings.ContainsAny(secret, "\r\n") {
		return errors.New("WW_CHAT_PROXY_SECRET 须设置为 32 至 256 字符的随机密钥")
	}
	u, err := parseLegacyUpstream(upstream)
	if err != nil {
		return err
	}
	transport := &http.Transport{
		Proxy: nil, MaxIdleConnsPerHost: 32, IdleConnTimeout: 30 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			if address != u.Host {
				return nil, errors.New("unexpected chat upstream address")
			}
			return (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, network, address)
		},
	}
	a.chat = &chatProxy{upstream: u, secret: secret,
		client: &http.Client{Transport: transport, Timeout: 32 * time.Second,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
	return nil
}

func (a *app) chatHistory(w http.ResponseWriter, r *http.Request, accountID string, _ [32]byte) {
	a.forwardChat(w, r, accountID, "/world", false)
}
func (a *app) chatEvents(w http.ResponseWriter, r *http.Request, accountID string, _ [32]byte) {
	a.forwardChat(w, r, accountID, "/world/events", false)
}
func (a *app) chatSend(w http.ResponseWriter, r *http.Request, accountID string, _ [32]byte) {
	a.forwardChat(w, r, accountID, "/world", true)
}

func (a *app) forwardChat(w http.ResponseWriter, r *http.Request, accountID, path string, sending bool) {
	if a.chat == nil {
		fail(w, 503, "chat_unavailable", "聊天服务暂时不可用。")
		return
	}
	var body []byte
	var err error
	if sending {
		if r.URL.RawQuery != "" || strings.TrimSpace(strings.Split(r.Header.Get("Content-Type"), ";")[0]) != "application/json" {
			fail(w, 400, "invalid_request", "聊天请求格式无效。")
			return
		}
		body, err = io.ReadAll(http.MaxBytesReader(w, r.Body, chatBodyLimit))
		if err != nil {
			fail(w, 413, "request_too_large", "聊天内容过长。")
			return
		}
	}
	player, ok := a.store.player(accountID)
	if !ok {
		fail(w, 401, "unauthorized", "请重新登录。")
		return
	}
	role, err := a.readChatRole(r, player)
	if err != nil {
		fail(w, 503, "role_unavailable", "暂时无法读取游戏角色。")
		return
	}
	if role.id == "" {
		fail(w, 409, "role_required", "请先创建游戏角色。")
		return
	}
	target := a.chat.upstream
	target.Path = path
	if !sending {
		target.RawQuery = r.URL.RawQuery
	}
	request, err := http.NewRequestWithContext(r.Context(), r.Method, target.String(), bytes.NewReader(body))
	if err != nil {
		fail(w, 500, "internal_error", "聊天请求失败。")
		return
	}
	request.Header.Set("X-WW-Chat-Secret", a.chat.secret)
	request.Header.Set("X-WW-Account-ID", accountID)
	request.Header.Set("X-WW-Role-ID", role.id)
	if sending {
		request.Header.Set("Content-Type", "application/json")
		request.Header.Set("X-WW-Role-Name-B64", base64.RawURLEncoding.EncodeToString([]byte(role.name)))
		request.Header.Set("X-WW-Role-Head", strconv.Itoa(role.head))
		request.Header.Set("X-WW-Role-Head-Box", strconv.Itoa(role.headBox))
	}
	response, err := a.chat.client.Do(request)
	if err != nil {
		fail(w, 502, "chat_upstream_failed", "聊天服务暂时不可用。")
		return
	}
	defer response.Body.Close()
	if response.ContentLength > chatResponseLimit ||
		!strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		fail(w, 502, "chat_response_invalid", "聊天服务响应无效。")
		return
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, chatResponseLimit+1))
	if err != nil || len(data) > chatResponseLimit || !json.Valid(data) {
		fail(w, 502, "chat_response_invalid", "聊天服务响应无效。")
		return
	}
	if retry := response.Header.Get("Retry-After"); retry != "" {
		w.Header().Set("Retry-After", retry)
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(response.StatusCode)
	_, _ = w.Write(data)
}

// The Java save is authoritative for the original APK's numeric role ID,
// nickname and selected cosmetics. The separate Go prototype role is not used.
func (a *app) readChatRole(r *http.Request, player Player) (chatRole, error) {
	if a.legacy == nil {
		return chatRole{}, errors.New("legacy service unavailable")
	}
	// A long-poll request still needs room inside the gateway's 30-second
	// response deadline. Role lookup should be a short local hop.
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	lookup := r.Clone(ctx)
	lookup.Method = http.MethodGet
	request, err := a.makeLegacyRequest(lookup, player, "/__role", nil)
	if err != nil {
		return chatRole{}, err
	}
	response, err := a.legacy.client.Do(request)
	if err != nil {
		return chatRole{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 || response.ContentLength > legacyRoleLimit ||
		!strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		return chatRole{}, errors.New("invalid role response")
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, legacyRoleLimit+1))
	if err != nil || len(data) > legacyRoleLimit {
		return chatRole{}, errors.New("role response too large")
	}
	var role struct {
		Version int    `json:"version"`
		Exists  bool   `json:"exists"`
		RoleID  string `json:"roleId"`
		Name    string `json:"name"`
		Head    *int   `json:"head"`
		HeadBox *int   `json:"headBox"`
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if dec.Decode(&role) != nil || dec.Decode(new(any)) != io.EOF || role.Version != 1 {
		return chatRole{}, errors.New("invalid role response")
	}
	if !role.Exists {
		if role.RoleID != "" || role.Name != "" || (role.Head != nil && *role.Head != 0) || (role.HeadBox != nil && *role.HeadBox != 0) {
			return chatRole{}, errors.New("invalid role response")
		}
		return chatRole{}, nil
	}
	if !legacyRoleID.MatchString(role.RoleID) || !validChatRoleName(role.Name) {
		return chatRole{}, errors.New("invalid role identity")
	}
	if _, err = strconv.ParseInt(role.RoleID, 10, 64); err != nil {
		return chatRole{}, err
	}
	// Older Java role summaries lacked these fields. Their /role/role seed
	// selected both icon and frame 1, matching the save migration fallback.
	selected := chatRole{id: role.RoleID, name: role.Name, head: 1, headBox: 1}
	if role.Head != nil {
		selected.head = *role.Head
	}
	if role.HeadBox != nil {
		selected.headBox = *role.HeadBox
	}
	if selected.head == 0 {
		selected.head = 1
	}
	if selected.headBox == 0 {
		selected.headBox = 1
	}
	if selected.head < 0 || selected.head > 1<<31-1 || selected.headBox < 0 || selected.headBox > 1<<31-1 {
		return chatRole{}, errors.New("invalid role cosmetics")
	}
	return selected, nil
}

func validChatRoleName(name string) bool {
	if len(name) == 0 || len(name) > 128 || !utf8.ValidString(name) || strings.TrimSpace(name) != name {
		return false
	}
	for _, char := range name {
		if unicode.IsControl(char) || unicode.Is(unicode.Cf, char) {
			return false
		}
	}
	return true
}
