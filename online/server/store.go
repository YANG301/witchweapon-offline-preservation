package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"
	"unicode/utf8"
)

type Progress struct {
	StoryID   string    `json:"storyId"`
	LastLine  int       `json:"lastLine"`
	Completed bool      `json:"completed"`
	UpdatedAt time.Time `json:"updatedAt"`
}

// Role is the small amount of player identity the online lobby can use now.
// Gameplay inventory and currencies are intentionally absent until their
// server-side rules are implemented.
type Role struct {
	ID         string    `json:"id"`
	Nickname   string    `json:"nickname"`
	Level      int       `json:"level"`
	Experience int       `json:"experience"`
	CreatedAt  time.Time `json:"createdAt"`
}

type Player struct {
	ID            string     `json:"id"`
	PublicRID     int        `json:"publicRid"`
	Email         string     `json:"email"`
	EmailVerified bool       `json:"emailVerified"`
	Progress      []Progress `json:"progress"`
	Role          *Role      `json:"role"`
}

type account struct {
	ID            string              `json:"id"`
	PublicRID     int                 `json:"-"`
	EmailVerified bool                `json:"-"`
	Email         string              `json:"email"`
	Salt          []byte              `json:"salt"`
	Hash          []byte              `json:"passwordHash"`
	Iterations    int                 `json:"iterations"`
	Progress      map[string]Progress `json:"progress"`
	Role          *Role               `json:"role,omitempty"`
	Gameplay      *GameplayState      `json:"gameplay,omitempty"`
}

type diskState struct {
	Version int                 `json:"version"`
	Users   map[string]*account `json:"users"`
}

// Public numbers live outside state.json so older server binaries can keep
// reading the newest account/progress save during a rollback.
type publicRIDState struct {
	Version       int            `json:"version"`
	NextPublicRID int            `json:"nextPublicRid"`
	Users         map[string]int `json:"users"`
}

type store struct {
	mu                    sync.Mutex
	file                  string
	publicRIDFile         string
	emailVerificationFile string
	passwordRecoveryFile  string
	refreshFile           string
	lock                  *os.File
	state                 diskState
	publicRIDs            publicRIDState
	emailVerifications    emailVerificationState
	passwordRecoveries    passwordRecoveryState
	refreshState          refreshDiskState
	emails                map[string]string
}

var errDuplicate = errors.New("account already exists")
var errRoleExists = errors.New("account already has a role")

const publicRIDMin = 100000
const publicRIDMax = 999999
const ownerPublicRID = 114514

// Public snapshot: synthetic owner ID. Set the confirmed private ID before deploying to an existing registry.
// The public number never replaces either the account ID or legacy role ID.
const ownerPublicRIDAccount = "OwnerReviewAccount00001"

var errPublicRIDExhausted = errors.New("public RID range exhausted")

func nextPublicRIDAfter(rid int) int {
	rid++
	if rid == ownerPublicRID {
		rid++
	}
	return rid
}

// Existing numbers and the persisted high-water mark must be valid; conflicts
// never renumber users. Reserved records may outlive unsuccessful registration.
func validatePublicRIDs(state publicRIDState) error {
	if state.Version != 1 || state.Users == nil {
		return errors.New("unsupported public RID registry")
	}
	used := make(map[int]bool, len(state.Users))
	minimumNext := publicRIDMin
	for id, rid := range state.Users {
		if id == "" || len(id) > 128 || !utf8.ValidString(id) || rid < publicRIDMin || rid > publicRIDMax || used[rid] ||
			(rid == ownerPublicRID) != (id == ownerPublicRIDAccount) {
			return errors.New("invalid or conflicting public RID")
		}
		used[rid] = true
		if rid != ownerPublicRID && rid >= minimumNext {
			minimumNext = nextPublicRIDAfter(rid)
		}
	}
	if state.NextPublicRID < minimumNext || state.NextPublicRID > publicRIDMax+1 {
		return errors.New("invalid public RID high-water mark")
	}
	return nil
}

// Fill missing assignments in account ID order. A registry entry is permanent,
// even if its account was removed or registration did not finish.
func assignPublicRIDs(state publicRIDState, ids []string) (publicRIDState, bool, error) {
	if err := validatePublicRIDs(state); err != nil {
		return publicRIDState{}, false, err
	}
	next := publicRIDState{Version: state.Version, NextPublicRID: state.NextPublicRID,
		Users: make(map[string]int, len(state.Users)+len(ids))}
	for id, rid := range state.Users {
		next.Users[id] = rid
	}
	ordered := append([]string(nil), ids...)
	sort.Strings(ordered)
	changed := false
	for _, id := range ordered {
		if _, exists := next.Users[id]; exists {
			continue
		}
		if id == "" || len(id) > 128 || !utf8.ValidString(id) {
			return publicRIDState{}, false, errors.New("invalid public RID account ID")
		}
		rid := ownerPublicRID
		if id != ownerPublicRIDAccount {
			if next.NextPublicRID == ownerPublicRID {
				next.NextPublicRID++
			}
			if next.NextPublicRID > publicRIDMax {
				return publicRIDState{}, false, errPublicRIDExhausted
			}
			rid = next.NextPublicRID
			next.NextPublicRID = nextPublicRIDAfter(rid)
		}
		next.Users[id] = rid
		changed = true
	}
	return next, changed, nil
}

func (s *store) persistPublicRIDs(next publicRIDState) error {
	if err := persistJSON(s.publicRIDFile, next); err != nil {
		return err
	}
	s.publicRIDs = next
	return nil
}

func (s *store) loadPublicRIDs() error {
	f, err := os.Open(s.publicRIDFile)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if err == nil {
		defer f.Close()
		dec := json.NewDecoder(io.LimitReader(f, 64<<20))
		dec.DisallowUnknownFields()
		var registry publicRIDState
		if err := dec.Decode(&registry); err != nil {
			return fmt.Errorf("invalid public RID registry: %w", err)
		}
		if err := dec.Decode(new(any)); err != io.EOF {
			return errors.New("public RID registry has trailing data")
		}
		if err := f.Close(); err != nil {
			return err
		}
		s.publicRIDs = registry
	}
	ids := make([]string, 0, len(s.state.Users))
	for id := range s.state.Users {
		ids = append(ids, id)
	}
	next, changed, err := assignPublicRIDs(s.publicRIDs, ids)
	if err != nil {
		return err
	}
	if changed {
		if err := s.persistPublicRIDs(next); err != nil {
			return err
		}
	}
	for id, a := range s.state.Users {
		a.PublicRID = s.publicRIDs.Users[id]
	}
	return nil
}

func openStore(dir string) (*store, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	s := &store{file: filepath.Join(dir, "state.json"), publicRIDFile: filepath.Join(dir, "public_rids.json"), refreshFile: filepath.Join(dir, "refresh_sessions.json"), state: diskState{Version: 1, Users: make(map[string]*account)}, publicRIDs: publicRIDState{Version: 1, NextPublicRID: publicRIDMin, Users: make(map[string]int)}, refreshState: refreshDiskState{Version: 1, Tokens: make(map[string]refreshGrant)}, emails: make(map[string]string)}
	s.emailVerificationFile = filepath.Join(dir, "email_verifications.json")
	s.emailVerifications = emailVerificationState{Version: 2, Users: make(map[string]emailVerificationRecord), IPDays: make(map[string]emailRateWindow)}
	s.passwordRecoveryFile = filepath.Join(dir, "password_recoveries.json")
	s.passwordRecoveries = passwordRecoveryState{Version: 1, Records: make(map[string]passwordRecoveryRecord)}
	lock, err := acquireDataLock(filepath.Join(dir, ".instance.lock"))
	if err != nil {
		return nil, fmt.Errorf("存档目录已被其他服务使用，或无法取得锁: %w", err)
	}
	s.lock = lock
	success := false
	defer func() {
		if !success {
			_ = lock.Close()
		}
	}()
	f, err := os.Open(s.file)
	if errors.Is(err, os.ErrNotExist) {
		if err := s.loadRefreshState(); err != nil {
			return nil, err
		}
		if err := s.loadPublicRIDs(); err != nil {
			return nil, err
		}
		if err := s.loadEmailVerifications(); err != nil {
			return nil, err
		}
		if err := s.loadPasswordRecoveries(); err != nil {
			return nil, err
		}
		success = true
		return s, nil
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()
	dec := json.NewDecoder(io.LimitReader(f, 64<<20))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&s.state); err != nil {
		return nil, fmt.Errorf("invalid state file: %w", err)
	}
	if err := dec.Decode(new(any)); err != io.EOF {
		return nil, errors.New("state file has trailing data")
	}
	// Close before atomic replacement, including when running on Windows.
	if err := f.Close(); err != nil {
		return nil, err
	}
	if s.state.Version != 1 || s.state.Users == nil {
		return nil, errors.New("unsupported state format")
	}
	roleIDs := make(map[string]bool)
	for id, a := range s.state.Users {
		if a == nil || a.ID != id || id == "" || !validEmail(a.Email) || a.Email != normalizeEmail(a.Email) || len(a.Salt) != 32 || len(a.Hash) != 32 || a.Iterations != passwordIterations || a.Progress == nil {
			return nil, errors.New("invalid account record")
		}
		if _, exists := s.emails[a.Email]; exists {
			return nil, errors.New("duplicate stored email")
		}
		s.emails[a.Email] = id
		for storyID, p := range a.Progress {
			if storyID != p.StoryID || !validStoryID(storyID) || p.LastLine < 0 || p.UpdatedAt.IsZero() {
				return nil, errors.New("invalid progress record")
			}
		}
		if a.Role != nil {
			if a.Role.ID == "" || !validNickname(a.Role.Nickname) || a.Role.Level < 1 || a.Role.Experience < 0 || a.Role.CreatedAt.IsZero() || roleIDs[a.Role.ID] {
				return nil, errors.New("invalid role record")
			}
			roleIDs[a.Role.ID] = true
		}
		if err := validateGameplay(a.Gameplay); err != nil {
			return nil, fmt.Errorf("invalid gameplay record for account %s: %w", id, err)
		}
	}
	if err := s.loadRefreshState(); err != nil {
		return nil, err
	}
	if err := s.loadPublicRIDs(); err != nil {
		return nil, err
	}
	if err := s.loadEmailVerifications(); err != nil {
		return nil, err
	}
	if err := s.loadPasswordRecoveries(); err != nil {
		return nil, err
	}
	success = true
	return s, nil
}

func (s *store) Close() error { return s.lock.Close() }

// persist writes a complete new state to the same filesystem, syncs the file,
// and atomically replaces the previous file. Memory changes only after success.
// One server process must exclusively own this data directory.
func (s *store) persist(next diskState) error {
	return persistJSON(s.file, next)
}

func persistJSON(path string, state any) error {
	b, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".state-*.tmp")
	if err != nil {
		return err
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	defer f.Close()
	if err = f.Chmod(0o600); err != nil {
		return err
	}
	if _, err = f.Write(append(b, '\n')); err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = os.Rename(tmp, path); err != nil {
		return err
	}
	// Directory syncing is best effort: Windows does not support it in this form.
	if d, openErr := os.Open(filepath.Dir(path)); openErr == nil {
		_ = d.Sync()
		_ = d.Close()
	}
	return nil
}

func (s *store) copyState() diskState {
	next := diskState{Version: s.state.Version, Users: make(map[string]*account, len(s.state.Users)+1)}
	for id, a := range s.state.Users {
		next.Users[id] = a
	}
	return next
}

func (s *store) add(a *account) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.emails[a.Email]; ok {
		return errDuplicate
	}
	if _, ok := s.state.Users[a.ID]; ok {
		return errors.New("random account id collision")
	}
	if a.PublicRID != 0 {
		return errors.New("public RID must be assigned by the store")
	}
	registry, changed, err := assignPublicRIDs(s.publicRIDs, []string{a.ID})
	if err != nil {
		return err
	}
	// Reserve first. If the account save fails, the committed registry record
	// remains occupied; a successful registration always has a durable number.
	if changed {
		if err := s.persistPublicRIDs(registry); err != nil {
			return err
		}
	}
	updated := *a
	updated.PublicRID = s.publicRIDs.Users[a.ID]
	next := s.copyState()
	next.Users[a.ID] = &updated
	if err := s.persist(next); err != nil {
		return err
	}
	s.state = next
	s.emails[a.Email] = a.ID
	return nil
}

func (s *store) credentials(email string) (account, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	id, ok := s.emails[email]
	if !ok {
		return account{}, false
	}
	return *s.state.Users[id], true // Copy before password authentication.
}

func playerOf(a *account) Player {
	p := Player{ID: a.ID, PublicRID: a.PublicRID, Email: a.Email, EmailVerified: a.EmailVerified, Progress: make([]Progress, 0, len(a.Progress))}
	if a.Role != nil {
		role := *a.Role
		p.Role = &role
	}
	for _, v := range a.Progress {
		p.Progress = append(p.Progress, v)
	}
	sort.Slice(p.Progress, func(i, j int) bool { return p.Progress[i].StoryID < p.Progress[j].StoryID })
	return p
}

func (s *store) createRole(id string, role Role) (Role, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, ok := s.state.Users[id]
	if !ok {
		return Role{}, errors.New("missing account")
	}
	if a.Role != nil {
		return Role{}, errRoleExists
	}
	for _, other := range s.state.Users {
		if other.Role != nil && other.Role.ID == role.ID {
			return Role{}, errors.New("random role id collision")
		}
	}
	updated := *a
	updated.Role = &role
	next := s.copyState()
	next.Users[id] = &updated
	if err := s.persist(next); err != nil {
		return Role{}, err
	}
	s.state = next
	return role, nil
}

func (s *store) player(id string) (Player, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, ok := s.state.Users[id]
	if !ok {
		return Player{}, false
	}
	return playerOf(a), true
}

func (s *store) update(id, storyID string, line int, completed bool, now time.Time) (Player, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, ok := s.state.Users[id]
	if !ok {
		return Player{}, errors.New("missing account")
	}
	old, exists := a.Progress[storyID]
	if exists && old.LastLine >= line && (old.Completed || !completed) {
		return playerOf(a), nil
	}
	p := Progress{StoryID: storyID, LastLine: line, Completed: completed, UpdatedAt: now.UTC()}
	if exists {
		if old.LastLine > p.LastLine {
			p.LastLine = old.LastLine
		}
		p.Completed = old.Completed || completed
	}
	updated := *a
	updated.Progress = make(map[string]Progress, len(a.Progress)+1)
	for k, v := range a.Progress {
		updated.Progress[k] = v
	}
	updated.Progress[storyID] = p
	next := s.copyState()
	next.Users[id] = &updated
	if err := s.persist(next); err != nil {
		return Player{}, err
	}
	s.state = next
	return playerOf(&updated), nil
}
