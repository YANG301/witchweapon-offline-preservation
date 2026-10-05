package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func roleRequest(a *app, token, nickname string) *roleResult {
	body, _ := json.Marshal(map[string]string{"nickname": nickname})
	w := request(a, "POST", "/api/v1/role", token, string(body))
	var response struct {
		Role *Role `json:"role"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &response)
	return &roleResult{status: w.Code, role: response.Role, body: w.Body.String()}
}

type roleResult struct {
	status int
	role   *Role
	body   string
}

func readRole(t *testing.T, a *app, token string) *Role {
	t.Helper()
	w := request(a, "GET", "/api/v1/role", token, "")
	wantStatus(t, w, 200)
	var result struct {
		Role *Role `json:"role"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	return result.Role
}

func TestRoleCreateIsolationAndRestart(t *testing.T) {
	a, dir, stories := fixture(t)
	alice := registerTest(t, a, "role-alice@example.com")
	bob := registerTest(t, a, "role-bob@example.com")
	if alice.Player.Role != nil || bob.Player.Role != nil || readRole(t, a, alice.Token) != nil {
		t.Fatal("new accounts unexpectedly have roles")
	}
	wantStatus(t, request(a, "GET", "/api/v1/role", "", ""), 401)
	wantStatus(t, request(a, "POST", "/api/v1/role", "", `{"nickname":"魔女"}`), 401)
	for _, name := range []string{"", "a", " 昵称", "昵称 ", "昵称\n错", "昵\u200b称", strings.Repeat("甲", 17)} {
		result := roleRequest(a, alice.Token, name)
		if result.status != 400 {
			t.Fatalf("nickname %q: expected 400, got %d: %s", name, result.status, result.body)
		}
	}
	wantStatus(t, request(a, "POST", "/api/v1/role", alice.Token, `{"nickname":"正常","accountId":"other"}`), 400)
	created := roleRequest(a, alice.Token, "魔女之旅")
	if created.status != 201 || created.role == nil || created.role.ID == "" || created.role.Nickname != "魔女之旅" || created.role.Level != 1 || created.role.Experience != 0 || created.role.CreatedAt.IsZero() {
		t.Fatalf("invalid role creation: %+v", created)
	}
	if current := readRole(t, a, alice.Token); current == nil || *current != *created.role {
		t.Fatal("created role was not returned to its owner")
	}
	if readRole(t, a, bob.Token) != nil {
		t.Fatal("alice role leaked to bob")
	}
	if player := decodePlayer(t, request(a, "GET", "/api/v1/me", alice.Token, "")); player.Role == nil || *player.Role != *created.role {
		t.Fatal("/me does not include role")
	}
	if again := roleRequest(a, alice.Token, "different"); again.status != 409 {
		t.Fatalf("duplicate role creation: %+v", again)
	}
	bobRole := roleRequest(a, bob.Token, "魔女之旅")
	if bobRole.status != 201 || bobRole.role == nil || bobRole.role.ID == created.role.ID {
		t.Fatalf("different accounts did not get independent roles: %+v", bobRole)
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	wantStatus(t, request(b, "GET", "/api/v1/role", alice.Token, ""), 401)
	w := request(b, "POST", "/api/v1/auth/login", "", authBody("role-alice@example.com", testPassword))
	wantStatus(t, w, 200)
	var login authResponse
	if err := json.Unmarshal(w.Body.Bytes(), &login); err != nil {
		t.Fatal(err)
	}
	if login.Player.Role == nil || *login.Player.Role != *created.role {
		t.Fatal("login after restart lost saved role")
	}
	if current := readRole(t, b, login.Token); current == nil || *current != *created.role {
		t.Fatal("GET role after restart differs")
	}
}

func TestRoleConcurrentCreateAndFailedStorage(t *testing.T) {
	a, _, _ := fixture(t)
	user := registerTest(t, a, "concurrent-role@example.com")
	var wg sync.WaitGroup
	results := make(chan *roleResult, 24)
	for i := 0; i < cap(results); i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			results <- roleRequest(a, user.Token, fmt.Sprintf("测试角色%02d", i))
		}(i)
	}
	wg.Wait()
	close(results)
	created := 0
	for result := range results {
		if result.status == 201 {
			created++
		} else if result.status != 409 {
			t.Errorf("concurrent create status %d: %s", result.status, result.body)
		}
	}
	if created != 1 || readRole(t, a, user.Token) == nil {
		t.Fatalf("expected exactly one persisted role; got %d", created)
	}
	failing, _, _ := fixture(t)
	failingUser := registerTest(t, failing, "failing-role@example.com")
	failing.store.file = filepath.Join(t.TempDir(), "missing-directory", "state.json")
	if result := roleRequest(failing, failingUser.Token, "存储失败"); result.status != 500 {
		t.Fatalf("expected storage failure, got %+v", result)
	}
	if readRole(t, failing, failingUser.Token) != nil {
		t.Fatal("failed write committed role in memory")
	}
}

func TestInvalidPersistedRoleRejectsStartup(t *testing.T) {
	a, dir, stories := fixture(t)
	user := registerTest(t, a, "invalid-role@example.com")
	if result := roleRequest(a, user.Token, "存档校验"); result.status != 201 {
		t.Fatalf("create role: %+v", result)
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(dir, "state.json")
	var state diskState
	if err := json.Unmarshal(mustRead(t, file), &state); err != nil {
		t.Fatal(err)
	}
	state.Users[user.Player.ID].Role.Level = 0
	bad, err := json.Marshal(state)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(file, bad, 0o600); err != nil {
		t.Fatal(err)
	}
	if b, err := newApp(dir, stories); err == nil {
		b.Close()
		t.Fatal("invalid persisted role was accepted")
	}
}
