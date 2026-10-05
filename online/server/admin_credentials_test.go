package main

import (
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestAdminCredentialEncodingAndEnvFile(t *testing.T) {
	password := []byte("test-only-long-admin-password-58372")
	encoded, err := encodeAdminCredential(password)
	if err != nil {
		t.Fatal(err)
	}
	credential, err := decodeAdminCredential(encoded)
	if err != nil {
		t.Fatal(err)
	}
	wrong := adminPasswordKey([]byte("wrong-password"), credential.Salt[:])
	if credential.Hash != adminPasswordKey(password, credential.Salt[:]) || credential.Hash == wrong {
		t.Fatal("password verifier mismatch")
	}
	path := filepath.Join(t.TempDir(), "admin-auth.env")
	if err := writeAdminCredentialEnv(path, encoded); err != nil {
		t.Fatal(err)
	}
	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(contents) != adminCredentialEnvName+"="+encoded+"\n" ||
		strings.Contains(string(contents), string(password)) {
		t.Fatal("environment file contains unexpected content")
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(path)
		if err != nil || info.Mode().Perm() != 0600 {
			t.Fatal("admin credential file must be private")
		}
	}
	if _, err := encodeAdminCredential([]byte("short")); err == nil {
		t.Fatal("short password accepted")
	}
	if _, err := encodeAdminCredential([]byte("long-password\nwith-control")); err == nil {
		t.Fatal("control character accepted")
	}
}

func TestAdminCredentialTamperingRejected(t *testing.T) {
	encoded, err := encodeAdminCredential([]byte("test-only-long-admin-password-58372"))
	if err != nil {
		t.Fatal(err)
	}
	data, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		t.Fatal(err)
	}
	var record map[string]any
	if err := json.Unmarshal(data, &record); err != nil {
		t.Fatal(err)
	}
	for _, mutate := range []func(map[string]any){
		func(v map[string]any) { v["algorithm"] = "argon2id-m1048576-t999-p255" },
		func(v map[string]any) { v["username"] = "root" },
		func(v map[string]any) { v["salt"] = "abc" },
		func(v map[string]any) { v["extra"] = true },
	} {
		var original map[string]any
		_ = json.Unmarshal(data, &original)
		mutate(original)
		changed, _ := json.Marshal(original)
		if _, err := decodeAdminCredential(base64.RawURLEncoding.EncodeToString(changed)); err == nil {
			t.Fatal("tampered credential accepted")
		}
	}
}
