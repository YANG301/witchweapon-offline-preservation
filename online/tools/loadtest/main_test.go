package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestBurstRequestLimitAndStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			t.Errorf("method = %s", r.Method)
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("healthy"))
	}))
	defer srv.Close()
	c := defaultConfig()
	c.url, c.duration, c.requests, c.concurrency = srv.URL, 0, 40, 4
	s, err := run(context.Background(), c)
	if err != nil {
		t.Fatal(err)
	}
	if s.completed != 40 || s.succeeded != 40 || s.failed != 0 || s.statusCodes[200] != 40 || s.stopReason != "requests" {
		t.Fatalf("unexpected summary: %+v", s)
	}
}

func TestUsersModePacesAndActivatesUsers(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) }))
	defer srv.Close()
	c := defaultConfig()
	c.url, c.mode, c.users, c.rate, c.duration = srv.URL, "users", 5, 10, 750*time.Millisecond
	s, err := run(context.Background(), c)
	if err != nil {
		t.Fatal(err)
	}
	if s.activeWorkers != 5 || s.completed < 5 || s.completed > 10 || s.failed != 0 || s.stopReason != "duration" {
		t.Fatalf("unexpected virtual-user pacing: %+v", s)
	}
}

func TestUsersRequestCapWakesSleepingUsers(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) }))
	defer srv.Close()
	c := defaultConfig()
	c.url, c.mode, c.users, c.rate, c.duration, c.requests = srv.URL, "users", 1000, 50, 0, 5
	started := time.Now()
	s, err := run(context.Background(), c)
	if err != nil {
		t.Fatal(err)
	}
	if s.completed != 5 || s.stopReason != "requests" || time.Since(started) > time.Second {
		t.Fatalf("request cap did not wake users promptly: %+v", s)
	}
}

func TestErrorRateStopsEarly(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusServiceUnavailable) }))
	defer srv.Close()
	c := defaultConfig()
	c.url, c.concurrency, c.rate, c.duration, c.stopAfter = srv.URL, 1, 100, 3*time.Second, 5
	s, err := run(context.Background(), c)
	if err != nil {
		t.Fatal(err)
	}
	if s.stopReason != "error-rate" || s.completed < 5 || s.completed > 10 || s.failed != s.completed || s.statusCodes[503] != s.completed {
		t.Fatalf("auto-stop did not work: %+v", s)
	}
}

func TestRejectsUnsafeOrUnboundedConfiguration(t *testing.T) {
	for _, args := range [][]string{
		{"-url", "file:///etc/passwd"},
		{"-url", "https://user:password@example.test/"},
		{"-mode", "users"},
		{"-duration", "0s"},
		{"-concurrency", "10001"},
	} {
		if _, err := parseFlags(args); err == nil {
			t.Errorf("accepted args: %v", args)
		}
	}
}
