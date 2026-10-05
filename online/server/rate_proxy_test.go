package main

import (
	"net/http/httptest"
	"testing"
	"time"
)

func TestAuthRateKeyTrustsOnlySingleProxyIPFromLoopback(t *testing.T) {
	tests := []struct {
		name       string
		remoteAddr string
		realIPs    []string
		forwarded  string
		want       string
	}{
		{"public peer ignores spoof", "203.0.113.8:62000", []string{"198.51.100.7"}, "", "203.0.113.8"},
		{"local nginx ipv4", "127.0.0.1:42000", []string{"198.51.100.7"}, "", "198.51.100.7"},
		{"local nginx ipv6", "[::1]:42000", []string{"2001:db8::7"}, "", "2001:db8::7"},
		{"duplicate header rejected", "127.0.0.1:42000", []string{"198.51.100.7", "203.0.113.8"}, "", "127.0.0.1"},
		{"comma list rejected", "127.0.0.1:42000", []string{"198.51.100.7, 203.0.113.8"}, "", "127.0.0.1"},
		{"dns name rejected", "127.0.0.1:42000", []string{"client.example.com"}, "", "127.0.0.1"},
		{"whitespace rejected", "127.0.0.1:42000", []string{" 198.51.100.7"}, "", "127.0.0.1"},
		{"forwarded for ignored", "127.0.0.1:42000", nil, "198.51.100.7", "127.0.0.1"},
		{"malformed peer cannot trust header", "not-an-ip:42000", []string{"198.51.100.7"}, "", "not-an-ip"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			r := httptest.NewRequest("POST", "/api/v1/auth/login", nil)
			r.RemoteAddr = test.remoteAddr
			for _, value := range test.realIPs {
				r.Header.Add("X-Real-IP", value)
			}
			if test.forwarded != "" {
				r.Header.Set("X-Forwarded-For", test.forwarded)
			}
			if got := authRateKey(r); got != test.want {
				t.Fatalf("authRateKey = %q, want %q", got, test.want)
			}
		})
	}
}

func TestAuthRateLimitSeparatesNginxClientIPs(t *testing.T) {
	a, _, _ := fixture(t)
	a.now = func() time.Time { return time.Date(2026, 9, 23, 0, 0, 0, 0, time.UTC) }
	check := func(realIP string, want bool) {
		t.Helper()
		r := httptest.NewRequest("POST", "/api/v1/auth/login", nil)
		r.RemoteAddr = "127.0.0.1:40500"
		r.Header.Set("X-Real-IP", realIP)
		w := httptest.NewRecorder()
		if got := a.allowAuth(w, r); got != want {
			t.Fatalf("client %s: allowed=%t, want %t, status=%d", realIP, got, want, w.Code)
		}
	}
	for i := 0; i < 20; i++ {
		check("198.51.100.1", true)
	}
	check("198.51.100.1", false)
	check("198.51.100.2", true)
}
