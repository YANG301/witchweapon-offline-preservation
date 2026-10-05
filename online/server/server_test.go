package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

const testPassword = "  correct-password-42  "

func fixture(t *testing.T) (*app, string, string) {
	t.Helper()
	dir := t.TempDir()
	storyFile := filepath.Join(dir, "stories.json")
	stories := `{"stories":[{"id":"opening-10001","title":"序章·试读","lines":[{"speaker":"旁白","text":"第一行"},{"speaker":"角色","text":"第二行"},{"speaker":"旁白","text":"第三行"}]},{"id":"chapter-two","title":"第二章","lines":[{"speaker":"旁白","text":"唯一一行"}]}]}`
	if err := os.WriteFile(storyFile, []byte(stories), 0o600); err != nil {
		t.Fatal(err)
	}
	data := filepath.Join(dir, "state")
	a, err := newApp(data, storyFile)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = a.Close() })
	return a, data, storyFile
}

func request(a *app, method, path, token, body string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	return w
}
func authBody(email, password string) string {
	b, _ := json.Marshal(credentialsRequest{Email: email, Password: password})
	return string(b)
}
func registerTest(t *testing.T, a *app, email string) authResponse {
	t.Helper()
	w := request(a, "POST", "/api/v1/auth/register", "", authBody(email, testPassword))
	if w.Code != 201 {
		t.Fatalf("register status=%d body=%s", w.Code, w.Body.String())
	}
	var result authResponse
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Token) != 43 || result.RefreshToken != "" || result.RefreshExpiresAt != nil || result.Player.EmailVerified || result.Player.Progress == nil {
		t.Fatalf("bad auth response: player=%+v", result.Player)
	}
	return result
}
func decodePlayer(t *testing.T, w *httptest.ResponseRecorder) Player {
	t.Helper()
	if w.Code != 200 {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
	var p Player
	if err := json.Unmarshal(w.Body.Bytes(), &p); err != nil {
		t.Fatal(err)
	}
	return p
}
func wantStatus(t *testing.T, w *httptest.ResponseRecorder, status int) {
	t.Helper()
	if w.Code != status {
		t.Fatalf("want %d, got %d: %s", status, w.Code, w.Body.String())
	}
}

func TestAuthAndAccountIsolation(t *testing.T) {
	a, dir, _ := fixture(t)
	alice := registerTest(t, a, " Alice@Example.com ")
	bob := registerTest(t, a, "bob@example.com")
	if alice.Player.Email != "alice@example.com" || alice.Player.ID == bob.Player.ID || alice.Token == bob.Token {
		t.Fatal("account identity collision or normalization failure")
	}
	for _, path := range []string{"/api/v1/me", "/api/v1/stories", "/api/v1/stories/opening-10001"} {
		wantStatus(t, request(a, "GET", path, "", ""), 401)
	}
	p := decodePlayer(t, request(a, "PUT", "/api/v1/progress/opening-10001", alice.Token, `{"lastLine":1,"completed":false}`))
	if len(p.Progress) != 1 || p.Progress[0].LastLine != 1 {
		t.Fatal("alice update missing")
	}
	p = decodePlayer(t, request(a, "GET", "/api/v1/me", bob.Token, ""))
	if len(p.Progress) != 0 || p.ID != bob.Player.ID {
		t.Fatal("alice progress leaked to bob")
	}
	wantStatus(t, request(a, "PUT", "/api/v1/progress/opening-10001", bob.Token, fmt.Sprintf(`{"lastLine":2,"completed":true,"userId":%q}`, alice.Player.ID)), 400)
	wantStatus(t, request(a, "GET", "/api/v1/users/"+alice.Player.ID, bob.Token, ""), 404)
	wantStatus(t, request(a, "GET", "/api/v1/me", strings.Repeat("x", 43), ""), 401)
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody("alice@example.com", "wrong-password-99")), 401)
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody("nobody@example.com", "wrong-password-99")), 401)
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody("ALICE@example.com", strings.TrimSpace(testPassword))), 401)
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody("ALICE@example.com", testPassword)), 200)
	wantStatus(t, request(a, "POST", "/api/v1/auth/register", "", authBody("ALICE@example.com", testPassword)), 409)
	state, err := os.ReadFile(filepath.Join(dir, "state.json"))
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(state, []byte(testPassword)) || bytes.Contains(state, []byte(alice.Token)) || bytes.Contains(state, []byte(bob.Token)) {
		t.Fatal("plaintext password or session persisted")
	}
	ca, _ := a.store.credentials("alice@example.com")
	cb, _ := a.store.credentials("bob@example.com")
	if len(ca.Salt) != 32 || bytes.Equal(ca.Salt, cb.Salt) || ca.Iterations != 600000 {
		t.Fatal("invalid password salt or work factor")
	}
	wantStatus(t, request(a, "POST", "/api/v1/auth/logout", alice.Token, ""), 204)
	wantStatus(t, request(a, "GET", "/api/v1/me", alice.Token, ""), 401)
}

func TestRestartPersistenceAndSessionExpiry(t *testing.T) {
	a, dir, stories := fixture(t)
	auth := registerTest(t, a, "persist@example.com")
	before := decodePlayer(t, request(a, "PUT", "/api/v1/progress/opening-10001", auth.Token, `{"lastLine":2,"completed":true}`))
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := newApp(dir, stories)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	wantStatus(t, request(b, "GET", "/api/v1/me", auth.Token, ""), 401)
	w := request(b, "POST", "/api/v1/auth/login", "", authBody("persist@example.com", testPassword))
	wantStatus(t, w, 200)
	var login authResponse
	if err = json.Unmarshal(w.Body.Bytes(), &login); err != nil {
		t.Fatal(err)
	}
	if login.Player.ID != before.ID || len(login.Player.Progress) != 1 || login.Player.Progress[0] != before.Progress[0] {
		t.Fatal("restart lost persisted progress")
	}
	b.now = func() time.Time { return login.ExpiresAt }
	wantStatus(t, request(b, "GET", "/api/v1/me", login.Token, ""), 401)
}

func TestProgressValidationAndIdempotency(t *testing.T) {
	a, _, _ := fixture(t)
	auth := registerTest(t, a, "progress@example.com")
	wantStatus(t, request(a, "GET", "/api/v1/stories/unknown", auth.Token, ""), 404)
	wantStatus(t, request(a, "PUT", "/api/v1/progress/unknown", auth.Token, `{"lastLine":0,"completed":false}`), 404)
	for _, body := range []string{`{"lastLine":-1,"completed":false}`, `{"lastLine":3,"completed":false}`, `{"lastLine":1,"completed":true}`, `{"lastLine":0}`, `{"completed":false}`, `{"lastLine":0.5,"completed":false}`, `{"lastLine":null,"completed":false}`, `{"lastLine":0,"completed":false} {}`} {
		wantStatus(t, request(a, "PUT", "/api/v1/progress/opening-10001", auth.Token, body), 400)
	}
	one := decodePlayer(t, request(a, "PUT", "/api/v1/progress/opening-10001", auth.Token, `{"lastLine":1,"completed":false}`))
	a.now = func() time.Time { return one.Progress[0].UpdatedAt.Add(time.Hour) }
	for _, body := range []string{`{"lastLine":1,"completed":false}`, `{"lastLine":0,"completed":false}`} {
		again := decodePlayer(t, request(a, "PUT", "/api/v1/progress/opening-10001", auth.Token, body))
		if again.Progress[0] != one.Progress[0] {
			t.Fatal("duplicate/stale progress changed data or updatedAt")
		}
	}
	final := decodePlayer(t, request(a, "PUT", "/api/v1/progress/opening-10001", auth.Token, `{"lastLine":2,"completed":true}`))
	again := decodePlayer(t, request(a, "PUT", "/api/v1/progress/opening-10001", auth.Token, `{"lastLine":1,"completed":false}`))
	if !final.Progress[0].Completed || final.Progress[0].LastLine != 2 || again.Progress[0] != final.Progress[0] {
		t.Fatal("completed progress regressed")
	}
}

func TestInputLimitsAndUnicodePassword(t *testing.T) {
	a, _, _ := fixture(t)
	for _, password := range []string{strings.Repeat("a", 11), strings.Repeat("a", 129), strings.Repeat("密", 11), strings.Repeat("密", 129)} {
		wantStatus(t, request(a, "POST", "/api/v1/auth/register", "", authBody("length@example.com", password)), 400)
	}
	wantStatus(t, request(a, "POST", "/api/v1/auth/register", "", authBody("unicode@example.com", strings.Repeat("密", 12))), 201)
	wantStatus(t, request(a, "POST", "/api/v1/auth/login", "", authBody("unicode@example.com", strings.Repeat("密", 12))), 200)
	wantStatus(t, request(a, "POST", "/api/v1/auth/register", "", authBody("max@example.com", strings.Repeat("密", 128))), 201)
	wantStatus(t, request(a, "POST", "/api/v1/auth/register", "", authBody("large@example.com", strings.Repeat("a", requestLimit+1))), 413)
	for _, body := range []string{`null`, `{}`, `{"email":"invalid","password":"long-enough-password"}`, `{"email":"x@example.com","password":"long-enough-password","role":"admin"}`} {
		wantStatus(t, request(a, "POST", "/api/v1/auth/register", "", body), 400)
	}
	r := httptest.NewRequest("POST", "/api/v1/auth/login", strings.NewReader(`{}`))
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	wantStatus(t, w, 415)
}

func TestConcurrentProgressAndIsolation(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "parallel-a@example.com")
	bob := registerTest(t, a, "parallel-b@example.com")
	var wg sync.WaitGroup
	for i := 0; i < 48; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			line := i % 3
			complete := line == 2
			w := request(a, "PUT", "/api/v1/progress/opening-10001", alice.Token, fmt.Sprintf(`{"lastLine":%d,"completed":%t}`, line, complete))
			if w.Code != 200 {
				t.Errorf("concurrent update status %d", w.Code)
			}
			w = request(a, "PUT", "/api/v1/progress/chapter-two", bob.Token, `{"lastLine":0,"completed":true}`)
			if w.Code != 200 {
				t.Errorf("bob update status %d", w.Code)
			}
		}(i)
	}
	wg.Wait()
	p := decodePlayer(t, request(a, "GET", "/api/v1/me", alice.Token, ""))
	if len(p.Progress) != 1 || p.Progress[0].StoryID != "opening-10001" || p.Progress[0].LastLine != 2 || !p.Progress[0].Completed {
		t.Fatal("parallel alice progress corrupted")
	}
	p = decodePlayer(t, request(a, "GET", "/api/v1/me", bob.Token, ""))
	if len(p.Progress) != 1 || p.Progress[0].StoryID != "chapter-two" {
		t.Fatal("parallel account isolation failed")
	}
}

func TestAuthenticationBoundsAndConcurrentRegistration(t *testing.T) {
	a, _, _ := fixture(t)
	a.kdfSlots <- struct{}{}
	a.kdfSlots <- struct{}{}
	wantStatus(t, request(a, "POST", "/api/v1/auth/register", "", authBody("busy@example.com", testPassword)), 429)
	<-a.kdfSlots
	<-a.kdfSlots
	var wg sync.WaitGroup
	results := make(chan int, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			results <- request(a, "POST", "/api/v1/auth/register", "", authBody("same@example.com", testPassword)).Code
		}()
	}
	wg.Wait()
	close(results)
	created := 0
	for code := range results {
		if code == 201 {
			created++
		} else if code != 409 && code != 429 {
			t.Errorf("unexpected concurrent registration status %d", code)
		}
	}
	if created != 1 {
		t.Fatalf("created %d accounts for one email", created)
	}
	for i := 0; i < 20; i++ {
		_ = request(a, "POST", "/api/v1/auth/login", "", `{}`)
	}
	w := request(a, "POST", "/api/v1/auth/login", "", `{}`)
	wantStatus(t, w, 429)
	if w.Header().Get("Retry-After") == "" {
		t.Fatal("missing rate retry hint")
	}
}

func TestDataDirectoryLockAndCorruptState(t *testing.T) {
	a, dir, stories := fixture(t)
	if b, err := newApp(dir, stories); err == nil {
		b.Close()
		t.Fatal("second writer acquired locked data directory")
	}
	cmd := exec.Command(os.Args[0], "-test.run=^TestLockChildProcess$")
	cmd.Env = append(os.Environ(), "WITCH_TEST_LOCK_DIR="+dir)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("child lock check failed: %v %s", err, out)
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "state.json"), []byte(`{"broken":true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if b, err := newApp(dir, stories); err == nil {
		b.Close()
		t.Fatal("corrupt state silently accepted")
	}
	if string(mustRead(t, filepath.Join(dir, "state.json"))) != `{"broken":true}` {
		t.Fatal("corrupt state overwritten")
	}
}
func TestLockChildProcess(t *testing.T) {
	dir := os.Getenv("WITCH_TEST_LOCK_DIR")
	if dir == "" {
		return
	}
	lock, err := acquireDataLock(filepath.Join(dir, ".instance.lock"))
	if err == nil {
		lock.Close()
		t.Fatal("child acquired parent-held lock")
	}
}
func mustRead(t *testing.T, path string) []byte {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestPersistFailureDoesNotCommitMemory(t *testing.T) {
	a, _, _ := fixture(t)
	auth := registerTest(t, a, "disk@example.com")
	a.store.file = filepath.Join(t.TempDir(), "missing-directory", "state.json")
	wantStatus(t, request(a, "PUT", "/api/v1/progress/opening-10001", auth.Token, `{"lastLine":1,"completed":false}`), 500)
	p := decodePlayer(t, request(a, "GET", "/api/v1/me", auth.Token, ""))
	if len(p.Progress) != 0 {
		t.Fatal("failed disk write changed memory")
	}
}

func TestStoriesReadOnlyAndListenBoundary(t *testing.T) {
	a, _, storyFile := fixture(t)
	original := mustRead(t, storyFile)
	auth := registerTest(t, a, "story@example.com")
	w := request(a, "GET", "/api/v1/stories", auth.Token, "")
	wantStatus(t, w, 200)
	var list struct {
		Stories []storySummary `json:"stories"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &list); err != nil {
		t.Fatal(err)
	}
	if len(list.Stories) != 2 || list.Stories[0].LineCount != 3 {
		t.Fatal("wrong story summary")
	}
	wantStatus(t, request(a, "GET", "/api/v1/stories/opening-10001", auth.Token, ""), 200)
	wantStatus(t, request(a, "PUT", "/api/v1/stories/opening-10001", auth.Token, `{}`), 404)
	if !bytes.Equal(original, mustRead(t, storyFile)) {
		t.Fatal("story source modified")
	}
	for _, address := range []string{"0.0.0.0:18080", ":18080", "192.168.1.2:18080", "example.com:18080"} {
		if validateListen(address) == nil {
			t.Errorf("accepted non-loopback %s", address)
		}
	}
	for _, address := range []string{"127.0.0.1:18080", "[::1]:18080"} {
		if err := validateListen(address); err != nil {
			t.Errorf("rejected loopback %s: %v", address, err)
		}
	}
	w = request(a, "GET", "/health", "", "")
	wantStatus(t, w, http.StatusOK)
}
