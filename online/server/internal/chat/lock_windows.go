//go:build windows

package chat

import (
	"os"
	"syscall"
	"unsafe"
)

func acquireDataLock(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	proc := syscall.NewLazyDLL("kernel32.dll").NewProc("LockFileEx")
	var overlap syscall.Overlapped
	ok, _, callErr := proc.Call(f.Fd(), 3, 0, 1, 0, uintptr(unsafe.Pointer(&overlap)))
	if ok == 0 {
		_ = f.Close()
		return nil, callErr
	}
	return f, nil
}
