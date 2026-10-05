package main

import (
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/mail"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

const passwordIterations = 600000
const requestLimit = 4096
const sessionLifetime = 24 * time.Hour
const refreshLifetime = 30 * 24 * time.Hour
const maxRefreshDevices = 5
const refreshRatePerMinute = 3000

type StoryLine struct {
	Speaker string `json:"speaker"`
	Text    string `json:"text"`
}
type Story struct {
	ID    string      `json:"id"`
	Title string      `json:"title"`
	Lines []StoryLine `json:"lines"`
}
type storySummary struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	LineCount int    `json:"lineCount"`
}
type authResponse struct {
	Token            string     `json:"token"`
	ExpiresAt        time.Time  `json:"expiresAt"`
	RefreshToken     string     `json:"refreshToken,omitempty"`
	RefreshExpiresAt *time.Time `json:"refreshExpiresAt,omitempty"`
	Player           Player     `json:"player"`
}
type session struct {
	UserID    string
	ExpiresAt time.Time
	FamilyID  string
}
type rateEntry struct {
	Count int
	Until time.Time
}

type app struct {
	store             *store
	legacy            *legacyProxy
	chat              *chatProxy
	admin             *adminConfig
	mailCampaigns     *adminCampaignStore
	emailVerification *emailVerificationConfig
	stories           map[string]Story
	storyList         []storySummary
	mux               *http.ServeMux
	mu                sync.Mutex
	credentialMu      sync.RWMutex
	sessions          map[[32]byte]session
	rtmAccounts       map[string]*rtmAccount
	rtmConnTotal      int
	rates             map[string]rateEntry
	refreshRates      map[string]rateEntry
	kdfSlots          chan struct{}
	dummySalt         []byte
	now               func() time.Time
}

var storyIDPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,63}$`)

func validStoryID(s string) bool     { return storyIDPattern.MatchString(s) }
func normalizeEmail(s string) string { return strings.ToLower(strings.TrimSpace(s)) }
func validNickname(s string) bool {
	if !utf8.ValidString(s) || strings.TrimSpace(s) != s {
		return false
	}
	n := utf8.RuneCountInString(s)
	if n < 2 || n > 16 {
		return false
	}
	for _, r := range s {
		if unicode.IsControl(r) || unicode.Is(unicode.Cf, r) {
			return false
		}
	}
	return true
}
func validEmail(s string) bool {
	if len(s) < 3 || len(s) > 254 || !utf8.ValidString(s) {
		return false
	}
	a, err := mail.ParseAddress(s)
	return err == nil && a.Address == s && a.Name == "" && strings.Contains(s, "@")
}

func loadStories(path string) (map[string]Story, []storySummary, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, nil, err
	}
	defer f.Close()
	var data struct {
		Stories []Story `json:"stories"`
	}
	dec := json.NewDecoder(io.LimitReader(f, 64<<20))
	dec.DisallowUnknownFields()
	if err = dec.Decode(&data); err != nil {
		return nil, nil, err
	}
	if err = dec.Decode(new(any)); err != io.EOF {
		return nil, nil, errors.New("stories contain trailing data")
	}
	if len(data.Stories) == 0 {
		return nil, nil, errors.New("stories must not be empty")
	}
	stories := make(map[string]Story)
	list := make([]storySummary, 0, len(data.Stories))
	for _, story := range data.Stories {
		if !validStoryID(story.ID) || strings.TrimSpace(story.Title) == "" || len(story.Lines) == 0 {
			return nil, nil, errors.New("invalid story")
		}
		if _, ok := stories[story.ID]; ok {
			return nil, nil, errors.New("duplicate story id")
		}
		for _, line := range story.Lines {
			if !utf8.ValidString(line.Text) || strings.TrimSpace(line.Text) == "" {
				return nil, nil, errors.New("empty or invalid story text")
			}
		}
		stories[story.ID] = story
		list = append(list, storySummary{story.ID, story.Title, len(story.Lines)})
	}
	return stories, list, nil
}

func newApp(dataDir, storyFile string) (*app, error) {
	st, err := openStore(dataDir)
	if err != nil {
		return nil, err
	}
	stories, list, err := loadStories(storyFile)
	if err != nil {
		_ = st.Close()
		return nil, err
	}
	salt := make([]byte, 32)
	if _, err = rand.Read(salt); err != nil {
		_ = st.Close()
		return nil, err
	}
	a := &app{store: st, stories: stories, storyList: list, mux: http.NewServeMux(), sessions: make(map[[32]byte]session), rtmAccounts: make(map[string]*rtmAccount), rates: make(map[string]rateEntry), refreshRates: make(map[string]rateEntry), kdfSlots: make(chan struct{}, 2), dummySalt: salt, now: time.Now}
	a.mailCampaigns, err = openAdminCampaignStore(dataDir)
	if err != nil {
		// Mail task corruption must never take player authentication or game
		// traffic offline. This subsystem fails closed while preserving files.
		a.mailCampaigns = disabledAdminCampaignStore()
	}
	a.mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]string{"status": "ok", "version": "prototype-1"})
	})
	a.mux.HandleFunc("POST /api/v1/auth/register", a.register)
	a.mux.HandleFunc("POST /api/v1/auth/login", a.login)
	a.mux.HandleFunc("POST /api/v1/auth/password/send", a.sendPasswordRecovery)
	a.mux.HandleFunc("POST /api/v1/auth/password/reset", a.resetPasswordRecovery)
	a.mux.HandleFunc("POST /api/v1/auth/refresh", a.refresh)
	a.mux.HandleFunc("POST /api/v1/auth/revoke", a.revoke)
	a.mux.HandleFunc("POST /api/v1/auth/logout", a.auth(a.logout))
	a.mux.HandleFunc("GET /api/v1/me", a.auth(a.me))
	a.mux.HandleFunc("GET /api/v1/role", a.auth(a.getRole))
	a.mux.HandleFunc("POST /api/v1/role", a.auth(a.createRole))
	a.mux.HandleFunc("GET /api/v1/stories", a.auth(a.listStories))
	a.mux.HandleFunc("GET /api/v1/stories/{id}", a.auth(a.getStory))
	a.mux.HandleFunc("PUT /api/v1/progress/{id}", a.auth(a.progress))
	a.mux.HandleFunc("GET /api/v1/legacy-state", a.auth(a.legacyState))
	a.mux.HandleFunc("GET /api/v1/legacy-role", a.auth(a.legacyRole))
	a.mux.HandleFunc("GET /api/v1/chat/world", a.auth(a.chatHistory))
	a.mux.HandleFunc("GET /api/v1/chat/world/events", a.auth(a.chatEvents))
	a.mux.HandleFunc("POST /api/v1/chat/world", a.auth(a.chatSend))
	a.mux.HandleFunc("GET /api/v1/chat/rtm", a.auth(a.chatRTM))
	a.mux.HandleFunc("/api/v1/legacy/", a.legacyRoute)
	a.mountAdmin()
	a.mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { fail(w, 404, "not_found", "没有找到该接口。") })
	return a, nil
}

func (a *app) Close() error {
	if a.emailVerification != nil {
		a.emailVerification.recoveryWG.Wait()
	}
	a.mailCampaigns.close()
	return a.store.Close()
}

func (a *app) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if strings.HasPrefix(r.URL.Path, "/admin/") {
		w.Header().Set("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("X-Frame-Options", "DENY")
	}
	a.mux.ServeHTTP(w, r)
}
func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}
func fail(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code, "message": message}})
}
func decodeRequest(w http.ResponseWriter, r *http.Request, target any) bool {
	if strings.TrimSpace(strings.Split(r.Header.Get("Content-Type"), ";")[0]) != "application/json" {
		fail(w, 415, "invalid_request", "请使用 JSON 格式提交请求。")
		return false
	}
	r.Body = http.MaxBytesReader(w, r.Body, requestLimit)
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	err := dec.Decode(target)
	if err == nil {
		if tailErr := dec.Decode(new(any)); tailErr != io.EOF {
			if tailErr == nil {
				err = errors.New("multiple JSON values")
			} else {
				err = tailErr
			}
		}
	}
	if err != nil {
		var large *http.MaxBytesError
		if errors.As(err, &large) {
			fail(w, 413, "request_too_large", "请求内容过长。")
		} else {
			fail(w, 400, "invalid_request", "请求格式不正确或包含未知字段。")
		}
		return false
	}
	return true
}

func (a *app) allowAuth(w http.ResponseWriter, r *http.Request) bool {
	return a.allowRate(w, r, a.rates, 20, "登录或注册请求过于频繁，请稍后再试。")
}

func (a *app) allowRefresh(w http.ResponseWriter, r *http.Request) bool {
	return a.allowRate(w, r, a.refreshRates, refreshRatePerMinute, "刷新或退出请求过于频繁，请稍后再试。")
}

func (a *app) allowRate(w http.ResponseWriter, r *http.Request, rates map[string]rateEntry, limit int, message string) bool {
	ip := authRateKey(r)
	now := a.now()
	a.mu.Lock()
	defer a.mu.Unlock()
	for key, e := range rates {
		if !now.Before(e.Until) {
			delete(rates, key)
		}
	}
	e, exists := rates[ip]
	if !exists {
		if len(rates) >= 4096 {
			w.Header().Set("Retry-After", "60")
			fail(w, 429, "rate_limited", "请求较多，请稍后再试。")
			return false
		}
		e.Until = now.Add(time.Minute)
	}
	if e.Count >= limit {
		w.Header().Set("Retry-After", "60")
		fail(w, 429, "rate_limited", message)
		return false
	}
	e.Count++
	rates[ip] = e
	return true
}

// authRateKey trusts X-Real-IP only on the local Nginx-to-Go hop. Nginx must
// replace this header with $remote_addr; a public TCP peer cannot choose its
// own rate-limit bucket by sending a forged header.
func authRateKey(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	peer := net.ParseIP(host)
	if peer == nil {
		return host
	}
	if peer.IsLoopback() {
		values := r.Header.Values("X-Real-IP")
		if len(values) == 1 {
			if realIP := net.ParseIP(values[0]); realIP != nil {
				return realIP.String()
			}
		}
	}
	return peer.String()
}

type credentialsRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
	Remember bool   `json:"remember,omitempty"`
}

func (a *app) credentialsInput(w http.ResponseWriter, r *http.Request) (credentialsRequest, bool) {
	var c credentialsRequest
	if !a.allowAuth(w, r) || !decodeRequest(w, r, &c) {
		return c, false
	}
	c.Email = normalizeEmail(c.Email)
	if !validEmail(c.Email) || !utf8.ValidString(c.Password) || utf8.RuneCountInString(c.Password) < 12 || utf8.RuneCountInString(c.Password) > 128 {
		fail(w, 400, "invalid_request", "请输入有效邮箱，密码长度须为 12 至 128 个字符。")
		return c, false
	}
	select {
	case a.kdfSlots <- struct{}{}:
		return c, true
	default:
		w.Header().Set("Retry-After", "3")
		fail(w, 429, "server_busy", "正在处理其他登录请求，请稍后再试。")
		return c, false
	}
}
func randomID(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

func (a *app) register(w http.ResponseWriter, r *http.Request) {
	c, ok := a.credentialsInput(w, r)
	if !ok {
		return
	}
	defer func() { <-a.kdfSlots }()
	a.credentialMu.RLock()
	defer a.credentialMu.RUnlock()
	salt := make([]byte, 32)
	if _, err := rand.Read(salt); err != nil {
		fail(w, 500, "internal_error", "暂时无法创建账号。")
		return
	}
	hash, err := pbkdf2.Key(sha256.New, c.Password, salt, passwordIterations, 32)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法创建账号。")
		return
	}
	id, err := randomID(16)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法创建账号。")
		return
	}
	user := &account{ID: id, Email: c.Email, Salt: salt, Hash: hash, Iterations: passwordIterations, Progress: make(map[string]Progress)}
	if err := a.store.add(user); err != nil {
		if errors.Is(err, errDuplicate) {
			fail(w, 409, "email_exists", "该邮箱已经注册，请登录。")
		} else {
			fail(w, 500, "storage_error", "保存账号失败，请稍后再试。")
		}
		return
	}
	result, err := a.issueAuth(user.ID, c.Remember)
	if err != nil {
		fail(w, 500, "storage_error", "账号已创建，但保存登录信息失败；请稍后用该邮箱和密码登录。")
		return
	}
	writeJSON(w, 201, result)
}

func (a *app) login(w http.ResponseWriter, r *http.Request) {
	c, ok := a.credentialsInput(w, r)
	if !ok {
		return
	}
	defer func() { <-a.kdfSlots }()
	// Keep password authentication and session issuance on the same side of a
	// reset. An already-checked old password cannot issue a post-reset session.
	a.credentialMu.RLock()
	defer a.credentialMu.RUnlock()
	user, exists := a.store.credentials(c.Email)
	salt, expected := a.dummySalt, make([]byte, 32)
	if exists {
		salt, expected = user.Salt, user.Hash
	}
	hash, err := pbkdf2.Key(sha256.New, c.Password, salt, passwordIterations, 32)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法登录。")
		return
	}
	matched := subtle.ConstantTimeCompare(hash, expected) == 1
	if !exists || !matched {
		fail(w, 401, "invalid_credentials", "邮箱或密码不正确。")
		return
	}
	result, err := a.issueAuth(user.ID, c.Remember)
	if err != nil {
		fail(w, 500, "storage_error", "保存登录信息失败，请稍后再试。")
		return
	}
	writeJSON(w, 200, result)
}

func tokenHash(token string) string {
	hash := sha256.Sum256([]byte(token))
	return hex.EncodeToString(hash[:])
}

func validRefreshToken(token string) bool {
	if len(token) != 43 {
		return false
	}
	decoded, err := base64.RawURLEncoding.DecodeString(token)
	return err == nil && len(decoded) == 32 && base64.RawURLEncoding.EncodeToString(decoded) == token
}

func (a *app) issueAuth(userID string, remember bool) (authResponse, error) {
	token, err := randomID(32)
	if err != nil {
		return authResponse{}, err
	}
	now := a.now().UTC()
	expiry := now.Add(sessionLifetime).UTC()
	var player Player
	var evicted []string
	var refreshToken, familyID string
	var refreshExpiresAt *time.Time
	if remember {
		refreshToken, err = randomID(32)
		if err != nil {
			return authResponse{}, err
		}
		familyID, err = randomID(16)
		if err != nil {
			return authResponse{}, err
		}
		player, evicted, err = a.store.issueRefresh(userID, tokenHash(refreshToken), familyID, now)
		if err != nil {
			return authResponse{}, err
		}
		deadline := now.Add(refreshLifetime).UTC()
		refreshExpiresAt = &deadline
	} else {
		var ok bool
		player, ok = a.store.player(userID)
		if !ok {
			return authResponse{}, errors.New("missing account")
		}
	}
	a.mu.Lock()
	for key, s := range a.sessions {
		if !now.Before(s.ExpiresAt) || containsFamily(evicted, s.FamilyID) {
			delete(a.sessions, key)
		}
	}
	a.sessions[sha256.Sum256([]byte(token))] = session{UserID: userID, ExpiresAt: expiry, FamilyID: familyID}
	a.mu.Unlock()
	return authResponse{Token: token, ExpiresAt: expiry, RefreshToken: refreshToken, RefreshExpiresAt: refreshExpiresAt, Player: player}, nil
}

func containsFamily(families []string, family string) bool {
	for _, candidate := range families {
		if family == candidate {
			return true
		}
	}
	return false
}

type refreshRequest struct {
	RefreshToken string `json:"refreshToken"`
}

func (a *app) refreshInput(w http.ResponseWriter, r *http.Request) (refreshRequest, bool) {
	var input refreshRequest
	if !a.allowRefresh(w, r) || !decodeRequest(w, r, &input) {
		return input, false
	}
	if !validRefreshToken(input.RefreshToken) {
		fail(w, 400, "invalid_request", "刷新凭据格式不正确。")
		return input, false
	}
	return input, true
}

func (a *app) refresh(w http.ResponseWriter, r *http.Request) {
	input, ok := a.refreshInput(w, r)
	if !ok {
		return
	}
	a.credentialMu.RLock()
	defer a.credentialMu.RUnlock()
	accessToken, err := randomID(32)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法刷新登录。")
		return
	}
	newRefreshToken, err := randomID(32)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法刷新登录。")
		return
	}
	now := a.now().UTC()
	grant, player, err := a.store.rotateRefresh(tokenHash(input.RefreshToken), tokenHash(newRefreshToken), now)
	if errors.Is(err, errInvalidRefresh) {
		fail(w, 401, "invalid_refresh_token", "登录已失效，请重新登录。")
		return
	}
	if err != nil {
		fail(w, 500, "storage_error", "保存登录信息失败，请稍后再试。")
		return
	}
	expiry := now.Add(sessionLifetime).UTC()
	a.mu.Lock()
	a.sessions[sha256.Sum256([]byte(accessToken))] = session{UserID: grant.UserID, ExpiresAt: expiry, FamilyID: grant.FamilyID}
	a.mu.Unlock()
	writeJSON(w, 200, authResponse{Token: accessToken, ExpiresAt: expiry, RefreshToken: newRefreshToken, RefreshExpiresAt: &grant.ExpiresAt, Player: player})
}

func (a *app) revoke(w http.ResponseWriter, r *http.Request) {
	input, ok := a.refreshInput(w, r)
	if !ok {
		return
	}
	family, err := a.store.revokeRefreshToken(tokenHash(input.RefreshToken))
	if err != nil {
		fail(w, 500, "storage_error", "退出登录失败，请稍后重试。")
		return
	}
	if family != "" {
		a.mu.Lock()
		a.removeFamilySessionsLocked(family)
		a.mu.Unlock()
	}
	w.WriteHeader(204)
}

func (a *app) removeFamilySessionsLocked(family string) {
	for key, s := range a.sessions {
		if s.FamilyID == family {
			delete(a.sessions, key)
		}
	}
}

type privateHandler func(http.ResponseWriter, *http.Request, string, [32]byte)

func (a *app) auth(next privateHandler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		parts := strings.Fields(r.Header.Get("Authorization"))
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") || len(parts[1]) != 43 {
			fail(w, 401, "unauthorized", "请先登录，或重新登录后继续。")
			return
		}
		key := sha256.Sum256([]byte(parts[1]))
		a.mu.Lock()
		s, ok := a.sessions[key]
		if ok && !a.now().Before(s.ExpiresAt) {
			delete(a.sessions, key)
			ok = false
		}
		a.mu.Unlock()
		if !ok {
			fail(w, 401, "unauthorized", "登录已失效，请重新登录。")
			return
		}
		next(w, r, s.UserID, key)
	}
}
func (a *app) logout(w http.ResponseWriter, r *http.Request, id string, key [32]byte) {
	a.mu.Lock()
	family := a.sessions[key].FamilyID
	a.mu.Unlock()
	if family != "" {
		if _, err := a.store.revokeRefresh(family); err != nil {
			fail(w, 500, "storage_error", "退出登录失败，请稍后重试。")
			return
		}
	}
	a.mu.Lock()
	if family == "" {
		delete(a.sessions, key)
	} else {
		a.removeFamilySessionsLocked(family)
	}
	a.mu.Unlock()
	w.WriteHeader(204)
}
func (a *app) me(w http.ResponseWriter, r *http.Request, id string, key [32]byte) {
	p, ok := a.store.player(id)
	if !ok {
		fail(w, 401, "unauthorized", "请重新登录。")
		return
	}
	writeJSON(w, 200, p)
}
func (a *app) getRole(w http.ResponseWriter, r *http.Request, id string, key [32]byte) {
	p, ok := a.store.player(id)
	if !ok {
		fail(w, 401, "unauthorized", "请重新登录。")
		return
	}
	writeJSON(w, 200, map[string]*Role{"role": p.Role})
}
func (a *app) createRole(w http.ResponseWriter, r *http.Request, id string, key [32]byte) {
	var input struct {
		Nickname string `json:"nickname"`
	}
	if !decodeRequest(w, r, &input) {
		return
	}
	if !validNickname(input.Nickname) {
		fail(w, 400, "invalid_nickname", "昵称须为 2 至 16 个字符，且不能含首尾空格或控制字符。")
		return
	}
	roleID, err := randomID(16)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法创建角色。")
		return
	}
	role, err := a.store.createRole(id, Role{ID: roleID, Nickname: input.Nickname, Level: 1, Experience: 0, CreatedAt: a.now().UTC()})
	if err != nil {
		if errors.Is(err, errRoleExists) {
			fail(w, 409, "role_exists", "这个账号已有角色。")
		} else {
			fail(w, 500, "storage_error", "保存角色失败，请稍后重试。")
		}
		return
	}
	writeJSON(w, 201, map[string]Role{"role": role})
}
func (a *app) listStories(w http.ResponseWriter, r *http.Request, id string, key [32]byte) {
	writeJSON(w, 200, map[string]any{"stories": a.storyList})
}
func (a *app) getStory(w http.ResponseWriter, r *http.Request, id string, key [32]byte) {
	story, ok := a.stories[r.PathValue("id")]
	if !ok {
		fail(w, 404, "story_not_found", "没有找到该章节。")
		return
	}
	writeJSON(w, 200, story)
}
func (a *app) progress(w http.ResponseWriter, r *http.Request, id string, key [32]byte) {
	story, ok := a.stories[r.PathValue("id")]
	if !ok {
		fail(w, 404, "story_not_found", "没有找到该章节。")
		return
	}
	var input struct {
		LastLine  *int  `json:"lastLine"`
		Completed *bool `json:"completed"`
	}
	if !decodeRequest(w, r, &input) {
		return
	}
	if input.LastLine == nil || input.Completed == nil || *input.LastLine < 0 || *input.LastLine >= len(story.Lines) || (*input.Completed && *input.LastLine != len(story.Lines)-1) {
		fail(w, 400, "invalid_progress", "阅读位置无效；完成章节时须提交最后一行。")
		return
	}
	p, err := a.store.update(id, story.ID, *input.LastLine, *input.Completed, a.now())
	if err != nil {
		fail(w, 500, "storage_error", "保存进度失败，请稍后重试。")
		return
	}
	writeJSON(w, 200, p)
}
