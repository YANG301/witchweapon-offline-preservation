//go:build linux

package main

import (
	"errors"
	"io"
	"os"
	"syscall"
	"time"
)

func readAdminDiskUsageSnapshot() adminDiskUsageRaw {
	// Anchor all relative opens at a checked root-owned /run descriptor. The
	// directory and file are never supplied by a query parameter or user data.
	runFD, err := syscall.Open("/run", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return adminDiskUsageRaw{err: err}
	}
	defer syscall.Close(runFD)
	var runStat syscall.Stat_t
	if err := syscall.Fstat(runFD, &runStat); err != nil || !adminDiskUsageSafeDirectory(runStat) {
		return adminDiskUsageRaw{err: errors.New("unsafe disk inventory parent")}
	}
	directoryFD, err := syscall.Openat(runFD, "witchweapon-disk-usage", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return adminDiskUsageRaw{err: err}
	}
	defer syscall.Close(directoryFD)
	return readAdminDiskUsageAt(directoryFD)
}

func adminDiskUsageSafeDirectory(stat syscall.Stat_t) bool {
	return stat.Mode&syscall.S_IFMT == syscall.S_IFDIR && stat.Uid == 0 && stat.Mode&0022 == 0
}

func adminDiskUsageSafeFile(stat syscall.Stat_t) bool {
	return stat.Mode&syscall.S_IFMT == syscall.S_IFREG && stat.Uid == 0 && stat.Mode&0022 == 0 && stat.Nlink == 1 && stat.Size > 0 && stat.Size <= adminDiskUsageMaxSize
}

func readAdminDiskUsageAt(directoryFD int) adminDiskUsageRaw {
	var directoryStat syscall.Stat_t
	if err := syscall.Fstat(directoryFD, &directoryStat); err != nil || !adminDiskUsageSafeDirectory(directoryStat) {
		return adminDiskUsageRaw{err: errors.New("unsafe disk inventory directory")}
	}
	fd, err := syscall.Openat(directoryFD, "snapshot.json", syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return adminDiskUsageRaw{err: err}
	}
	file := os.NewFile(uintptr(fd), "disk-inventory")
	defer file.Close()
	var before syscall.Stat_t
	if err := syscall.Fstat(fd, &before); err != nil || !adminDiskUsageSafeFile(before) {
		return adminDiskUsageRaw{err: errors.New("unsafe disk inventory file")}
	}
	contents, err := io.ReadAll(io.LimitReader(file, adminDiskUsageMaxSize+1))
	if err != nil || len(contents) != int(before.Size) || len(contents) > adminDiskUsageMaxSize {
		return adminDiskUsageRaw{err: errors.New("invalid disk inventory file size")}
	}
	// The publisher replaces files atomically. In-place mutation is rejected
	// even if it preserves file length, and an opened old inode remains safe.
	var after syscall.Stat_t
	if err := syscall.Fstat(fd, &after); err != nil || !adminDiskUsageSafeFile(after) || before.Mode != after.Mode || before.Uid != after.Uid || before.Gid != after.Gid || before.Size != after.Size || before.Mtim != after.Mtim || before.Ctim != after.Ctim {
		return adminDiskUsageRaw{err: errors.New("disk inventory file changed while reading")}
	}
	return adminDiskUsageRaw{contents: contents, modifiedAt: time.Unix(before.Mtim.Sec, before.Mtim.Nsec)}
}
