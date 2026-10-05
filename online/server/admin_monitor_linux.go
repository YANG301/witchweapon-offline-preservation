//go:build linux

package main

import (
	"bufio"
	"errors"
	"io"
	"os"
	"syscall"
)

type adminMonitorLinuxCollector struct{}

func newAdminMonitorCollector() adminMonitorCollector { return adminMonitorLinuxCollector{} }

func (adminMonitorLinuxCollector) collect() adminMonitorRaw {
	var raw adminMonitorRaw
	cpuFile, err := os.Open("/proc/stat")
	if err != nil {
		raw.cpuError = err
	} else {
		line, readErr := bufio.NewReader(io.LimitReader(cpuFile, 2048)).ReadString('\n')
		cpuFile.Close()
		if readErr != nil {
			raw.cpuError = errors.New("cannot read aggregate CPU counters")
		} else {
			raw.cpu, raw.cpuError = parseAdminMonitorCPU(line)
		}
	}
	memoryFile, err := os.Open("/proc/meminfo")
	if err != nil {
		raw.memoryError = err
	} else {
		contents, readErr := io.ReadAll(io.LimitReader(memoryFile, 65537))
		memoryFile.Close()
		if readErr != nil || len(contents) > 65536 {
			raw.memoryError = errors.New("cannot read memory counters")
		} else {
			raw.memoryTotal, raw.memoryFree, raw.memoryError = parseAdminMonitorMemory(string(contents))
		}
	}
	var filesystem syscall.Statfs_t
	if err := syscall.Statfs("/", &filesystem); err != nil {
		raw.diskError = err
	} else if filesystem.Bsize <= 0 {
		raw.diskError = errors.New("invalid filesystem block size")
	} else {
		raw.diskTotal, raw.diskFree, raw.diskError = adminMonitorDiskBytes(filesystem.Blocks, filesystem.Bavail, uint64(filesystem.Bsize))
	}
	raw.diskUsage = readAdminDiskUsageSnapshot()
	return raw
}
