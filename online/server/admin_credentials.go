package main

import (
	"bytes"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"unicode"
	"unicode/utf8"

	"golang.org/x/crypto/argon2"
	"golang.org/x/term"
)

const (
	adminUsername          = "admin"
	adminArgonMemoryKiB    = 19 * 1024
	adminArgonIterations   = 2
	adminArgonParallelism  = 1
	adminCredentialEnvName = "WW_ADMIN_CREDENTIALS_V1"
)

// The systemd EnvironmentFile is readable only by root. It contains this
// encoded password verifier, never the administrator's plaintext password.
// Fixed, validated KDF parameters avoid an untrusted config exhausting RAM.
type adminCredentialRecord struct {
	Version   int    `json:"version"`
	Username  string `json:"username"`
	Algorithm string `json:"algorithm"`
	Salt      string `json:"salt"`
	Hash      string `json:"hash"`
}

type adminCredential struct {
	Salt [16]byte
	Hash [32]byte
}

func adminPasswordKey(password, salt []byte) [32]byte {
	var out [32]byte
	copy(out[:], argon2.IDKey(password, salt, adminArgonIterations, adminArgonMemoryKiB, adminArgonParallelism, 32))
	return out
}

func validAdminPassword(password []byte) bool {
	if len(password) < 12 || len(password) > 256 || !utf8.Valid(password) {
		return false
	}
	count := 0
	for _, r := range string(password) {
		count++
		if unicode.IsControl(r) || unicode.Is(unicode.Cf, r) {
			return false
		}
	}
	return count >= 12 && count <= 128
}

func encodeAdminCredential(password []byte) (string, error) {
	if !validAdminPassword(password) {
		return "", errors.New("管理员密码须为 12 至 128 个字符、至多 256 字节，且不能包含控制字符")
	}
	var salt [16]byte
	if _, err := rand.Read(salt[:]); err != nil {
		return "", err
	}
	hash := adminPasswordKey(password, salt[:])
	record := adminCredentialRecord{
		Version: 1, Username: adminUsername, Algorithm: "argon2id-m19456-t2-p1",
		Salt: base64.RawURLEncoding.EncodeToString(salt[:]),
		Hash: base64.RawURLEncoding.EncodeToString(hash[:]),
	}
	data, err := json.Marshal(record)
	if err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(data), nil
}

func decodeAdminCredential(encoded string) (adminCredential, error) {
	invalid := errors.New("管理员凭据配置无效")
	if len(encoded) < 80 || len(encoded) > 1024 || strings.TrimSpace(encoded) != encoded {
		return adminCredential{}, invalid
	}
	data, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		return adminCredential{}, invalid
	}
	var record adminCredentialRecord
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&record) != nil || decoder.Decode(new(any)) != io.EOF ||
		record.Version != 1 || record.Username != adminUsername || record.Algorithm != "argon2id-m19456-t2-p1" {
		return adminCredential{}, invalid
	}
	salt, saltErr := base64.RawURLEncoding.DecodeString(record.Salt)
	hash, hashErr := base64.RawURLEncoding.DecodeString(record.Hash)
	if saltErr != nil || hashErr != nil || len(salt) != 16 || len(hash) != 32 {
		return adminCredential{}, invalid
	}
	var result adminCredential
	copy(result.Salt[:], salt)
	copy(result.Hash[:], hash)
	return result, nil
}

func zeroBytes(data []byte) {
	for i := range data {
		data[i] = 0
	}
}

func readAdminPassword(prompt string) ([]byte, error) {
	fd := int(os.Stdin.Fd())
	if !term.IsTerminal(fd) {
		return nil, errors.New("设置管理员密码需要交互式终端")
	}
	_, _ = fmt.Fprint(os.Stderr, prompt)
	password, err := term.ReadPassword(fd)
	_, _ = fmt.Fprintln(os.Stderr)
	return password, err
}

// runAdminSetPassword is called only from a real terminal; password bytes
// never occur in argv, shell history, process environment, or the output file.
func runAdminSetPassword(path string) error {
	if !filepath.IsAbs(path) {
		return errors.New("-admin-credential-env 必须是绝对路径")
	}
	first, err := readAdminPassword("设置 admin 密码：")
	if err != nil {
		return err
	}
	defer zeroBytes(first)
	if !validAdminPassword(first) {
		return errors.New("管理员密码须为 12 至 128 个字符、至多 256 字节，且不能包含控制字符")
	}
	second, err := readAdminPassword("再次输入密码：")
	if err != nil {
		return err
	}
	defer zeroBytes(second)
	if subtle.ConstantTimeCompare(first, second) != 1 {
		return errors.New("两次输入的密码不一致")
	}
	encoded, err := encodeAdminCredential(first)
	if err != nil {
		return err
	}
	if err := writeAdminCredentialEnv(path, encoded); err != nil {
		return err
	}
	_, _ = fmt.Fprintln(os.Stdout, "管理员密码已设置；重启游戏网关后生效，旧管理会话将失效。")
	return nil
}

func writeAdminCredentialEnv(path, encoded string) error {
	if _, err := decodeAdminCredential(encoded); err != nil {
		return err
	}
	if info, err := os.Lstat(path); err == nil {
		if !info.Mode().IsRegular() {
			return errors.New("管理员凭据目标不是普通文件")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	dir := filepath.Dir(path)
	temp, err := os.CreateTemp(dir, ".admin-auth-*")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	if err := temp.Chmod(0600); err != nil {
		_ = temp.Close()
		return err
	}
	if _, err := io.WriteString(temp, adminCredentialEnvName+"="+encoded+"\n"); err != nil {
		_ = temp.Close()
		return err
	}
	if err := temp.Sync(); err != nil {
		_ = temp.Close()
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}
	if err := os.Rename(temp.Name(), path); err != nil {
		return err
	}
	if runtime.GOOS == "linux" {
		directory, err := os.Open(dir)
		if err != nil {
			return err
		}
		syncErr := directory.Sync()
		closeErr := directory.Close()
		if syncErr != nil {
			return syncErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	return nil
}
