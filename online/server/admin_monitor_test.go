package main

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
	"math"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"
)

type fakeAdminMonitorCollector struct {
	reading adminMonitorRaw
	calls   int
}

func (c *fakeAdminMonitorCollector) collect() adminMonitorRaw {
	c.calls++
	return c.reading
}

func newAdminMonitorTestState() (*adminMonitorState, *fakeAdminMonitorCollector, *time.Time) {
	now := time.Date(2026, 10, 4, 1, 0, 0, 0, time.FixedZone("test", 8*3600))
	collector := &fakeAdminMonitorCollector{reading: adminMonitorRaw{memoryTotal: 10000, memoryFree: 5000, diskTotal: 10000, diskFree: 5000, diskUsage: adminDiskUsageTestRaw(now)}}
	return &adminMonitorState{collector: collector, now: func() time.Time { return now }}, collector, &now
}

func adminMonitorTestCPUAdvance(collector *fakeAdminMonitorCollector, usage uint64) {
	collector.reading.cpu[0] += usage
	collector.reading.cpu[3] += 100 - usage
}

func adminMonitorTestAlert(result adminMonitorResponse, id string) (adminMonitorAlert, bool) {
	for _, alert := range result.Alerts {
		if alert.ID == id {
			return alert, true
		}
	}
	return adminMonitorAlert{}, false
}

func TestAdminMonitorCPUCounterSemantics(t *testing.T) {
	first, err := parseAdminMonitorCPU("cpu 100 20 30 40 50 6 7 8 9999 9999\n")
	if err != nil {
		t.Fatal(err)
	}
	second, err := parseAdminMonitorCPU("cpu 120 25 40 90 60 8 8 10 999999 999999\n")
	if err != nil {
		t.Fatal(err)
	}
	usage, iowait, valid := adminMonitorCPUUsage(first, second)
	// Busy is 20+5+10+2+1+2=40 out of 100. Guest fields are not added;
	// idle and I/O wait are excluded from CPU execution utilization.
	if !valid || math.Abs(usage-40) > 1e-9 || math.Abs(iowait-10) > 1e-9 {
		t.Fatalf("wrong CPU semantics: usage %v iowait %v valid %v", usage, iowait, valid)
	}
	for _, contents := range []string{"cpu0 1 2 3 4 5 6 7 8", "cpu 1 2 3", "cpu 1 2 3 4 5 6 7 -8", "cpu 1 2 3 4 5 6 7 x"} {
		if _, err := parseAdminMonitorCPU(contents); err == nil {
			t.Fatalf("accepted malformed CPU counters %q", contents)
		}
	}
	if _, _, valid := adminMonitorCPUUsage(second, first); valid {
		t.Fatal("accepted counter rollback")
	}
	if _, _, valid := adminMonitorCPUUsage(first, first); valid {
		t.Fatal("accepted CPU counters with no elapsed ticks")
	}
}

func TestAdminMonitorMemoryUsesAvailableNotFree(t *testing.T) {
	total, available, err := parseAdminMonitorMemory("MemTotal: 1000 kB\nMemFree: 1 kB\nCached: 800 kB\nMemAvailable: 400 kB\n")
	if err != nil || total != 1000*1024 || available != 400*1024 {
		t.Fatalf("memory parse total %d available %d error %v", total, available, err)
	}
	metric := adminMonitorCapacityValue(total, available, nil)
	if !metric.Available || metric.UsedBytes != 600*1024 || metric.UsagePercent != 60 {
		t.Fatalf("memory calculation %+v", metric)
	}
	for _, contents := range []string{
		"MemTotal: 1000 kB\nMemFree: 50 kB\n",
		"MemTotal: 1000 kB\nMemAvailable: 1001 kB\n",
		"MemTotal: 0 kB\nMemAvailable: 0 kB\n",
		"MemTotal: 1000 kB\nMemAvailable: 20 MB\n",
		"MemTotal: 18446744073709551615 kB\nMemAvailable: 20 kB\n",
		"MemTotal: 1000 kB\nMemAvailable: 20 kB\nMemAvailable: 20 kB\n",
	} {
		if _, _, err := parseAdminMonitorMemory(contents); err == nil {
			t.Fatalf("accepted invalid memory counters %q", contents)
		}
	}
}

func TestAdminMonitorDiskAvailableAndOverflow(t *testing.T) {
	total, available, err := adminMonitorDiskBytes(100, 12, 4096)
	if err != nil || total != 409600 || available != 49152 {
		t.Fatalf("disk byte conversion %d %d %v", total, available, err)
	}
	metric := adminMonitorCapacityValue(total, available, nil)
	if metric.UsagePercent != 88 || metric.UsedBytes != 88*4096 {
		t.Fatalf("disk capacity %+v", metric)
	}
	for _, counters := range [][3]uint64{{0, 0, 4096}, {100, 101, 4096}, {100, 12, 0}, {^uint64(0), 0, 4096}} {
		if _, _, err := adminMonitorDiskBytes(counters[0], counters[1], counters[2]); err == nil {
			t.Fatalf("accepted invalid disk counters %v", counters)
		}
	}
}

func TestAdminMonitorCacheAndConcurrentRequests(t *testing.T) {
	monitor, collector, now := newAdminMonitorTestState()
	first := monitor.sample()
	if first.CPU.Available || first.CPU.Reason != "warming_up" || first.Status != "ok" || len(first.Alerts) != 0 || first.Alerts == nil {
		t.Fatalf("initial monitor state %+v", first)
	}
	if first.SampledAt.Location() != time.UTC || first.SampleIntervalSeconds != 5 || first.Disk.Mount != "/" {
		t.Fatal("monitor response contract")
	}
	*now = now.Add(4 * time.Second)
	var group sync.WaitGroup
	for index := 0; index < 100; index++ {
		group.Add(1)
		go func() {
			defer group.Done()
			monitor.sample()
		}()
	}
	group.Wait()
	if collector.calls != 1 {
		t.Fatalf("collecting for cached or parallel requests: %d", collector.calls)
	}
	*now = now.Add(time.Second)
	adminMonitorTestCPUAdvance(collector, 30)
	second := monitor.sample()
	if collector.calls != 2 || !second.CPU.Available || second.CPU.UsagePercent != 30 || second.CPU.SampleWindowSeconds != 5 {
		t.Fatalf("second monitor sample %+v, calls %d", second, collector.calls)
	}
}

func TestAdminMonitorCPUAlertRequiresContinuousThirtySeconds(t *testing.T) {
	for _, testCase := range []struct {
		usage uint64
		level string
	}{{80, "warning"}, {95, "critical"}} {
		t.Run(testCase.level, func(t *testing.T) {
			monitor, collector, now := newAdminMonitorTestState()
			monitor.sample()
			for sample := 1; sample <= 6; sample++ {
				*now = now.Add(5 * time.Second)
				adminMonitorTestCPUAdvance(collector, testCase.usage)
				if result := monitor.sample(); len(result.Alerts) != 0 {
					t.Fatalf("CPU alert before thirty observed seconds: %+v", result)
				}
			}
			*now = now.Add(5 * time.Second)
			adminMonitorTestCPUAdvance(collector, testCase.usage)
			result := monitor.sample()
			alert, found := adminMonitorTestAlert(result, "cpu_usage")
			if !found || alert.Level != testCase.level || result.Status != testCase.level {
				t.Fatalf("missing sustained CPU alert %+v", result)
			}
			*now = now.Add(5 * time.Second)
			adminMonitorTestCPUAdvance(collector, 20)
			if result := monitor.sample(); len(result.Alerts) != 0 || result.Status != "ok" {
				t.Fatalf("CPU recovery did not clear alert %+v", result)
			}
		})
	}
}

func TestAdminMonitorCPUGapRewarmsAndResetsAlert(t *testing.T) {
	monitor, collector, now := newAdminMonitorTestState()
	monitor.sample()
	for sample := 0; sample < 7; sample++ {
		*now = now.Add(5 * time.Second)
		adminMonitorTestCPUAdvance(collector, 97)
		monitor.sample()
	}
	*now = now.Add(16 * time.Second)
	adminMonitorTestCPUAdvance(collector, 97)
	gap := monitor.sample()
	if gap.CPU.Available || gap.CPU.Reason != "warming_up" || len(gap.Alerts) != 0 || gap.Status != "ok" {
		t.Fatalf("gap did not rewarm CPU %+v", gap)
	}
	*now = now.Add(5 * time.Second)
	adminMonitorTestCPUAdvance(collector, 97)
	after := monitor.sample()
	if !after.CPU.Available || after.CPU.UsagePercent != 97 || after.CPU.SampleWindowSeconds != 5 || len(after.Alerts) != 0 {
		t.Fatalf("CPU did not resume fresh short-window sampling %+v", after)
	}
}

func TestAdminMonitorCPUCounterResetAndRecovery(t *testing.T) {
	monitor, collector, now := newAdminMonitorTestState()
	collector.reading.cpu[0] = 100
	monitor.sample()
	*now = now.Add(5 * time.Second)
	collector.reading.cpu[0] = 1
	result := monitor.sample()
	if result.CPU.Available || result.CPU.Reason != "counter_reset" || result.Status != "unavailable" {
		t.Fatalf("counter reset not visible %+v", result)
	}
	*now = now.Add(5 * time.Second)
	adminMonitorTestCPUAdvance(collector, 10)
	if result := monitor.sample(); !result.CPU.Available || result.Status != "ok" {
		t.Fatalf("reset baseline did not recover %+v", result)
	}
	*now = now.Add(-time.Minute)
	adminMonitorTestCPUAdvance(collector, 10)
	if result := monitor.sample(); result.CPU.Available || result.CPU.Reason != "counter_reset" {
		t.Fatalf("clock rollback left stale CPU %+v", result)
	}
}

func TestAdminMonitorCapacityAlertThresholds(t *testing.T) {
	for _, testCase := range []struct {
		memoryFree, diskFree           uint64
		memoryLevel, diskLevel, status string
	}{
		{1501, 2001, "", "", "ok"},
		{1500, 2000, "warning", "warning", "warning"},
		{501, 1001, "warning", "warning", "warning"},
		{500, 1000, "critical", "critical", "critical"},
		{0, 0, "critical", "critical", "critical"},
	} {
		monitor, collector, _ := newAdminMonitorTestState()
		collector.reading.memoryFree, collector.reading.diskFree = testCase.memoryFree, testCase.diskFree
		result := monitor.sample()
		memory, hasMemory := adminMonitorTestAlert(result, "memory_usage")
		disk, hasDisk := adminMonitorTestAlert(result, "disk_usage")
		if hasMemory != (testCase.memoryLevel != "") || hasDisk != (testCase.diskLevel != "") || memory.Level != testCase.memoryLevel || disk.Level != testCase.diskLevel || result.Status != testCase.status {
			t.Fatalf("capacity threshold result %+v for %+v", result, testCase)
		}
	}
}

func TestAdminMonitorFailuresAreExplicitAndSanitized(t *testing.T) {
	monitor, collector, now := newAdminMonitorTestState()
	secretError := errors.New("/secret/account-path?password=private-hostname")
	collector.reading.cpuError = secretError
	collector.reading.memoryError = secretError
	collector.reading.diskError = secretError
	result := monitor.sample()
	if result.Status != "unavailable" || len(result.Alerts) != 3 || result.CPU.Available || result.Memory.Available || result.Disk.Available {
		t.Fatalf("failure presented as healthy %+v", result)
	}
	encoded, err := json.Marshal(result)
	if err != nil || strings.Contains(string(encoded), "secret") || strings.Contains(string(encoded), "password") || strings.Contains(string(encoded), "private-hostname") {
		t.Fatal("collector error leaked into output")
	}
	collector.reading.cpuError, collector.reading.memoryError, collector.reading.diskError = nil, nil, nil
	*now = now.Add(5 * time.Second)
	if result := monitor.sample(); result.CPU.Reason != "warming_up" || result.Status != "ok" || len(result.Alerts) != 0 {
		t.Fatalf("read failure recovery %+v", result)
	}
	collector.reading.memoryFree = 0
	collector.reading.diskError = secretError
	*now = now.Add(5 * time.Second)
	adminMonitorTestCPUAdvance(collector, 10)
	if result := monitor.sample(); result.Status != "critical" {
		t.Fatal("unavailable metric hid confirmed critical memory alert")
	}
}

func TestAdminMonitorUnsupportedAndInvalidCapacity(t *testing.T) {
	monitor, collector, _ := newAdminMonitorTestState()
	collector.reading = adminMonitorRaw{cpuError: errAdminMonitorUnsupported, memoryError: errAdminMonitorUnsupported, diskError: errAdminMonitorUnsupported, diskUsage: adminDiskUsageRaw{err: errAdminMonitorUnsupported}}
	result := monitor.sample()
	if result.Status != "unavailable" || result.CPU.Reason != "unsupported" || result.Memory.Reason != "unsupported" || result.Disk.Reason != "unsupported" || result.Disk.Breakdown.Status != "unsupported" || len(result.Alerts) != 4 {
		t.Fatalf("unsupported platform response %+v", result)
	}
	for _, metric := range []adminMonitorCapacity{adminMonitorCapacityValue(0, 0, nil), adminMonitorCapacityValue(10, 11, nil)} {
		if metric.Available || metric.Reason != "read_failed" {
			t.Fatalf("invalid capacity pretended to be healthy %+v", metric)
		}
	}
}

func TestAdminMonitorEndpointUsesAdminAuthBeforeCollecting(t *testing.T) {
	monitor, collector, now := newAdminMonitorTestState()
	token := strings.Repeat("M", 43)
	a := &app{mux: http.NewServeMux(), now: func() time.Time { return *now }, admin: &adminConfig{sessions: map[[32]byte]time.Time{sha256.Sum256([]byte(token)): now.Add(time.Minute)}}}
	a.mux.HandleFunc("GET /admin/api/monitor", a.adminAuth(monitor.handler))
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/monitor", "", ""), 401)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/monitor", strings.Repeat("P", 43), ""), 401)
	if collector.calls != 0 {
		t.Fatal("unauthenticated request collected host metrics")
	}
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/monitor?path=/secret", token, ""), 400)
	if collector.calls != 0 {
		t.Fatal("invalid request collected host metrics")
	}
	response := adminRequest(a, http.MethodGet, "/admin/api/monitor", token, "")
	wantStatus(t, response, 200)
	if response.Header().Get("Cache-Control") != "no-store" || collector.calls != 1 {
		t.Fatal("monitor endpoint caching or collection contract")
	}
	var result adminMonitorResponse
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil || !result.Memory.Available || !result.Disk.Breakdown.Available || result.Status != "ok" {
		t.Fatalf("invalid authenticated response %s", response.Body.String())
	}
	*now = now.Add(time.Minute)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/monitor", token, ""), 401)
	if collector.calls != 1 {
		t.Fatal("expired administrator session collected host metrics")
	}
}

func TestAdminMonitorRouteIsMounted(t *testing.T) {
	a, _, _ := fixture(t)
	configureAdminTest(t, a)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/monitor", "", ""), 401)
	token := loginAdminTest(t, a)
	response := adminRequest(a, http.MethodGet, "/admin/api/monitor", token, "")
	wantStatus(t, response, 200)
	var result adminMonitorResponse
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil || result.Disk.Mount != "/" || result.SampleIntervalSeconds != 5 || result.Alerts == nil {
		t.Fatalf("mounted route monitor contract: %s", response.Body.String())
	}
}
