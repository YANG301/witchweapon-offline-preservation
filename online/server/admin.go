package main

import (
	"bytes"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const adminSessionLifetime = 30 * time.Minute
const adminLegacyLimit = 4096

var adminAccountID = regexp.MustCompile(`^[A-Za-z0-9_-]{22}$`)

// Admin sessions are separate from player sessions and exist only in memory.
type adminConfig struct {
	passwordSalt [16]byte
	passwordHash [32]byte
	usernameHash [32]byte
	publicOrigin string
	publicHost   string
	sessions     map[[32]byte]time.Time
	rates        map[string]rateEntry
}

func (a *app) configureAdmin(encodedCredential string) error {
	if encodedCredential == "" {
		return nil
	}
	credential, err := decodeAdminCredential(encodedCredential)
	if err != nil {
		return err
	}
	a.admin = &adminConfig{
		passwordSalt: credential.Salt,
		passwordHash: credential.Hash,
		usernameHash: sha256.Sum256([]byte(adminUsername)),
		sessions:     make(map[[32]byte]time.Time),
		rates:        make(map[string]rateEntry),
	}
	return nil
}

// An optional public admin endpoint must be a distinct, exact HTTPS origin
// at an explicit public IP and port; other domains and game API hosts are not
// accepted just because they share the same loopback reverse proxy.
func (a *app) configureAdminPublicOrigin(origin string) error {
	if origin == "" {
		return nil
	}
	if a.admin == nil {
		return errors.New("启用管理公网入口前须设置管理员凭据")
	}
	u, err := url.Parse(origin)
	if err != nil || u.Scheme != "https" || u.User != nil || u.Opaque != "" ||
		u.Path != "" || u.RawPath != "" || u.RawQuery != "" || u.Fragment != "" || u.ForceQuery {
		return errors.New("WW_ADMIN_PUBLIC_ORIGIN 须为精确的 HTTPS IP:端口来源")
	}
	host, rawPort, err := net.SplitHostPort(u.Host)
	ip := net.ParseIP(host)
	if err != nil || ip == nil || !ip.IsGlobalUnicast() {
		return errors.New("WW_ADMIN_PUBLIC_ORIGIN 须为非回环 IP 和明确端口")
	}
	port, err := strconv.Atoi(rawPort)
	if err != nil || port < 1 || port > 65535 || u.String() != origin {
		return errors.New("WW_ADMIN_PUBLIC_ORIGIN 端口或格式无效")
	}
	a.admin.publicOrigin = origin
	a.admin.publicHost = u.Host
	return nil
}

func (a *app) mountAdmin() {
	a.mux.HandleFunc("POST /admin/api/login", a.adminLogin)
	a.mux.HandleFunc("POST /admin/api/logout", a.adminAuth(a.adminLogout))
	a.mux.HandleFunc("GET /admin/api/me", a.adminAuth(a.adminMe))
	a.mux.HandleFunc("GET /admin/api/accounts", a.adminAuth(a.adminAccounts))
	a.mux.HandleFunc("GET /admin/api/accounts/{id}", a.adminAuth(a.adminAccount))
	a.mux.HandleFunc("PATCH /admin/api/accounts/{id}/legacy", a.adminAuth(a.adminPatchLegacy))
	a.mountAdminData()
	a.mountAdminCampaigns()
	a.mountAdminMonitor()
	a.mux.HandleFunc("POST /admin/api/accounts/{id}/mail", a.adminAuth(a.adminSendMail))
	a.mux.HandleFunc("GET /admin/api/accounts/{id}/mail/catalog", a.adminAuth(a.adminMailCatalog))
	a.mountAdminAssets()
	a.mux.HandleFunc("GET /admin/api/", func(w http.ResponseWriter, _ *http.Request) {
		fail(w, 404, "not_found", "没有找到该管理接口。")
	})
}

// Both the SSH tunnel and the dedicated HTTPS reverse proxy connect to Go
// over loopback. Host and Origin must match the selected entry point exactly;
// forwarding headers are never trusted for administrator authentication.
func (a *app) adminLocal(r *http.Request) bool {
	if a.admin == nil {
		return false
	}
	peerHost, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return false
	}
	peer := net.ParseIP(peerHost)
	if peer == nil || !peer.IsLoopback() {
		return false
	}
	for header := range r.Header {
		lower := strings.ToLower(header)
		if lower == "x-real-ip" || lower == "forwarded" || strings.HasPrefix(lower, "x-forwarded-") {
			return false
		}
	}
	expectedOrigin := ""
	if a.admin.publicOrigin != "" && r.Host == a.admin.publicHost {
		expectedOrigin = a.admin.publicOrigin
	} else {
		host := r.Host
		if h, _, splitErr := net.SplitHostPort(r.Host); splitErr == nil {
			host = h
		}
		target := net.ParseIP(host)
		if target == nil || !target.IsLoopback() {
			return false
		}
		scheme := "http"
		if r.TLS != nil {
			scheme = "https"
		}
		expectedOrigin = scheme + "://" + r.Host
	}
	origins := r.Header.Values("Origin")
	if len(origins) > 1 || (len(origins) == 1 && origins[0] != expectedOrigin) {
		return false
	}
	if r.Method == http.MethodPost || r.Method == http.MethodPatch || r.Method == http.MethodPut || r.Method == http.MethodDelete {
		if len(origins) != 1 {
			return false
		}
	}
	return true
}

func (a *app) adminRejectUnlessLocal(w http.ResponseWriter, r *http.Request) bool {
	if !a.adminLocal(r) {
		fail(w, 404, "not_found", "没有找到该接口。")
		return false
	}
	return true
}

func (a *app) adminLogin(w http.ResponseWriter, r *http.Request) {
	if !a.adminRejectUnlessLocal(w, r) {
		return
	}
	if a.admin == nil {
		fail(w, 404, "not_found", "没有找到该接口。")
		return
	}
	if r.URL.RawQuery != "" {
		fail(w, 400, "invalid_request", "登录不接受查询参数。")
		return
	}
	now := a.now()
	// This endpoint cannot accept forwarding headers, so all permitted peers
	// share the loopback bucket. A forged header cannot reset the limit.
	key := "loopback"
	limit := 5
	if a.admin.publicOrigin != "" && r.Host == a.admin.publicHost {
		// Nginx has the real remote IP and applies per-IP throttling. Go
		// accepts no forwarded IP headers, so this independent global cap
		// limits aggregate KDF work without allowing one client to consume
		// the five-attempt SSH bucket.
		key = "public"
		limit = 60
	}
	a.mu.Lock()
	for ip, rate := range a.admin.rates {
		if !now.Before(rate.Until) {
			delete(a.admin.rates, ip)
		}
	}
	rate := a.admin.rates[key]
	if rate.Until.IsZero() {
		if len(a.admin.rates) >= 256 {
			a.mu.Unlock()
			fail(w, 429, "rate_limited", "请稍后再试。")
			return
		}
		rate.Until = now.Add(time.Minute)
	}
	if rate.Count >= limit {
		a.mu.Unlock()
		w.Header().Set("Retry-After", "60")
		fail(w, 429, "rate_limited", "请稍后再试。")
		return
	}
	rate.Count++
	a.admin.rates[key] = rate
	a.mu.Unlock()

	var input struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if !decodeRequest(w, r, &input) {
		return
	}
	select {
	case a.kdfSlots <- struct{}{}:
		defer func() { <-a.kdfSlots }()
	default:
		w.Header().Set("Retry-After", "3")
		fail(w, 429, "server_busy", "登录请求较多，请稍后再试。")
		return
	}
	// Hash even an unknown username to keep the response independent of
	// account existence. Only the single configured administrator can log in.
	givenUsername := sha256.Sum256([]byte(input.Username))
	givenPassword := adminPasswordKey([]byte(input.Password), a.admin.passwordSalt[:])
	if !validAdminPassword([]byte(input.Password)) ||
		subtle.ConstantTimeCompare(givenUsername[:], a.admin.usernameHash[:]) != 1 ||
		subtle.ConstantTimeCompare(givenPassword[:], a.admin.passwordHash[:]) != 1 {
		fail(w, 401, "invalid_credentials", "用户名或密码不正确。")
		return
	}
	token, err := randomID(32)
	if err != nil {
		fail(w, 500, "internal_error", "暂时无法创建管理会话。")
		return
	}
	expiry := now.Add(adminSessionLifetime).UTC()
	a.mu.Lock()
	for hash, expires := range a.admin.sessions {
		if !now.Before(expires) {
			delete(a.admin.sessions, hash)
		}
	}
	if len(a.admin.sessions) >= 16 {
		a.mu.Unlock()
		fail(w, 429, "session_limit", "管理会话过多，请稍后重试。")
		return
	}
	a.admin.sessions[sha256.Sum256([]byte(token))] = expiry
	a.mu.Unlock()
	writeJSON(w, 200, map[string]any{"token": token, "expiresAt": expiry})
}

type adminHandler func(http.ResponseWriter, *http.Request, [32]byte, time.Time)

func (a *app) adminAuth(next adminHandler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !a.adminRejectUnlessLocal(w, r) {
			return
		}
		if a.admin == nil {
			fail(w, 404, "not_found", "没有找到该接口。")
			return
		}
		values := r.Header.Values("Authorization")
		parts := strings.Fields(r.Header.Get("Authorization"))
		if len(values) != 1 || len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") || len(parts[1]) != 43 {
			fail(w, 401, "unauthorized", "请先登录管理后台。")
			return
		}
		key := sha256.Sum256([]byte(parts[1]))
		a.mu.Lock()
		expires, ok := a.admin.sessions[key]
		if ok && !a.now().Before(expires) {
			delete(a.admin.sessions, key)
			ok = false
		}
		a.mu.Unlock()
		if !ok {
			fail(w, 401, "unauthorized", "管理会话已失效，请重新登录。")
			return
		}
		next(w, r, key, expires)
	}
}

func (a *app) adminMe(w http.ResponseWriter, _ *http.Request, _ [32]byte, expires time.Time) {
	writeJSON(w, 200, map[string]any{"authenticated": true, "expiresAt": expires})
}

func (a *app) adminLogout(w http.ResponseWriter, _ *http.Request, key [32]byte, _ time.Time) {
	a.mu.Lock()
	delete(a.admin.sessions, key)
	a.mu.Unlock()
	w.WriteHeader(204)
}

type adminAccountSummary struct {
	ID            string `json:"id"`
	PublicRID     int    `json:"publicRid"`
	Email         string `json:"email"`
	EmailVerified bool   `json:"emailVerified"`
	Role          *Role  `json:"role"`
	ProgressCount int    `json:"progressCount"`
}

type adminAccountListQuery struct {
	q, field, verified, sort, cursor string
	limit                            int
	cursorRID                        int
}

// Keep the original account-ID ordering for existing callers and links.
func (s *store) adminAccounts(q, cursor string, limit int) ([]adminAccountSummary, int, string) {
	items, total, next, _ := s.adminAccountsFiltered(adminAccountListQuery{
		q: q, field: "all", verified: "all", cursor: cursor, limit: limit,
	})
	return items, total, next
}

func (s *store) adminAccountsFiltered(query adminAccountListQuery) ([]adminAccountSummary, int, string, int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	ids := make([]string, 0, len(s.state.Users))
	for id, account := range s.state.Users {
		if query.verified == "yes" && !account.EmailVerified || query.verified == "no" && account.EmailVerified {
			continue
		}
		matches := query.q == ""
		if !matches {
			switch query.field {
			case "rid":
				matches = query.q == strconv.Itoa(account.PublicRID)
			case "email":
				matches = strings.Contains(strings.ToLower(account.Email), query.q)
			case "id":
				matches = strings.Contains(strings.ToLower(id), query.q)
			default:
				matches = strings.Contains(strings.ToLower(id), query.q) ||
					strings.Contains(strings.ToLower(account.Email), query.q) || query.q == strconv.Itoa(account.PublicRID)
			}
		}
		if matches {
			ids = append(ids, id)
		}
	}
	// The cursor contains the RID itself instead of depending on the account
	// still existing, so deleting an account between pages cannot repeat a page.
	less := func(leftRID int, leftID string, rightRID int, rightID string) bool {
		if query.sort == "rid_asc" && leftRID != rightRID {
			return leftRID < rightRID
		}
		if query.sort == "rid_desc" && leftRID != rightRID {
			return leftRID > rightRID
		}
		return leftID < rightID
	}
	sort.Slice(ids, func(i, j int) bool {
		return less(s.state.Users[ids[i]].PublicRID, ids[i], s.state.Users[ids[j]].PublicRID, ids[j])
	})
	total := len(ids)
	start := 0
	if query.cursor != "" {
		start = sort.Search(len(ids), func(i int) bool {
			return less(query.cursorRID, query.cursor, s.state.Users[ids[i]].PublicRID, ids[i])
		})
	}
	end := start + query.limit
	if end > len(ids) {
		end = len(ids)
	}
	items := make([]adminAccountSummary, 0, end-start)
	for _, id := range ids[start:end] {
		account := s.state.Users[id]
		item := adminAccountSummary{ID: id, PublicRID: account.PublicRID, Email: account.Email, EmailVerified: account.EmailVerified, ProgressCount: len(account.Progress)}
		if account.Role != nil {
			role := *account.Role
			item.Role = &role
		}
		items = append(items, item)
	}
	next := ""
	if end < len(ids) && end > start {
		next = ids[end-1]
		if query.sort != "" {
			next = strconv.Itoa(s.state.Users[next].PublicRID) + ":" + next
		}
	}
	return items, total, next, len(s.state.Users)
}

func (a *app) adminAccounts(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	query, err := url.ParseQuery(r.URL.RawQuery)
	if err != nil || len(query) > 6 {
		fail(w, 400, "invalid_request", "查询参数无效。")
		return
	}
	for key, values := range query {
		if key != "q" && key != "limit" && key != "cursor" && key != "field" && key != "verified" && key != "sort" || len(values) != 1 {
			fail(w, 400, "invalid_request", "查询参数无效。")
			return
		}
	}
	q := strings.ToLower(strings.TrimSpace(query.Get("q")))
	if len(q) > 254 || !utf8.ValidString(query.Get("q")) || strings.IndexFunc(q, unicode.IsControl) >= 0 {
		fail(w, 400, "invalid_request", "搜索内容无效。")
		return
	}
	field := query.Get("field")
	if field == "" {
		field = "all"
	}
	if field != "all" && field != "rid" && field != "email" && field != "id" {
		fail(w, 400, "invalid_request", "搜索字段无效。")
		return
	}
	verified := query.Get("verified")
	if verified == "" {
		verified = "all"
	}
	if verified != "all" && verified != "yes" && verified != "no" {
		fail(w, 400, "invalid_request", "邮箱验证筛选无效。")
		return
	}
	order := query.Get("sort")
	if order != "" && order != "rid_asc" && order != "rid_desc" {
		fail(w, 400, "invalid_request", "账号排序无效。")
		return
	}
	cursor := query.Get("cursor")
	cursorRID := 0
	validCursor := cursor == ""
	if cursor != "" {
		if order == "" {
			validCursor = adminAccountID.MatchString(cursor)
		} else {
			var rawRID string
			var found bool
			rawRID, cursor, found = strings.Cut(cursor, ":")
			cursorRID, err = strconv.Atoi(rawRID)
			validCursor = found && err == nil && cursorRID >= publicRIDMin && cursorRID <= publicRIDMax &&
				strconv.Itoa(cursorRID) == rawRID && adminAccountID.MatchString(cursor)
		}
	}
	if !validCursor {
		fail(w, 400, "invalid_request", "分页位置无效。")
		return
	}
	limit := 50
	if raw := query.Get("limit"); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil || n < 1 || n > 200 {
			fail(w, 400, "invalid_request", "每页数量应为 1 至 200。")
			return
		}
		limit = n
	}
	items, total, next, accountTotal := a.store.adminAccountsFiltered(adminAccountListQuery{
		q: q, field: field, verified: verified, sort: order, cursor: cursor, cursorRID: cursorRID, limit: limit,
	})
	writeJSON(w, 200, map[string]any{"items": items, "total": total, "accountTotal": accountTotal, "limit": limit, "nextCursor": next})
}

func (a *app) adminAccount(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		fail(w, 400, "invalid_request", "详情路径无效。")
		return
	}
	id := r.PathValue("id")
	if !adminAccountID.MatchString(id) {
		fail(w, 404, "not_found", "没有找到该账号。")
		return
	}
	player, ok := a.store.player(id)
	if !ok {
		fail(w, 404, "not_found", "没有找到该账号。")
		return
	}
	legacy, err := a.adminLegacyState(r, id)
	if err != nil {
		reason := "unavailable"
		if errors.Is(err, errAdminLegacyNotStarted) {
			reason = "not_started"
		}
		writeJSON(w, 200, map[string]any{"account": player, "legacy": map[string]any{"available": false, "reason": reason}})
		return
	}
	writeJSON(w, 200, map[string]any{"account": player, "legacy": adminLegacyView(legacy)})
}

type adminLegacySummary struct {
	Available        bool   `json:"available"`
	Revision         string `json:"revision"`
	Name             string `json:"name"`
	Gold             int64  `json:"gold"`
	RoleCreated      bool   `json:"roleCreated"`
	RoleID           string `json:"roleId"`
	Exp              int64  `json:"exp"`
	Wins             int64  `json:"wins"`
	Attempts         int64  `json:"attempts"`
	Stars            int64  `json:"stars"`
	MazeWins         int64  `json:"mazeWins"`
	MazeAttempts     int64  `json:"mazeAttempts"`
	MazeStars        int64  `json:"mazeStars"`
	MazeRound        int64  `json:"mazeRound"`
	DrawCount        *int64 `json:"drawCount,omitempty"`
	CreatedAt        *int64 `json:"createdAt,omitempty"`
	LastSettlementAt *int64 `json:"lastSettlementAt,omitempty"`
	Active           bool   `json:"active"`
}

var errAdminLegacyNotStarted = errors.New("Java save does not exist")

func adminLegacyView(summary adminLegacySummary) map[string]any {
	state := map[string]any{
		"name": summary.Name, "gold": summary.Gold,
		"roleCreated": summary.RoleCreated, "roleId": summary.RoleID,
		"exp": summary.Exp, "wins": summary.Wins, "attempts": summary.Attempts,
		"stars": summary.Stars, "mazeWins": summary.MazeWins,
		"mazeAttempts": summary.MazeAttempts, "mazeStars": summary.MazeStars,
		"mazeRound": summary.MazeRound, "active": summary.Active,
	}
	if summary.DrawCount != nil {
		state["drawCount"] = *summary.DrawCount
	}
	if summary.CreatedAt != nil {
		state["createdAt"] = *summary.CreatedAt
	}
	if summary.LastSettlementAt != nil {
		// Existing Java battle saves store settlement time in Unix seconds,
		// while creation time is Unix milliseconds. The browser uses Date(ms).
		settledAt := *summary.LastSettlementAt
		if settledAt > 0 && settledAt < 100000000000 {
			settledAt *= 1000
		}
		state["lastSettlementAt"] = settledAt
	}
	roleName := ""
	if summary.RoleCreated {
		roleName = summary.Name
	}
	return map[string]any{
		"available": true, "revision": summary.Revision,
		"role": map[string]any{"version": 1, "exists": summary.RoleCreated,
			"roleId": summary.RoleID, "name": roleName},
		"state": state,
	}
}

func (a *app) adminJavaRequest(r *http.Request, id, method, path string, body io.Reader) (*http.Response, error) {
	if a.legacy == nil {
		return nil, errors.New("legacy disabled")
	}
	target := a.legacy.upstream
	target.Path = path
	request, err := http.NewRequestWithContext(r.Context(), method, target.String(), body)
	if err != nil {
		return nil, err
	}
	request.Header.Set("X-WW-Account-ID", id)
	request.Header.Set("X-WW-Proxy-Secret", a.legacy.secret)
	if method == http.MethodPost {
		request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	return a.legacy.client.Do(request)
}

func parseAdminLegacy(body []byte) (adminLegacySummary, error) {
	var fields map[string]json.RawMessage
	if json.Unmarshal(body, &fields) != nil {
		return adminLegacySummary{}, errors.New("invalid Java admin JSON")
	}
	for _, key := range []string{
		"version", "revision", "name", "gold", "roleCreated", "roleId",
		"exp", "wins", "attempts", "stars", "mazeWins", "mazeAttempts",
		"mazeStars", "mazeRound", "active",
	} {
		value, present := fields[key]
		if !present || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return adminLegacySummary{}, errors.New("missing Java admin field")
		}
	}
	var raw struct {
		Version          int         `json:"version"`
		Revision         json.Number `json:"revision"`
		Name             string      `json:"name"`
		Gold             int64       `json:"gold"`
		RoleCreated      bool        `json:"roleCreated"`
		RoleID           string      `json:"roleId"`
		Exp              int64       `json:"exp"`
		Wins             int64       `json:"wins"`
		Attempts         int64       `json:"attempts"`
		Stars            int64       `json:"stars"`
		MazeWins         int64       `json:"mazeWins"`
		MazeAttempts     int64       `json:"mazeAttempts"`
		MazeStars        int64       `json:"mazeStars"`
		MazeRound        int64       `json:"mazeRound"`
		DrawCount        *int64      `json:"drawCount"`
		CreatedAt        *int64      `json:"createdAt"`
		LastSettlementAt *int64      `json:"lastSettlementAt"`
		Active           bool        `json:"active"`
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	decoder.UseNumber()
	if decoder.Decode(&raw) != nil || decoder.Decode(new(any)) != io.EOF || raw.Version != 1 {
		return adminLegacySummary{}, errors.New("invalid Java admin summary")
	}
	revision, err := strconv.ParseUint(raw.Revision.String(), 10, 63)
	if err != nil || raw.Name == "" || len(raw.Name) > 128 || !utf8.ValidString(raw.Name) ||
		raw.Gold < 0 || raw.Exp < 0 || raw.Wins < 0 || raw.Attempts < 0 || raw.Stars < 0 ||
		raw.MazeWins < 0 || raw.MazeAttempts < 0 || raw.MazeStars < 0 || raw.MazeRound < 0 ||
		(raw.DrawCount != nil && *raw.DrawCount < 0) ||
		(raw.CreatedAt != nil && *raw.CreatedAt < 0) ||
		(raw.LastSettlementAt != nil && *raw.LastSettlementAt < 0) ||
		(raw.RoleCreated && !legacyRoleID.MatchString(raw.RoleID)) ||
		(!raw.RoleCreated && raw.RoleID != "") {
		return adminLegacySummary{}, errors.New("invalid Java admin summary")
	}
	if raw.RoleCreated {
		if _, err := strconv.ParseInt(raw.RoleID, 10, 64); err != nil {
			return adminLegacySummary{}, errors.New("invalid Java admin role ID")
		}
	}
	for _, char := range raw.Name {
		if unicode.IsControl(char) || unicode.Is(unicode.Cf, char) {
			return adminLegacySummary{}, errors.New("invalid Java admin name")
		}
	}
	return adminLegacySummary{
		Available: true, Revision: strconv.FormatUint(revision, 10), Name: raw.Name,
		Gold: raw.Gold, RoleCreated: raw.RoleCreated, RoleID: raw.RoleID,
		Exp: raw.Exp, Wins: raw.Wins, Attempts: raw.Attempts, Stars: raw.Stars,
		MazeWins: raw.MazeWins, MazeAttempts: raw.MazeAttempts, MazeStars: raw.MazeStars,
		MazeRound: raw.MazeRound, DrawCount: raw.DrawCount, CreatedAt: raw.CreatedAt,
		LastSettlementAt: raw.LastSettlementAt, Active: raw.Active,
	}, nil
}

func (a *app) adminLegacyState(r *http.Request, id string) (adminLegacySummary, error) {
	response, err := a.adminJavaRequest(r, id, http.MethodGet, "/__admin/state", nil)
	if err != nil {
		return adminLegacySummary{}, err
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusNotFound {
		return adminLegacySummary{}, errAdminLegacyNotStarted
	}
	if response.StatusCode != 200 || response.ContentLength > adminLegacyLimit ||
		!strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		return adminLegacySummary{}, errors.New("Java admin unavailable")
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, adminLegacyLimit+1))
	if err != nil || len(body) > adminLegacyLimit {
		return adminLegacySummary{}, errors.New("Java admin response too large")
	}
	return parseAdminLegacy(body)
}

func (a *app) adminPatchLegacy(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		fail(w, 400, "invalid_request", "修改路径无效。")
		return
	}
	id := r.PathValue("id")
	if !adminAccountID.MatchString(id) {
		fail(w, 404, "not_found", "没有找到该账号。")
		return
	}
	if _, exists := a.store.player(id); !exists {
		fail(w, 404, "not_found", "没有找到该账号。")
		return
	}
	var input struct {
		ExpectedRevision string          `json:"expectedRevision"`
		Changes          json.RawMessage `json:"changes"`
		Reason           string          `json:"reason"`
	}
	if !decodeRequest(w, r, &input) {
		return
	}
	expectedRevision, revisionError := strconv.ParseUint(input.ExpectedRevision, 10, 63)
	if revisionError != nil || strconv.FormatUint(expectedRevision, 10) != input.ExpectedRevision ||
		utf8.RuneCountInString(input.Reason) < 8 || utf8.RuneCountInString(input.Reason) > 200 ||
		len([]byte(input.Reason)) > 512 ||
		!utf8.ValidString(input.Reason) || strings.TrimSpace(input.Reason) != input.Reason ||
		strings.IndexFunc(input.Reason, unicode.IsControl) >= 0 {
		fail(w, 400, "invalid_request", "版本或修改原因无效。")
		return
	}
	var changes map[string]json.RawMessage
	if err := json.Unmarshal(input.Changes, &changes); err != nil || len(changes) == 0 || len(changes) > 2 {
		fail(w, 400, "invalid_request", "修改字段无效。")
		return
	}
	form := url.Values{"expectedRevision": {input.ExpectedRevision}, "reason": {input.Reason}}
	for key, value := range changes {
		switch key {
		case "name":
			var name string
			if json.Unmarshal(value, &name) != nil || !validNickname(name) ||
				len([]byte(name)) > 128 {
				fail(w, 400, "invalid_request", "角色昵称无效。")
				return
			}
			form.Set("name", name)
		case "gold":
			var gold int64
			if json.Unmarshal(value, &gold) != nil || gold < 0 || gold > 1000000000 {
				fail(w, 400, "invalid_request", "金币数量无效。")
				return
			}
			form.Set("gold", strconv.FormatInt(gold, 10))
		default:
			fail(w, 400, "invalid_request", "只允许修改昵称和金币。")
			return
		}
	}
	response, err := a.adminJavaRequest(r, id, http.MethodPost, "/__admin/patch", strings.NewReader(form.Encode()))
	if err != nil {
		fail(w, 502, "legacy_unavailable", "游戏存档服务暂时不可用。")
		return
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusNotFound {
		fail(w, 409, "save_not_started", "该账号尚无游戏存档。")
		return
	}
	if response.StatusCode == 409 {
		errorBody, _ := io.ReadAll(io.LimitReader(response.Body, 4097))
		var upstreamError struct {
			Error string `json:"error"`
		}
		if len(errorBody) <= 4096 && json.Unmarshal(errorBody, &upstreamError) == nil && upstreamError.Error == "active_battle" {
			fail(w, 409, "active_battle", "该玩家正在战斗或迷宫整备中，当前状态结算完成后可修改存档。")
		} else {
			fail(w, 409, "revision_conflict", "存档已更新，请刷新后重试。")
		}
		return
	}
	if response.StatusCode == 422 {
		fail(w, 422, "invalid_change", "游戏存档拒绝了该修改。")
		return
	}
	if response.StatusCode != 200 || response.ContentLength > adminLegacyLimit ||
		!strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		fail(w, 502, "legacy_invalid", "存档服务未确认修改结果。")
		return
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, adminLegacyLimit+1))
	if err != nil || len(body) > adminLegacyLimit {
		fail(w, 502, "legacy_invalid", "存档服务响应无效。")
		return
	}
	summary, err := parseAdminLegacy(body)
	if err != nil {
		fail(w, 502, "legacy_invalid", "存档服务响应无效。")
		return
	}
	writeJSON(w, 200, map[string]any{"legacy": adminLegacyView(summary)})
}
