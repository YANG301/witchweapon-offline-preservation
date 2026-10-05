package main

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"
)

func adminDiskUsageTestSnapshot(now time.Time) adminDiskUsageSnapshot {
	total := uint64(0)
	result := adminDiskUsageSnapshot{SchemaVersion: 1, SampledAt: now.UTC(), RefreshIntervalSeconds: adminDiskUsageRefresh, Status: "ok"}
	for _, category := range adminDiskUsageCategories {
		value, files := uint64(1024), uint64(1)
		result.Items = append(result.Items, adminDiskUsageSnapshotItem{ID: category.id, Status: "ok", AllocatedBytes: &value, FileCount: &files})
		total += value
	}
	confirmed := total
	result.AllocatedBytes, result.ConfirmedAllocatedBytes = &total, &confirmed
	return result
}

func adminDiskUsageTestRaw(now time.Time) adminDiskUsageRaw {
	body, _ := json.Marshal(adminDiskUsageTestSnapshot(now))
	return adminDiskUsageRaw{contents: body, modifiedAt: now}
}

func adminDiskUsageTestEncode(t *testing.T, snapshot adminDiskUsageSnapshot, modified time.Time) adminDiskUsageRaw {
	t.Helper()
	body, err := json.Marshal(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	return adminDiskUsageRaw{contents: body, modifiedAt: modified}
}

func TestAdminDiskUsageCompleteOrderAndZero(t *testing.T) {
	now := time.Date(2026, 10, 4, 1, 0, 0, 0, time.UTC)
	snapshot := adminDiskUsageTestSnapshot(now)
	snapshot.Items[0], snapshot.Items[7] = snapshot.Items[7], snapshot.Items[0]
	result := parseAdminDiskUsage(adminDiskUsageTestEncode(t, snapshot, now), now)
	if !result.Available || result.Status != "ok" || result.SampledAt == nil || result.AllocatedBytes == nil || *result.AllocatedBytes != 8192 || result.ConfirmedAllocatedBytes == nil || *result.ConfirmedAllocatedBytes != 8192 || len(result.Items) != 8 || adminDiskUsageAlert(result) != nil {
		t.Fatalf("complete inventory %+v", result)
	}
	for index, item := range result.Items {
		if item.ID != adminDiskUsageCategories[index].id || item.Label != adminDiskUsageCategories[index].label || !item.Available || item.Status != "ok" || item.AllocatedBytes == nil || item.FileCount == nil || item.Detail == "" {
			t.Fatalf("inventory item ordering or labels %+v", item)
		}
	}
	for index := range snapshot.Items {
		zeroBytes, zeroFiles := uint64(0), uint64(0)
		snapshot.Items[index].AllocatedBytes, snapshot.Items[index].FileCount = &zeroBytes, &zeroFiles
	}
	zeroTotal, zeroConfirmed := uint64(0), uint64(0)
	snapshot.AllocatedBytes, snapshot.ConfirmedAllocatedBytes = &zeroTotal, &zeroConfirmed
	if zero := parseAdminDiskUsage(adminDiskUsageTestEncode(t, snapshot, now), now); !zero.Available || zero.AllocatedBytes == nil || *zero.AllocatedBytes != 0 {
		t.Fatalf("confirmed genuine zero rejected %+v", zero)
	}
}

func TestAdminDiskUsagePartialLowerBoundAndUnavailable(t *testing.T) {
	now := time.Date(2026, 10, 4, 1, 0, 0, 0, time.UTC)
	snapshot := adminDiskUsageTestSnapshot(now)
	snapshot.Status, snapshot.AllocatedBytes = "partial", nil
	snapshot.Items[0].Status = "partial"
	snapshot.Items[1].Status, snapshot.Items[1].AllocatedBytes, snapshot.Items[1].FileCount = "unavailable", nil, nil
	confirmed := uint64(7168)
	snapshot.ConfirmedAllocatedBytes = &confirmed
	result := parseAdminDiskUsage(adminDiskUsageTestEncode(t, snapshot, now), now)
	if !result.Available || result.Status != "partial" || result.AllocatedBytes != nil || result.ConfirmedAllocatedBytes == nil || *result.ConfirmedAllocatedBytes != confirmed || !result.Items[0].Available || result.Items[0].Status != "partial" || !strings.Contains(result.Items[0].Detail, "下限") || result.Items[1].Available || result.Items[1].AllocatedBytes != nil || result.Items[1].FileCount != nil {
		t.Fatalf("partial inventory %+v", result)
	}
	if alert := adminDiskUsageAlert(result); alert == nil || alert.ID != "storage_inventory" || alert.Level != "warning" {
		t.Fatal("partial inventory warning is missing or mislabeled")
	}
	for index := range snapshot.Items {
		snapshot.Items[index].Status, snapshot.Items[index].AllocatedBytes, snapshot.Items[index].FileCount = "unavailable", nil, nil
	}
	confirmed = 0
	allUnavailable := parseAdminDiskUsage(adminDiskUsageTestEncode(t, snapshot, now), now)
	if allUnavailable.Available || allUnavailable.Status != "unavailable" || allUnavailable.AllocatedBytes != nil || allUnavailable.ConfirmedAllocatedBytes != nil {
		t.Fatalf("all failed categories presented as zero %+v", allUnavailable)
	}
}

func TestAdminDiskUsageStaleAndTimestampValidation(t *testing.T) {
	now := time.Date(2026, 10, 4, 1, 0, 0, 0, time.UTC)
	stale := parseAdminDiskUsage(adminDiskUsageTestRaw(now.Add(-16*time.Minute)), now)
	if stale.Available || stale.Status != "stale" || stale.AllocatedBytes == nil || stale.SampledAt == nil || len(stale.Items) != 8 || !stale.Items[0].Available {
		t.Fatalf("stale inventory lost its reference detail or became current %+v", stale)
	}
	if alert := adminDiskUsageAlert(stale); alert == nil || !strings.Contains(alert.Detail, "15 分钟") {
		t.Fatal("stale inventory did not explain expiration")
	}
	atBoundary := parseAdminDiskUsage(adminDiskUsageTestRaw(now.Add(-15*time.Minute)), now)
	if !atBoundary.Available || atBoundary.Status != "ok" {
		t.Fatal("fifteen minute boundary is prematurely stale")
	}
	for _, raw := range []adminDiskUsageRaw{
		adminDiskUsageTestRaw(now.Add(61 * time.Second)),
		{contents: adminDiskUsageTestRaw(now).contents, modifiedAt: now.Add(61 * time.Second)},
		{contents: adminDiskUsageTestRaw(now).contents, modifiedAt: now.Add(-3 * time.Minute)},
		{contents: adminDiskUsageTestRaw(now).contents},
	} {
		if result := parseAdminDiskUsage(raw, now); result.Available || result.Status != "unavailable" || result.SampledAt != nil {
			t.Fatalf("inconsistent timestamp accepted %+v", result)
		}
	}
}

func TestAdminDiskUsageInvalidSchemaAndTotals(t *testing.T) {
	now := time.Date(2026, 10, 4, 1, 0, 0, 0, time.UTC)
	for _, testCase := range []struct {
		name string
		edit func(*adminDiskUsageSnapshot)
	}{
		{"version", func(s *adminDiskUsageSnapshot) { s.SchemaVersion = 2 }},
		{"interval", func(s *adminDiskUsageSnapshot) { s.RefreshIntervalSeconds = 5 }},
		{"unknown status", func(s *adminDiskUsageSnapshot) { s.Status = "critical" }},
		{"missing item", func(s *adminDiskUsageSnapshot) { s.Items = s.Items[:7] }},
		{"unknown id", func(s *adminDiskUsageSnapshot) { s.Items[0].ID = "/private/player-path" }},
		{"duplicate id", func(s *adminDiskUsageSnapshot) { s.Items[0].ID = s.Items[1].ID }},
		{"item status", func(s *adminDiskUsageSnapshot) { s.Items[0].Status = "stale" }},
		{"missing bytes", func(s *adminDiskUsageSnapshot) { s.Items[0].AllocatedBytes = nil }},
		{"missing count", func(s *adminDiskUsageSnapshot) { s.Items[0].FileCount = nil }},
		{"full total", func(s *adminDiskUsageSnapshot) { *s.AllocatedBytes = 1 }},
		{"confirmed total", func(s *adminDiskUsageSnapshot) { *s.ConfirmedAllocatedBytes = 1 }},
		{"null full total", func(s *adminDiskUsageSnapshot) { s.AllocatedBytes = nil }},
		{"partial with full total", func(s *adminDiskUsageSnapshot) { s.Status = "partial"; s.Items[0].Status = "partial" }},
		{"partial with all ok", func(s *adminDiskUsageSnapshot) { s.Status = "partial"; s.AllocatedBytes = nil }},
		{"unavailable with bytes", func(s *adminDiskUsageSnapshot) { s.Items[0].Status = "unavailable" }},
		{"unsafe count", func(s *adminDiskUsageSnapshot) { *s.Items[0].FileCount = adminDiskUsageMaxInteger + 1 }},
		{"sum overflow", func(s *adminDiskUsageSnapshot) { *s.Items[0].AllocatedBytes = adminDiskUsageMaxInteger }},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			snapshot := adminDiskUsageTestSnapshot(now)
			testCase.edit(&snapshot)
			result := parseAdminDiskUsage(adminDiskUsageTestEncode(t, snapshot, now), now)
			if result.Available || result.Status != "unavailable" || result.AllocatedBytes != nil || result.ConfirmedAllocatedBytes != nil {
				t.Fatalf("invalid schema accepted %+v", result)
			}
		})
	}
}

func TestAdminDiskUsageRejectsAmbiguousOrInjectedJSON(t *testing.T) {
	now := time.Date(2026, 10, 4, 1, 0, 0, 0, time.UTC)
	valid := string(adminDiskUsageTestRaw(now).contents)
	for _, contents := range []string{
		valid + " {}",
		strings.Replace(valid, `"schemaVersion":1`, `"schemaVersion":1,"schemaVersion":1`, 1),
		strings.Replace(valid, `"schemaVersion":1`, `"schemaVersion":1,"\u0073chemaVersion":1`, 1),
		strings.Replace(valid, `"schemaVersion":1`, `"SchemaVersion":1`, 1),
		strings.Replace(valid, `"schemaVersion":1`, `"schemaVersion":1,"path":"/private/secret-account"`, 1),
		strings.Replace(valid, `"id":"programs"`, `"id":"programs","id":"programs"`, 1),
		strings.Replace(valid, `"id":"programs"`, `"id":"programs","label":"Injected hostname"`, 1),
		strings.Replace(valid, `"fileCount":1`, `"fileCount":1.5`, 1),
		strings.Replace(valid, `"fileCount":1`, `"fileCount":-1`, 1),
		strings.Replace(valid, `"fileCount":1`, `"fileCount":18446744073709551616`, 1),
		strings.Replace(valid, `"fileCount":1`, `"fileCount":null`, 1),
		strings.Repeat(" ", adminDiskUsageMaxSize+1),
		"{\xff}",
		"",
	} {
		result := parseAdminDiskUsage(adminDiskUsageRaw{contents: []byte(contents), modifiedAt: now}, now)
		if result.Available || result.Status != "unavailable" {
			t.Fatalf("ambiguous or injected JSON accepted %+v", result)
		}
		encoded, _ := json.Marshal(result)
		if strings.Contains(string(encoded), "secret-account") || strings.Contains(string(encoded), "Injected hostname") {
			t.Fatal("untrusted disk inventory content leaked")
		}
	}
}

func TestAdminDiskUsageFailureKeepsHostDiskCapacity(t *testing.T) {
	monitor, collector, _ := newAdminMonitorTestState()
	collector.reading.diskUsage = adminDiskUsageRaw{err: errors.New("/private/data: password=secret")}
	result := monitor.sample()
	if !result.Disk.Available || result.Disk.UsagePercent != 50 || result.Disk.Breakdown.Available || result.Disk.Breakdown.Status != "unavailable" || result.Status != "warning" {
		t.Fatalf("inventory failure broke whole-disk capacity %+v", result)
	}
	alert, found := adminMonitorTestAlert(result, "storage_inventory")
	if !found || alert.Level != "warning" {
		t.Fatal("inventory warning missing")
	}
	encoded, _ := json.Marshal(result)
	if strings.Contains(string(encoded), "password") || strings.Contains(string(encoded), "/private/data") || !strings.Contains(string(encoded), `"allocatedBytes":null`) {
		t.Fatal("inventory errors leaked or missing values appeared as zero")
	}
}
