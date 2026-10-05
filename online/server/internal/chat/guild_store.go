package chat

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

// Guild history is isolated from world.jsonl. The Java GuildStore owns
// membership; this log only persists messages for already-authorized senders.
func (s *Server) openGuildStore() error {
	path := filepath.Join(filepath.Dir(s.filePath), "guild.jsonl")
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR|os.O_APPEND, 0o600)
	if err != nil {
		return err
	}
	s.guildFile, s.guildFilePath = file, path
	s.guildRecords = make([]record, 0, maxMessages)
	s.guildDedup = make(map[string]record)
	if err := s.loadGuild(); err != nil {
		_ = file.Close()
		s.guildFile = nil
		return err
	}
	return nil
}

func validGuildRecord(item record, previous uint64) bool {
	return item.Seq > previous && item.ID == "guild-"+strconv.FormatUint(item.Seq, 10) &&
		item.Channel == "guild" && guildIDPattern.MatchString(item.GuildID) &&
		accountPattern.MatchString(item.AccountID) && rolePattern.MatchString(item.RoleID) &&
		validName(item.Nickname) && validContent(item.Content) &&
		item.Head >= 0 && item.Head <= 1<<31-1 && item.HeadBox >= 0 && item.HeadBox <= 1<<31-1 &&
		clientPattern.MatchString(item.ClientID) && !item.CreatedAt.IsZero() &&
		(len(item.TypedJSON) == 0 || (len(item.TypedJSON) <= maxTypedJSONBytes && json.Valid(item.TypedJSON)))
}

// Requires s.mu.
func (s *Server) rememberGuild(item record) {
	s.guildRecords = append(s.guildRecords, item)
	s.guildDedup[dedupKey(item.AccountID, item.ClientID)] = item
	if len(s.guildRecords) > maxMessages {
		old := s.guildRecords[0]
		delete(s.guildDedup, dedupKey(old.AccountID, old.ClientID))
		s.guildRecords = s.guildRecords[1:]
	}
	s.guildSeq = item.Seq
}

func (s *Server) loadGuild() error {
	st, err := s.guildFile.Stat()
	if err != nil {
		return err
	}
	if st.Size() > 2*maxLogBytes {
		return errors.New("guild chat log exceeds safe load limit")
	}
	if _, err := s.guildFile.Seek(0, io.SeekStart); err != nil {
		return err
	}
	reader := bufio.NewReader(s.guildFile)
	var offset int64
	for {
		line, readErr := reader.ReadBytes('\n')
		if readErr == io.EOF && len(line) == 0 {
			break
		}
		if readErr != nil {
			return fmt.Errorf("guild chat log at byte %d: %w", offset, readErr)
		}
		if len(line) > maxRecordBytes {
			return fmt.Errorf("guild chat log oversized record at byte %d", offset)
		}
		var item record
		if json.Unmarshal(line, &item) != nil || !validGuildRecord(item, s.guildSeq) {
			return fmt.Errorf("guild chat log corrupt at byte %d", offset)
		}
		s.rememberGuild(item)
		offset += int64(len(line))
	}
	s.guildLogSize = offset
	_, err = s.guildFile.Seek(0, io.SeekEnd)
	return err
}

func (s *Server) guildHistory(guildID string, limit int) []record {
	s.mu.Lock()
	defer s.mu.Unlock()
	result := make([]record, 0, limit)
	for i := len(s.guildRecords) - 1; i >= 0 && len(result) < limit; i-- {
		if s.guildRecords[i].GuildID == guildID {
			result = append(result, s.guildRecords[i])
		}
	}
	for i, j := 0, len(result)-1; i < j; i, j = i+1, j-1 {
		result[i], result[j] = result[j], result[i]
	}
	return result
}

func (s *Server) publishGuild(identity Identity, guildID, content, clientID string, typedJSON json.RawMessage) (Message, bool, error) {
	if !guildIDPattern.MatchString(guildID) || !accountPattern.MatchString(identity.AccountID) ||
		!rolePattern.MatchString(identity.RoleID) || !validName(identity.Nickname) ||
		!validContent(content) || !clientPattern.MatchString(clientID) ||
		identity.Head < 0 || identity.Head > 1<<31-1 || identity.HeadBox < 0 || identity.HeadBox > 1<<31-1 ||
		len(typedJSON) > maxTypedJSONBytes {
		return Message{}, false, ErrInvalidMessage
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if existing, ok := s.guildDedup[dedupKey(identity.AccountID, clientID)]; ok {
		if existing.GuildID != guildID || existing.Content != content || !bytes.Equal(existing.TypedJSON, typedJSON) {
			return Message{}, false, ErrClientIDConflict
		}
		return existing.Message, false, nil
	}
	now := s.now().UTC()
	rate := s.rates[identity.AccountID]
	if now.Sub(rate.Window) >= time.Minute {
		rate.Window, rate.Count = now, 0
	}
	if now.Sub(rate.Last) < 2*time.Second || rate.Count >= 20 {
		return Message{}, false, ErrRateLimited
	}
	if s.guildWriteFailed || s.guildFile == nil {
		return Message{}, false, ErrStorageUnavailable
	}
	if s.guildLogSize > maxLogBytes && s.compactGuild() != nil && s.guildLogSize >= 2*maxLogBytes {
		return Message{}, false, ErrStorageUnavailable
	}
	item := record{Message: Message{ID: "guild-" + strconv.FormatUint(s.guildSeq+1, 10),
		Seq: s.guildSeq + 1, Channel: "guild", RoleID: identity.RoleID,
		Nickname: identity.Nickname, Content: content, Head: identity.Head,
		HeadBox: identity.HeadBox, CreatedAt: now}, AccountID: identity.AccountID,
		ClientID: clientID, TypedJSON: typedJSON, GuildID: guildID}
	line, err := encodeRecord(item)
	if err != nil || len(line) > maxRecordBytes {
		return Message{}, false, ErrInvalidMessage
	}
	before := s.guildLogSize
	if _, err = s.guildFile.Write(line); err == nil {
		err = s.guildFile.Sync()
	}
	if err != nil {
		_ = s.guildFile.Truncate(before)
		_, _ = s.guildFile.Seek(0, io.SeekEnd)
		s.guildWriteFailed = true
		return Message{}, false, ErrStorageUnavailable
	}
	s.guildLogSize += int64(len(line))
	s.rememberGuild(item)
	rate.Last, rate.Count = now, rate.Count+1
	s.rates[identity.AccountID] = rate
	if len(s.rates) > 4096 {
		s.pruneRates(now)
	}
	if s.guildLogSize > maxLogBytes {
		_ = s.compactGuild()
	}
	return item.Message, true, nil
}

// Requires s.mu. It keeps the newest recoverable bounded history, including
// its authoritative guildId, and preserves the sequence across compaction.
func (s *Server) compactGuild() error {
	lines := make([][]byte, len(s.guildRecords))
	keepFrom := len(s.guildRecords)
	var keptBytes int64
	for i := len(s.guildRecords) - 1; i >= 0; i-- {
		line, err := encodeRecord(s.guildRecords[i])
		if err != nil {
			return err
		}
		if keptBytes+int64(len(line)) > maxLogBytes {
			break
		}
		lines[i], keepFrom = line, i
		keptBytes += int64(len(line))
	}
	if len(s.guildRecords) > 0 && keepFrom == len(s.guildRecords) {
		return errors.New("single guild chat record exceeds log size limit")
	}
	tmp, err := os.CreateTemp(filepath.Dir(s.guildFilePath), ".guild-chat-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	defer tmp.Close()
	if err = tmp.Chmod(0o600); err != nil {
		return err
	}
	for _, line := range lines[keepFrom:] {
		if _, err = tmp.Write(line); err != nil {
			return err
		}
	}
	if err = tmp.Sync(); err != nil {
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	if err = s.guildFile.Close(); err != nil {
		s.guildWriteFailed = true
		return err
	}
	s.guildFile = nil
	if err = os.Rename(tmp.Name(), s.guildFilePath); err != nil {
		if reopened, openErr := os.OpenFile(s.guildFilePath, os.O_RDWR|os.O_APPEND, 0o600); openErr == nil {
			s.guildFile = reopened
		} else {
			s.guildWriteFailed = true
		}
		return err
	}
	s.guildFile, err = os.OpenFile(s.guildFilePath, os.O_RDWR|os.O_APPEND, 0o600)
	if err != nil {
		s.guildWriteFailed = true
		return err
	}
	s.guildLogSize = keptBytes
	if keepFrom > 0 {
		s.guildRecords = s.guildRecords[keepFrom:]
		s.guildDedup = make(map[string]record, len(s.guildRecords))
		for _, item := range s.guildRecords {
			s.guildDedup[dedupKey(item.AccountID, item.ClientID)] = item
		}
	}
	if dir, openErr := os.Open(filepath.Dir(s.guildFilePath)); openErr == nil {
		_ = dir.Sync()
		_ = dir.Close()
	}
	return nil
}
