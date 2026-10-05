package chat

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func dialRTM(t *testing.T, origin, account, role, nickname, secret string) (*websocket.Conn, *http.Response, error) {
	t.Helper()
	url := "ws" + strings.TrimPrefix(origin, "http") + "/rtm?subprotocol=lc.json.*"
	header := http.Header{}
	header.Set("X-WW-Chat-Secret", secret)
	header.Set("X-WW-Account-ID", account)
	header.Set("X-WW-Role-ID", role)
	header.Set("X-WW-Role-Name-B64", base64.RawURLEncoding.EncodeToString([]byte(nickname)))
	return (&websocket.Dialer{HandshakeTimeout: 2 * time.Second}).Dial(url, header)
}

func TestRTMHistoryCosmeticFallbackDoesNotRewriteStoredMessages(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "chat")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	created := time.Date(2026, 9, 24, 0, 0, 0, 0, time.UTC)
	items := []record{
		{Message: Message{ID: "world-1", Seq: 1, Channel: "world", RoleID: "101", Nickname: "旧角色",
			Content: "旧头像", CreatedAt: created}, AccountID: aliceID, ClientID: "old-icon-0001",
			TypedJSON: json.RawMessage(`{"_lctype":2,"ChatContent":"旧头像","ChannelType":0,"Head":0,"HeadBox":0,"Name":"旧角色","idRole":"101"}`)},
		{Message: Message{ID: "world-2", Seq: 2, Channel: "world", RoleID: "202", Nickname: "自选头像",
			Content: "非零头像", CreatedAt: created.Add(time.Second)}, AccountID: bobID, ClientID: "old-icon-0002",
			TypedJSON: json.RawMessage(`{"_lctype":2,"ChatContent":"非零头像","ChannelType":0,"Head":42,"HeadBox":7,"Name":"自选头像","idRole":"202"}`)},
	}
	var stored []byte
	for _, item := range items {
		line, err := encodeRecord(item)
		if err != nil {
			t.Fatal(err)
		}
		stored = append(stored, line...)
	}
	path := filepath.Join(dir, "world.jsonl")
	if err := os.WriteFile(path, stored, 0o600); err != nil {
		t.Fatal(err)
	}
	s, err := New(dir, testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	server := httptest.NewServer(s)
	defer server.Close()
	conn, _, err := dialRTM(t, server.URL, aliceID, "101", "旧角色", testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	_ = rtmExchange(t, conn, map[string]any{"cmd": "session", "op": "open", "peerId": "101", "i": 1})
	answer := rtmExchange(t, conn, map[string]any{"cmd": "logs", "cid": worldConversationID, "l": 20, "peerId": "101", "i": 2})
	var logs []map[string]json.RawMessage
	if err := json.Unmarshal(answer["logs"], &logs); err != nil || len(logs) != 2 {
		t.Fatalf("history=%v err=%v", answer, err)
	}
	for index, want := range []struct{ head, box int }{{1, 1}, {42, 7}} {
		var body string
		if err := json.Unmarshal(logs[index]["data"], &body); err != nil {
			t.Fatal(err)
		}
		var message struct{ Head, HeadBox int }
		if err := json.Unmarshal([]byte(body), &message); err != nil || message.Head != want.head || message.HeadBox != want.box {
			t.Fatalf("history cosmetics %d: %+v err=%v", index, message, err)
		}
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(after, stored) {
		t.Fatalf("historical JSONL rewritten: err=%v", err)
	}
}

func rtmExchange(t *testing.T, conn *websocket.Conn, request any) map[string]json.RawMessage {
	t.Helper()
	if err := conn.WriteJSON(request); err != nil {
		t.Fatal(err)
	}
	_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	var answer map[string]json.RawMessage
	if err := conn.ReadJSON(&answer); err != nil {
		t.Fatal(err)
	}
	return answer
}

func field(t *testing.T, value map[string]json.RawMessage, key string) string {
	t.Helper()
	var text string
	if err := json.Unmarshal(value[key], &text); err != nil {
		t.Fatalf("%s missing/invalid: %v in %v", key, err, value)
	}
	return text
}

func TestRTMOriginalCommandsTrustedActorAndPersistence(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "chat")
	s, err := New(dir, testSecret)
	if err != nil {
		t.Fatal(err)
	}
	httpServer := httptest.NewServer(s)
	if conn, response, err := dialRTM(t, httpServer.URL, aliceID, "101", "爱丽丝", "bad-secret"); err == nil {
		conn.Close()
		t.Fatal("accepted bad proxy secret")
	} else if response == nil || response.StatusCode != 403 {
		t.Fatalf("bad secret response=%v err=%v", response, err)
	}
	if conn, response, err := dialRTM(t, httpServer.URL, aliceID, "", "爱丽丝", testSecret); err == nil {
		conn.Close()
		t.Fatal("accepted missing role")
	} else if response == nil || response.StatusCode != 403 {
		t.Fatalf("missing role response=%v err=%v", response, err)
	}
	alice, _, err := dialRTM(t, httpServer.URL, aliceID, "101", "爱丽丝", testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer alice.Close()
	bob, _, err := dialRTM(t, httpServer.URL, bobID, "202", "鲍勃", testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer bob.Close()
	for _, sample := range []struct {
		conn *websocket.Conn
		peer string
	}{{alice, "101"}, {bob, "202"}} {
		answer := rtmExchange(t, sample.conn, map[string]any{"cmd": "session", "op": "open", "peerId": sample.peer,
			"appId": "diagnostic", "configBitmap": 1, "ua": "Unity", "i": -65535})
		if field(t, answer, "cmd") != "session" || field(t, answer, "op") != "opened" || string(answer["i"]) != "-65535" || field(t, answer, "st") == "" {
			t.Fatalf("open response=%v", answer)
		}
	}
	if err := alice.WriteMessage(websocket.TextMessage, []byte(`{}`)); err != nil {
		t.Fatal(err)
	}
	for index, cid := range []string{worldConversationID, systemConversationID, notifyConversationID} {
		answer := rtmExchange(t, alice, map[string]any{"cmd": "conv", "op": "query", "i": -65534 + index,
			"peerId": "101", "where": map[string]any{"objectId": cid}})
		if field(t, answer, "cmd") != "conv" || string(answer["i"]) != string(mustJSON(t, -65534+index)) {
			t.Fatalf("query response=%v", answer)
		}
		var results []map[string]string
		if err := json.Unmarshal(answer["results"], &results); err != nil || len(results) != 1 || results[0]["objectId"] != cid {
			t.Fatalf("query %s results=%v err=%v", cid, results, err)
		}
	}
	for _, sample := range []struct {
		conn *websocket.Conn
		peer string
	}{{alice, "101"}, {bob, "202"}} {
		answer := rtmExchange(t, sample.conn, map[string]any{"cmd": "conv", "op": "add", "cid": worldConversationID,
			"m": []string{sample.peer}, "i": -65530, "peerId": sample.peer})
		if field(t, answer, "cmd") != "conv" {
			t.Fatalf("add=%v", answer)
		}
	}
	initial := rtmExchange(t, bob, map[string]any{"cmd": "logs", "cid": worldConversationID, "l": 20,
		"i": -65529, "peerId": "202"})
	var empty []any
	if err := json.Unmarshal(initial["logs"], &empty); err != nil || len(empty) != 0 {
		t.Fatalf("initial logs=%v err=%v", initial, err)
	}
	read := rtmExchange(t, bob, map[string]any{"cmd": "read", "convs": []map[string]any{{"cid": worldConversationID,
		"mid": "local-history-1", "timestamp": time.Now().UnixMilli()}}, "i": -65526, "peerId": "202"})
	if field(t, read, "cmd") != "read" || string(read["i"]) != "-65526" {
		t.Fatalf("read acknowledgement=%v", read)
	}
	typed := `{"ChatContent":"你好，世界","ChannelType":0,"Head":0,"HeadBox":0,"Guildid":"","Name":"冒名者",` +
		`"CountAchieve":0,"CountStory":0,"CountWeapon":0,"CountServant":0,"idTitle":0,"idRole":"999",` +
		`"guildPrivilege":0,"guildEmblemBorder":0,"guildEmblemBackground":0,"guildEmblem":0,` +
		`"guildEmblemBackgroundColor":0,"guildEmblemBorderColor":0,"guildEmblemColor":0,"roleLv":20,` +
		`"_lctype":2,"_lcattrs":{}}`
	ack := rtmExchange(t, alice, map[string]any{"cmd": "direct", "cid": worldConversationID,
		"msg": typed, "i": -65528, "peerId": "101"})
	if field(t, ack, "cmd") != "direct" || field(t, ack, "uid") != "world-1" || string(ack["i"]) != "-65528" {
		t.Fatalf("direct ack=%v", ack)
	}
	_ = bob.SetReadDeadline(time.Now().Add(2 * time.Second))
	var pushed map[string]json.RawMessage
	if err := bob.ReadJSON(&pushed); err != nil {
		t.Fatal(err)
	}
	if field(t, pushed, "cmd") != "direct" || field(t, pushed, "cid") != worldConversationID || field(t, pushed, "fromPeerId") != "101" {
		t.Fatalf("push=%v", pushed)
	}
	var typedText string
	if err := json.Unmarshal(pushed["msg"], &typedText); err != nil {
		t.Fatal(err)
	}
	var cleaned map[string]any
	if err := json.Unmarshal([]byte(typedText), &cleaned); err != nil || cleaned["Name"] != "爱丽丝" || cleaned["idRole"] != "101" ||
		cleaned["ChatContent"] != "你好，世界" || cleaned["Head"] != float64(1) || cleaned["HeadBox"] != float64(1) {
		t.Fatalf("untrusted actor preserved: %v %v", cleaned, err)
	}
	if attrs, ok := cleaned["_lcattrs"].(map[string]any); !ok || len(attrs) != 0 {
		t.Fatalf("original empty attrs changed: %v", cleaned["_lcattrs"])
	}
	receivedAck := rtmExchange(t, bob, map[string]any{"cmd": "ack", "cid": worldConversationID,
		"mid": "world-1", "i": -65522, "peerId": "202"})
	if field(t, receivedAck, "cmd") != "ack" || string(receivedAck["i"]) != "-65522" {
		t.Fatalf("received-message ack=%v", receivedAck)
	}
	answer := rtmExchange(t, bob, map[string]any{"cmd": "logs", "cid": worldConversationID, "l": 20,
		"i": -65527, "peerId": "202"})
	var logs []map[string]json.RawMessage
	if err := json.Unmarshal(answer["logs"], &logs); err != nil || len(logs) != 1 || field(t, logs[0], "from") != "101" || field(t, logs[0], "data") != typedText {
		t.Fatalf("logs=%v err=%v", logs, err)
	}
	retryAck := rtmExchange(t, alice, map[string]any{"cmd": "direct", "cid": worldConversationID,
		"msg": typed, "i": -65528, "peerId": "101"})
	if field(t, retryAck, "uid") != "world-1" {
		t.Fatalf("idempotent retry=%v", retryAck)
	}
	// If the retry was broadcast again, this read will receive an unexpected
	// direct frame before the requested logs response.
	answer = rtmExchange(t, bob, map[string]any{"cmd": "logs", "cid": worldConversationID, "l": 20,
		"i": -65524, "peerId": "202"})
	if field(t, answer, "cmd") != "logs" {
		t.Fatalf("duplicate broadcast on retry=%v", answer)
	}
	bob.Close()
	bob, _, err = dialRTM(t, httpServer.URL, bobID, "202", "鲍勃", testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer bob.Close()
	_ = rtmExchange(t, bob, map[string]any{"cmd": "session", "op": "open", "peerId": "202", "i": -65535,
		"r": 1, "st": "old-session-ticket"})
	answer = rtmExchange(t, bob, map[string]any{"cmd": "logs", "cid": worldConversationID, "l": 20,
		"i": -65524, "peerId": "202"})
	logs = nil
	if err := json.Unmarshal(answer["logs"], &logs); err != nil || len(logs) != 1 || field(t, logs[0], "data") != typedText {
		t.Fatalf("reconnect history=%v err=%v", logs, err)
	}
	bad := rtmExchange(t, alice, map[string]any{"cmd": "direct", "cid": systemConversationID,
		"msg": typed, "i": -65526, "peerId": "101"})
	if string(bad["code"]) != "403" {
		t.Fatalf("cross-channel send=%v", bad)
	}
	bad = rtmExchange(t, alice, map[string]any{"cmd": "direct", "cid": worldConversationID,
		"msg": strings.Repeat("x", maxTypedJSONBytes+1), "i": -65525, "peerId": "101"})
	if string(bad["code"]) != "400" {
		t.Fatalf("oversized send=%v", bad)
	}
	if err := alice.WriteJSON(map[string]any{"cmd": "direct", "cid": worldConversationID,
		"msg": typed, "i": -65523, "peerId": "999"}); err != nil {
		t.Fatal(err)
	}
	_ = alice.SetReadDeadline(time.Now().Add(2 * time.Second))
	var spoofAnswer map[string]json.RawMessage
	if err := alice.ReadJSON(&spoofAnswer); err == nil && string(spoofAnswer["uid"]) != "" {
		t.Fatalf("forged peerId sent chat: %v", spoofAnswer)
	}
	alice.Close()
	bob.Close()
	httpServer.Close()
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = New(dir, testSecret)
	if err != nil {
		t.Fatalf("RTM history did not persist: %v", err)
	}
	defer s.Close()
	history := s.History(0, 10)
	if len(history.Messages) != 1 || history.Messages[0].Nickname != "爱丽丝" || history.Messages[0].Content != "你好，世界" {
		t.Fatalf("persisted history=%+v", history)
	}
}

func mustJSON(t *testing.T, value any) []byte {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestRTMSessionRejectsClientPeerID(t *testing.T) {
	s, err := New(filepath.Join(t.TempDir(), "chat"), testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	httpServer := httptest.NewServer(s)
	defer httpServer.Close()
	conn, _, err := dialRTM(t, httpServer.URL, aliceID, "101", "爱丽丝", testSecret)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if err := conn.WriteJSON(map[string]any{"cmd": "session", "op": "open", "peerId": "999", "i": -65535}); err != nil {
		t.Fatal(err)
	}
	_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	var answer map[string]json.RawMessage
	if err := conn.ReadJSON(&answer); err == nil && field(t, answer, "op") == "opened" {
		t.Fatalf("spoofed role opened session: %v", answer)
	}
}
