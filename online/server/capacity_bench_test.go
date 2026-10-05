//go:build capacity

package main

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"testing"
	"time"
)

const capacityAccountCount = 1000

const capacityLegacyConcurrency = 8

// capacityFixture is entirely local to testing.TB.TempDir. It never opens the
// deployed data directory, contacts a server, or uses a real account password.
func capacityFixture(tb testing.TB) (*store, string, [capacityAccountCount]string) {
	tb.Helper()
	dir := tb.TempDir()
	storyFile := filepath.Join(dir, "stories.json")
	if err := os.WriteFile(storyFile, []byte(`{"stories":[{"id":"capacity-story","title":"Capacity fixture","lines":[{"speaker":"Test","text":"Fictional text"}]}]}`), 0o600); err != nil {
		tb.Fatal(err)
	}
	s, err := openStore(filepath.Join(dir, "state"))
	if err != nil {
		tb.Fatal(err)
	}

	created := time.Date(2020, time.January, 1, 0, 0, 0, 0, time.UTC)
	next := diskState{Version: 1, Users: make(map[string]*account, capacityAccountCount)}
	var ids [capacityAccountCount]string
	for i := range ids {
		// Java accepts exactly 22 ASCII account-ID characters. This reserved
		// fictional prefix also keeps the isolated Java save tree identifiable.
		id := fmt.Sprintf("CAPACITY%014d", i)
		ids[i] = id
		salt := sha256.Sum256([]byte("fictional-salt-" + id))
		hash := sha256.Sum256([]byte("fictional-unusable-hash-" + id))
		next.Users[id] = &account{
			ID: id, Email: fmt.Sprintf("capacity-%04d@example.invalid", i),
			Salt: salt[:], Hash: hash[:], Iterations: passwordIterations,
			Progress: map[string]Progress{"capacity-story": {
				StoryID: "capacity-story", LastLine: 0, UpdatedAt: created,
			}},
			Role: &Role{ID: fmt.Sprintf("capacity-role-%04d", i),
				Nickname: fmt.Sprintf("测试玩家%04d", i), Level: 1, Experience: 0, CreatedAt: created},
		}
	}
	// The one-time fixture creation is excluded from every measured operation.
	if err := s.persist(next); err != nil {
		_ = s.Close()
		tb.Fatal(err)
	}
	s.state = next
	return s, storyFile, ids
}

func capacityToken(id string) string {
	seed := sha256.Sum256([]byte("fictional-session-" + id))
	return base64.RawURLEncoding.EncodeToString(seed[:])
}

// BenchmarkCapacityPersist1000Accounts isolates the cost of one full state
// replacement at a steady 1000-account state size. It deliberately leaves the
// state unchanged so every iteration writes the same number of bytes.
func BenchmarkCapacityPersist1000Accounts(b *testing.B) {
	b.StopTimer()
	s, _, _ := capacityFixture(b)
	b.Cleanup(func() { _ = s.Close() })
	info, err := os.Stat(s.file)
	if err != nil {
		b.Fatal(err)
	}
	b.ResetTimer()
	b.StartTimer()
	for i := 0; i < b.N; i++ {
		s.mu.Lock()
		next := s.copyState()
		err := s.persist(next)
		s.mu.Unlock()
		if err != nil {
			b.Fatal(err)
		}
	}
	b.StopTimer()
	b.ReportMetric(float64(info.Size()), "state-bytes")
}

// BenchmarkCapacityReadMe1000Accounts measures the authenticated Go HTTP
// handler, including session lookup, store lock, and JSON response encoding.
// It does not include TLS, Nginx, network latency, Java, or 1000 simultaneous
// users; those need a separate controlled end-to-end load test.
func BenchmarkCapacityReadMe1000Accounts(b *testing.B) {
	b.StopTimer()
	s, storyFile, ids := capacityFixture(b)
	if err := s.Close(); err != nil {
		b.Fatal(err)
	}
	a, err := newApp(filepath.Dir(s.file), storyFile)
	if err != nil {
		b.Fatal(err)
	}
	b.Cleanup(func() { _ = a.Close() })
	requests := make([]*http.Request, capacityAccountCount)
	for i, id := range ids {
		token := capacityToken(id)
		a.sessions[sha256.Sum256([]byte(token))] = session{
			UserID: id, ExpiresAt: time.Now().Add(time.Hour),
		}
		r := httptest.NewRequest(http.MethodGet, "http://127.0.0.1/api/v1/me", nil)
		r.Header.Set("Authorization", "Bearer "+token)
		requests[i] = r
	}
	// Check the setup outside the timed loop so a broken fixture cannot yield a
	// misleading fast benchmark.
	probe := httptest.NewRecorder()
	a.ServeHTTP(probe, requests[0])
	if probe.Code != http.StatusOK {
		b.Fatalf("fixture /api/v1/me returned %d", probe.Code)
	}
	b.ResetTimer()
	b.StartTimer()
	for i := 0; i < b.N; i++ {
		response := httptest.NewRecorder()
		a.ServeHTTP(response, requests[i%capacityAccountCount])
		if response.Code != http.StatusOK {
			b.Fatalf("/api/v1/me returned %d", response.Code)
		}
	}
}

type capacityLegacyResult struct {
	path     string
	status   int
	duration time.Duration
}

func capacityPercentile(samples []time.Duration, percentile int) time.Duration {
	if len(samples) == 0 {
		return 0
	}
	sort.Slice(samples, func(i, j int) bool { return samples[i] < samples[j] })
	rank := (len(samples)*percentile+99)/100 - 1
	if rank >= len(samples) {
		rank = len(samples) - 1
	}
	return samples[rank]
}

// TestCapacityLegacyLobby1000Accounts is opt-in and reaches only an explicitly
// selected loopback Java instance. Start a separate Java process with its own
// temporary data directory and response fixture before setting both env vars.
// The deployed Java port 19877 is refused to avoid creating capacity saves in
// its real player-data directory. Go storage always comes from TempDir above.
func TestCapacityLegacyLobby1000Accounts(t *testing.T) {
	upstream, hasUpstream := os.LookupEnv("WW_CAPACITY_LEGACY_UPSTREAM")
	secret, hasSecret := os.LookupEnv("WW_LEGACY_PROXY_SECRET")
	if !hasUpstream && !hasSecret {
		t.Skip("set both WW_CAPACITY_LEGACY_UPSTREAM and WW_LEGACY_PROXY_SECRET for an isolated Java instance")
	}
	if !hasUpstream || !hasSecret {
		t.Fatal("both capacity upstream and proxy secret must be set")
	}
	address, err := parseLegacyUpstream(upstream)
	if err != nil || address.Port() == "19877" {
		t.Fatal("capacity Java upstream must be a separate numeric loopback address, not the deployed port 19877")
	}

	s, storyFile, ids := capacityFixture(t)
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	a, err := newApp(filepath.Dir(s.file), storyFile)
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	if err := a.configureLegacyProxy(upstream, secret); err != nil {
		t.Fatal("invalid isolated Java proxy configuration")
	}

	// Each fictional account has its own in-memory session; no password login,
	// registration, real account data, or public HTTP endpoint is involved.
	tokens := make([]string, capacityAccountCount)
	expires := time.Now().Add(time.Hour)
	for i, id := range ids {
		tokens[i] = capacityToken(id)
		a.sessions[sha256.Sum256([]byte(tokens[i]))] = session{UserID: id, ExpiresAt: expires}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	jobs := make(chan int, capacityLegacyConcurrency)
	results := make(chan capacityLegacyResult, 2*capacityAccountCount)
	var workers sync.WaitGroup
	request := func(index int, method, path string) bool {
		r := httptest.NewRequest(method, "http://127.0.0.1:18080"+path, nil).WithContext(ctx)
		r.Header.Set("Authorization", "Bearer "+tokens[index])
		if method == http.MethodPost {
			r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		}
		response := httptest.NewRecorder()
		started := time.Now()
		a.ServeHTTP(response, r)
		results <- capacityLegacyResult{path: path, status: response.Code, duration: time.Since(started)}
		return response.Code == http.StatusOK
	}
	started := time.Now()
	for range capacityLegacyConcurrency {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for index := range jobs {
				if ctx.Err() != nil {
					return
				}
				if !request(index, http.MethodPost, "/api/v1/legacy/task/all") {
					cancel()
					return
				}
				if ctx.Err() != nil {
					return
				}
				if !request(index, http.MethodGet, "/api/v1/legacy-state") {
					cancel()
					return
				}
			}
		}()
	}
produce:
	for index := range ids {
		if ctx.Err() != nil {
			break
		}
		select {
		case jobs <- index:
		case <-ctx.Done():
			break produce
		}
	}
	close(jobs)
	workers.Wait()
	close(results)
	total := time.Since(started)

	counts := map[string]map[int]int{}
	latencies := map[string][]time.Duration{}
	completed := 0
	for result := range results {
		completed++
		if counts[result.path] == nil {
			counts[result.path] = map[int]int{}
		}
		counts[result.path][result.status]++
		latencies[result.path] = append(latencies[result.path], result.duration)
	}
	for _, path := range []string{"/api/v1/legacy/task/all", "/api/v1/legacy-state"} {
		t.Logf("%s statuses=%v requests=%d p95=%s p99=%s", path, counts[path],
			len(latencies[path]), capacityPercentile(latencies[path], 95), capacityPercentile(latencies[path], 99))
	}
	t.Logf("lobby chain total_requests=%d total_wall=%s max_in_flight=%d accounts=%d",
		completed, total, capacityLegacyConcurrency, capacityAccountCount)
	if completed != 2*capacityAccountCount ||
		counts["/api/v1/legacy/task/all"][http.StatusOK] != capacityAccountCount ||
		counts["/api/v1/legacy-state"][http.StatusOK] != capacityAccountCount {
		t.Fatal("isolated Java lobby chain stopped on failure, timeout, or incomplete account coverage")
	}
}
