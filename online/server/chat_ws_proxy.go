package main

import (
	"context"
	"encoding/base64"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

const (
	maxRTMConnectionsPerAccount = 2
	maxRTMConnectionsTotal      = 1500
	maxRTMFrameBytes            = 64 << 10
)

// A slot is acquired before the Java role lookup, so a cosmetic change can
// invalidate even a WebSocket whose handshake is still in progress.
type rtmAccount struct {
	count int
	epoch uint64
	links map[*rtmLink]struct{}
}

type rtmLink struct {
	client, upstream *websocket.Conn
}

// chatRTM is a byte-preserving JSON WebSocket gateway. The LeanCloud command
// compatibility adapter lives behind it in the isolated chat service. The
// original SDK's peerId is only a protocol field, never an authentication ID.
func (a *app) chatRTM(w http.ResponseWriter, r *http.Request, accountID string, sessionKey [32]byte) {
	if a.chat == nil {
		fail(w, 503, "chat_unavailable", "聊天服务暂时不可用。")
		return
	}
	if !websocket.IsWebSocketUpgrade(r) {
		fail(w, 426, "upgrade_required", "需要 WebSocket 连接。")
		return
	}
	// The native Android bridge supplies a Bearer header. Browser cross-site
	// WebSocket requests have an Origin and are not part of this protocol.
	if r.Header.Get("Origin") != "" {
		fail(w, 403, "forbidden", "不接受浏览器跨站连接。")
		return
	}
	if !validRTMPath(r.URL.RawQuery) {
		fail(w, 400, "invalid_request", "聊天连接地址无效。")
		return
	}
	epoch, ok := a.takeRTMSlot(accountID)
	if !ok {
		w.Header().Set("Retry-After", "30")
		fail(w, 429, "too_many_connections", "聊天连接过多，请稍后重试。")
		return
	}
	defer a.releaseRTMSlot(accountID)
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

	endpoint := a.chat.upstream
	endpoint.Scheme = "ws"
	endpoint.Path = "/rtm"
	endpoint.RawQuery = r.URL.RawQuery
	upstreamHeader := http.Header{}
	upstreamHeader.Set("X-WW-Chat-Secret", a.chat.secret)
	upstreamHeader.Set("X-WW-Account-ID", accountID)
	upstreamHeader.Set("X-WW-Role-ID", role.id)
	upstreamHeader.Set("X-WW-Role-Name-B64", base64.RawURLEncoding.EncodeToString([]byte(role.name)))
	upstreamHeader.Set("X-WW-Role-Head", strconv.Itoa(role.head))
	upstreamHeader.Set("X-WW-Role-Head-Box", strconv.Itoa(role.headBox))
	// A fresh Dialer is used per request because subprotocol selection varies
	// per original SDK handshake. It cannot dial any address except the pinned
	// numeric loopback chat upstream.
	dialer := websocket.Dialer{
		Proxy: nil, HandshakeTimeout: 5 * time.Second, EnableCompression: false,
		Subprotocols: websocket.Subprotocols(r),
		NetDialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			if address != a.chat.upstream.Host {
				return nil, errUnexpectedChatAddress
			}
			return (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, network, address)
		},
	}
	upstream, response, err := dialer.DialContext(r.Context(), endpoint.String(), upstreamHeader)
	if err != nil {
		if response != nil && response.Body != nil {
			_ = response.Body.Close()
		}
		fail(w, 502, "chat_upstream_failed", "聊天连接暂时不可用。")
		return
	}
	defer upstream.Close()
	selected := upstream.Subprotocol()
	upgrader := websocket.Upgrader{ReadBufferSize: 4096, WriteBufferSize: 4096, EnableCompression: false,
		CheckOrigin: func(req *http.Request) bool { return req.Header.Get("Origin") == "" }}
	if selected != "" {
		upgrader.Subprotocols = []string{selected}
	}
	client, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	defer client.Close()
	client.SetReadLimit(maxRTMFrameBytes)
	upstream.SetReadLimit(maxRTMFrameBytes)
	link := &rtmLink{client: client, upstream: upstream}
	if !a.registerRTMLink(accountID, epoch, link) {
		// A successful avatar change occurred while this handshake was in flight.
		// The SDK can retry and the next handshake reads the new Java selection.
		return
	}
	defer a.unregisterRTMLink(accountID, link)

	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	done := make(chan struct{}, 2)
	go func() { pumpRTM(upstream, client); done <- struct{}{} }()
	go func() { pumpRTM(client, upstream); done <- struct{}{} }()
	go a.watchRTMSession(ctx, sessionKey, client, upstream)
	<-done
	cancel()
	_ = client.Close()
	_ = upstream.Close()
	<-done
}

var errUnexpectedChatAddress = &url.Error{Op: "dial", URL: "chat-upstream", Err: net.InvalidAddrError("unexpected upstream address")}

func (a *app) takeRTMSlot(accountID string) (uint64, bool) {
	a.mu.Lock()
	defer a.mu.Unlock()
	account := a.rtmAccounts[accountID]
	if (account != nil && account.count >= maxRTMConnectionsPerAccount) || a.rtmConnTotal >= maxRTMConnectionsTotal {
		return 0, false
	}
	if account == nil {
		account = &rtmAccount{links: make(map[*rtmLink]struct{})}
		a.rtmAccounts[accountID] = account
	}
	account.count++
	a.rtmConnTotal++
	return account.epoch, true
}

func (a *app) releaseRTMSlot(accountID string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if account := a.rtmAccounts[accountID]; account != nil && account.count > 0 {
		account.count--
		a.rtmConnTotal--
		if account.count == 0 {
			delete(a.rtmAccounts, accountID)
		}
	}
}

func (a *app) registerRTMLink(accountID string, epoch uint64, link *rtmLink) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	account := a.rtmAccounts[accountID]
	if account == nil || account.epoch != epoch {
		return false
	}
	account.links[link] = struct{}{}
	return true
}

func (a *app) unregisterRTMLink(accountID string, link *rtmLink) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if account := a.rtmAccounts[accountID]; account != nil {
		delete(account.links, link)
	}
}

// Called only after Java returned HTTP 200 for this account's avatar change.
// A new handshake reads /__role again, while sockets of other accounts stay up.
func (a *app) refreshRTMCosmetics(accountID string) {
	a.mu.Lock()
	account := a.rtmAccounts[accountID]
	if account == nil {
		a.mu.Unlock()
		return
	}
	account.epoch++
	links := make([]*rtmLink, 0, len(account.links))
	for link := range account.links {
		links = append(links, link)
	}
	a.mu.Unlock()
	for _, link := range links {
		_ = link.client.Close()
		_ = link.upstream.Close()
	}
}

func (a *app) watchRTMSession(ctx context.Context, key [32]byte, client, upstream *websocket.Conn) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			a.mu.Lock()
			s, ok := a.sessions[key]
			valid := ok && a.now().Before(s.ExpiresAt)
			a.mu.Unlock()
			if !valid {
				_ = client.Close()
				_ = upstream.Close()
				return
			}
		}
	}
}

func pumpRTM(dst, src *websocket.Conn) {
	for {
		messageType, data, err := src.ReadMessage()
		if err != nil {
			return
		}
		if messageType != websocket.TextMessage && messageType != websocket.BinaryMessage {
			return
		}
		if len(data) > maxRTMFrameBytes {
			return
		}
		if err = dst.WriteMessage(messageType, data); err != nil {
			return
		}
	}
}

// Helper shared by WS tests: the gateway must never treat a supplied peerId,
// account ID or role ID as trusted merely because it appears in a URL.
func validRTMPath(raw string) bool {
	return raw == "" || (!strings.ContainsAny(raw, "\r\n#") && len(raw) <= 1024)
}
