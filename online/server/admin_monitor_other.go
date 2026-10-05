//go:build !linux

package main

type adminMonitorUnsupportedCollector struct{}

func newAdminMonitorCollector() adminMonitorCollector { return adminMonitorUnsupportedCollector{} }

func (adminMonitorUnsupportedCollector) collect() adminMonitorRaw {
	return adminMonitorRaw{cpuError: errAdminMonitorUnsupported, memoryError: errAdminMonitorUnsupported, diskError: errAdminMonitorUnsupported, diskUsage: adminDiskUsageRaw{err: errAdminMonitorUnsupported}}
}
