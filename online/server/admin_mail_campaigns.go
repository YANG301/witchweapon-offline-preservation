package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

const adminCampaignMaxRecipients = 5000
const adminCampaignMaxJobs = 100
const adminCampaignSnapshotLimit = 8 << 20
const adminCampaignJournalLimit = 32 << 20
const adminCampaignRequestLimit = 192 << 10
const adminCampaignPreviewLifetime = 15 * time.Minute

type adminCampaignFilter struct {
	Q        string `json:"q"`
	Field    string `json:"field"`
	Verified string `json:"verified"`
}

type adminCampaignInput struct {
	RequestID   string                `json:"requestId"`
	Scope       string                `json:"scope"`
	Filter      adminCampaignFilter   `json:"filter"`
	AccountIDs  []string              `json:"accountIds"`
	Title       string                `json:"title"`
	Sender      string                `json:"sender"`
	Content     string                `json:"content"`
	Reason      string                `json:"reason"`
	Attachments []adminMailAttachment `json:"attachments"`
}

type adminCampaignRecipient struct {
	AccountID     string `json:"accountId"`
	PublicRID     int    `json:"publicRid"`
	Email         string `json:"email"`
	Name          string `json:"name"`
	Status        string `json:"status"`
	Message       string `json:"message"`
	Attempts      int    `json:"attempts"`
	MailID        string `json:"mailId,omitempty"`
	UpdatedAt     int64  `json:"updatedAt"`
	DeliveryID    string `json:"deliveryId"`
	NextAttemptAt int64  `json:"nextAttemptAt,omitempty"`
}

type adminCampaign struct {
	Version          int                      `json:"version"`
	ID               string                   `json:"id"`
	CreatedAt        int64                    `json:"createdAt"`
	ExpiresAt        int64                    `json:"expiresAt"`
	UpdatedAt        int64                    `json:"updatedAt"`
	Status           string                   `json:"status"`
	PreviewRequestID string                   `json:"previewRequestId"`
	CommitRequestID  string                   `json:"commitRequestId,omitempty"`
	Input            adminCampaignInput       `json:"input"`
	Recipients       []adminCampaignRecipient `json:"recipients"`
	Seq              int64                    `json:"-"`
}

type adminCampaignEvent struct {
	Seq             int64                   `json:"seq"`
	At              int64                   `json:"at"`
	Kind            string                  `json:"kind"`
	Status          string                  `json:"status,omitempty"`
	CommitRequestID string                  `json:"commitRequestId,omitempty"`
	Index           *int                    `json:"index,omitempty"`
	Recipient       *adminCampaignRecipient `json:"recipient,omitempty"`
}

type adminCampaignCounts struct {
	Targeted int `json:"targeted"`
	Eligible int `json:"eligible"`
	Skipped  int `json:"skipped"`
	Pending  int `json:"pending"`
	Sending  int `json:"sending"`
	Sent     int `json:"sent"`
	Failed   int `json:"failed"`
	Canceled int `json:"canceled"`
}

type adminCampaignView struct {
	ID             string                   `json:"id"`
	CreatedAt      int64                    `json:"createdAt"`
	ExpiresAt      int64                    `json:"expiresAt"`
	UpdatedAt      int64                    `json:"updatedAt"`
	Status         string                   `json:"status"`
	Scope          string                   `json:"scope"`
	Filter         adminCampaignFilter      `json:"filter"`
	Mail           adminMailInput           `json:"mail"`
	Counts         adminCampaignCounts      `json:"counts"`
	Sample         []adminCampaignRecipient `json:"sample,omitempty"`
	Recipients     []adminCampaignRecipient `json:"recipients,omitempty"`
	RecipientTotal int                      `json:"recipientTotal"`
	NextOffset     *int                     `json:"nextOffset"`
	ServiceError   string                   `json:"serviceError,omitempty"`
}

type adminCampaignStore struct {
	mu         sync.Mutex
	dir        string
	jobs       map[string]*adminCampaign
	previewing bool
	fault      bool
	cancel     context.CancelFunc
	done       chan struct{}
	interval   time.Duration
}

func (m *adminCampaignStore) stopOnStorageError(err error) {
	if !m.fault {
		log.Printf("管理邮件任务持久记录故障，已停止投递：%v", err)
	}
	m.fault = true
}

func disabledAdminCampaignStore() *adminCampaignStore {
	log.Print("管理邮件任务记录无法读取，邮件中心已隔离并停止投递；游戏网关继续运行，请检查邮件任务记录和磁盘。")
	return &adminCampaignStore{jobs: make(map[string]*adminCampaign), fault: true, interval: 250 * time.Millisecond}
}

// Authentication always runs first. Queue failures are confined to this
// subsystem; immutable catalog queries and all game endpoints remain usable.
func (a *app) adminCampaignAuth(next adminHandler) http.HandlerFunc {
	return a.adminAuth(func(w http.ResponseWriter, r *http.Request, key [32]byte, expires time.Time) {
		m := a.mailCampaigns
		if m == nil {
			fail(w, 503, "mail_queue_unavailable", "邮件任务记录不可用，已停止投递，请检查服务日志和磁盘。")
			return
		}
		m.mu.Lock()
		fault := m.fault
		m.mu.Unlock()
		if fault {
			fail(w, 503, "mail_queue_unavailable", "邮件任务记录不可用，已停止投递；游戏服务仍可使用，请检查服务日志和磁盘。")
			return
		}
		next(w, r, key, expires)
	})
}

func adminCampaignUUID() (string, error) {
	var id [16]byte
	if _, err := rand.Read(id[:]); err != nil {
		return "", err
	}
	id[6] = id[6]&15 | 0x40
	id[8] = id[8]&63 | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", id[:4], id[4:6], id[6:8], id[8:10], id[10:]), nil
}

func campaignSafeFile(path string, optional bool) error {
	info, err := os.Lstat(path)
	if optional && errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("mail campaign file is not a regular file")
	}
	return nil
}

func campaignSyncDirectory(path string) error {
	if runtime.GOOS == "windows" {
		// Windows does not expose directory fsync through os.File. Individual
		// files still use FlushFileBuffers; production is the Linux gateway.
		return nil
	}
	d, err := os.Open(path)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}

func (m *adminCampaignStore) safeDirectory() error {
	info, err := os.Lstat(m.dir)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("unsafe mail campaign directory")
	}
	return nil
}

// Canonicalize the configured data root once (including systemd StateDirectory
// aliases), then refuse links in every component owned by the mail subsystem.
func openAdminCampaignStore(dataRoot string) (*adminCampaignStore, error) {
	root, err := filepath.EvalSymlinks(dataRoot)
	if err != nil {
		return nil, err
	}
	dir := filepath.Join(root, "mail-campaigns")
	if err = os.Mkdir(dir, 0o700); err != nil && !errors.Is(err, os.ErrExist) {
		return nil, err
	}
	if err == nil {
		if err = campaignSyncDirectory(root); err != nil {
			return nil, err
		}
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("mail campaign directory is not a safe directory")
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	m := &adminCampaignStore{dir: dir, jobs: make(map[string]*adminCampaign), interval: 250 * time.Millisecond}
	manifestBytes := int64(0)
	totalRecipients := 0
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || entry.Type()&os.ModeSymlink != 0 {
			return nil, errors.New("unexpected linked mail campaign entry")
		}
		// A crash during the atomic initial manifest write can leave an unused
		// temporary file. It is never read as a committed campaign.
		if strings.HasPrefix(name, ".state-") && strings.HasSuffix(name, ".tmp") {
			if err := campaignSafeFile(filepath.Join(dir, name), false); err != nil {
				return nil, err
			}
			continue
		}
		ext := filepath.Ext(name)
		if (ext != ".json" && ext != ".jsonl") || !adminMailRequestID.MatchString(strings.TrimSuffix(name, ext)) {
			return nil, errors.New("unknown mail campaign file")
		}
		if err := campaignSafeFile(filepath.Join(dir, name), false); err != nil {
			return nil, err
		}
		if ext != ".json" {
			continue
		}
		if len(m.jobs) >= adminCampaignMaxJobs {
			return nil, errors.New("mail campaign capacity exceeded")
		}
		fileInfo, err := entry.Info()
		if err != nil || fileInfo.Size() > adminCampaignSnapshotLimit {
			return nil, errors.New("mail campaign manifest exceeds capacity")
		}
		manifestBytes += fileInfo.Size()
		if manifestBytes > 64<<20 {
			return nil, errors.New("mail campaign store exceeds capacity")
		}
		body, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil || len(body) > adminCampaignSnapshotLimit || !validAdminDataJSON(body, false) {
			return nil, errors.New("invalid mail campaign manifest")
		}
		var c adminCampaign
		dec := json.NewDecoder(bytes.NewReader(body))
		dec.DisallowUnknownFields()
		if dec.Decode(&c) != nil || dec.Decode(new(any)) != io.EOF || c.ID != strings.TrimSuffix(name, ext) || !validAdminCampaignSnapshot(&c) {
			return nil, errors.New("invalid mail campaign manifest")
		}
		if err = m.loadJournal(&c); err != nil {
			return nil, err
		}
		totalRecipients += len(c.Recipients)
		if totalRecipients > 100000 {
			return nil, errors.New("mail campaign recipient history exceeds capacity")
		}
		m.jobs[c.ID] = &c
	}
	for _, entry := range entries {
		if strings.HasSuffix(entry.Name(), ".jsonl") && m.jobs[strings.TrimSuffix(entry.Name(), ".jsonl")] == nil {
			return nil, errors.New("orphan mail campaign journal")
		}
	}
	previewKeys, commitKeys := make(map[string]bool), make(map[string]bool)
	for _, c := range m.jobs {
		if previewKeys[c.PreviewRequestID] || c.CommitRequestID != "" && commitKeys[c.CommitRequestID] {
			return nil, errors.New("duplicate campaign request key")
		}
		previewKeys[c.PreviewRequestID] = true
		if c.CommitRequestID != "" {
			commitKeys[c.CommitRequestID] = true
		}
	}
	return m, nil
}

func validAdminCampaignInput(input *adminCampaignInput) bool {
	if !adminMailRequestID.MatchString(input.RequestID) {
		return false
	}
	if input.Attachments == nil {
		input.Attachments = []adminMailAttachment{}
	}
	switch input.Scope {
	case "all", "filtered", "selected":
	default:
		return false
	}
	if input.Filter.Field == "" {
		input.Filter.Field = "all"
	}
	if input.Filter.Verified == "" {
		input.Filter.Verified = "all"
	}
	input.Filter.Q = strings.ToLower(strings.TrimSpace(input.Filter.Q))
	if len(input.Filter.Q) > 254 || !utf8.ValidString(input.Filter.Q) || strings.IndexFunc(input.Filter.Q, unicode.IsControl) >= 0 {
		return false
	}
	if input.Filter.Field != "all" && input.Filter.Field != "rid" && input.Filter.Field != "email" && input.Filter.Field != "id" || input.Filter.Verified != "all" && input.Filter.Verified != "yes" && input.Filter.Verified != "no" {
		return false
	}
	if input.Scope != "filtered" && (input.Filter.Q != "" || input.Filter.Field != "all" || input.Filter.Verified != "all") {
		return false
	}
	if input.Scope == "selected" {
		if len(input.AccountIDs) == 0 || len(input.AccountIDs) > adminCampaignMaxRecipients {
			return false
		}
		seen := make(map[string]bool)
		for _, id := range input.AccountIDs {
			if !adminAccountID.MatchString(id) || seen[id] {
				return false
			}
			seen[id] = true
		}
		sort.Strings(input.AccountIDs)
	} else if len(input.AccountIDs) > 0 {
		return false
	}
	mail := adminMailInput{ExpectedRevision: "0", RequestID: input.RequestID, Title: input.Title, Sender: input.Sender, Content: input.Content, Reason: input.Reason, Attachments: input.Attachments}
	return validateAdminMail(mail)
}

func validAdminCampaignSnapshot(c *adminCampaign) bool {
	if c.Version != 1 || !adminMailRequestID.MatchString(c.ID) || c.Status != "preview" || c.CreatedAt <= 0 || c.UpdatedAt != c.CreatedAt || c.ExpiresAt != c.CreatedAt+adminCampaignPreviewLifetime.Milliseconds() || c.CommitRequestID != "" || c.PreviewRequestID != c.Input.RequestID || !validAdminCampaignInput(&c.Input) || len(c.Recipients) > adminCampaignMaxRecipients {
		return false
	}
	seen := make(map[string]bool)
	for _, r := range c.Recipients {
		if !adminAccountID.MatchString(r.AccountID) || seen[r.AccountID] || !adminMailRequestID.MatchString(r.DeliveryID) || r.Status != "pending" && r.Status != "skipped" || r.Attempts != 0 || r.MailID != "" || r.UpdatedAt != c.CreatedAt || r.NextAttemptAt != 0 || r.PublicRID < publicRIDMin || r.PublicRID > publicRIDMax || len(r.Email) > 254 || len(r.Name) > 128 || len(r.Message) > 200 {
			return false
		}
		seen[r.AccountID] = true
	}
	return true
}

func (m *adminCampaignStore) loadJournal(c *adminCampaign) error {
	path := filepath.Join(m.dir, c.ID+".jsonl")
	if err := campaignSafeFile(path, true); err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_RDWR, 0o600)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || info.Size() > adminCampaignJournalLimit {
		return errors.New("mail campaign journal exceeds capacity")
	}
	reader := bufio.NewReaderSize(f, 4096)
	offset := int64(0)
	for {
		line, readErr := reader.ReadBytes('\n')
		if readErr == io.EOF {
			if len(line) > 0 {
				if err = f.Truncate(offset); err != nil {
					return err
				}
				if err = f.Sync(); err != nil {
					return err
				}
			}
			return nil
		}
		if readErr != nil || len(line) > 4096 || !validAdminDataJSON(line, false) {
			return errors.New("invalid complete mail campaign journal record")
		}
		var event adminCampaignEvent
		dec := json.NewDecoder(bytes.NewReader(line))
		dec.DisallowUnknownFields()
		if dec.Decode(&event) != nil || dec.Decode(new(any)) != io.EOF || m.applyEvent(c, event) != nil {
			return errors.New("invalid mail campaign event")
		}
		offset += int64(len(line))
	}
}

func campaignCounts(c *adminCampaign) adminCampaignCounts {
	v := adminCampaignCounts{Targeted: len(c.Recipients)}
	for _, r := range c.Recipients {
		switch r.Status {
		case "pending":
			v.Pending++
		case "sending":
			v.Sending++
		case "sent":
			v.Sent++
		case "failed":
			v.Failed++
		case "skipped":
			v.Skipped++
		case "canceled":
			v.Canceled++
		}
	}
	v.Eligible = v.Targeted - v.Skipped
	return v
}

func (m *adminCampaignStore) view(c *adminCampaign, sample bool) adminCampaignView {
	v := adminCampaignView{ID: c.ID, CreatedAt: c.CreatedAt, ExpiresAt: c.ExpiresAt, UpdatedAt: c.UpdatedAt, Status: c.Status, Scope: c.Input.Scope, Filter: c.Input.Filter, Counts: campaignCounts(c), Mail: adminMailInput{RequestID: c.PreviewRequestID, Title: c.Input.Title, Sender: c.Input.Sender, Content: c.Input.Content, Reason: c.Input.Reason, Attachments: append([]adminMailAttachment{}, c.Input.Attachments...)}}
	if sample {
		n := len(c.Recipients)
		if n > 10 {
			n = 10
		}
		v.Sample = append([]adminCampaignRecipient{}, c.Recipients[:n]...)
		for i := range v.Sample {
			v.Sample[i].DeliveryID = ""
		}
	}
	if m.fault {
		v.ServiceError = "邮件任务持久记录发生故障，已停止投递，请检查服务日志和磁盘。"
	}
	return v
}

func validCampaignStatus(s string) bool {
	return s == "preview" || s == "queued" || s == "running" || s == "paused" || s == "completed" || s == "canceled"
}
func validRecipientStatus(s string) bool {
	return s == "pending" || s == "sending" || s == "sent" || s == "failed" || s == "skipped" || s == "canceled"
}

func (m *adminCampaignStore) applyEvent(c *adminCampaign, e adminCampaignEvent) error {
	if e.Seq != c.Seq+1 || e.At < c.CreatedAt {
		return errors.New("invalid mail event sequence")
	}
	switch e.Kind {
	case "state":
		if !validCampaignStatus(e.Status) || e.Status == "preview" || e.Index != nil || e.Recipient != nil {
			return errors.New("invalid campaign state")
		}
		if c.Status == "preview" {
			if e.Status != "queued" || !adminMailRequestID.MatchString(e.CommitRequestID) {
				return errors.New("invalid campaign confirmation")
			}
			if campaignCounts(c).Eligible == 0 {
				return errors.New("confirmed campaign has no recipients")
			}
			c.CommitRequestID = e.CommitRequestID
		} else if e.CommitRequestID != "" {
			return errors.New("duplicate campaign confirmation")
		} else {
			validTransition := c.Status == "queued" && (e.Status == "running" || e.Status == "paused" || e.Status == "completed") || c.Status == "running" && (e.Status == "paused" || e.Status == "completed") || c.Status == "paused" && (e.Status == "queued" || e.Status == "completed")
			if !validTransition {
				return errors.New("invalid campaign state transition")
			}
		}
		if e.Status == "completed" {
			counts := campaignCounts(c)
			if counts.Pending+counts.Sending != 0 {
				return errors.New("incomplete campaign marked completed")
			}
		}
		c.Status = e.Status
	case "cancel":
		if (c.Status != "queued" && c.Status != "running" && c.Status != "paused") || e.Status != "" || e.Index != nil || e.Recipient != nil || e.CommitRequestID != "" {
			return errors.New("invalid cancel event")
		}
		for i := range c.Recipients {
			if c.Recipients[i].Status == "pending" {
				c.Recipients[i].Status = "canceled"
				c.Recipients[i].Message = "尚未投递，已取消。"
				c.Recipients[i].UpdatedAt = e.At
			}
		}
		c.Status = "canceled"
	case "retry_failed":
		if c.Status == "preview" || c.Status == "canceled" || e.Status != "" || e.Index != nil || e.Recipient != nil || e.CommitRequestID != "" {
			return errors.New("invalid retry event")
		}
		if campaignCounts(c).Failed == 0 {
			return errors.New("retry event has no failed recipients")
		}
		for i := range c.Recipients {
			if c.Recipients[i].Status == "failed" {
				c.Recipients[i].Status = "pending"
				c.Recipients[i].Message = "等待重新投递。"
				c.Recipients[i].NextAttemptAt = 0
				c.Recipients[i].UpdatedAt = e.At
			}
		}
		if c.Status == "completed" {
			c.Status = "queued"
		}
	case "recipient":
		if c.Status == "preview" || e.Index == nil || *e.Index < 0 || *e.Index >= len(c.Recipients) || e.Recipient == nil || e.Status != "" || e.CommitRequestID != "" {
			return errors.New("invalid recipient event")
		}
		before := c.Recipients[*e.Index]
		after := *e.Recipient
		if after.AccountID != before.AccountID || after.PublicRID != before.PublicRID || after.Email != before.Email || after.Name != before.Name || after.DeliveryID != before.DeliveryID || !validRecipientStatus(after.Status) || after.Status == "skipped" || after.UpdatedAt != e.At || after.Attempts < before.Attempts || after.Attempts > before.Attempts+1 || len(after.Message) > 200 || len(after.MailID) > 64 || after.NextAttemptAt < 0 || before.Status == "sent" || before.Status == "skipped" || before.Status == "canceled" {
			return errors.New("invalid recipient transition")
		}
		if after.Status == "sent" && after.MailID == "" {
			return errors.New("sent mail missing receipt")
		}
		if before.Status == "pending" && (after.Status != "sending" || after.Attempts != before.Attempts+1) || before.Status == "sending" && (after.Status != "sending" && after.Status != "sent" && after.Status != "failed") || before.Status == "failed" {
			return errors.New("invalid recipient state transition")
		}
		if after.Status != "sent" && after.MailID != "" {
			return errors.New("unsent recipient has receipt")
		}
		if after.Status == "sent" && (!validAdminDataRevision(after.MailID) || after.MailID == "0") {
			return errors.New("invalid mail receipt ID")
		}
		c.Recipients[*e.Index] = after
	default:
		return errors.New("unknown mail event")
	}
	c.Seq = e.Seq
	c.UpdatedAt = e.At
	return nil
}

// Each append is synced before the state becomes visible. In particular a
// stable delivery ID is durably marked sending before the Java side effect.
func (m *adminCampaignStore) appendEvent(c *adminCampaign, e adminCampaignEvent) error {
	if m.fault {
		return errors.New("mail journal unavailable")
	}
	e.Seq = c.Seq + 1
	if err := m.safeDirectory(); err != nil {
		m.stopOnStorageError(err)
		return err
	}
	path := filepath.Join(m.dir, c.ID+".jsonl")
	if err := campaignSafeFile(path, true); err != nil {
		m.stopOnStorageError(err)
		return err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		m.stopOnStorageError(err)
		return err
	}
	body, err := json.Marshal(e)
	info, statErr := f.Stat()
	if err == nil && (statErr != nil || info.Size()+int64(len(body))+1 > adminCampaignJournalLimit) {
		err = errors.New("mail journal capacity exceeded")
	}
	if err == nil {
		_, err = f.Write(append(body, '\n'))
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err == nil {
		err = campaignSyncDirectory(m.dir)
	}
	if err != nil {
		m.stopOnStorageError(err)
		return err
	}
	if err = m.applyEvent(c, e); err != nil {
		m.stopOnStorageError(err)
		return err
	}
	return nil
}

// Only expired, never-confirmed previews are removed. Confirmed campaigns and
// their audit journals remain available in the history; no player save is read
// or modified here.
func (m *adminCampaignStore) prunePreviews(now int64) error {
	if err := m.safeDirectory(); err != nil {
		return err
	}
	for id, c := range m.jobs {
		if c.Status != "preview" || c.ExpiresAt >= now {
			continue
		}
		manifest := filepath.Join(m.dir, id+".json")
		journal := filepath.Join(m.dir, id+".jsonl")
		if err := campaignSafeFile(manifest, false); err != nil {
			return err
		}
		if err := campaignSafeFile(journal, true); err != nil {
			return err
		}
		if info, err := os.Stat(journal); err == nil {
			if info.Size() != 0 {
				return errors.New("unconfirmed preview contains journal records")
			}
			if err := os.Remove(journal); err != nil {
				return err
			}
		} else if !errors.Is(err, os.ErrNotExist) {
			return err
		}
		if err := os.Remove(manifest); err != nil {
			return err
		}
		if err := campaignSyncDirectory(m.dir); err != nil {
			return err
		}
		delete(m.jobs, id)
	}
	return nil
}

func (a *app) mountAdminCampaigns() {
	a.mux.HandleFunc("GET /admin/api/mail/catalog", a.adminAuth(a.adminCampaignCatalog))
	a.mux.HandleFunc("POST /admin/api/mail/preview", a.adminCampaignAuth(a.adminCampaignPreview))
	a.mux.HandleFunc("GET /admin/api/mail/campaigns", a.adminCampaignAuth(a.adminCampaignList))
	a.mux.HandleFunc("POST /admin/api/mail/campaigns", a.adminCampaignAuth(a.adminCampaignCreate))
	a.mux.HandleFunc("GET /admin/api/mail/campaigns/by-request/{request}", a.adminCampaignAuth(a.adminCampaignByRequest))
	a.mux.HandleFunc("GET /admin/api/mail/campaigns/{campaign}", a.adminCampaignAuth(a.adminCampaignDetail))
	a.mux.HandleFunc("POST /admin/api/mail/campaigns/{campaign}/control", a.adminCampaignAuth(a.adminCampaignControl))
}

func decodeCampaignRequest(w http.ResponseWriter, r *http.Request, target any) bool {
	if strings.TrimSpace(strings.Split(r.Header.Get("Content-Type"), ";")[0]) != "application/json" {
		fail(w, 415, "invalid_request", "请使用 JSON 格式提交邮件任务。")
		return false
	}
	if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		fail(w, 400, "invalid_request", "邮件任务路径无效。")
		return false
	}
	r.Body = http.MaxBytesReader(w, r.Body, adminCampaignRequestLimit)
	body, err := io.ReadAll(r.Body)
	if err != nil {
		var large *http.MaxBytesError
		if errors.As(err, &large) {
			fail(w, 413, "request_too_large", "邮件任务内容过长。")
		} else {
			fail(w, 400, "invalid_request", "邮件任务内容无效。")
		}
		return false
	}
	if !validAdminDataJSON(body, false) {
		fail(w, 400, "invalid_request", "邮件任务 JSON 无效或包含重复字段。")
		return false
	}
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.DisallowUnknownFields()
	if dec.Decode(target) != nil || dec.Decode(new(any)) != io.EOF {
		fail(w, 400, "invalid_request", "邮件任务格式无效或包含未知字段。")
		return false
	}
	return true
}

// This Java endpoint only reads the immutable catalog. The sentinel is a legal
// account header, not a registered player, and never creates or reads a save.
func (a *app) campaignCatalog(r *http.Request) ([]adminCatalogEntry, error) {
	response, err := a.adminJavaRequest(r, "AAAAAAAAAAAAAAAAAAAAAA", http.MethodGet, "/__admin/mail/catalog", nil)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 || response.ContentLength > adminMailCatalogLimit || !strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		return nil, errors.New("catalog unavailable")
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, adminMailCatalogLimit+1))
	if err != nil || len(body) > adminMailCatalogLimit {
		return nil, errors.New("catalog too large")
	}
	var value struct {
		Version int                 `json:"version"`
		Entries []adminCatalogEntry `json:"entries"`
	}
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.DisallowUnknownFields()
	if !validAdminDataJSON(body, false) || dec.Decode(&value) != nil || dec.Decode(new(any)) != io.EOF || value.Version != 1 || len(value.Entries) < 2 || len(value.Entries) > 2000 {
		return nil, errors.New("invalid catalog")
	}
	seen := make(map[[2]int64]bool)
	for _, e := range value.Entries {
		key := [2]int64{int64(e.Type), e.ID}
		if seen[key] || len(e.Name) == 0 || len(e.Name) > 96 || !utf8.ValidString(e.Name) || e.MaxCount < 1 || e.MaxCount > 1000000 || (e.Type != 2 && e.Type != 3 && e.Type != 13 && e.Type != 98) || ((e.Type == 13 || e.Type == 98) && e.ID != 0) || ((e.Type == 2 || e.Type == 3) && e.ID <= 0) {
			return nil, errors.New("invalid catalog entry")
		}
		if e.Type == 98 && e.MaxCount > 100000 || (e.Type == 2 || e.Type == 3) && e.MaxCount > 999 {
			return nil, errors.New("invalid catalog type maximum")
		}
		seen[key] = true
	}
	namesJSON, err := adminAssets.ReadFile("admin/mail_catalog_names.json")
	if err != nil {
		return nil, err
	}
	var names map[string]string
	if json.Unmarshal(namesJSON, &names) != nil {
		return nil, errors.New("catalog names unavailable")
	}
	for i := range value.Entries {
		e := &value.Entries[i]
		if name := names[strconv.Itoa(e.Type)+":"+strconv.FormatInt(e.ID, 10)]; name != "" && len(name) <= 96 && utf8.ValidString(name) {
			e.Name = name
		}
	}
	return value.Entries, nil
}

func (a *app) adminCampaignCatalog(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		fail(w, 400, "invalid_request", "物资目录路径无效。")
		return
	}
	entries, err := a.campaignCatalog(r)
	if err != nil {
		fail(w, 502, "legacy_unavailable", "游戏物资目录暂时不可用。")
		return
	}
	writeJSON(w, 200, map[string]any{"version": 1, "entries": entries})
}

func (s *store) campaignTargets(input adminCampaignInput) ([]adminAccountSummary, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	ids := make([]string, 0)
	if input.Scope == "selected" {
		ids = append(ids, input.AccountIDs...)
		for _, id := range ids {
			if s.state.Users[id] == nil {
				return nil, errors.New("selected account missing")
			}
		}
	} else {
		for id, acct := range s.state.Users {
			if input.Scope == "filtered" {
				f := input.Filter
				if f.Verified == "yes" && !acct.EmailVerified || f.Verified == "no" && acct.EmailVerified {
					continue
				}
				matches := f.Q == ""
				if !matches {
					switch f.Field {
					case "rid":
						matches = f.Q == strconv.Itoa(acct.PublicRID)
					case "email":
						matches = strings.Contains(strings.ToLower(acct.Email), f.Q)
					case "id":
						matches = strings.Contains(strings.ToLower(id), f.Q)
					default:
						matches = strings.Contains(strings.ToLower(id), f.Q) || strings.Contains(strings.ToLower(acct.Email), f.Q) || f.Q == strconv.Itoa(acct.PublicRID)
					}
				}
				if !matches {
					continue
				}
			}
			ids = append(ids, id)
			if len(ids) > adminCampaignMaxRecipients {
				return nil, errCampaignTooMany
			}
		}
	}
	sort.Slice(ids, func(i, j int) bool {
		l, r := s.state.Users[ids[i]], s.state.Users[ids[j]]
		if l.PublicRID != r.PublicRID {
			return l.PublicRID < r.PublicRID
		}
		return ids[i] < ids[j]
	})
	result := make([]adminAccountSummary, 0, len(ids))
	for _, id := range ids {
		acct := s.state.Users[id]
		result = append(result, adminAccountSummary{ID: id, PublicRID: acct.PublicRID, Email: acct.Email, EmailVerified: acct.EmailVerified})
	}
	return result, nil
}

var errCampaignTooMany = errors.New("too many campaign recipients")

func (a *app) adminCampaignPreview(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	var input adminCampaignInput
	if !decodeCampaignRequest(w, r, &input) {
		return
	}
	if len(input.AccountIDs) > adminCampaignMaxRecipients {
		fail(w, 413, "too_many_recipients", "每项邮件任务最多支持 5,000 个账号，请缩小筛选范围。")
		return
	}
	if !validAdminCampaignInput(&input) {
		fail(w, 400, "invalid_request", "邮件内容、附件或收件人范围无效。")
		return
	}
	m := a.mailCampaigns
	m.mu.Lock()
	if err := m.prunePreviews(a.now().UnixMilli()); err != nil {
		m.stopOnStorageError(err)
	}
	for _, c := range m.jobs {
		if c.PreviewRequestID == input.RequestID {
			before, _ := json.Marshal(c.Input)
			after, _ := json.Marshal(input)
			if !bytes.Equal(before, after) {
				m.mu.Unlock()
				fail(w, 409, "request_conflict", "该请求编号已经用于另一份预览。")
				return
			}
			v := m.view(c, true)
			m.mu.Unlock()
			writeJSON(w, 200, v)
			return
		}
	}
	if m.fault || len(m.jobs) >= adminCampaignMaxJobs {
		m.mu.Unlock()
		fail(w, 503, "campaign_capacity", "邮件任务存储不可用或已达到 100 项容量。")
		return
	}
	if m.previewing {
		m.mu.Unlock()
		fail(w, 409, "preview_busy", "另一项收件人预览正在核对，请稍后重试。")
		return
	}
	m.previewing = true
	m.mu.Unlock()
	defer func() { m.mu.Lock(); m.previewing = false; m.mu.Unlock() }()
	ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
	defer cancel()
	readRequest := r.WithContext(ctx)
	entries, err := a.campaignCatalog(readRequest)
	if err != nil {
		fail(w, 502, "legacy_unavailable", "无法核对物资目录，请稍后重新预览。")
		return
	}
	known := make(map[[2]int64]int64)
	for _, e := range entries {
		known[[2]int64{int64(e.Type), e.ID}] = e.MaxCount
	}
	for _, gift := range input.Attachments {
		if gift.Count > known[[2]int64{int64(gift.Type), gift.ID}] {
			fail(w, 422, "invalid_attachment", "附件不存在于游戏目录或数量超出限制。")
			return
		}
	}
	targets, err := a.store.campaignTargets(input)
	if errors.Is(err, errCampaignTooMany) {
		fail(w, 413, "too_many_recipients", "每项邮件任务最多支持 5,000 个账号，请缩小筛选范围。")
		return
	}
	if err != nil {
		fail(w, 409, "account_missing", "所选账号已不存在，请重新选择。")
		return
	}
	m.mu.Lock()
	totalRecipients := len(targets)
	for _, c := range m.jobs {
		totalRecipients += len(c.Recipients)
	}
	m.mu.Unlock()
	if totalRecipients > 100000 {
		fail(w, 503, "campaign_capacity", "邮件任务历史已达到 100,000 个收件人记录容量，请联系维护者处理历史记录后再创建任务。")
		return
	}
	created := a.now().UnixMilli()
	recipients := make([]adminCampaignRecipient, len(targets))
	work := make(chan int)
	var wg sync.WaitGroup
	var failed bool
	var failureMu sync.Mutex
	workers := 8
	if len(targets) < workers {
		workers = len(targets)
	}
	for n := 0; n < workers; n++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range work {
				acct := targets[i]
				delivery, uuidErr := adminCampaignUUID()
				summary, stateErr := a.adminLegacyState(readRequest, acct.ID)
				recipient := adminCampaignRecipient{AccountID: acct.ID, PublicRID: acct.PublicRID, Email: acct.Email, Name: summary.Name, Status: "pending", Message: "等待投递。", DeliveryID: delivery, UpdatedAt: created}
				if errors.Is(stateErr, errAdminLegacyNotStarted) || stateErr == nil && !summary.RoleCreated {
					recipient.Status = "skipped"
					recipient.Message = "尚未创建游戏角色，不发送邮件。"
				} else if stateErr != nil || uuidErr != nil {
					failureMu.Lock()
					failed = true
					failureMu.Unlock()
				}
				recipients[i] = recipient
			}
		}()
	}
	for i := range targets {
		select {
		case work <- i:
		case <-ctx.Done():
			failureMu.Lock()
			failed = true
			failureMu.Unlock()
		}
	}
	close(work)
	wg.Wait()
	if failed || ctx.Err() != nil {
		fail(w, 502, "preview_incomplete", "收件人核对未完成；没有生成任务，也没有发送邮件，请稍后重试。")
		return
	}
	id, err := adminCampaignUUID()
	if err != nil {
		fail(w, 500, "internal_error", "无法生成邮件任务编号。")
		return
	}
	c := &adminCampaign{Version: 1, ID: id, CreatedAt: created, ExpiresAt: created + adminCampaignPreviewLifetime.Milliseconds(), UpdatedAt: created, Status: "preview", PreviewRequestID: input.RequestID, Input: input, Recipients: recipients}
	m.mu.Lock()
	defer m.mu.Unlock()
	if err = m.safeDirectory(); err == nil {
		err = campaignSafeFile(filepath.Join(m.dir, c.ID+".json"), true)
	}
	if err == nil {
		err = persistJSON(filepath.Join(m.dir, c.ID+".json"), c)
	}
	if err == nil {
		err = campaignSyncDirectory(m.dir)
	}
	if err != nil {
		m.stopOnStorageError(err)
		fail(w, 503, "storage_unavailable", "无法保存邮件预览，未发送邮件。")
		return
	}
	m.jobs[id] = c
	writeJSON(w, 201, m.view(c, true))
}

func (a *app) adminCampaignCreate(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	var input struct {
		PreviewID    string `json:"previewId"`
		RequestID    string `json:"requestId"`
		Confirmation string `json:"confirmation"`
	}
	if !decodeCampaignRequest(w, r, &input) {
		return
	}
	if !adminMailRequestID.MatchString(input.PreviewID) || !adminMailRequestID.MatchString(input.RequestID) {
		fail(w, 400, "invalid_request", "邮件任务编号无效。")
		return
	}
	m := a.mailCampaigns
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, c := range m.jobs {
		if c.CommitRequestID == input.RequestID {
			if c.ID != input.PreviewID || input.Confirmation != "发送 "+strconv.Itoa(campaignCounts(c).Eligible)+" 人" {
				fail(w, 409, "request_conflict", "该确认编号已经用于另一项任务。")
				return
			}
			writeJSON(w, 200, m.view(c, true))
			return
		}
	}
	c := m.jobs[input.PreviewID]
	if c == nil {
		fail(w, 404, "not_found", "没有找到这份邮件预览。")
		return
	}
	if c.Status != "preview" {
		fail(w, 409, "already_confirmed", "该邮件预览已经确认，请查看任务状态。")
		return
	}
	counts := campaignCounts(c)
	if counts.Eligible == 0 {
		fail(w, 409, "no_recipients", "没有已经创建游戏角色的收件人。")
		return
	}
	if a.now().UnixMilli() > c.ExpiresAt {
		fail(w, 409, "preview_expired", "收件人预览已过期，请重新预览。")
		return
	}
	if input.Confirmation != "发送 "+strconv.Itoa(counts.Eligible)+" 人" {
		fail(w, 400, "confirmation_required", "确认内容与收件人数不一致。")
		return
	}
	if err := m.appendEvent(c, adminCampaignEvent{At: a.now().UnixMilli(), Kind: "state", Status: "queued", CommitRequestID: input.RequestID}); err != nil {
		fail(w, 503, "storage_unavailable", "任务确认结果暂时不确定，请用相同请求编号核对，勿新建重复任务。")
		return
	}
	writeJSON(w, 202, m.view(c, true))
}

func campaignQuery(r *http.Request, allowed ...string) (url.Values, error) {
	if r.URL.EscapedPath() != r.URL.Path {
		return nil, errors.New("encoded campaign path")
	}
	q, err := url.ParseQuery(r.URL.RawQuery)
	if err != nil {
		return nil, err
	}
	for key, vals := range q {
		found := false
		for _, name := range allowed {
			if key == name {
				found = true
			}
		}
		if !found || len(vals) != 1 {
			return nil, errors.New("invalid campaign query")
		}
	}
	return q, nil
}

func campaignIntQuery(q url.Values, key string, defaultValue, maximum int) (int, error) {
	s := q.Get(key)
	if s == "" {
		return defaultValue, nil
	}
	v, err := strconv.Atoi(s)
	if err != nil || v < 0 || v > maximum || strconv.Itoa(v) != s {
		return 0, errors.New("invalid integer query")
	}
	return v, nil
}

func (a *app) adminCampaignList(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	q, err := campaignQuery(r, "limit", "cursor")
	if err != nil {
		fail(w, 400, "invalid_request", "邮件任务查询无效。")
		return
	}
	limit, err := campaignIntQuery(q, "limit", 20, 50)
	if err != nil || limit < 1 {
		fail(w, 400, "invalid_request", "邮件任务分页无效。")
		return
	}
	cursor := q.Get("cursor")
	if cursor != "" && !adminMailRequestID.MatchString(cursor) {
		fail(w, 400, "invalid_request", "邮件任务分页无效。")
		return
	}
	m := a.mailCampaigns
	m.mu.Lock()
	defer m.mu.Unlock()
	jobs := make([]*adminCampaign, 0, len(m.jobs))
	for _, c := range m.jobs {
		if c.Status != "preview" {
			jobs = append(jobs, c)
		}
	}
	sort.Slice(jobs, func(i, j int) bool {
		if jobs[i].CreatedAt != jobs[j].CreatedAt {
			return jobs[i].CreatedAt > jobs[j].CreatedAt
		}
		return jobs[i].ID < jobs[j].ID
	})
	start := 0
	if cursor != "" {
		start = -1
		for i, c := range jobs {
			if c.ID == cursor {
				start = i + 1
				break
			}
		}
		if start < 0 {
			fail(w, 400, "invalid_request", "邮件任务分页已失效。")
			return
		}
	}
	end := start + limit
	if end > len(jobs) {
		end = len(jobs)
	}
	items := make([]adminCampaignView, 0, end-start)
	for _, c := range jobs[start:end] {
		items = append(items, m.view(c, false))
	}
	next := ""
	if end < len(jobs) && end > start {
		next = jobs[end-1].ID
	}
	writeJSON(w, 200, map[string]any{"items": items, "total": len(jobs), "nextCursor": next})
}

func (a *app) adminCampaignByRequest(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	q, err := campaignQuery(r)
	if err != nil || len(q) != 0 || !adminMailRequestID.MatchString(r.PathValue("request")) {
		fail(w, 400, "invalid_request", "邮件任务查询无效。")
		return
	}
	m := a.mailCampaigns
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, c := range m.jobs {
		if c.CommitRequestID == r.PathValue("request") {
			writeJSON(w, 200, m.view(c, true))
			return
		}
	}
	fail(w, 404, "not_found", "尚未找到这次确认对应的邮件任务。")
}

func (a *app) adminCampaignDetail(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	q, err := campaignQuery(r, "limit", "offset", "status")
	if err != nil || !adminMailRequestID.MatchString(r.PathValue("campaign")) {
		fail(w, 400, "invalid_request", "邮件任务查询无效。")
		return
	}
	limit, e1 := campaignIntQuery(q, "limit", 50, 200)
	offset, e2 := campaignIntQuery(q, "offset", 0, adminCampaignMaxRecipients)
	status := q.Get("status")
	if status == "" {
		status = "all"
	}
	if e1 != nil || e2 != nil || limit < 1 || status != "all" && !validRecipientStatus(status) {
		fail(w, 400, "invalid_request", "收件人分页或状态无效。")
		return
	}
	m := a.mailCampaigns
	m.mu.Lock()
	defer m.mu.Unlock()
	c := m.jobs[r.PathValue("campaign")]
	if c == nil {
		fail(w, 404, "not_found", "没有找到该邮件任务。")
		return
	}
	v := m.view(c, false)
	matches := make([]adminCampaignRecipient, 0, len(c.Recipients))
	for _, recipient := range c.Recipients {
		if status == "all" || recipient.Status == status {
			recipient.DeliveryID = ""
			matches = append(matches, recipient)
		}
	}
	if offset > len(matches) {
		offset = len(matches)
	}
	end := offset + limit
	if end > len(matches) {
		end = len(matches)
	}
	v.Recipients = append([]adminCampaignRecipient{}, matches[offset:end]...)
	v.RecipientTotal = len(matches)
	if end < len(matches) {
		v.NextOffset = &end
	}
	writeJSON(w, 200, v)
}

func (a *app) adminCampaignControl(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	var input struct {
		Action string `json:"action"`
	}
	if !decodeCampaignRequest(w, r, &input) {
		return
	}
	if !adminMailRequestID.MatchString(r.PathValue("campaign")) {
		fail(w, 404, "not_found", "没有找到该邮件任务。")
		return
	}
	m := a.mailCampaigns
	m.mu.Lock()
	defer m.mu.Unlock()
	c := m.jobs[r.PathValue("campaign")]
	if c == nil {
		fail(w, 404, "not_found", "没有找到该邮件任务。")
		return
	}
	if c.Status == "preview" {
		fail(w, 409, "not_confirmed", "请先确认邮件预览。")
		return
	}
	event := adminCampaignEvent{At: a.now().UnixMilli(), Kind: "state"}
	switch input.Action {
	case "pause":
		if c.Status == "paused" {
			writeJSON(w, 200, m.view(c, true))
			return
		}
		if c.Status != "queued" && c.Status != "running" {
			fail(w, 409, "invalid_state", "此任务当前不能暂停。")
			return
		}
		event.Status = "paused"
	case "resume":
		if c.Status == "queued" || c.Status == "running" {
			writeJSON(w, 200, m.view(c, true))
			return
		}
		if c.Status != "paused" {
			fail(w, 409, "invalid_state", "此任务当前不能继续。")
			return
		}
		event.Status = "queued"
	case "cancel":
		if c.Status == "canceled" {
			writeJSON(w, 200, m.view(c, true))
			return
		}
		if c.Status == "completed" {
			fail(w, 409, "invalid_state", "已完成的任务不能取消已送达邮件。")
			return
		}
		event.Kind = "cancel"
	case "retry_failed":
		if c.Status == "canceled" || campaignCounts(c).Failed == 0 {
			fail(w, 409, "no_failures", "此任务没有可以重新投递的失败收件人。")
			return
		}
		event.Kind = "retry_failed"
	default:
		fail(w, 400, "invalid_request", "邮件任务操作无效。")
		return
	}
	if err := m.appendEvent(c, event); err != nil {
		fail(w, 503, "storage_unavailable", "无法保存任务操作，已停止投递。")
		return
	}
	writeJSON(w, 200, m.view(c, true))
}

func (a *app) startAdminMailWorker() {
	m := a.mailCampaigns
	if m == nil || a.admin == nil || a.legacy == nil {
		return
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.cancel != nil || m.fault {
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	m.cancel = cancel
	m.done = make(chan struct{})
	go func() {
		defer close(m.done)
		ticker := time.NewTicker(m.interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				a.campaignDeliveryStep(ctx)
			}
		}
	}()
}

func (m *adminCampaignStore) close() {
	if m == nil {
		return
	}
	m.mu.Lock()
	cancel, done := m.cancel, m.done
	m.mu.Unlock()
	if cancel != nil {
		cancel()
		<-done
	}
}

func (a *app) campaignDeliveryStep(ctx context.Context) {
	m := a.mailCampaigns
	m.mu.Lock()
	if m.fault {
		m.mu.Unlock()
		return
	}
	jobs := make([]*adminCampaign, 0, len(m.jobs))
	for _, c := range m.jobs {
		if c.Status == "queued" || c.Status == "running" || c.Status == "canceled" && campaignCounts(c).Sending > 0 {
			jobs = append(jobs, c)
		}
	}
	sort.Slice(jobs, func(i, j int) bool {
		if jobs[i].CreatedAt != jobs[j].CreatedAt {
			return jobs[i].CreatedAt < jobs[j].CreatedAt
		}
		return jobs[i].ID < jobs[j].ID
	})
	var chosen *adminCampaign
	index := -1
	now := a.now().UnixMilli()
	for _, c := range jobs {
		counts := campaignCounts(c)
		if counts.Pending+counts.Sending == 0 {
			if c.Status != "canceled" {
				if m.appendEvent(c, adminCampaignEvent{At: now, Kind: "state", Status: "completed"}) != nil {
					m.mu.Unlock()
					return
				}
			}
			continue
		}
		// Resolve an uncertain earlier send before starting another recipient.
		for i, recipient := range c.Recipients {
			if recipient.Status == "sending" {
				if recipient.NextAttemptAt <= now {
					chosen, index = c, i
				}
				break
			}
		}
		if counts.Sending > 0 {
			if chosen != nil {
				break
			}
			continue
		}
		if c.Status == "canceled" {
			continue
		}
		for i, recipient := range c.Recipients {
			if recipient.Status == "pending" && recipient.NextAttemptAt <= now {
				chosen, index = c, i
				break
			}
		}
		if chosen != nil {
			break
		}
	}
	if chosen == nil {
		m.mu.Unlock()
		return
	}
	if chosen.Status == "queued" {
		if m.appendEvent(chosen, adminCampaignEvent{At: now, Kind: "state", Status: "running"}) != nil {
			m.mu.Unlock()
			return
		}
	}
	recipient := chosen.Recipients[index]
	recipient.Status = "sending"
	recipient.Message = "正在投递；若结果不确定，将使用同一请求编号核对。"
	recipient.Attempts++
	recipient.UpdatedAt = now
	recipient.NextAttemptAt = 0
	if m.appendEvent(chosen, adminCampaignEvent{At: now, Kind: "recipient", Index: &index, Recipient: &recipient}) != nil {
		m.mu.Unlock()
		return
	}
	input := chosen.Input
	m.mu.Unlock()
	result := a.deliverCampaignRecipient(ctx, input, recipient)
	m.mu.Lock()
	defer m.mu.Unlock()
	result.UpdatedAt = a.now().UnixMilli()
	if m.appendEvent(chosen, adminCampaignEvent{At: result.UpdatedAt, Kind: "recipient", Index: &index, Recipient: &result}) != nil {
		return
	}
	counts := campaignCounts(chosen)
	if counts.Pending+counts.Sending == 0 && chosen.Status != "canceled" {
		_ = m.appendEvent(chosen, adminCampaignEvent{At: result.UpdatedAt, Kind: "state", Status: "completed"})
	}
}

func (a *app) deliverCampaignRecipient(ctx context.Context, input adminCampaignInput, result adminCampaignRecipient) adminCampaignRecipient {
	transient := func(message string) adminCampaignRecipient {
		result.Status = "sending"
		result.Message = message
		seconds := result.Attempts
		if seconds > 60 {
			seconds = 60
		}
		result.NextAttemptAt = a.now().Add(time.Duration(seconds) * time.Second).UnixMilli()
		return result
	}
	permanent := func(message string) adminCampaignRecipient {
		result.Status = "failed"
		result.Message = message
		result.NextAttemptAt = 0
		return result
	}
	if _, exists := a.store.player(result.AccountID); !exists {
		return permanent("账号已不存在，未开始新的投递。")
	}
	r, _ := http.NewRequestWithContext(ctx, http.MethodGet, "http://127.0.0.1/", nil)
	summary, err := a.adminLegacyState(r, result.AccountID)
	if errors.Is(err, errAdminLegacyNotStarted) || err == nil && !summary.RoleCreated {
		return permanent("游戏角色已不存在，无法投递。")
	}
	if err != nil {
		return transient("游戏存档暂时无法读取，等待使用同一编号重试。")
	}
	attachments, _ := json.Marshal(input.Attachments)
	form := url.Values{"expectedRevision": {summary.Revision}, "requestId": {result.DeliveryID}, "reason": {input.Reason}, "title": {input.Title}, "sender": {input.Sender}, "content": {input.Content}, "attachments": {string(attachments)}}
	response, err := a.adminJavaRequest(r, result.AccountID, http.MethodPost, "/__admin/mail/send", strings.NewReader(form.Encode()))
	if err != nil {
		return transient("投递结果尚未确定，等待使用同一编号核对，勿另发重复邮件。")
	}
	defer response.Body.Close()
	switch response.StatusCode {
	case 404:
		return permanent("游戏角色已不存在，无法投递。")
	case 400, 422:
		return permanent("游戏拒绝邮件或附件，请检查附件和邮箱容量。")
	case 409:
		return transient("存档版本已变化，等待读取最新版本后按同一编号核对。")
	case 200:
	default:
		return transient("游戏邮件服务暂时不可用，等待使用同一编号核对。")
	}
	if response.ContentLength > adminMailResponseLimit || !strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		return transient("邮件回执无效，等待使用同一编号核对。")
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, adminMailResponseLimit+1))
	var receipt struct {
		ID        string `json:"id"`
		Revision  string `json:"revision"`
		Duplicate bool   `json:"duplicate"`
	}
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.DisallowUnknownFields()
	if err != nil || len(body) > adminMailResponseLimit || !validAdminDataJSON(body, false) || dec.Decode(&receipt) != nil || dec.Decode(new(any)) != io.EOF || !validAdminDataRevision(receipt.ID) || receipt.ID == "0" || !validAdminDataRevision(receipt.Revision) {
		return transient("邮件回执尚未确认，等待使用同一编号核对。")
	}
	result.Status = "sent"
	result.MailID = receipt.ID
	result.NextAttemptAt = 0
	result.Message = "邮件已送达游戏邮箱。"
	if receipt.Duplicate {
		result.Message = "已核对原邮件，未重复发放。"
	}
	return result
}
