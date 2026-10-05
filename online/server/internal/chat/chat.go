// Package chat implements the isolated, loopback-only game chat service.
// The public game API authenticates players and forwards a trusted identity.
package chat

import (
	"bufio"
	"bytes"
	"context"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	maxMessages         = 5000
	maxLogBytes         = 8 << 20
	maxBodyBytes        = 2048
	maxContentBytes     = 1024
	maxContentRunes     = 300
	maxResponseMessages = 100
	maxRecordBytes      = 16 << 10
	maxTypedJSONBytes   = 8 << 10
)

var (
	accountPattern        = regexp.MustCompile(`^[A-Za-z0-9_-]{22}$`)
	rolePattern           = regexp.MustCompile(`^[1-9][0-9]{0,18}$`)
	clientPattern         = regexp.MustCompile(`^[A-Za-z0-9_-]{8,64}$`)
	ErrBadSecret          = errors.New("chat proxy secret must be 32–256 characters")
	ErrInvalidMessage     = errors.New("invalid chat message")
	ErrClientIDConflict   = errors.New("client ID already used for different content")
	ErrRateLimited        = errors.New("chat send rate exceeded")
	ErrStorageUnavailable = errors.New("chat storage unavailable")
)

// Identity is provided by the trusted Go gateway or another authenticated
// transport adapter. It must never be copied from a player's message body.
type Identity struct {
	AccountID string
	RoleID    string
	Nickname  string
	Head      int
	HeadBox   int
}

type Message struct {
	ID        string    `json:"id"`
	Seq       uint64    `json:"seq"`
	Channel   string    `json:"channel"`
	RoleID    string    `json:"roleId"`
	Nickname  string    `json:"nickname"`
	Content   string    `json:"content"`
	Head      int       `json:"head,omitempty"`
	HeadBox   int       `json:"headBox,omitempty"`
	CreatedAt time.Time `json:"createdAt"`
}

type record struct {
	Message
	AccountID string          `json:"accountId"`
	ClientID  string          `json:"clientId"`
	TypedJSON json.RawMessage `json:"typedJson,omitempty"`
	GuildID   string          `json:"guildId,omitempty"`
}

type HistoryResult struct {
	Messages         []Message `json:"messages"`
	NextSeq          uint64    `json:"nextSeq"`
	HistoryTruncated bool      `json:"historyTruncated"`
}

type rateEntry struct {
	Last   time.Time
	Window time.Time
	Count  int
}

type Server struct {
	mu               sync.Mutex
	secret           string
	file             *os.File
	filePath         string
	lock             *os.File
	logSize          int64
	seq              uint64
	messages         []record
	dedup            map[string]record
	rates            map[string]rateEntry
	updates          chan struct{}
	now              func() time.Time
	writeFailed      bool
	guildMembership  *guildMembershipClient
	guildFile        *os.File
	guildFilePath    string
	guildLogSize     int64
	guildSeq         uint64
	guildRecords     []record
	guildDedup       map[string]record
	guildWriteFailed bool
	rtmMu            sync.Mutex
	rtmClients       map[*rtmClient]struct{}
	rtmClosing       bool
	rtmWait          sync.WaitGroup
}

func New(dataDir, secret string) (*Server, error) {
	if len(secret) < 32 || len(secret) > 256 {
		return nil, ErrBadSecret
	}
	if err := os.MkdirAll(dataDir, 0o700); err != nil {
		return nil, err
	}
	lock, err := acquireDataLock(filepath.Join(dataDir, ".instance.lock"))
	if err != nil {
		return nil, fmt.Errorf("chat data directory is already in use: %w", err)
	}
	path := filepath.Join(dataDir, "world.jsonl")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR|os.O_APPEND, 0o600)
	if err != nil {
		_ = lock.Close()
		return nil, err
	}
	s := &Server{secret: secret, file: f, filePath: path, lock: lock,
		messages: make([]record, 0, maxMessages), dedup: make(map[string]record),
		rates: make(map[string]rateEntry), updates: make(chan struct{}), now: time.Now,
		rtmClients: make(map[*rtmClient]struct{})}
	if err = s.load(); err != nil {
		_ = f.Close()
		_ = lock.Close()
		return nil, err
	}
	return s, nil
}

func (s *Server) Close() error {
	s.rtmMu.Lock()
	s.rtmClosing = true
	clients := make([]*rtmClient, 0, len(s.rtmClients))
	for client := range s.rtmClients {
		clients = append(clients, client)
	}
	s.rtmMu.Unlock()
	for _, client := range clients {
		client.close()
	}
	s.rtmWait.Wait()
	s.mu.Lock()
	defer s.mu.Unlock()
	var err error
	if s.file != nil {
		err = s.file.Close()
		s.file = nil
	}
	if s.guildFile != nil {
		if closeErr := s.guildFile.Close(); err == nil {
			err = closeErr
		}
		s.guildFile = nil
	}
	if s.guildMembership != nil {
		s.guildMembership.http.CloseIdleConnections()
	}
	if s.lock != nil {
		if lockErr := s.lock.Close(); err == nil {
			err = lockErr
		}
		s.lock = nil
	}
	return err
}

func validName(name string) bool {
	if !utf8.ValidString(name) || len(name) < 1 || len(name) > 128 || strings.TrimSpace(name) != name {
		return false
	}
	for _, r := range name {
		if unicode.IsControl(r) || unicode.Is(unicode.Cf, r) {
			return false
		}
	}
	return true
}

func validContent(content string) bool {
	if !utf8.ValidString(content) || len(content) == 0 || len(content) > maxContentBytes ||
		utf8.RuneCountInString(content) > maxContentRunes || strings.TrimSpace(content) != content {
		return false
	}
	for _, r := range content {
		if unicode.IsControl(r) || unicode.Is(unicode.Cf, r) {
			return false
		}
	}
	return true
}

func validRecord(item record, previous uint64) bool {
	return item.Seq > previous && item.ID == "world-"+strconv.FormatUint(item.Seq, 10) &&
		item.Channel == "world" && item.GuildID == "" && accountPattern.MatchString(item.AccountID) &&
		rolePattern.MatchString(item.RoleID) && validName(item.Nickname) &&
		item.Head >= 0 && item.Head <= 1<<31-1 && item.HeadBox >= 0 && item.HeadBox <= 1<<31-1 &&
		validContent(item.Content) && clientPattern.MatchString(item.ClientID) && !item.CreatedAt.IsZero() &&
		(len(item.TypedJSON) == 0 || (len(item.TypedJSON) <= maxTypedJSONBytes && json.Valid(item.TypedJSON)))
}

func dedupKey(accountID, clientID string) string { return accountID + "\x00" + clientID }

func encodeRecord(item record) ([]byte, error) {
	var line bytes.Buffer
	encoder := json.NewEncoder(&line)
	// Avoid json.Marshal's HTML escaping: otherwise 1024 legal '<' characters
	// expand beyond the maximum recoverable record size on restart.
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(item); err != nil {
		return nil, err
	}
	return line.Bytes(), nil
}

func (s *Server) remember(item record) {
	s.messages = append(s.messages, item)
	s.dedup[dedupKey(item.AccountID, item.ClientID)] = item
	if len(s.messages) > maxMessages {
		old := s.messages[0]
		delete(s.dedup, dedupKey(old.AccountID, old.ClientID))
		s.messages = s.messages[1:]
	}
	s.seq = item.Seq
}

func (s *Server) load() error {
	st, err := s.file.Stat()
	if err != nil {
		return err
	}
	if st.Size() > 2*maxLogBytes {
		return errors.New("chat log exceeds safe load limit; archive it before startup")
	}
	if _, err = s.file.Seek(0, io.SeekStart); err != nil {
		return err
	}
	reader := bufio.NewReader(s.file)
	var offset int64
	for {
		line, readErr := reader.ReadBytes('\n')
		if readErr == io.EOF && len(line) == 0 {
			break
		}
		if readErr != nil {
			return fmt.Errorf("chat log at byte %d: %w", offset, readErr)
		}
		if len(line) > maxRecordBytes {
			return fmt.Errorf("chat log oversized record at byte %d", offset)
		}
		var item record
		if json.Unmarshal(line, &item) != nil || !validRecord(item, s.seq) {
			return fmt.Errorf("chat log corrupt at byte %d", offset)
		}
		s.remember(item)
		offset += int64(len(line))
	}
	s.logSize = offset
	_, err = s.file.Seek(0, io.SeekEnd)
	return err
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if r.URL.Path == "/health" && r.Method == http.MethodGet {
		respond(w, 200, map[string]string{"status": "ok", "service": "chat"})
		return
	}
	provided := r.Header.Get("X-WW-Chat-Secret")
	if len(provided) != len(s.secret) || subtle.ConstantTimeCompare([]byte(provided), []byte(s.secret)) != 1 {
		errorResponse(w, 403, "forbidden")
		return
	}
	accountID := r.Header.Get("X-WW-Account-ID")
	if !accountPattern.MatchString(accountID) {
		errorResponse(w, 403, "forbidden")
		return
	}
	switch {
	case r.URL.Path == "/rtm" && r.Method == http.MethodGet:
		s.serveRTM(w, r, accountID)
	case r.URL.Path == "/world" && r.Method == http.MethodGet:
		s.list(w, r, false)
	case r.URL.Path == "/world/events" && r.Method == http.MethodGet:
		s.list(w, r, true)
	case r.URL.Path == "/world" && r.Method == http.MethodPost:
		s.send(w, r, accountID)
	default:
		errorResponse(w, 404, "not_found")
	}
}

// Only the authenticated gateway can provide these headers. Missing values
// support a rolling upgrade from the older gateway, whose preserved game seed
// selected icon and frame 1. A present malformed value is never accepted.
func trustedCosmetics(r *http.Request) (int, int, bool) {
	parse := func(key string) (int, bool) {
		values := r.Header.Values(key)
		if len(values) == 0 {
			return 1, true
		}
		if len(values) != 1 || values[0] == "" {
			return 0, false
		}
		value, err := strconv.ParseUint(values[0], 10, 31)
		if value == 0 && err == nil {
			value = 1
		}
		return int(value), err == nil
	}
	head, ok := parse("X-WW-Role-Head")
	if !ok {
		return 0, 0, false
	}
	headBox, ok := parse("X-WW-Role-Head-Box")
	return head, headBox, ok
}

func respond(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func errorResponse(w http.ResponseWriter, status int, code string) {
	respond(w, status, map[string]any{"error": map[string]string{"code": code}})
}

func (s *Server) list(w http.ResponseWriter, r *http.Request, events bool) {
	if len(r.URL.Query()) > 2 {
		errorResponse(w, 400, "invalid_request")
		return
	}
	for key, values := range r.URL.Query() {
		if len(values) != 1 || (key != "after" && (!events || key != "wait") && (events || key != "limit")) {
			errorResponse(w, 400, "invalid_request")
			return
		}
	}
	after := uint64(0)
	if value := r.URL.Query().Get("after"); value != "" {
		var err error
		after, err = strconv.ParseUint(value, 10, 64)
		if err != nil {
			errorResponse(w, 400, "invalid_request")
			return
		}
	}
	limit := 50
	if !events {
		if value := r.URL.Query().Get("limit"); value != "" {
			var err error
			limit, err = strconv.Atoi(value)
			if err != nil || limit < 1 || limit > maxResponseMessages {
				errorResponse(w, 400, "invalid_request")
				return
			}
		}
	}
	wait := 0
	if events {
		wait = 25
		if value := r.URL.Query().Get("wait"); value != "" {
			var err error
			wait, err = strconv.Atoi(value)
			if err != nil || wait < 0 || wait > 25 {
				errorResponse(w, 400, "invalid_request")
				return
			}
		}
	}
	var response HistoryResult
	if events {
		response = s.WaitHistory(r.Context(), after, limit, time.Duration(wait)*time.Second)
	} else {
		response = s.History(after, limit)
	}
	if r.Context().Err() == nil {
		respond(w, 200, response)
	}
}

// History returns a bounded snapshot. after=0 returns the newest messages;
// subsequent calls use the last received sequence number.
func (s *Server) History(after uint64, limit int) HistoryResult {
	if limit < 1 {
		limit = 1
	}
	if limit > maxResponseMessages {
		limit = maxResponseMessages
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.snapshot(after, limit)
}

// WaitHistory is transport-independent and can also feed an RTM adapter.
func (s *Server) WaitHistory(ctx context.Context, after uint64, limit int, wait time.Duration) HistoryResult {
	if limit < 1 {
		limit = 1
	}
	if limit > maxResponseMessages {
		limit = maxResponseMessages
	}
	if wait < 0 {
		wait = 0
	}
	if wait > 25*time.Second {
		wait = 25 * time.Second
	}
	timer := time.NewTimer(wait)
	defer timer.Stop()
	for {
		s.mu.Lock()
		response := s.snapshot(after, limit)
		updates := s.updates
		s.mu.Unlock()
		if len(response.Messages) > 0 || response.HistoryTruncated || wait == 0 {
			return response
		}
		select {
		case <-updates:
			continue
		case <-timer.C:
			return response
		case <-ctx.Done():
			return response
		}
	}
}

// snapshot requires s.mu.
func (s *Server) snapshot(after uint64, limit int) HistoryResult {
	response := HistoryResult{Messages: make([]Message, 0, limit), NextSeq: after}
	if len(s.messages) == 0 {
		return response
	}
	oldest := s.messages[0].Seq
	if after == 0 {
		start := len(s.messages) - limit
		if start < 0 {
			start = 0
		}
		response.HistoryTruncated = start > 0 || oldest > 1
		for _, item := range s.messages[start:] {
			response.Messages = append(response.Messages, item.Message)
		}
	} else {
		response.HistoryTruncated = after < oldest-1
		for _, item := range s.messages {
			if item.Seq > after {
				response.Messages = append(response.Messages, item.Message)
			}
			if len(response.Messages) == limit {
				break
			}
		}
	}
	if n := len(response.Messages); n > 0 {
		response.NextSeq = response.Messages[n-1].Seq
	}
	return response
}

func (s *Server) send(w http.ResponseWriter, r *http.Request, accountID string) {
	if r.URL.RawQuery != "" || strings.TrimSpace(strings.Split(r.Header.Get("Content-Type"), ";")[0]) != "application/json" {
		errorResponse(w, 400, "invalid_request")
		return
	}
	roleID := r.Header.Get("X-WW-Role-ID")
	nameBytes, err := base64.RawURLEncoding.DecodeString(r.Header.Get("X-WW-Role-Name-B64"))
	name := string(nameBytes)
	head, headBox, cosmeticsOK := trustedCosmetics(r)
	if err != nil || !rolePattern.MatchString(roleID) || !validName(name) || !cosmeticsOK {
		errorResponse(w, 403, "forbidden")
		return
	}
	var payload struct {
		Content  string `json:"content"`
		ClientID string `json:"clientId"`
	}
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxBodyBytes))
	dec.DisallowUnknownFields()
	if dec.Decode(&payload) != nil || dec.Decode(new(any)) != io.EOF {
		errorResponse(w, 400, "invalid_request")
		return
	}
	message, created, err := s.Publish(Identity{AccountID: accountID, RoleID: roleID, Nickname: name,
		Head: head, HeadBox: headBox}, payload.Content, payload.ClientID)
	switch {
	case errors.Is(err, ErrInvalidMessage):
		errorResponse(w, 400, "invalid_request")
	case errors.Is(err, ErrClientIDConflict):
		errorResponse(w, 409, "client_id_conflict")
	case errors.Is(err, ErrRateLimited):
		w.Header().Set("Retry-After", "2")
		errorResponse(w, 429, "rate_limited")
	case err != nil:
		errorResponse(w, 503, "storage_unavailable")
	case created:
		respond(w, 201, map[string]Message{"message": message})
	default:
		respond(w, 200, map[string]Message{"message": message})
	}
}

// Publish persists a world message before returning it or notifying readers.
// An RTM adapter can call this with a trusted Identity after authenticating
// the player's current account and server-side role.
func (s *Server) Publish(identity Identity, content, clientID string) (Message, bool, error) {
	return s.publish(identity, content, clientID, nil)
}

func (s *Server) publish(identity Identity, content, clientID string, typedJSON json.RawMessage) (Message, bool, error) {
	if !accountPattern.MatchString(identity.AccountID) || !rolePattern.MatchString(identity.RoleID) ||
		!validName(identity.Nickname) || !validContent(content) || !clientPattern.MatchString(clientID) ||
		identity.Head < 0 || identity.Head > 1<<31-1 || identity.HeadBox < 0 || identity.HeadBox > 1<<31-1 ||
		len(typedJSON) > maxTypedJSONBytes {
		return Message{}, false, ErrInvalidMessage
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if existing, ok := s.dedup[dedupKey(identity.AccountID, clientID)]; ok {
		if existing.Content != content || !bytes.Equal(existing.TypedJSON, typedJSON) {
			return Message{}, false, ErrClientIDConflict
		}
		return existing.Message, false, nil
	}
	now := s.now().UTC()
	rate := s.rates[identity.AccountID]
	if now.Sub(rate.Window) >= time.Minute {
		rate.Window = now
		rate.Count = 0
	}
	if now.Sub(rate.Last) < 2*time.Second || rate.Count >= 20 {
		return Message{}, false, ErrRateLimited
	}
	if s.writeFailed || s.file == nil {
		return Message{}, false, ErrStorageUnavailable
	}
	if s.logSize > maxLogBytes && s.compact() != nil && s.logSize >= 2*maxLogBytes {
		return Message{}, false, ErrStorageUnavailable
	}
	item := record{Message: Message{ID: "world-" + strconv.FormatUint(s.seq+1, 10), Seq: s.seq + 1,
		Channel: "world", RoleID: identity.RoleID, Nickname: identity.Nickname, Content: content,
		Head: identity.Head, HeadBox: identity.HeadBox, CreatedAt: now},
		AccountID: identity.AccountID, ClientID: clientID, TypedJSON: typedJSON}
	line, err := encodeRecord(item)
	if err != nil {
		return Message{}, false, err
	}
	before := s.logSize
	if _, err = s.file.Write(line); err == nil {
		err = s.file.Sync()
	}
	if err != nil {
		_ = s.file.Truncate(before)
		_, _ = s.file.Seek(0, io.SeekEnd)
		s.writeFailed = true
		return Message{}, false, ErrStorageUnavailable
	}
	s.logSize += int64(len(line))
	s.remember(item)
	rate.Last = now
	rate.Count++
	s.rates[identity.AccountID] = rate
	if len(s.rates) > 4096 {
		s.pruneRates(now)
	}
	close(s.updates)
	s.updates = make(chan struct{})
	if s.logSize > maxLogBytes {
		_ = s.compact()
	}
	return item.Message, true, nil
}

func (s *Server) pruneRates(now time.Time) {
	for id, entry := range s.rates {
		if now.Sub(entry.Window) > time.Minute {
			delete(s.rates, id)
		}
	}
	if len(s.rates) > 4096 {
		for id := range s.rates {
			delete(s.rates, id)
			if len(s.rates) <= 4096 {
				break
			}
		}
	}
}

func (s *Server) compact() error {
	// Keep the newest records that fit the durable log, not merely the newest
	// maxMessages. JSON escaping can make 5000 individually valid messages
	// exceed the safe on-disk limit.
	lines := make([][]byte, len(s.messages))
	keepFrom := len(s.messages)
	var keptBytes int64
	for i := len(s.messages) - 1; i >= 0; i-- {
		line, err := encodeRecord(s.messages[i])
		if err != nil {
			return err
		}
		if keptBytes+int64(len(line)) > maxLogBytes {
			break
		}
		lines[i] = line
		keepFrom = i
		keptBytes += int64(len(line))
	}
	if len(s.messages) > 0 && keepFrom == len(s.messages) {
		return errors.New("single chat record exceeds log size limit")
	}
	tmp, err := os.CreateTemp(filepath.Dir(s.filePath), ".chat-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	defer tmp.Close()
	if err = tmp.Chmod(0o600); err != nil {
		return err
	}
	for _, line := range lines[keepFrom:] {
		if _, err = tmp.Write(line); err != nil {
			return err
		}
	}
	if err = tmp.Sync(); err != nil {
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	// Windows will not replace a destination file while our append handle is
	// open. Reopen the original on a rename failure so this process can keep
	// serving the intact log instead of losing its writer.
	if err = s.file.Close(); err != nil {
		s.writeFailed = true
		return err
	}
	s.file = nil
	if err = os.Rename(tmp.Name(), s.filePath); err != nil {
		if reopened, openErr := os.OpenFile(s.filePath, os.O_RDWR|os.O_APPEND, 0o600); openErr == nil {
			s.file = reopened
		} else {
			s.writeFailed = true
		}
		return err
	}
	s.file, err = os.OpenFile(s.filePath, os.O_RDWR|os.O_APPEND, 0o600)
	if err != nil {
		s.writeFailed = true
		return err
	}
	st, err := s.file.Stat()
	if err != nil {
		s.writeFailed = true
		return err
	}
	s.logSize = st.Size()
	if keepFrom > 0 {
		s.messages = s.messages[keepFrom:]
		s.dedup = make(map[string]record, len(s.messages))
		for _, item := range s.messages {
			s.dedup[dedupKey(item.AccountID, item.ClientID)] = item
		}
	}
	if dir, openErr := os.Open(filepath.Dir(s.filePath)); openErr == nil {
		_ = dir.Sync()
		_ = dir.Close()
	}
	return nil
}
