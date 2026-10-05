package main

import (
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	adminMonitorSampleInterval = 5 * time.Second
	adminMonitorCPUAlertDelay  = 30 * time.Second
	adminMonitorMaxCPUGap      = 15 * time.Second
)

var errAdminMonitorUnsupported = errors.New("host monitoring unsupported")

// The collector reads only aggregate host counters. No process names, command
// lines, hostnames, player data, or configurable filesystem paths are exposed.
type adminMonitorCollector interface {
	collect() adminMonitorRaw
}

type adminMonitorCPUCounters [8]uint64

type adminMonitorRaw struct {
	cpu                     adminMonitorCPUCounters
	cpuError                error
	memoryTotal, memoryFree uint64
	memoryError             error
	diskTotal, diskFree     uint64
	diskError               error
	diskUsage               adminDiskUsageRaw
}

type adminMonitorCPU struct {
	Available           bool    `json:"available"`
	UsagePercent        float64 `json:"usagePercent"`
	IOWaitPercent       float64 `json:"iowaitPercent"`
	SampleWindowSeconds float64 `json:"sampleWindowSeconds"`
	Reason              string  `json:"reason,omitempty"`
}

type adminMonitorCapacity struct {
	Available      bool    `json:"available"`
	TotalBytes     uint64  `json:"totalBytes"`
	AvailableBytes uint64  `json:"availableBytes"`
	UsedBytes      uint64  `json:"usedBytes"`
	UsagePercent   float64 `json:"usagePercent"`
	Reason         string  `json:"reason,omitempty"`
}

type adminMonitorDisk struct {
	adminMonitorCapacity
	Mount     string                  `json:"mount"`
	Breakdown adminDiskUsageBreakdown `json:"breakdown"`
}

type adminMonitorAlert struct {
	ID     string `json:"id"`
	Level  string `json:"level"`
	Title  string `json:"title"`
	Detail string `json:"detail"`
}

type adminMonitorResponse struct {
	SampledAt             time.Time            `json:"sampledAt"`
	SampleIntervalSeconds int                  `json:"sampleIntervalSeconds"`
	CPU                   adminMonitorCPU      `json:"cpu"`
	Memory                adminMonitorCapacity `json:"memory"`
	Disk                  adminMonitorDisk     `json:"disk"`
	Alerts                []adminMonitorAlert  `json:"alerts"`
	Status                string               `json:"status"`
}

type adminMonitorState struct {
	mu            sync.Mutex
	collector     adminMonitorCollector
	now           func() time.Time
	last          adminMonitorResponse
	hasSample     bool
	previousCPU   adminMonitorCPUCounters
	previousAt    time.Time
	hasCPU        bool
	warningSince  time.Time
	criticalSince time.Time
}

func (a *app) mountAdminMonitor() {
	monitor := &adminMonitorState{collector: newAdminMonitorCollector(), now: func() time.Time { return a.now() }}
	a.mux.HandleFunc("GET /admin/api/monitor", a.adminAuth(monitor.handler))
}

func (m *adminMonitorState) handler(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		fail(w, 400, "invalid_request", "服务器监控不接受查询参数或编码路径。")
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, m.sample())
}

func (m *adminMonitorState) sample() adminMonitorResponse {
	m.mu.Lock()
	defer m.mu.Unlock()
	now := m.now()
	if m.hasSample && !now.Before(m.last.SampledAt) && now.Sub(m.last.SampledAt) < adminMonitorSampleInterval {
		return m.last
	}
	raw := m.collector.collect()
	result := adminMonitorResponse{
		SampledAt: now.UTC(), SampleIntervalSeconds: int(adminMonitorSampleInterval / time.Second),
		Alerts: make([]adminMonitorAlert, 0, 3), Status: "ok",
	}
	result.Memory = adminMonitorCapacityValue(raw.memoryTotal, raw.memoryFree, raw.memoryError)
	result.Disk = adminMonitorDisk{adminMonitorCapacity: adminMonitorCapacityValue(raw.diskTotal, raw.diskFree, raw.diskError), Mount: "/", Breakdown: parseAdminDiskUsage(raw.diskUsage, now)}
	if alert := adminDiskUsageAlert(result.Disk.Breakdown); alert != nil {
		result.Alerts = append(result.Alerts, *alert)
	}
	result.CPU = m.sampleCPU(raw.cpu, raw.cpuError, now)
	for _, metric := range []struct {
		id, title, reason string
	}{
		{"cpu", "CPU", result.CPU.Reason},
		{"memory", "内存", result.Memory.Reason},
		{"disk", "磁盘", result.Disk.Reason},
	} {
		if metric.reason == "" || metric.reason == "warming_up" {
			continue
		}
		detail := "无法读取服务器指标，请检查服务器运行状态；当前值不可用。"
		if metric.reason == "unsupported" {
			detail = "当前系统不支持宿主资源监控；此功能用于 Linux 游戏服务器。"
		} else if metric.reason == "counter_reset" {
			detail = "CPU 计数发生变化，已重置采样；请等待下一次有效采样。"
		}
		result.Alerts = append(result.Alerts, adminMonitorAlert{metric.id + "_unavailable", "warning", metric.title + "监控不可用", detail})
		result.Status = "unavailable"
	}
	if result.CPU.Available {
		if !m.criticalSince.IsZero() && now.Sub(m.criticalSince) >= adminMonitorCPUAlertDelay {
			result.Alerts = append(result.Alerts, adminMonitorAlert{"cpu_usage", "critical", "CPU 持续高负载", "CPU 使用率已连续至少 30 秒达到 95%，请检查业务负载。"})
		} else if !m.warningSince.IsZero() && now.Sub(m.warningSince) >= adminMonitorCPUAlertDelay {
			result.Alerts = append(result.Alerts, adminMonitorAlert{"cpu_usage", "warning", "CPU 负载偏高", "CPU 使用率已连续至少 30 秒达到 80%，请留意服务器响应。"})
		}
	}
	result.Alerts = adminMonitorCapacityAlert(result.Alerts, "memory", "内存", result.Memory, 85, 95)
	result.Alerts = adminMonitorCapacityAlert(result.Alerts, "disk", "根分区磁盘", result.Disk.adminMonitorCapacity, 80, 90)
	for _, alert := range result.Alerts {
		if alert.Level == "critical" {
			result.Status = "critical"
			break
		}
		if result.Status == "ok" {
			result.Status = "warning"
		}
	}
	m.last, m.hasSample = result, true
	return result
}

func (m *adminMonitorState) sampleCPU(current adminMonitorCPUCounters, err error, now time.Time) adminMonitorCPU {
	if err != nil {
		m.hasCPU = false
		m.warningSince, m.criticalSince = time.Time{}, time.Time{}
		return adminMonitorCPU{Reason: adminMonitorErrorReason(err)}
	}
	previous, previousAt, hadCPU := m.previousCPU, m.previousAt, m.hasCPU
	m.previousCPU, m.previousAt, m.hasCPU = current, now, true
	if !hadCPU {
		return adminMonitorCPU{Reason: "warming_up"}
	}
	window := now.Sub(previousAt)
	if window <= 0 {
		m.warningSince, m.criticalSince = time.Time{}, time.Time{}
		return adminMonitorCPU{Reason: "counter_reset"}
	}
	// After an inactive browser or long polling gap, collect a fresh baseline
	// rather than presenting a long-term average as current CPU usage.
	if window > adminMonitorMaxCPUGap {
		m.warningSince, m.criticalSince = time.Time{}, time.Time{}
		return adminMonitorCPU{Reason: "warming_up"}
	}
	usage, iowait, valid := adminMonitorCPUUsage(previous, current)
	if !valid {
		m.warningSince, m.criticalSince = time.Time{}, time.Time{}
		return adminMonitorCPU{Reason: "counter_reset"}
	}
	if usage >= 80 {
		if m.warningSince.IsZero() {
			m.warningSince = now
		}
	} else {
		m.warningSince = time.Time{}
	}
	if usage >= 95 {
		if m.criticalSince.IsZero() {
			m.criticalSince = now
		}
	} else {
		m.criticalSince = time.Time{}
	}
	return adminMonitorCPU{Available: true, UsagePercent: usage, IOWaitPercent: iowait, SampleWindowSeconds: window.Seconds()}
}

func adminMonitorCPUUsage(previous, current adminMonitorCPUCounters) (usage, iowait float64, valid bool) {
	var total, idle, io float64
	for index := range current {
		if current[index] < previous[index] {
			return 0, 0, false
		}
		delta := float64(current[index] - previous[index])
		total += delta
		if index == 3 {
			idle = delta
		}
		if index == 4 {
			io = delta
		}
	}
	if total <= 0 {
		return 0, 0, false
	}
	return (total - idle - io) / total * 100, io / total * 100, true
}

func adminMonitorCapacityValue(total, available uint64, err error) adminMonitorCapacity {
	if err != nil {
		return adminMonitorCapacity{Reason: adminMonitorErrorReason(err)}
	}
	if total == 0 || available > total {
		return adminMonitorCapacity{Reason: "read_failed"}
	}
	// For root disk capacity, available is statfs.Bavail: blocks available to
	// ordinary users. "Used" also includes filesystem reserved space.
	used := total - available
	return adminMonitorCapacity{Available: true, TotalBytes: total, AvailableBytes: available, UsedBytes: used, UsagePercent: float64(used) / float64(total) * 100}
}

func adminMonitorErrorReason(err error) string {
	if errors.Is(err, errAdminMonitorUnsupported) {
		return "unsupported"
	}
	return "read_failed"
}

func adminMonitorCapacityAlert(alerts []adminMonitorAlert, id, title string, metric adminMonitorCapacity, warning, critical float64) []adminMonitorAlert {
	if !metric.Available || metric.UsagePercent < warning {
		return alerts
	}
	level, threshold := "warning", warning
	if metric.UsagePercent >= critical {
		level, threshold = "critical", critical
	}
	detail := fmt.Sprintf("%s使用率已达到 %.0f%% 告警线，当前为 %.1f%%；请检查剩余可用容量。", title, threshold, metric.UsagePercent)
	return append(alerts, adminMonitorAlert{id + "_usage", level, title + "容量不足", detail})
}

// Linux guest/guest_nice counters are already included in user/nice and must
// not be summed again. Only the first eight aggregate CPU fields are used.
func parseAdminMonitorCPU(line string) (adminMonitorCPUCounters, error) {
	var counters adminMonitorCPUCounters
	fields := strings.Fields(line)
	if len(fields) < 9 || fields[0] != "cpu" {
		return counters, errors.New("invalid aggregate CPU counters")
	}
	for index := range counters {
		value, err := strconv.ParseUint(fields[index+1], 10, 64)
		if err != nil {
			return adminMonitorCPUCounters{}, errors.New("invalid CPU counter")
		}
		counters[index] = value
	}
	return counters, nil
}

func parseAdminMonitorMemory(contents string) (total, available uint64, err error) {
	found := make(map[string]bool, 2)
	for _, line := range strings.Split(contents, "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 || fields[0] != "MemTotal:" && fields[0] != "MemAvailable:" {
			continue
		}
		if len(fields) != 3 || fields[2] != "kB" || found[fields[0]] {
			return 0, 0, errors.New("invalid memory counter")
		}
		value, parseErr := strconv.ParseUint(fields[1], 10, 64)
		if parseErr != nil || value > ^uint64(0)/1024 {
			return 0, 0, errors.New("invalid memory counter")
		}
		found[fields[0]] = true
		if fields[0] == "MemTotal:" {
			total = value * 1024
		} else {
			available = value * 1024
		}
	}
	if !found["MemTotal:"] || !found["MemAvailable:"] || total == 0 || available > total {
		return 0, 0, errors.New("missing or inconsistent memory counters")
	}
	return total, available, nil
}

func adminMonitorDiskBytes(blocks, available, blockSize uint64) (uint64, uint64, error) {
	if blockSize == 0 || blocks == 0 || available > blocks || blocks > ^uint64(0)/blockSize {
		return 0, 0, errors.New("invalid filesystem counters")
	}
	return blocks * blockSize, available * blockSize, nil
}
