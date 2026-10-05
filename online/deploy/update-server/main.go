// update-server builds and serves signed AssetBundle update releases.
// It is deliberately independent of the game, login, and chat services.
package main

import (
	"archive/zip"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	schemaVersion   = 1
	maxAssetSize    = 128 << 20
	maxAssets       = 256
	maxTotalSize    = 512 << 20
	maxManifestSize = 2 << 20
)

var (
	shaPattern  = regexp.MustCompile(`^[0-9a-f]{64}$`)
	namePattern = regexp.MustCompile(`^[0-9]+-[0-9a-f]{64}$`)
)

type asset struct {
	Path   string `json:"path"`
	URL    string `json:"url"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
}

type manifest struct {
	Schema              int     `json:"schema"`
	PackageID           string  `json:"packageId"`
	TargetAppVersion    string  `json:"targetAppVersion"`
	MinBootstrapVersion int     `json:"minBootstrapVersion"`
	ReleaseSequence     int64   `json:"releaseSequence"`
	Assets              []asset `json:"assets"`
}

type names []string

func (n *names) String() string     { return strings.Join(*n, ",") }
func (n *names) Set(v string) error { *n = append(*n, v); return nil }

func main() {
	log.SetFlags(0)
	if len(os.Args) < 2 {
		fail("usage: update-server keygen|publish|verify|serve [options]")
	}
	var err error
	switch os.Args[1] {
	case "keygen":
		err = keygen(os.Args[2:])
	case "publish":
		err = publish(os.Args[2:])
	case "verify":
		err = verify(os.Args[2:])
	case "rollback":
		err = rollback(os.Args[2:])
	case "serve":
		err = serve(os.Args[2:])
	default:
		err = fmt.Errorf("unknown command %q", os.Args[1])
	}
	if err != nil {
		fail(err.Error())
	}
}

func fail(msg string) { log.Print(msg); os.Exit(1) }

func keygen(args []string) error {
	f := flag.NewFlagSet("keygen", flag.ContinueOnError)
	privatePath := f.String("private", "", "new PKCS#8 PEM private key file")
	publicPath := f.String("public", "", "new X.509 DER public key file")
	if err := f.Parse(args); err != nil {
		return err
	}
	if *privatePath == "" || *publicPath == "" {
		return errors.New("both -private and -public are required")
	}
	if filepath.Clean(*privatePath) == filepath.Clean(*publicPath) {
		return errors.New("private and public paths must differ")
	}
	for _, p := range []string{*privatePath, *publicPath} {
		if _, err := os.Lstat(p); err == nil {
			return fmt.Errorf("refusing to overwrite %s", p)
		} else if !os.IsNotExist(err) {
			return err
		}
	}
	key, err := rsa.GenerateKey(rand.Reader, 3072)
	if err != nil {
		return err
	}
	pkcs8, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return err
	}
	der, err := x509.MarshalPKIXPublicKey(&key.PublicKey)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(*privatePath), 0700); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(*publicPath), 0755); err != nil {
		return err
	}
	privatePEM := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: pkcs8})
	if err := writeExclusive(*privatePath, privatePEM, 0600); err != nil {
		return err
	}
	if err := writeExclusive(*publicPath, der, 0644); err != nil {
		return err
	}
	pubHash := sha256.Sum256(der)
	fmt.Printf("public_key_sha256=%x\npublic_key_path=%s\n", pubHash, *publicPath)
	return nil
}

func writeExclusive(p string, data []byte, mode os.FileMode) error {
	f, err := os.OpenFile(p, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		return err
	}
	if _, err = f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

func readPrivate(p string) (*rsa.PrivateKey, error) {
	data, err := os.ReadFile(p)
	if err != nil {
		return nil, err
	}
	block, _ := pem.Decode(data)
	if block == nil || block.Type != "PRIVATE KEY" {
		return nil, errors.New("expected unencrypted PKCS#8 RSA PRIVATE KEY PEM")
	}
	parsed, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, err
	}
	key, ok := parsed.(*rsa.PrivateKey)
	if !ok || key.N.BitLen() < 3072 {
		return nil, errors.New("RSA private key must be at least 3072 bits")
	}
	return key, nil
}

func readPublic(p string) (*rsa.PublicKey, error) {
	data, err := os.ReadFile(p)
	if err != nil {
		return nil, err
	}
	parsed, err := x509.ParsePKIXPublicKey(data)
	if err != nil {
		return nil, err
	}
	key, ok := parsed.(*rsa.PublicKey)
	if !ok || key.N.BitLen() < 3072 {
		return nil, errors.New("RSA public key must be at least 3072 bits")
	}
	return key, nil
}

func safeAssetPath(p string) bool {
	if len(p) > 240 || !strings.HasPrefix(p, "assetbundle/") || !strings.HasSuffix(p, ".ab") || strings.ContainsAny(p, "\\:<>?*|\"") {
		return false
	}
	for _, c := range p {
		if c < 0x20 || c > 0x7e {
			return false
		}
	}
	if path.Clean(p) != p || strings.Contains(p, "//") {
		return false
	}
	for _, part := range strings.Split(p, "/") {
		if part == "" || part == "." || part == ".." {
			return false
		}
	}
	return true
}

func zipAssets(apk string) (map[string]*zip.File, func() error, error) {
	r, err := zip.OpenReader(apk)
	if err != nil {
		return nil, nil, err
	}
	out := map[string]*zip.File{}
	for _, f := range r.File {
		if !strings.HasPrefix(f.Name, "assets/assetbundle/") {
			continue
		}
		p := strings.TrimPrefix(f.Name, "assets/")
		if !strings.HasSuffix(p, ".ab") {
			continue
		}
		if !safeAssetPath(p) {
			r.Close()
			return nil, nil, fmt.Errorf("unsafe APK asset path %q", f.Name)
		}
		if f.UncompressedSize64 > maxAssetSize {
			r.Close()
			return nil, nil, fmt.Errorf("asset exceeds size limit: %s", p)
		}
		if _, exists := out[p]; exists {
			r.Close()
			return nil, nil, fmt.Errorf("duplicate asset path %q", p)
		}
		out[p] = f
	}
	return out, r.Close, nil
}

func zipSHA(file *zip.File) ([32]byte, error) {
	var empty [32]byte
	r, err := file.Open()
	if err != nil {
		return empty, err
	}
	h := sha256.New()
	n, copyErr := io.Copy(h, io.LimitReader(r, maxAssetSize+1))
	closeErr := r.Close()
	if copyErr != nil {
		return empty, copyErr
	}
	if closeErr != nil {
		return empty, closeErr
	}
	if n != int64(file.UncompressedSize64) {
		return empty, fmt.Errorf("short or oversized ZIP entry %s", file.Name)
	}
	var sum [32]byte
	copy(sum[:], h.Sum(nil))
	return sum, nil
}

func publish(args []string) error {
	f := flag.NewFlagSet("publish", flag.ContinueOnError)
	root := f.String("root", "", "release root directory")
	apk := f.String("apk", "", "source APK")
	base := f.String("base-apk", "", "bootstrap/base APK; unchanged ABs are omitted")
	privatePath := f.String("private", "", "PKCS#8 RSA signing key")
	packageID := f.String("package-id", "", "Android package name")
	target := f.String("target-version", "", "target app/content version")
	bootstrap := f.Int("min-bootstrap-version", 1, "minimum updater protocol version")
	sequence := f.Int64("sequence", 0, "monotonic release sequence > 0")
	maxTotal := f.Int64("max-total-bytes", 256<<20, "maximum sum of included AB bytes")
	var includes names
	f.Var(&includes, "include", "specific logical assetbundle/... path; repeat to publish only selected assets")
	if err := f.Parse(args); err != nil {
		return err
	}
	if *root == "" || *apk == "" || *base == "" || *privatePath == "" || *packageID == "" || *target == "" || *sequence < 1 || *bootstrap < 1 {
		return errors.New("-root, -apk, -base-apk, -private, -package-id, -target-version, positive -sequence and -min-bootstrap-version are required")
	}
	if *maxTotal <= 0 || *maxTotal > maxTotalSize {
		return errors.New("max-total-bytes outside allowed range")
	}
	if !regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9_.]{2,199}$`).MatchString(*packageID) || strings.HasSuffix(*packageID, ".") {
		return errors.New("invalid package-id")
	}
	if len(*target) > 100 || strings.ContainsAny(*target, "\r\n\x00") {
		return errors.New("invalid target-version")
	}
	for _, p := range includes {
		if !safeAssetPath(p) {
			return fmt.Errorf("invalid -include path %q", p)
		}
	}
	key, err := readPrivate(*privatePath)
	if err != nil {
		return err
	}
	source, closeSource, err := zipAssets(*apk)
	if err != nil {
		return err
	}
	defer closeSource()
	baseline, closeBase, err := zipAssets(*base)
	if err != nil {
		return err
	}
	defer closeBase()
	selected := make([]string, 0)
	if len(includes) > 0 {
		seen := map[string]bool{}
		for _, p := range includes {
			if source[p] == nil {
				return fmt.Errorf("APK does not contain %s", p)
			}
			if !seen[p] {
				selected = append(selected, p)
				seen[p] = true
			}
		}
	} else {
		for p, s := range source {
			b := baseline[p]
			if b == nil || b.UncompressedSize64 != s.UncompressedSize64 || b.CRC32 != s.CRC32 {
				selected = append(selected, p)
				continue
			}
			// ZIP CRC is only a fast prefilter; use SHA-256 before omitting an AB.
			sumSource, err := zipSHA(s)
			if err != nil {
				return err
			}
			sumBase, err := zipSHA(b)
			if err != nil {
				return err
			}
			if sumSource != sumBase {
				selected = append(selected, p)
			}
		}
	}
	sort.Strings(selected)
	var total int64
	for _, p := range selected {
		total += int64(source[p].UncompressedSize64)
		if total > *maxTotal {
			return fmt.Errorf("selected AB total %d exceeds max-total-bytes %d", total, *maxTotal)
		}
	}
	if len(selected) > maxAssets {
		return errors.New("too many assets")
	}
	if err := os.MkdirAll(*root, 0755); err != nil {
		return err
	}
	rootAbs, err := filepath.Abs(*root)
	if err != nil {
		return err
	}
	if err := ensureRealDirectory(rootAbs); err != nil {
		return err
	}
	currentPath := filepath.Join(rootAbs, "current")
	if old, err := readCurrent(rootAbs); err == nil {
		oldBytes, err := os.ReadFile(filepath.Join(rootAbs, "releases", old, "manifest.json"))
		if err != nil {
			return err
		}
		var oldManifest manifest
		if err := json.Unmarshal(oldBytes, &oldManifest); err != nil {
			return err
		}
		if *sequence <= oldManifest.ReleaseSequence {
			return fmt.Errorf("release sequence %d must exceed current %d", *sequence, oldManifest.ReleaseSequence)
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	blobRoot := filepath.Join(rootAbs, "blobs")
	if err := os.MkdirAll(blobRoot, 0755); err != nil {
		return err
	}
	result := manifest{Schema: schemaVersion, PackageID: *packageID, TargetAppVersion: *target, MinBootstrapVersion: *bootstrap, ReleaseSequence: *sequence, Assets: make([]asset, 0, len(selected))}
	for _, p := range selected {
		z := source[p]
		r, err := z.Open()
		if err != nil {
			return err
		}
		temp, err := os.CreateTemp(blobRoot, ".blob-")
		if err != nil {
			r.Close()
			return err
		}
		h := sha256.New()
		n, copyErr := io.Copy(io.MultiWriter(temp, h), io.LimitReader(r, maxAssetSize+1))
		closeErr := r.Close()
		if copyErr != nil || closeErr != nil || n != int64(z.UncompressedSize64) {
			temp.Close()
			os.Remove(temp.Name())
			return fmt.Errorf("failed reading %s: %v %v", p, copyErr, closeErr)
		}
		if err := temp.Sync(); err != nil {
			temp.Close()
			os.Remove(temp.Name())
			return err
		}
		if err := temp.Close(); err != nil {
			os.Remove(temp.Name())
			return err
		}
		sha := hex.EncodeToString(h.Sum(nil))
		blobPath := filepath.Join(blobRoot, sha)
		if err := installBlob(temp.Name(), blobPath, sha, n); err != nil {
			os.Remove(temp.Name())
			return err
		}
		result.Assets = append(result.Assets, asset{Path: p, URL: "/updates/stable/blobs/" + sha, Size: n, SHA256: sha})
	}
	manifestBytes, err := json.Marshal(result)
	if err != nil {
		return err
	}
	if len(manifestBytes) > maxManifestSize {
		return errors.New("manifest exceeds size limit")
	}
	digest := sha256.Sum256(manifestBytes)
	signature, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, digest[:])
	if err != nil {
		return err
	}
	sigBytes := []byte(base64.StdEncoding.EncodeToString(signature) + "\n")
	name := fmt.Sprintf("%d-%x", *sequence, digest)
	releasesRoot := filepath.Join(rootAbs, "releases")
	if err := os.MkdirAll(releasesRoot, 0755); err != nil {
		return err
	}
	releaseDir := filepath.Join(releasesRoot, name)
	if err := os.Mkdir(releaseDir, 0755); err != nil {
		return err
	}
	if err := writeExclusive(filepath.Join(releaseDir, "manifest.json"), manifestBytes, 0644); err != nil {
		return err
	}
	if err := writeExclusive(filepath.Join(releaseDir, "manifest.sig"), sigBytes, 0644); err != nil {
		return err
	}
	if err := verifyRelease(rootAbs, name, &key.PublicKey); err != nil {
		return err
	}
	tempPointer, err := os.CreateTemp(rootAbs, ".current-")
	if err != nil {
		return err
	}
	if _, err := tempPointer.WriteString(name + "\n"); err != nil {
		tempPointer.Close()
		os.Remove(tempPointer.Name())
		return err
	}
	if err := tempPointer.Sync(); err != nil {
		tempPointer.Close()
		os.Remove(tempPointer.Name())
		return err
	}
	if err := tempPointer.Close(); err != nil {
		os.Remove(tempPointer.Name())
		return err
	}
	if err := os.Rename(tempPointer.Name(), currentPath); err != nil {
		os.Remove(tempPointer.Name())
		return err
	}
	fmt.Printf("published_sequence=%d\nmanifest_sha256=%x\nassets=%d\nbytes=%d\n", *sequence, digest, len(result.Assets), total)
	return nil
}

func ensureRealDirectory(p string) error {
	info, err := os.Lstat(p)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("not a real directory: %s", p)
	}
	return nil
}

func installBlob(temp, final, sha string, size int64) error {
	if info, err := os.Lstat(final); err == nil {
		if !info.Mode().IsRegular() || info.Size() != size {
			return fmt.Errorf("existing blob has wrong type/size: %s", final)
		}
		if err := verifyFile(final, sha, size); err != nil {
			return err
		}
		return os.Remove(temp)
	} else if !os.IsNotExist(err) {
		return err
	}
	if err := os.Rename(temp, final); err != nil {
		return err
	}
	return verifyFile(final, sha, size)
}

func verifyFile(p, sha string, size int64) error {
	f, err := os.Open(p)
	if err != nil {
		return err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() != size {
		return fmt.Errorf("file size/type mismatch: %s", p)
	}
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return err
	}
	if hex.EncodeToString(h.Sum(nil)) != sha {
		return fmt.Errorf("SHA-256 mismatch: %s", p)
	}
	return nil
}

func readCurrent(root string) (string, error) {
	b, err := os.ReadFile(filepath.Join(root, "current"))
	if err != nil {
		return "", err
	}
	name := strings.TrimSpace(string(b))
	if !namePattern.MatchString(name) {
		return "", errors.New("invalid current pointer")
	}
	return name, nil
}

func readVerifiedManifest(root, name string, key *rsa.PublicKey) (manifest, error) {
	var m manifest
	if !namePattern.MatchString(name) {
		return m, errors.New("invalid release name")
	}
	dir := filepath.Join(root, "releases", name)
	if err := ensureRealDirectory(dir); err != nil {
		return m, err
	}
	data, err := os.ReadFile(filepath.Join(dir, "manifest.json"))
	if err != nil {
		return m, err
	}
	if len(data) > maxManifestSize {
		return m, errors.New("manifest too large")
	}
	sigText, err := os.ReadFile(filepath.Join(dir, "manifest.sig"))
	if err != nil {
		return m, err
	}
	sig, err := base64.StdEncoding.DecodeString(strings.TrimSpace(string(sigText)))
	if err != nil {
		return m, err
	}
	digest := sha256.Sum256(data)
	if err := rsa.VerifyPKCS1v15(key, crypto.SHA256, digest[:], sig); err != nil {
		return m, fmt.Errorf("manifest signature failed: %w", err)
	}
	if err := json.Unmarshal(data, &m); err != nil {
		return m, err
	}
	if m.Schema != schemaVersion || m.ReleaseSequence < 1 || m.MinBootstrapVersion < 1 {
		return m, errors.New("invalid manifest header")
	}
	if want := fmt.Sprintf("%d-%x", m.ReleaseSequence, digest); name != want {
		return m, errors.New("release name does not match manifest")
	}
	seen := map[string]bool{}
	if len(m.Assets) > maxAssets {
		return m, errors.New("too many manifest assets")
	}
	var total int64
	for _, a := range m.Assets {
		if !safeAssetPath(a.Path) || !shaPattern.MatchString(a.SHA256) || a.URL != "/updates/stable/blobs/"+a.SHA256 || a.Size < 0 || a.Size > maxAssetSize || seen[a.Path] {
			return m, errors.New("invalid manifest asset")
		}
		seen[a.Path] = true
		total += a.Size
		if total > maxTotalSize {
			return m, errors.New("manifest assets exceed total size limit")
		}
	}
	return m, nil
}

func verifyRelease(root, name string, key *rsa.PublicKey) error {
	m, err := readVerifiedManifest(root, name, key)
	if err != nil {
		return err
	}
	for _, a := range m.Assets {
		if err := verifyFile(filepath.Join(root, "blobs", a.SHA256), a.SHA256, a.Size); err != nil {
			return err
		}
	}
	return nil
}

func verify(args []string) error {
	f := flag.NewFlagSet("verify", flag.ContinueOnError)
	root := f.String("root", "", "release root directory")
	publicPath := f.String("public", "", "X.509 DER RSA public key")
	if err := f.Parse(args); err != nil {
		return err
	}
	if *root == "" || *publicPath == "" {
		return errors.New("-root and -public required")
	}
	key, err := readPublic(*publicPath)
	if err != nil {
		return err
	}
	name, err := readCurrent(*root)
	if err != nil {
		return err
	}
	if err := verifyRelease(*root, name, key); err != nil {
		return err
	}
	fmt.Printf("verified_release=%s\n", name)
	return nil
}

// rollback publishes a new, higher sequence containing the full override set
// of an earlier signed release. A lower pointer alone would be rejected by
// clients which correctly remember the highest applied releaseSequence.
func rollback(args []string) error {
	f := flag.NewFlagSet("rollback", flag.ContinueOnError)
	root := f.String("root", "", "release root directory")
	privatePath := f.String("private", "", "PKCS#8 RSA signing key")
	publicPath := f.String("public", "", "X.509 DER RSA public key")
	toSequence := f.Int64("to-sequence", 0, "previous sequence whose content should be restored")
	if err := f.Parse(args); err != nil {
		return err
	}
	if *root == "" || *privatePath == "" || *publicPath == "" || *toSequence < 1 {
		return errors.New("-root, -private, -public and positive -to-sequence are required")
	}
	rootAbs, err := filepath.Abs(*root)
	if err != nil {
		return err
	}
	if err := ensureRealDirectory(rootAbs); err != nil {
		return err
	}
	key, err := readPrivate(*privatePath)
	if err != nil {
		return err
	}
	pub, err := readPublic(*publicPath)
	if err != nil {
		return err
	}
	if key.PublicKey.E != pub.E || key.PublicKey.N.Cmp(pub.N) != 0 {
		return errors.New("private/public key mismatch")
	}
	currentName, err := readCurrent(rootAbs)
	if err != nil {
		return err
	}
	current, err := readVerifiedManifest(rootAbs, currentName, pub)
	if err != nil {
		return err
	}
	if *toSequence >= current.ReleaseSequence {
		return errors.New("rollback target must precede current release")
	}
	entries, err := os.ReadDir(filepath.Join(rootAbs, "releases"))
	if err != nil {
		return err
	}
	var oldName string
	for _, entry := range entries {
		if entry.IsDir() && strings.HasPrefix(entry.Name(), fmt.Sprintf("%d-", *toSequence)) && namePattern.MatchString(entry.Name()) {
			if oldName != "" {
				return errors.New("ambiguous rollback target")
			}
			oldName = entry.Name()
		}
	}
	if oldName == "" {
		return errors.New("rollback target release not found")
	}
	old, err := readVerifiedManifest(rootAbs, oldName, pub)
	if err != nil {
		return err
	}
	if old.PackageID != current.PackageID || old.TargetAppVersion != current.TargetAppVersion || old.MinBootstrapVersion != current.MinBootstrapVersion {
		return errors.New("rollback target is incompatible with current APK/bootstrap")
	}
	if err := verifyRelease(rootAbs, oldName, pub); err != nil {
		return err
	}
	old.ReleaseSequence = current.ReleaseSequence + 1
	data, err := json.Marshal(old)
	if err != nil {
		return err
	}
	digest := sha256.Sum256(data)
	sig, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, digest[:])
	if err != nil {
		return err
	}
	name := fmt.Sprintf("%d-%x", old.ReleaseSequence, digest)
	dir := filepath.Join(rootAbs, "releases", name)
	if err := os.Mkdir(dir, 0755); err != nil {
		return err
	}
	if err := writeExclusive(filepath.Join(dir, "manifest.json"), data, 0644); err != nil {
		return err
	}
	if err := writeExclusive(filepath.Join(dir, "manifest.sig"), []byte(base64.StdEncoding.EncodeToString(sig)+"\n"), 0644); err != nil {
		return err
	}
	if err := verifyRelease(rootAbs, name, pub); err != nil {
		return err
	}
	temp, err := os.CreateTemp(rootAbs, ".current-")
	if err != nil {
		return err
	}
	if _, err := temp.WriteString(name + "\n"); err != nil {
		temp.Close()
		os.Remove(temp.Name())
		return err
	}
	if err := temp.Sync(); err != nil {
		temp.Close()
		os.Remove(temp.Name())
		return err
	}
	if err := temp.Close(); err != nil {
		os.Remove(temp.Name())
		return err
	}
	if err := os.Rename(temp.Name(), filepath.Join(rootAbs, "current")); err != nil {
		os.Remove(temp.Name())
		return err
	}
	fmt.Printf("rollback_as_sequence=%d\nrestored_from_sequence=%d\nmanifest_sha256=%x\n", old.ReleaseSequence, *toSequence, digest)
	return nil
}

func serve(args []string) error {
	f := flag.NewFlagSet("serve", flag.ContinueOnError)
	root := f.String("root", "", "release root directory")
	publicPath := f.String("public", "", "X.509 DER RSA public key")
	listen := f.String("listen", "127.0.0.1:19444", "listen address")
	cert := f.String("tls-cert", "", "TLS certificate PEM")
	keyPath := f.String("tls-key", "", "TLS private key PEM")
	accessLogPath := f.String("access-log", "", "optional access log: method, endpoint path, status only")
	if err := f.Parse(args); err != nil {
		return err
	}
	if *root == "" || *publicPath == "" {
		return errors.New("-root and -public required")
	}
	if (*cert == "") != (*keyPath == "") {
		return errors.New("-tls-cert and -tls-key must both be provided or both omitted")
	}
	if !strings.HasPrefix(*listen, "127.0.0.1:") && !strings.HasPrefix(*listen, "[::1]:") {
		return errors.New("this standalone server may listen on loopback only")
	}
	pub, err := readPublic(*publicPath)
	if err != nil {
		return err
	}
	rootAbs, err := filepath.Abs(*root)
	if err != nil {
		return err
	}
	if err := ensureRealDirectory(rootAbs); err != nil {
		return err
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/updates/health", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" && r.Method != "HEAD" {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		name, err := readCurrent(rootAbs)
		if err != nil {
			http.Error(w, "release unavailable", http.StatusServiceUnavailable)
			return
		}
		m, err := readVerifiedManifest(rootAbs, name, pub)
		if err != nil {
			http.Error(w, "invalid release", http.StatusServiceUnavailable)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		if r.Method == "GET" {
			fmt.Fprintf(w, `{"status":"ok","releaseSequence":%d}`, m.ReleaseSequence)
		}
	})
	mux.HandleFunc("/updates/stable/manifest.json", func(w http.ResponseWriter, r *http.Request) { serveReleaseFile(w, r, rootAbs, pub, "manifest.json") })
	mux.HandleFunc("/updates/stable/manifest.sig", func(w http.ResponseWriter, r *http.Request) { serveReleaseFile(w, r, rootAbs, pub, "manifest.sig") })
	mux.HandleFunc("/updates/stable/blobs/", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" && r.Method != "HEAD" {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		sha := strings.TrimPrefix(r.URL.Path, "/updates/stable/blobs/")
		if !shaPattern.MatchString(sha) {
			http.NotFound(w, r)
			return
		}
		// Blobs are immutable and content-addressed. Keep old signed-release
		// blobs available while a client completes a download across a publish.
		f, err := os.Open(filepath.Join(rootAbs, "blobs", sha))
		if err != nil {
			http.NotFound(w, r)
			return
		}
		defer f.Close()
		info, err := f.Stat()
		if err != nil || !info.Mode().IsRegular() {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/octet-stream")
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
		w.Header().Set("ETag", strconv.Quote(sha))
		http.ServeContent(w, r, sha, info.ModTime(), f)
	})
	handler := http.Handler(mux)
	if *accessLogPath != "" {
		file, err := os.OpenFile(*accessLogPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
		if err != nil {
			return err
		}
		defer file.Close()
		logger := log.New(file, "", 0)
		handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			loggedPath := "[other]"
			switch {
			case r.URL.Path == "/updates/health",
				r.URL.Path == "/updates/stable/manifest.json",
				r.URL.Path == "/updates/stable/manifest.sig":
				loggedPath = r.URL.Path
			case strings.HasPrefix(r.URL.Path, "/updates/stable/blobs/") &&
				shaPattern.MatchString(strings.TrimPrefix(r.URL.Path, "/updates/stable/blobs/")):
				loggedPath = r.URL.Path
			}
			observed := &statusWriter{ResponseWriter: w, status: http.StatusOK}
			mux.ServeHTTP(observed, r)
			logger.Printf("%s %s %d", r.Method, loggedPath, observed.status)
		})
	}
	server := &http.Server{Addr: *listen, Handler: handler, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 8192}
	if *cert != "" {
		log.Printf("signed update server listening on https://%s", *listen)
		return server.ListenAndServeTLS(*cert, *keyPath)
	}
	log.Printf("signed update server listening on http://%s (loopback only)", *listen)
	return server.ListenAndServe()
}

type statusWriter struct {
	http.ResponseWriter
	status int
	wrote  bool
}

func (w *statusWriter) WriteHeader(status int) {
	if w.wrote {
		return
	}
	w.status = status
	w.wrote = true
	w.ResponseWriter.WriteHeader(status)
}

func (w *statusWriter) Write(data []byte) (int, error) {
	if !w.wrote {
		w.WriteHeader(http.StatusOK)
	}
	return w.ResponseWriter.Write(data)
}

func serveReleaseFile(w http.ResponseWriter, r *http.Request, root string, pub *rsa.PublicKey, file string) {
	if r.Method != "GET" && r.Method != "HEAD" {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	name, err := readCurrent(root)
	if err != nil {
		http.Error(w, "release unavailable", http.StatusServiceUnavailable)
		return
	}
	if _, err := readVerifiedManifest(root, name, pub); err != nil {
		http.Error(w, "invalid release", http.StatusServiceUnavailable)
		return
	}
	p := filepath.Join(root, "releases", name, file)
	data, err := os.ReadFile(p)
	if err != nil {
		http.Error(w, "release unavailable", http.StatusServiceUnavailable)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	if file == "manifest.json" {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
	} else {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	}
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	if r.Method == "GET" {
		w.Write(data)
	}
}
