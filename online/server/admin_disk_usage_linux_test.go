//go:build linux

package main

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestAdminDiskUsageLinuxMetadataChecks(t *testing.T) {
	goodDirectory := syscall.Stat_t{Mode: syscall.S_IFDIR | 0755, Uid: 0}
	if !adminDiskUsageSafeDirectory(goodDirectory) {
		t.Fatal("root-owned safe directory rejected")
	}
	for _, directory := range []syscall.Stat_t{
		{Mode: syscall.S_IFLNK | 0755, Uid: 0},
		{Mode: syscall.S_IFDIR | 0775, Uid: 0},
		{Mode: syscall.S_IFDIR | 0757, Uid: 0},
		{Mode: syscall.S_IFDIR | 0755, Uid: 1000},
	} {
		if adminDiskUsageSafeDirectory(directory) {
			t.Fatal("unsafe inventory directory accepted")
		}
	}
	goodFile := syscall.Stat_t{Mode: syscall.S_IFREG | 0644, Uid: 0, Nlink: 1, Size: adminDiskUsageMaxSize}
	if !adminDiskUsageSafeFile(goodFile) {
		t.Fatal("root-owned safe file rejected")
	}
	for _, mutate := range []func(*syscall.Stat_t){
		func(s *syscall.Stat_t) { s.Mode = syscall.S_IFIFO | 0644 },
		func(s *syscall.Stat_t) { s.Mode = syscall.S_IFLNK | 0644 },
		func(s *syscall.Stat_t) { s.Mode |= 0020 },
		func(s *syscall.Stat_t) { s.Mode |= 0002 },
		func(s *syscall.Stat_t) { s.Uid = 1000 },
		func(s *syscall.Stat_t) { s.Nlink = 2 },
		func(s *syscall.Stat_t) { s.Size = 0 },
		func(s *syscall.Stat_t) { s.Size++ },
	} {
		candidate := goodFile
		mutate(&candidate)
		if adminDiskUsageSafeFile(candidate) {
			t.Fatal("unsafe inventory file accepted")
		}
	}
}

func TestAdminDiskUsageLinuxRootOwnedFileReader(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("root ownership fixtures require a root test namespace")
	}
	for _, testCase := range []struct {
		name      string
		prepare   func(string, string) error
		wantError bool
	}{
		{"regular", nil, false},
		{"group writable file", func(_ string, file string) error { return os.Chmod(file, 0664) }, true},
		{"world writable directory", func(directory, _ string) error { return os.Chmod(directory, 0777) }, true},
		{"oversized", func(_ string, file string) error { return os.Truncate(file, adminDiskUsageMaxSize+1) }, true},
		{"hard link", func(directory, file string) error { return os.Link(file, filepath.Join(directory, "second-link")) }, true},
		{"symbolic link", func(directory, file string) error {
			if err := os.Rename(file, filepath.Join(directory, "target.json")); err != nil {
				return err
			}
			return os.Symlink("target.json", file)
		}, true},
		{"fifo", func(_ string, file string) error {
			if err := os.Remove(file); err != nil {
				return err
			}
			return syscall.Mkfifo(file, 0644)
		}, true},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			directory := t.TempDir()
			file := filepath.Join(directory, "snapshot.json")
			if err := os.WriteFile(file, []byte(`{"fixture":true}`), 0644); err != nil {
				t.Fatal(err)
			}
			if testCase.prepare != nil {
				if err := testCase.prepare(directory, file); err != nil {
					t.Fatal(err)
				}
			}
			fd, err := syscall.Open(directory, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
			if err != nil {
				t.Fatal(err)
			}
			defer syscall.Close(fd)
			raw := readAdminDiskUsageAt(fd)
			if (raw.err != nil) != testCase.wantError {
				t.Fatalf("safe file reader error %v", raw.err)
			}
			if !testCase.wantError && (string(raw.contents) != `{"fixture":true}` || raw.modifiedAt.IsZero()) {
				t.Fatal("safe file bytes or metadata changed")
			}
		})
	}
}
