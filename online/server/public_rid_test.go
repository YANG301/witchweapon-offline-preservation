package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// All account records in these tests are synthetic; no live save is opened.
func publicRIDTestAccount(id string) *account {
	return &account{ID: id, Email: strings.ToLower(id) + "@example.com", Salt: make([]byte, 32), Hash: make([]byte, 32),
		Iterations: passwordIterations, Progress: make(map[string]Progress)}
}

func writePublicRIDTestState(t *testing.T, dir string, state diskState) []byte {
	t.Helper()
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "state.json"), data, 0o600); err != nil {
		t.Fatal(err)
	}
	return data
}

func writePublicRIDTestRegistry(t *testing.T, dir string, registry publicRIDState) []byte {
	t.Helper()
	data, err := json.MarshalIndent(registry, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "public_rids.json"), data, 0o600); err != nil {
		t.Fatal(err)
	}
	return data
}

func TestPublicRIDLegacyBackfillIsStableAndPreservesIdentity(t *testing.T) {
	dir := t.TempDir()
	alice := publicRIDTestAccount("alice")
	alice.Role = &Role{ID: "unchanged-internal-role", Nickname: "原有昵称", Level: 12, CreatedAt: time.Now().UTC()}
	stateBefore := writePublicRIDTestState(t, dir, diskState{Version: 1, Users: map[string]*account{
		"zebra": publicRIDTestAccount("zebra"), "alice": alice,
		ownerPublicRIDAccount: publicRIDTestAccount(ownerPublicRIDAccount),
	}})
	s, err := openStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]int{"alice": 100000, "zebra": 100001, ownerPublicRIDAccount: ownerPublicRID}
	for id, rid := range want {
		p, ok := s.player(id)
		if !ok || p.PublicRID != rid || p.ID != id {
			t.Fatalf("incorrect public identity for %s", id)
		}
	}
	if got, _ := s.player("alice"); got.Role == nil || *got.Role != *alice.Role {
		t.Fatal("public RID backfill changed the existing internal role")
	}
	if s.publicRIDs.NextPublicRID != 100002 {
		t.Fatal("owner reservation incorrectly advanced ordinary allocation")
	}
	if !bytes.Equal(stateBefore, mustRead(t, s.file)) {
		t.Fatal("public RID migration rewrote the backward-compatible account save")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	persisted := mustRead(t, filepath.Join(dir, "public_rids.json"))
	reopened, err := openStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	for id, rid := range want {
		if p, _ := reopened.player(id); p.PublicRID != rid {
			t.Fatal("restart renumbered an account")
		}
	}
	if !bytes.Equal(persisted, mustRead(t, filepath.Join(dir, "public_rids.json"))) {
		t.Fatal("restart rewrote an already migrated state")
	}
}

func TestPublicRIDNewStoreConcurrentAllocationAndRestart(t *testing.T) {
	dir := t.TempDir()
	s, err := openStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	const count = 16
	errs := make(chan error, count)
	var wg sync.WaitGroup
	for i := 0; i < count; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			errs <- s.add(publicRIDTestAccount(fmt.Sprintf("test-%02d", i)))
		}(i)
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	if err := s.add(publicRIDTestAccount(ownerPublicRIDAccount)); err != nil {
		t.Fatal(err)
	}
	assigned := make(map[string]int)
	seen := make(map[int]bool)
	for id := range s.state.Users {
		p, _ := s.player(id)
		if p.PublicRID < publicRIDMin || p.PublicRID > publicRIDMax || seen[p.PublicRID] ||
			(p.PublicRID == ownerPublicRID) != (id == ownerPublicRIDAccount) {
			t.Fatal("new store allocated an invalid or duplicate public RID")
		}
		seen[p.PublicRID] = true
		assigned[id] = p.PublicRID
	}
	if s.publicRIDs.NextPublicRID != publicRIDMin+count {
		t.Fatal("new store did not persist its allocation high-water mark")
	}
	accountSave := mustRead(t, s.file)
	if bytes.Contains(accountSave, []byte("publicRid")) || bytes.Contains(accountSave, []byte("nextPublicRid")) {
		t.Fatal("new account persistence changed the old state.json schema")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := openStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	for id, rid := range assigned {
		if p, _ := reopened.player(id); p.PublicRID != rid {
			t.Fatal("new-store public RID changed on restart")
		}
	}
}

func TestPublicRIDSkipsReservationAndDoesNotRecycle(t *testing.T) {
	dir := t.TempDir()
	writePublicRIDTestState(t, dir, diskState{Version: 1, Users: make(map[string]*account)})
	writePublicRIDTestRegistry(t, dir, publicRIDState{Version: 1, NextPublicRID: ownerPublicRID - 1,
		Users: make(map[string]int)})
	s, err := openStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"first", "second", ownerPublicRIDAccount} {
		if err := s.add(publicRIDTestAccount(id)); err != nil {
			t.Fatal(err)
		}
	}
	for id, rid := range map[string]int{"first": ownerPublicRID - 1, "second": ownerPublicRID + 1,
		ownerPublicRIDAccount: ownerPublicRID} {
		if p, _ := s.player(id); p.PublicRID != rid {
			t.Fatal("reserved number was assigned to an ordinary account")
		}
	}
	next := s.copyState()
	// Simulate an administrative removal while retaining the allocation cursor.
	delete(next.Users, "second")
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	writePublicRIDTestState(t, dir, next)
	reopened, err := openStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if err := reopened.add(publicRIDTestAccount("third")); err != nil {
		t.Fatal(err)
	}
	if p, _ := reopened.player("third"); p.PublicRID != ownerPublicRID+2 {
		t.Fatal("removed account's public RID was recycled")
	}
}

func TestPublicRIDInvalidStoredAssignmentsFailWithoutRewriting(t *testing.T) {
	for _, tc := range []struct {
		name  string
		a, b  int
		owner bool
		next  int
	}{
		{name: "below-six-digits", a: publicRIDMin - 1},
		{name: "above-six-digits", a: publicRIDMax + 1},
		{name: "duplicate", a: publicRIDMin, b: publicRIDMin},
		{name: "owner-number-taken", a: ownerPublicRID},
		{name: "owner-number-changed", a: publicRIDMin, owner: true},
		{name: "cursor-rewinds", a: publicRIDMin, next: publicRIDMin},
		{name: "cursor-out-of-range", next: publicRIDMax + 2},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			id := "first"
			if tc.owner {
				id = ownerPublicRIDAccount
			}
			a := publicRIDTestAccount(id)
			b := publicRIDTestAccount("second")
			before := writePublicRIDTestState(t, dir, diskState{Version: 1,
				Users: map[string]*account{id: a, "second": b}})
			registry := publicRIDState{Version: 1, NextPublicRID: publicRIDMax + 1, Users: make(map[string]int)}
			if tc.a != 0 {
				registry.Users[id] = tc.a
			}
			if tc.b != 0 {
				registry.Users["second"] = tc.b
			}
			if tc.next != 0 {
				registry.NextPublicRID = tc.next
			}
			registryBefore := writePublicRIDTestRegistry(t, dir, registry)
			if s, err := openStore(dir); err == nil {
				s.Close()
				t.Fatal("invalid public RID state accepted")
			}
			if !bytes.Equal(before, mustRead(t, filepath.Join(dir, "state.json"))) {
				t.Fatal("invalid state was silently renumbered or rewritten")
			}
			if !bytes.Equal(registryBefore, mustRead(t, filepath.Join(dir, "public_rids.json"))) {
				t.Fatal("invalid registry was silently renumbered or rewritten")
			}
			// A failed open must release the instance lock.
			writePublicRIDTestState(t, dir, diskState{Version: 1, Users: map[string]*account{"fixed": publicRIDTestAccount("fixed")}})
			writePublicRIDTestRegistry(t, dir, publicRIDState{Version: 1, NextPublicRID: publicRIDMin, Users: make(map[string]int)})
			fixed, err := openStore(dir)
			if err != nil {
				t.Fatal(err)
			}
			fixed.Close()
		})
	}
}

func TestPublicRIDExhaustionAndPersistenceFailureAreAtomic(t *testing.T) {
	dir := t.TempDir()
	writePublicRIDTestState(t, dir, diskState{Version: 1, Users: make(map[string]*account)})
	writePublicRIDTestRegistry(t, dir, publicRIDState{Version: 1, NextPublicRID: publicRIDMax + 1,
		Users: make(map[string]int)})
	s, err := openStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	before := mustRead(t, s.file)
	if err := s.add(publicRIDTestAccount("ordinary")); !errors.Is(err, errPublicRIDExhausted) {
		t.Fatal("exhausted range did not fail closed")
	}
	if len(s.state.Users) != 0 || !bytes.Equal(before, mustRead(t, s.file)) {
		t.Fatal("exhausted allocation partially created an account")
	}
	// The independently reserved owner number still remains available.
	if err := s.add(publicRIDTestAccount(ownerPublicRIDAccount)); err != nil {
		t.Fatal(err)
	}
	if p, _ := s.player(ownerPublicRIDAccount); p.PublicRID != ownerPublicRID {
		t.Fatal("reserved owner allocation failed")
	}

	failedDir := t.TempDir()
	failed := &store{file: filepath.Join(failedDir, "missing-parent", "state.json"),
		publicRIDFile: filepath.Join(failedDir, "public_rids.json"),
		state:         diskState{Version: 1, Users: make(map[string]*account)}, emails: make(map[string]string),
		publicRIDs: publicRIDState{Version: 1, NextPublicRID: publicRIDMin, Users: make(map[string]int)}}
	newAccount := publicRIDTestAccount("not-persisted")
	if err := failed.add(newAccount); err == nil {
		t.Fatal("storage failure was ignored")
	}
	if len(failed.state.Users) != 0 || failed.publicRIDs.NextPublicRID != publicRIDMin+1 || newAccount.PublicRID != 0 ||
		failed.publicRIDs.Users[newAccount.ID] != publicRIDMin {
		t.Fatal("failed account persistence did not retain its durable RID reservation")
	}
	failed.file = filepath.Join(failedDir, "state.json")
	if err := failed.add(publicRIDTestAccount("after-failure")); err != nil {
		t.Fatal(err)
	}
	if p, _ := failed.player("after-failure"); p.PublicRID != publicRIDMin+1 {
		t.Fatal("failed registration's reserved RID was recycled")
	}
	recovered, err := openStore(failedDir)
	if err != nil {
		t.Fatal(err)
	}
	defer recovered.Close()
	if recovered.publicRIDs.Users[newAccount.ID] != publicRIDMin {
		t.Fatal("restart lost an unfinished registration's reservation")
	}
	if err := recovered.add(publicRIDTestAccount("after-restart")); err != nil {
		t.Fatal(err)
	}
	if p, _ := recovered.player("after-restart"); p.PublicRID != publicRIDMin+2 {
		t.Fatal("restart recycled an unfinished registration's public RID")
	}
}

func TestPublicRIDBackfillsAccountsCreatedDuringOlderServerRollback(t *testing.T) {
	dir := t.TempDir()
	s, err := openStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.add(publicRIDTestAccount("before-rollback")); err != nil {
		t.Fatal(err)
	}
	oldID, _ := s.player("before-rollback")
	state := s.copyState()
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	// An older binary writes only the original account schema and leaves the
	// public registry untouched. This models its newly registered account.
	state.Users["during-rollback"] = publicRIDTestAccount("during-rollback")
	before := writePublicRIDTestState(t, dir, state)
	reopened, err := openStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if p, _ := reopened.player("before-rollback"); p.PublicRID != oldID.PublicRID {
		t.Fatal("server rollback changed an existing public RID")
	}
	if p, _ := reopened.player("during-rollback"); p.PublicRID != publicRIDMin+1 {
		t.Fatal("new rollback-era account did not receive its stable public RID")
	}
	if !bytes.Equal(before, mustRead(t, reopened.file)) {
		t.Fatal("registry backfill rewrote rollback-era account progress")
	}
}
