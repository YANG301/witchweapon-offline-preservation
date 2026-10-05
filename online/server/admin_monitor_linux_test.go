//go:build linux

package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"testing"
	"time"
)

// This test can run in a read-only namespace as an unprivileged user.
// It samples the real Linux host without credentials, player data or network
// connections, and emits only the same aggregate JSON shown in the admin UI.
func TestAdminMonitorLinuxHostCollector(t *testing.T) {
	monitor := &adminMonitorState{collector: newAdminMonitorCollector(), now: time.Now}
	first := monitor.sample()
	if first.CPU.Available || first.CPU.Reason != "warming_up" || !first.Memory.Available || !first.Disk.Available {
		t.Fatalf("Linux initial aggregate counters unavailable: %+v", first)
	}
	time.Sleep(adminMonitorSampleInterval + 20*time.Millisecond)
	token := strings.Repeat("L", 43)
	a := &app{mux: http.NewServeMux(), now: time.Now, admin: &adminConfig{sessions: map[[32]byte]time.Time{sha256.Sum256([]byte(token)): time.Now().Add(time.Minute)}}}
	a.mux.HandleFunc("GET /admin/api/monitor", a.adminAuth(monitor.handler))
	response := adminRequest(a, http.MethodGet, "/admin/api/monitor", token, "")
	wantStatus(t, response, http.StatusOK)
	var result adminMonitorResponse
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal("Linux authenticated monitor JSON is invalid")
	}
	if !result.CPU.Available || !result.Memory.Available || !result.Disk.Available || result.CPU.SampleWindowSeconds < 5 || result.CPU.SampleWindowSeconds > 15 || result.Disk.Mount != "/" {
		t.Fatalf("Linux second aggregate counters unavailable: %+v", result)
	}
	if result.Memory.TotalBytes == 0 || result.Memory.AvailableBytes > result.Memory.TotalBytes || result.Disk.TotalBytes == 0 || result.Disk.AvailableBytes > result.Disk.TotalBytes || result.CPU.UsagePercent < 0 || result.CPU.UsagePercent > 100 {
		t.Fatal("Linux aggregate counters are inconsistent")
	}
	encoded, err := json.Marshal(result)
	if err != nil {
		t.Fatal("Linux aggregate monitor output cannot be encoded")
	}
	fmt.Printf("MONITOR_HOST_SAMPLE=%s\n", encoded)
}
