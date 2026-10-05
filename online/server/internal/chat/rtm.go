package chat

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
)

// The IDs are pinned in the isolated Android diagnostic build. The original
// game obtains all three from /misc/getLeancloudInfo before opening RTM.
const (
	worldConversationID  = "xinfengzhou-world"
	systemConversationID = "xinfengzhou-system"
	notifyConversationID = "xinfengzhou-notify"
	maxRTMFrameBytes     = 64 << 10
	maxRTMConnections    = 1500
)

var rtmUpgrade = websocket.Upgrader{
	ReadBufferSize: 4096, WriteBufferSize: 4096, EnableCompression: false,
	CheckOrigin: func(r *http.Request) bool { return r.Header.Get("Origin") == "" },
}

type rtmClient struct {
	ws       *websocket.Conn
	identity Identity
	nonce    string
	out      chan any
	done     chan struct{}
	once     sync.Once
	opened   atomic.Bool
	world    atomic.Bool
	guildCID atomic.Value // string: authorized conversation this socket joined
}

func (c *rtmClient) close() {
	c.once.Do(func() {
		close(c.done)
		_ = c.ws.Close()
	})
}

func (c *rtmClient) send(frame any) bool {
	select {
	case <-c.done:
		return false
	default:
	}
	select {
	case c.out <- frame:
		return true
	case <-c.done:
		return false
	default:
		c.close() // A slow reader may not hold every other player's send.
		return false
	}
}

func (c *rtmClient) writeLoop() {
	for {
		select {
		case <-c.done:
			return
		case frame := <-c.out:
			_ = c.ws.SetWriteDeadline(time.Now().Add(5 * time.Second))
			if err := c.ws.WriteJSON(frame); err != nil {
				c.close()
				return
			}
		}
	}
}

func (s *Server) serveRTM(w http.ResponseWriter, r *http.Request, accountID string) {
	if !websocket.IsWebSocketUpgrade(r) || r.Header.Get("Origin") != "" {
		errorResponse(w, 403, "forbidden")
		return
	}
	roleID := r.Header.Get("X-WW-Role-ID")
	nameBytes, err := base64.RawURLEncoding.DecodeString(r.Header.Get("X-WW-Role-Name-B64"))
	head, headBox, cosmeticsOK := trustedCosmetics(r)
	identity := Identity{AccountID: accountID, RoleID: roleID, Nickname: string(nameBytes),
		Head: head, HeadBox: headBox}
	if err != nil || !rolePattern.MatchString(identity.RoleID) || !validName(identity.Nickname) || !cosmeticsOK {
		errorResponse(w, 403, "forbidden")
		return
	}
	nonceBytes := make([]byte, 12)
	if _, err := rand.Read(nonceBytes); err != nil {
		errorResponse(w, 503, "unavailable")
		return
	}
	s.rtmMu.Lock()
	full := s.rtmClosing || len(s.rtmClients) >= maxRTMConnections
	s.rtmMu.Unlock()
	if full {
		errorResponse(w, 429, "too_many_connections")
		return
	}
	ws, err := rtmUpgrade.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	ws.SetReadLimit(maxRTMFrameBytes)
	c := &rtmClient{ws: ws, identity: identity, nonce: hex.EncodeToString(nonceBytes),
		out: make(chan any, 32), done: make(chan struct{})}
	defer c.close()
	s.rtmMu.Lock()
	if s.rtmClosing || len(s.rtmClients) >= maxRTMConnections {
		s.rtmMu.Unlock()
		return
	}
	s.rtmClients[c] = struct{}{}
	s.rtmWait.Add(1)
	s.rtmMu.Unlock()
	defer func() { s.rtmMu.Lock(); delete(s.rtmClients, c); s.rtmMu.Unlock(); s.rtmWait.Done() }()
	go c.writeLoop()
	for {
		kind, payload, readErr := ws.ReadMessage()
		if readErr != nil {
			return
		}
		if kind != websocket.TextMessage || len(payload) > maxRTMFrameBytes {
			return
		}
		if !s.handleRTM(c, payload) {
			return
		}
	}
}

func commandIndex(command map[string]json.RawMessage) (json.RawMessage, bool) {
	raw := command["i"]
	if len(raw) == 0 || len(raw) > 20 {
		return nil, false
	}
	if _, err := strconv.ParseInt(string(raw), 10, 64); err != nil {
		return nil, false
	}
	return raw, true
}

func readString(command map[string]json.RawMessage, key string) string {
	var value string
	_ = json.Unmarshal(command[key], &value)
	return value
}

func rtmError(cmd string, index json.RawMessage, code int, reason string) map[string]any {
	return map[string]any{"cmd": cmd, "i": index, "code": code, "reason": reason}
}

func (s *Server) handleRTM(c *rtmClient, payload []byte) bool {
	var command map[string]json.RawMessage
	if json.Unmarshal(payload, &command) != nil || command == nil {
		return false
	}
	// The original SDK periodically sends an empty JSON object as an idle
	// heartbeat. It has no request index and does not expect a response.
	if len(command) == 0 {
		return true
	}
	index, ok := commandIndex(command)
	if !ok {
		return false
	}
	cmd := readString(command, "cmd")
	op := readString(command, "op")
	if cmd == "session" && op == "open" {
		if readString(command, "peerId") != c.identity.RoleID {
			_ = c.send(rtmError("session", index, 403, "role mismatch"))
			return false
		}
		if !c.opened.Load() {
			c.opened.Store(true)
		}
		return c.send(map[string]any{"cmd": "session", "op": "opened", "i": index,
			"st": "rtm-" + c.nonce, "stTtl": 3600})
	}
	if !c.opened.Load() {
		_ = c.send(rtmError(cmd, index, 403, "session not open"))
		return false
	}
	if peerID := readString(command, "peerId"); peerID != "" && peerID != c.identity.RoleID {
		_ = c.send(rtmError(cmd, index, 403, "role mismatch"))
		return false
	}
	switch cmd {
	case "session":
		if op == "close" {
			_ = c.send(map[string]any{"cmd": "session", "op": "closed", "i": index})
			return false
		}
		if op == "refresh" {
			return c.send(map[string]any{"cmd": "session", "op": "refreshed", "i": index,
				"st": "rtm-" + c.nonce, "stTtl": 3600})
		}
	case "conv":
		return s.handleConversation(c, command, op, index)
	case "logs":
		return s.handleLogs(c, command, index)
	case "direct":
		return s.handleDirect(c, command, index)
	case "read":
		// The original client acknowledges displayed history. Read receipts are
		// not player messages and need no durable or public state.
		return c.send(map[string]any{"cmd": "read", "i": index})
	case "ack":
		// The SDK acknowledges a received direct push with a correlated i.
		return c.send(map[string]any{"cmd": "ack", "i": index})
	}
	return c.send(rtmError(cmd, index, 400, "unsupported command"))
}

func knownConversation(id string) bool {
	return id == worldConversationID || id == systemConversationID || id == notifyConversationID ||
		isGuildConversationID(id)
}

// The original SDK may encode where as an object or as JSON text. We only
// return one of the three server-created conversations, never an arbitrary
// client-selected conversation.
func findConversation(value any, depth int) string {
	if depth > 8 {
		return ""
	}
	switch node := value.(type) {
	case string:
		if knownConversation(node) {
			return node
		}
		if len(node) < 4096 && strings.HasPrefix(strings.TrimSpace(node), "{") {
			var nested any
			if json.Unmarshal([]byte(node), &nested) == nil {
				return findConversation(nested, depth+1)
			}
		}
	case map[string]any:
		if value, ok := node["objectId"]; ok {
			if id := findConversation(value, depth+1); id != "" {
				return id
			}
		}
		for key, value := range node {
			if key != "objectId" {
				if id := findConversation(value, depth+1); id != "" {
					return id
				}
			}
		}
	case []any:
		for _, item := range node {
			if id := findConversation(item, depth+1); id != "" {
				return id
			}
		}
	}
	return ""
}

func (s *Server) handleConversation(c *rtmClient, command map[string]json.RawMessage, op string, index json.RawMessage) bool {
	switch op {
	case "query":
		var where any
		if len(command["where"]) > 4096 || json.Unmarshal(command["where"], &where) != nil {
			return c.send(rtmError("conv", index, 400, "invalid query"))
		}
		id := findConversation(where, 0)
		var results []map[string]any = []map[string]any{}
		if id != "" {
			if isGuildConversationID(id) {
				member, err := s.resolveGuildMembership(c.identity.AccountID, c.identity.RoleID)
				if errors.Is(err, errGuildUnavailable) {
					return c.send(guildAccessError("conv", index, err))
				}
				if err != nil || member.ConversationID != id {
					return c.send(map[string]any{"cmd": "conv", "op": "queried", "i": index, "results": results})
				}
				c.guildCID.Store(id)
			}
			results = append(results, map[string]any{"objectId": id})
			if id == worldConversationID {
				c.world.Store(true)
			}
		}
		return c.send(map[string]any{"cmd": "conv", "op": "queried", "i": index, "results": results})
	case "add":
		id := readString(command, "cid")
		if !knownConversation(id) {
			return c.send(rtmError("conv", index, 404, "conversation not found"))
		}
		if isGuildConversationID(id) {
			member, err := s.resolveGuildMembership(c.identity.AccountID, c.identity.RoleID)
			if err != nil || member.ConversationID != id {
				return c.send(guildAccessError("conv", index, err))
			}
			c.guildCID.Store(id)
		}
		if id == worldConversationID {
			c.world.Store(true)
		}
		return c.send(map[string]any{"cmd": "conv", "op": "added", "i": index})
	}
	return c.send(rtmError("conv", index, 400, "unsupported conversation command"))
}

func (s *Server) handleLogs(c *rtmClient, command map[string]json.RawMessage, index json.RawMessage) bool {
	id := readString(command, "cid")
	if !knownConversation(id) {
		return c.send(rtmError("logs", index, 404, "conversation not found"))
	}
	limit := 20
	if raw := command["l"]; len(raw) > 0 {
		parsed, err := strconv.Atoi(string(raw))
		if err != nil || parsed < 1 || parsed > maxResponseMessages {
			return c.send(rtmError("logs", index, 400, "invalid limit"))
		}
		limit = parsed
	}
	logs := make([]map[string]any, 0)
	if isGuildConversationID(id) {
		member, err := s.resolveGuildMembership(c.identity.AccountID, c.identity.RoleID)
		if err != nil || member.ConversationID != id {
			return c.send(guildAccessError("logs", index, err))
		}
		for _, item := range s.guildHistory(member.GuildID, limit) {
			logs = append(logs, map[string]any{"data": historicalTypedMessage(item),
				"cid": id, "from": item.RoleID, "timestamp": item.CreatedAt.UnixMilli(), "id": item.ID})
		}
		c.guildCID.Store(id)
	}
	if id == worldConversationID {
		s.mu.Lock()
		start := len(s.messages) - limit
		if start < 0 {
			start = 0
		}
		for _, item := range s.messages[start:] {
			data := historicalTypedMessage(item)
			logs = append(logs, map[string]any{"data": data, "cid": id, "from": item.RoleID,
				"timestamp": item.CreatedAt.UnixMilli(), "id": item.ID})
		}
		s.mu.Unlock()
		c.world.Store(true)
	}
	return c.send(map[string]any{"cmd": "logs", "i": index, "logs": logs})
}

func defaultTypedMessage(item record) string {
	message := item.Message
	head, headBox := message.Head, message.HeadBox
	if head == 0 {
		head = 1
	}
	if headBox == 0 {
		headBox = 1
	}
	channelType := 0
	if message.Channel == "guild" {
		channelType = 1
	}
	data, _ := json.Marshal(map[string]any{"_lctype": 2, "ChatContent": message.Content,
		"ChannelType": channelType, "Guildid": item.GuildID, "Name": message.Nickname, "idRole": message.RoleID,
		"roleLv": 0, "Head": head, "HeadBox": headBox})
	return string(data)
}

// Previously stored messages may contain the old client's zero icon values.
// Repair only the outgoing history representation; the JSONL record and any
// legitimate nonzero historical selection remain unchanged.
func historicalTypedMessage(item record) string {
	if len(item.TypedJSON) == 0 {
		return defaultTypedMessage(item)
	}
	var typed map[string]json.RawMessage
	if json.Unmarshal(item.TypedJSON, &typed) != nil || typed == nil {
		return string(item.TypedJSON)
	}
	changed := false
	nestedContent := false
	if rawAttrs, exists := typed["_lcattrs"]; exists {
		var attrs map[string]json.RawMessage
		attrsAsString := false
		if json.Unmarshal(rawAttrs, &attrs) != nil {
			var attrsText string
			if json.Unmarshal(rawAttrs, &attrsText) == nil && json.Unmarshal([]byte(attrsText), &attrs) == nil {
				attrsAsString = true
			}
		}
		if attrs != nil {
			_, nestedContent = attrs["ChatContent"]
			if nestedContent && backfillHistoricalCosmetics(attrs) {
				encoded, err := json.Marshal(attrs)
				if err == nil {
					if attrsAsString {
						typed["_lcattrs"], _ = json.Marshal(string(encoded))
					} else {
						typed["_lcattrs"] = encoded
					}
					changed = true
				}
			}
			if nestedContent {
				for _, key := range []string{"Head", "HeadBox"} {
					if rawOuter, exists := typed[key]; exists {
						var outer int64
						if json.Unmarshal(rawOuter, &outer) != nil || outer <= 0 || outer > 1<<31-1 {
							typed[key] = attrs[key]
							changed = true
						}
					}
				}
			}
		}
	}
	if !nestedContent {
		changed = backfillHistoricalCosmetics(typed)
	}
	if !changed {
		return string(item.TypedJSON)
	}
	encoded, err := json.Marshal(typed)
	if err != nil {
		return string(item.TypedJSON)
	}
	return string(encoded)
}

func backfillHistoricalCosmetics(fields map[string]json.RawMessage) bool {
	changed := false
	for _, key := range []string{"Head", "HeadBox"} {
		var selected int64
		if json.Unmarshal(fields[key], &selected) != nil || selected <= 0 || selected > 1<<31-1 {
			fields[key] = json.RawMessage("1")
			changed = true
		}
	}
	return changed
}

func normalizeTypedMessage(raw string, identity Identity, channelType int, guildID string) (string, json.RawMessage, error) {
	if len(raw) == 0 || len(raw) > maxTypedJSONBytes {
		return "", nil, ErrInvalidMessage
	}
	var typed map[string]json.RawMessage
	if json.Unmarshal([]byte(raw), &typed) != nil || typed == nil {
		return "", nil, ErrInvalidMessage
	}
	if rawType, exists := typed["_lctype"]; exists {
		var lcType int
		if json.Unmarshal(rawType, &lcType) != nil || lcType != 2 {
			return "", nil, ErrInvalidMessage
		}
	}
	fields := typed
	var attrsAsString bool
	var nestedAttrs bool
	if rawAttrs, exists := typed["_lcattrs"]; exists {
		var attrs map[string]json.RawMessage
		if json.Unmarshal(rawAttrs, &attrs) != nil {
			var attrsText string
			if json.Unmarshal(rawAttrs, &attrsText) != nil || json.Unmarshal([]byte(attrsText), &attrs) != nil {
				return "", nil, ErrInvalidMessage
			}
			attrsAsString = true
		}
		if attrs == nil {
			return "", nil, ErrInvalidMessage
		}
		if _, hasContent := attrs["ChatContent"]; hasContent {
			fields = attrs
			nestedAttrs = true
		}
	}
	var content string
	if json.Unmarshal(fields["ChatContent"], &content) != nil || !validContent(content) {
		return "", nil, ErrInvalidMessage
	}
	if rawChannel, exists := fields["ChannelType"]; exists {
		var channel int
		if json.Unmarshal(rawChannel, &channel) != nil || channel != channelType {
			return "", nil, ErrInvalidMessage
		}
	}
	fields["Name"], _ = json.Marshal(identity.Nickname)
	fields["idRole"], _ = json.Marshal(identity.RoleID)
	fields["ChannelType"] = json.RawMessage(strconv.Itoa(channelType))
	fields["Guildid"], _ = json.Marshal(guildID)
	fields["Head"], _ = json.Marshal(identity.Head)
	fields["HeadBox"], _ = json.Marshal(identity.HeadBox)
	if nestedAttrs {
		attrs, err := json.Marshal(fields)
		if err != nil {
			return "", nil, err
		}
		if attrsAsString {
			typed["_lcattrs"], _ = json.Marshal(string(attrs))
		} else {
			typed["_lcattrs"] = attrs
		}
	}
	// If a wrapper and outer fields coexist, do not leave spoofed outer actor
	// fields where a client renderer could choose them.
	if _, exists := typed["Name"]; exists {
		typed["Name"], _ = json.Marshal(identity.Nickname)
	}
	if _, exists := typed["idRole"]; exists {
		typed["idRole"], _ = json.Marshal(identity.RoleID)
	}
	if _, exists := typed["Head"]; exists {
		typed["Head"], _ = json.Marshal(identity.Head)
	}
	if _, exists := typed["HeadBox"]; exists {
		typed["HeadBox"], _ = json.Marshal(identity.HeadBox)
	}
	if _, exists := typed["ChannelType"]; exists {
		typed["ChannelType"] = json.RawMessage(strconv.Itoa(channelType))
	}
	if _, exists := typed["Guildid"]; exists {
		typed["Guildid"], _ = json.Marshal(guildID)
	}
	cleaned, err := json.Marshal(typed)
	if err != nil || len(cleaned) > maxTypedJSONBytes {
		return "", nil, ErrInvalidMessage
	}
	return content, cleaned, nil
}

func (s *Server) handleDirect(c *rtmClient, command map[string]json.RawMessage, index json.RawMessage) bool {
	id := readString(command, "cid")
	if id != worldConversationID && !isGuildConversationID(id) {
		return c.send(rtmError("direct", index, 403, "conversation not writable"))
	}
	if peerID := readString(command, "peerId"); peerID != "" && peerID != c.identity.RoleID {
		return c.send(rtmError("direct", index, 403, "role mismatch"))
	}
	channelType, guildID := 0, ""
	if id != worldConversationID {
		member, err := s.resolveGuildMembership(c.identity.AccountID, c.identity.RoleID)
		if err != nil || member.ConversationID != id {
			return c.send(guildAccessError("direct", index, err))
		}
		channelType, guildID = 1, member.GuildID
	}
	content, typed, err := normalizeTypedMessage(readString(command, "msg"), c.identity, channelType, guildID)
	if err != nil {
		return c.send(rtmError("direct", index, 400, "invalid message"))
	}
	clientID := "rtm-" + c.nonce + "-" + string(index)
	var message Message
	var created bool
	if channelType == 1 {
		message, created, err = s.publishGuild(c.identity, guildID, content, clientID, typed)
	} else {
		message, created, err = s.publish(c.identity, content, clientID, typed)
	}
	switch {
	case errors.Is(err, ErrRateLimited):
		return c.send(rtmError("direct", index, 429, "rate limited"))
	case errors.Is(err, ErrClientIDConflict):
		return c.send(rtmError("direct", index, 409, "message ID conflict"))
	case err != nil:
		return c.send(rtmError("direct", index, 503, "message unavailable"))
	}
	if !c.send(map[string]any{"cmd": "direct", "i": index, "uid": message.ID,
		"t": message.CreatedAt.UnixMilli()}) {
		return false
	}
	if created {
		if channelType == 1 {
			s.broadcastGuild(c, guildID, message, string(typed))
		} else {
			s.broadcastWorld(c, message, string(typed))
		}
	}
	return true
}

func (s *Server) broadcastWorld(sender *rtmClient, message Message, typed string) {
	frame := map[string]any{"cmd": "direct", "cid": worldConversationID, "fromPeerId": message.RoleID,
		"id": message.ID, "timestamp": message.CreatedAt.UnixMilli(), "msg": typed}
	s.rtmMu.Lock()
	clients := make([]*rtmClient, 0, len(s.rtmClients))
	for client := range s.rtmClients {
		if client != sender && client.opened.Load() && client.world.Load() {
			clients = append(clients, client)
		}
	}
	s.rtmMu.Unlock()
	for _, client := range clients {
		client.send(frame)
	}
}

// The Java store remains authoritative even for sockets that joined earlier:
// a kick or leave removes access without requiring a WebSocket reconnect.
func (s *Server) broadcastGuild(sender *rtmClient, guildID string, message Message, typed string) {
	cid := guildConversationID(guildID)
	frame := map[string]any{"cmd": "direct", "cid": cid, "fromPeerId": message.RoleID,
		"id": message.ID, "timestamp": message.CreatedAt.UnixMilli(), "msg": typed}
	s.rtmMu.Lock()
	clients := make([]*rtmClient, 0, len(s.rtmClients))
	for client := range s.rtmClients {
		if client == sender || !client.opened.Load() || client.guildCID.Load() != cid {
			continue
		}
		clients = append(clients, client)
	}
	s.rtmMu.Unlock()
	// Bound concurrent loopback lookups so one busy guild cannot overwhelm the
	// Java save store; a failed lookup always drops that recipient's push.
	semaphore := make(chan struct{}, 16)
	var group sync.WaitGroup
	for _, client := range clients {
		semaphore <- struct{}{}
		group.Add(1)
		go func(client *rtmClient) {
			defer group.Done()
			defer func() { <-semaphore }()
			member, err := s.resolveGuildMembership(client.identity.AccountID, client.identity.RoleID)
			if err == nil && member.GuildID == guildID && client.guildCID.Load() == cid {
				client.send(frame)
			}
		}(client)
	}
	group.Wait()
}
