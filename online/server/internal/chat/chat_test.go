package chat

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const testSecret = "chat-proxy-secret-for-unit-testing-0123456789"
const aliceID = "AAAAAAAAAAAAAAAAAAAAAA"
const bobID = "BBBBBBBBBBBBBBBBBBBBBB"

func testRequest(s *Server, method, path, account, role, name, body string, secret string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	if secret != "" {
		r.Header.Set("X-WW-Chat-Secret", secret)
	}
	if account != "" {
		r.Header.Set("X-WW-Account-ID", account)
	}
	if role != "" {
		r.Header.Set("X-WW-Role-ID", role)
	}
	if name != "" {
		r.Header.Set("X-WW-Role-Name-B64", base64.RawURLEncoding.EncodeToString([]byte(name)))
	}
	if method == http.MethodPost {
		r.Header.Set("Content-Type", "application/json")
	}
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}

func decodeList(t *testing.T, w *httptest.ResponseRecorder) HistoryResult {
	t.Helper()
	if w.Code != 200 {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
	var result HistoryResult
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	return result
}

func TestWorldChatPersistenceAuthAndIsolation(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "chat")
	s, err := New(dir, testSecret)
	if err != nil {
		t.Fatal(err)
	}
	clock := time.Date(2026, 9, 23, 12, 0, 0, 0, time.UTC)
	s.now = func() time.Time { return clock }
	if got := testRequest(s, "GET", "/health", "", "", "", "", ""); got.Code != 200 {
		t.Fatal(got.Code)
	}
	if got := testRequest(s, "GET", "/world", aliceID, "", "", "", ""); got.Code != 403 {
		t.Fatal(got.Code)
	}
	if got := testRequest(s, "GET", "/world", "forged", "", "", "", testSecret); got.Code != 403 {
		t.Fatal(got.Code)
	}
	if got := testRequest(s, "POST", "/world", aliceID, "", "", "{}", testSecret); got.Code != 403 {
		t.Fatal(got.Code)
	}

	body := `{"content":"你好，世界","clientId":"alice-msg-0001"}`
	w := testRequest(s, "POST", "/world", aliceID, "101", "爱丽丝", body, testSecret)
	if w.Code != 201 {
		t.Fatalf("send=%d %s", w.Code, w.Body.String())
	}
	var created struct {
		Message Message `json:"message"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.Message.Seq != 1 || created.Message.Nickname != "爱丽丝" || created.Message.RoleID != "101" || created.Message.Content != "你好，世界" {
		t.Fatalf("bad message: %+v", created.Message)
	}
	if strings.Contains(w.Body.String(), aliceID) || strings.Contains(w.Body.String(), "alice-msg-0001") {
		t.Fatal("internal identity leaked")
	}
	w = testRequest(s, "POST", "/world", aliceID, "101", "爱丽丝", body, testSecret)
	if w.Code != 200 {
		t.Fatalf("idempotent=%d %s", w.Code, w.Body.String())
	}
	w = testRequest(s, "POST", "/world", aliceID, "101", "爱丽丝", `{"content":"changed","clientId":"alice-msg-0001"}`, testSecret)
	if w.Code != 409 {
		t.Fatalf("client id collision=%d", w.Code)
	}
	w = testRequest(s, "POST", "/world", aliceID, "101", "爱丽丝", `{"content":"fast","clientId":"alice-msg-0002"}`, testSecret)
	if w.Code != 429 || w.Header().Get("Retry-After") != "2" {
		t.Fatalf("rate=%d", w.Code)
	}
	clock = clock.Add(3 * time.Second)
	w = testRequest(s, "POST", "/world", bobID, "202", "鲍勃", `{"content":"我也在","clientId":"bob-msg-00001"}`, testSecret)
	if w.Code != 201 {
		t.Fatalf("bob=%d %s", w.Code, w.Body.String())
	}
	result := decodeList(t, testRequest(s, "GET", "/world?after=0&limit=50", aliceID, "", "", "", testSecret))
	if len(result.Messages) != 2 || result.NextSeq != 2 || result.Messages[1].Nickname != "鲍勃" {
		t.Fatalf("list=%+v", result)
	}
	result = decodeList(t, testRequest(s, "GET", "/world?after=1&limit=50", bobID, "", "", "", testSecret))
	if len(result.Messages) != 1 || result.Messages[0].Seq != 2 {
		t.Fatalf("after=%+v", result)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = New(dir, testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	result = decodeList(t, testRequest(s, "GET", "/world?after=0", aliceID, "", "", "", testSecret))
	if len(result.Messages) != 2 || result.NextSeq != 2 {
		t.Fatalf("restart lost messages: %+v", result)
	}
	w = testRequest(s, "POST", "/world", aliceID, "101", "爱丽丝", body, testSecret)
	if w.Code != 200 {
		t.Fatalf("restart lost dedup: %d", w.Code)
	}
}

func TestWorldChatInputAndLongPoll(t *testing.T) {
	s, err := New(filepath.Join(t.TempDir(), "chat"), testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	for _, body := range []string{
		`{"content":"hi","clientId":"x","zone":"other"}`,
		`{"content":"` + strings.Repeat("x", 1025) + `","clientId":"valid-msg-001"}`,
		`{"content":"line\nbreak","clientId":"valid-msg-001"}`,
		`{"content":"hi","clientId":"bad"}`,
	} {
		w := testRequest(s, "POST", "/world", aliceID, "101", "爱丽丝", body, testSecret)
		if w.Code != 400 {
			t.Fatalf("body %q returned %d", body, w.Code)
		}
	}
	for _, path := range []string{"/other", "/world?after=nope", "/world?limit=101", "/world/events?wait=26", "/world?zone=other"} {
		w := testRequest(s, "GET", path, aliceID, "", "", "", testSecret)
		if w.Code != 400 && w.Code != 404 {
			t.Fatalf("path %s returned %d", path, w.Code)
		}
	}
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() { done <- testRequest(s, "GET", "/world/events?after=0&wait=2", aliceID, "", "", "", testSecret) }()
	time.Sleep(50 * time.Millisecond)
	w := testRequest(s, "POST", "/world", aliceID, "101", "爱丽丝", `{"content":"ping","clientId":"long-poll-001"}`, testSecret)
	if w.Code != 201 {
		t.Fatalf("post=%d %s", w.Code, w.Body.String())
	}
	select {
	case result := <-done:
		list := decodeList(t, result)
		if len(list.Messages) != 1 || list.Messages[0].Content != "ping" {
			t.Fatalf("poll=%+v", list)
		}
	case <-time.After(time.Second):
		t.Fatal("long poll did not wake")
	}
}

func TestCoreAPIExclusiveStoreAndCorruptionRefusal(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "chat")
	s, err := New(dir, testSecret)
	if err != nil {
		t.Fatal(err)
	}
	if second, err := New(dir, testSecret); err == nil {
		_ = second.Close()
		t.Fatal("same directory opened twice")
	}
	identity := Identity{AccountID: aliceID, RoleID: "101", Nickname: "爱丽丝"}
	message, created, err := s.Publish(identity, "核心消息", "core-msg-0001")
	if err != nil || !created || message.Seq != 1 {
		t.Fatalf("publish=%+v %v %v", message, created, err)
	}
	if result := s.History(0, 50); len(result.Messages) != 1 || result.Messages[0].Content != "核心消息" {
		t.Fatalf("history=%+v", result)
	}
	if _, _, err = s.Publish(Identity{AccountID: bobID, RoleID: "", Nickname: "伪造"}, "bad", "core-msg-0002"); err != ErrInvalidMessage {
		t.Fatalf("invalid role accepted: %v", err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(dir, "world.jsonl")
	f, err := os.OpenFile(file, os.O_APPEND|os.O_WRONLY, 0)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.Write([]byte(`{"broken":`)); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	if reopened, err := New(dir, testSecret); err == nil {
		_ = reopened.Close()
		t.Fatal("corrupt log silently accepted")
	}
}

func TestCoreCompactionAndRestart(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "chat")
	s, err := New(dir, testSecret)
	if err != nil {
		t.Fatal(err)
	}
	identity := Identity{AccountID: aliceID, RoleID: "101", Nickname: "爱丽丝"}
	first, created, err := s.Publish(identity, "轮换前", "compact-msg-0001")
	if err != nil || !created || first.Seq != 1 {
		t.Fatalf("first=%+v %t %v", first, created, err)
	}
	s.mu.Lock()
	err = s.compact()
	s.mu.Unlock()
	if err != nil {
		t.Fatal(err)
	}
	second, created, err := s.Publish(Identity{AccountID: bobID, RoleID: "202", Nickname: "鲍勃"}, "轮换后", "compact-msg-0002")
	if err != nil || !created || second.Seq != 2 {
		t.Fatalf("second=%+v %t %v", second, created, err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = New(dir, testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	history := s.History(0, 50)
	if len(history.Messages) != 2 || history.Messages[0].Content != "轮换前" || history.Messages[1].Content != "轮换后" {
		t.Fatalf("history after compaction=%+v", history)
	}
	if retry, created, err := s.Publish(identity, "轮换前", "compact-msg-0001"); err != nil || created || retry.Seq != first.Seq {
		t.Fatalf("dedup after compaction=%+v %t %v", retry, created, err)
	}
}

func TestCoreMaxContentRestartAndBoundedCompaction(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "chat")
	s, err := New(dir, testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	identity := Identity{AccountID: aliceID, RoleID: "101", Nickname: "爱丽丝"}
	content := strings.Repeat("<", 300)
	if _, created, err := s.Publish(identity, content, "html-msg-0001"); err != nil || !created {
		t.Fatalf("publish legal content: %t %v", created, err)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = New(dir, testSecret)
	if err != nil {
		t.Fatalf("legal message made log unreadable: %v", err)
	}
	defer s.Close()
	if got := s.History(0, 1); len(got.Messages) != 1 || got.Messages[0].Content != content {
		t.Fatalf("lost content: %+v", got)
	}

	// Populate the in-memory window with maximum-rune, quote-heavy records,
	// then verify compaction stays below the loader's safe size.
	s.mu.Lock()
	for i := 2; i <= maxMessages; i++ {
		item := record{Message: Message{ID: fmt.Sprintf("world-%d", i), Seq: uint64(i), Channel: "world",
			RoleID: "101", Nickname: "爱丽丝", Content: strings.Repeat(`"`, 300), CreatedAt: time.Now().UTC()},
			AccountID: aliceID, ClientID: fmt.Sprintf("quote-%08d", i)}
		s.remember(item)
	}
	err = s.compact()
	kept := len(s.messages)
	logSize := s.logSize
	s.mu.Unlock()
	if err != nil || kept != maxMessages || logSize > maxLogBytes {
		t.Fatalf("bounded compact: kept=%d bytes=%d err=%v", kept, logSize, err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = New(dir, testSecret)
	if err != nil {
		t.Fatalf("bounded compact unreadable: %v", err)
	}
	defer s.Close()
	if got := s.History(0, 1); len(got.Messages) != 1 || got.Messages[0].Seq != maxMessages || !got.HistoryTruncated {
		t.Fatalf("bounded history: %+v", got)
	}
}
