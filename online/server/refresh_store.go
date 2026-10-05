package main

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"time"
)

// Refresh grants live apart from state.json so an older server binary can
// still read account/progress data after a rollback.
type refreshDiskState struct {
	Version int                     `json:"version"`
	Tokens  map[string]refreshGrant `json:"tokens"`
}

// The map key is SHA-256(refresh token), encoded as lowercase hex. No bearer
// token or password is written to either state file.
type refreshGrant struct {
	UserID    string    `json:"userId"`
	FamilyID  string    `json:"familyId"`
	CreatedAt time.Time `json:"createdAt"`
	ExpiresAt time.Time `json:"expiresAt"`
}

var errInvalidRefresh = errors.New("invalid refresh token")

func (s *store) loadRefreshState() error {
	f, err := os.Open(s.refreshFile)
	if errors.Is(err, os.ErrNotExist) {
		return nil // Accounts from older server versions have no grants.
	}
	if err != nil {
		return err
	}
	defer f.Close()
	dec := json.NewDecoder(io.LimitReader(f, 64<<20))
	dec.DisallowUnknownFields()
	var state refreshDiskState
	if err := dec.Decode(&state); err != nil {
		return fmt.Errorf("invalid refresh state file: %w", err)
	}
	if err := dec.Decode(new(any)); err != io.EOF {
		return errors.New("refresh state file has trailing data")
	}
	if state.Version != 1 || state.Tokens == nil {
		return errors.New("unsupported refresh state format")
	}
	families := make(map[string]bool)
	counts := make(map[string]int)
	for hash, grant := range state.Tokens {
		decoded, err := hex.DecodeString(hash)
		if err != nil || len(decoded) != 32 || hex.EncodeToString(decoded) != hash || s.state.Users[grant.UserID] == nil || grant.FamilyID == "" || families[grant.FamilyID] || grant.CreatedAt.IsZero() || !grant.ExpiresAt.After(grant.CreatedAt) || grant.ExpiresAt.After(grant.CreatedAt.Add(refreshLifetime)) {
			return errors.New("invalid refresh token record")
		}
		families[grant.FamilyID] = true
		counts[grant.UserID]++
		if counts[grant.UserID] > maxRefreshDevices {
			return errors.New("too many refresh grants for account")
		}
	}
	s.refreshState = state
	return nil
}

func (s *store) copyRefreshState() refreshDiskState {
	next := refreshDiskState{Version: s.refreshState.Version, Tokens: make(map[string]refreshGrant, len(s.refreshState.Tokens)+1)}
	for hash, grant := range s.refreshState.Tokens {
		next.Tokens[hash] = grant
	}
	return next
}

func (s *store) persistRefresh(next refreshDiskState) error {
	return persistJSON(s.refreshFile, next)
}

// issueRefresh creates a grant after password authentication. The oldest of
// at most five active grants per account is removed on a sixth login.
func (s *store) issueRefresh(id, hash, family string, now time.Time) (Player, []string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	user := s.state.Users[id]
	if user == nil {
		return Player{}, nil, errors.New("missing account")
	}
	if _, exists := s.refreshState.Tokens[hash]; exists {
		return Player{}, nil, errors.New("random refresh token collision")
	}
	for _, grant := range s.refreshState.Tokens {
		if grant.FamilyID == family {
			return Player{}, nil, errors.New("random refresh family collision")
		}
	}
	next := s.copyRefreshState()
	for key, grant := range next.Tokens {
		if !now.Before(grant.ExpiresAt) {
			delete(next.Tokens, key)
		}
	}
	count, oldestHash := 0, ""
	var oldest refreshGrant
	for key, grant := range next.Tokens {
		if grant.UserID != id {
			continue
		}
		count++
		if oldestHash == "" || grant.CreatedAt.Before(oldest.CreatedAt) || (grant.CreatedAt.Equal(oldest.CreatedAt) && key < oldestHash) {
			oldestHash, oldest = key, grant
		}
	}
	var evicted []string
	if count >= maxRefreshDevices {
		delete(next.Tokens, oldestHash)
		evicted = append(evicted, oldest.FamilyID)
	}
	next.Tokens[hash] = refreshGrant{UserID: id, FamilyID: family, CreatedAt: now.UTC(), ExpiresAt: now.Add(refreshLifetime).UTC()}
	if err := s.persistRefresh(next); err != nil {
		return Player{}, nil, err
	}
	s.refreshState = next
	return playerOf(user), evicted, nil
}

// rotateRefresh consumes exactly one token. A concurrent replay cannot issue
// another token because validation and the durable replacement share s.mu.
func (s *store) rotateRefresh(oldHash, newHash string, now time.Time) (refreshGrant, Player, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	grant, ok := s.refreshState.Tokens[oldHash]
	if !ok || !now.Before(grant.ExpiresAt) {
		return refreshGrant{}, Player{}, errInvalidRefresh
	}
	if _, exists := s.refreshState.Tokens[newHash]; exists {
		return refreshGrant{}, Player{}, errors.New("random refresh token collision")
	}
	user := s.state.Users[grant.UserID]
	if user == nil {
		return refreshGrant{}, Player{}, errors.New("missing account")
	}
	next := s.copyRefreshState()
	delete(next.Tokens, oldHash)
	next.Tokens[newHash] = grant // Preserve the original hard expiry.
	if err := s.persistRefresh(next); err != nil {
		return refreshGrant{}, Player{}, err
	}
	s.refreshState = next
	return grant, playerOf(user), nil
}

// revokeRefresh removes the family even when the caller presents an access
// token from before the most recent refresh rotation.
func (s *store) revokeRefresh(family string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for hash, grant := range s.refreshState.Tokens {
		if grant.FamilyID != family {
			continue
		}
		next := s.copyRefreshState()
		delete(next.Tokens, hash)
		if err := s.persistRefresh(next); err != nil {
			return false, err
		}
		s.refreshState = next
		return true, nil
	}
	return false, nil
}

// revokeRefreshToken intentionally treats unknown/expired tokens the same as
// already revoked ones. The endpoint returns 204 for all well-formed tokens.
func (s *store) revokeRefreshToken(hash string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	grant, ok := s.refreshState.Tokens[hash]
	if !ok {
		return "", nil
	}
	next := s.copyRefreshState()
	delete(next.Tokens, hash)
	if err := s.persistRefresh(next); err != nil {
		return "", err
	}
	s.refreshState = next
	return grant.FamilyID, nil
}
