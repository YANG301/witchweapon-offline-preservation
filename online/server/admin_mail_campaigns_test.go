package main

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

type campaignJavaFake struct {
	mu          sync.Mutex
	roles       map[string]bool
	missing     map[string]bool
	broken      map[string]bool
	modes       map[string]string
	revisions   map[string]int
	requests    map[string][]string
	attachments map[string]string
	ledger      map[string]string
	started     chan struct{}
	release     chan struct{}
}

func campaignTestID(n int) string { return fmt.Sprintf("%022d", n) }

func campaignFixture(t *testing.T) (*app, string, *campaignJavaFake, string) {
	t.Helper()
	a, data, _ := fixture(t)
	token := strings.Repeat("m", 43)
	a.admin = &adminConfig{sessions: map[[32]byte]time.Time{sha256.Sum256([]byte(token)): time.Now().Add(time.Hour)}, rates: make(map[string]rateEntry)}
	j := &campaignJavaFake{roles: map[string]bool{}, missing: map[string]bool{}, broken: map[string]bool{}, modes: map[string]string{}, revisions: map[string]int{}, requests: map[string][]string{}, attachments: map[string]string{}, ledger: map[string]string{}}
	for n := 1; n <= 4; n++ {
		id := campaignTestID(n)
		a.store.state.Users[id] = &account{ID: id, PublicRID: 100000 + n, Email: fmt.Sprintf("synthetic-%d@example.invalid", n), EmailVerified: n%2 == 0, Progress: map[string]Progress{}}
		j.roles[id] = n <= 2
		j.revisions[id] = 5
	}
	j.missing[campaignTestID(4)] = true
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-WW-Proxy-Secret") != strings.Repeat("x", 40) || r.Header.Get("Authorization") != "" {
			t.Error("campaign proxy secret or administrator bearer isolation")
			w.WriteHeader(403)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		id := r.Header.Get("X-WW-Account-ID")
		j.mu.Lock()
		defer j.mu.Unlock()
		switch r.URL.Path {
		case "/__admin/mail/catalog":
			if id != "AAAAAAAAAAAAAAAAAAAAAA" {
				t.Error("global catalog used player account")
			}
			fmt.Fprint(w, `{"version":1,"entries":[{"type":13,"id":0,"name":"金币","maxCount":1000000},{"type":98,"id":0,"name":"钻石","maxCount":100000},{"type":3,"id":40320001,"name":"物品","maxCount":999}]}`)
		case "/__admin/state":
			if j.broken[id] {
				w.WriteHeader(503)
				return
			}
			if j.missing[id] {
				w.WriteHeader(404)
				return
			}
			roleID := ""
			if j.roles[id] {
				roleID = "123456"
			}
			fmt.Fprintf(w, `{"version":1,"revision":%d,"name":"合成测试角色","gold":0,"roleCreated":%t,"roleId":%q,"exp":0,"wins":0,"attempts":0,"stars":0,"mazeWins":0,"mazeAttempts":0,"mazeStars":0,"mazeRound":0,"active":false}`, j.revisions[id], j.roles[id], roleID)
		case "/__admin/mail/send":
			if r.Method != http.MethodPost {
				t.Error("mail method")
			}
			if err := r.ParseForm(); err != nil {
				t.Error(err)
			}
			key := r.Form.Get("requestId")
			j.attachments[id] = r.Form.Get("attachments")
			j.requests[id] = append(j.requests[id], key)
			if !adminMailRequestID.MatchString(key) {
				t.Error("invalid stable UUIDv4 delivery key")
			}
			ledgerKey := id + ":" + key
			if mailID := j.ledger[ledgerKey]; mailID != "" {
				fmt.Fprintf(w, `{"id":%q,"revision":%q,"duplicate":true}`, mailID, fmt.Sprint(j.revisions[id]))
				return
			}
			mode := j.modes[id]
			if mode == "reject" {
				w.WriteHeader(422)
				return
			}
			if mode == "cas_once" {
				j.modes[id] = ""
				j.revisions[id]++
				w.WriteHeader(409)
				return
			}
			if mode == "block" {
				j.modes[id] = ""
				j.mu.Unlock()
				close(j.started)
				<-j.release
				j.mu.Lock()
			}
			if r.Form.Get("expectedRevision") != fmt.Sprint(j.revisions[id]) {
				t.Error("worker did not reread current revision")
				w.WriteHeader(409)
				return
			}
			mailID := fmt.Sprint(900000 + len(j.ledger))
			j.ledger[ledgerKey] = mailID
			j.revisions[id]++
			if mode == "unknown_once" {
				j.modes[id] = ""
				w.WriteHeader(503)
				return
			}
			fmt.Fprintf(w, `{"id":%q,"revision":%q,"duplicate":false}`, mailID, fmt.Sprint(j.revisions[id]))
		default:
			t.Errorf("unexpected campaign Java route %s", r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	t.Cleanup(java.Close)
	if err := a.configureLegacyProxy(java.URL, strings.Repeat("x", 40)); err != nil {
		t.Fatal(err)
	}
	return a, token, j, data
}

func campaignInputTest(t *testing.T, scope string, ids ...string) adminCampaignInput {
	t.Helper()
	key, err := adminCampaignUUID()
	if err != nil {
		t.Fatal(err)
	}
	return adminCampaignInput{RequestID: key, Scope: scope, AccountIDs: ids, Title: "合成邮件测试", Sender: "新丰洲", Content: "这是完全隔离的本地测试邮件。", Reason: "验证全服邮件任务安全投递", Attachments: []adminMailAttachment{{Type: 13, ID: 0, Count: 10}}}
}
func campaignBody(t *testing.T, input any) string {
	t.Helper()
	b, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}
func campaignPreviewTest(t *testing.T, a *app, token string, input adminCampaignInput) adminCampaignView {
	t.Helper()
	response := adminRequest(a, http.MethodPost, "/admin/api/mail/preview", token, campaignBody(t, input))
	if response.Code != 201 && response.Code != 200 {
		t.Fatalf("preview %d: %s", response.Code, response.Body.String())
	}
	var v adminCampaignView
	if err := json.Unmarshal(response.Body.Bytes(), &v); err != nil {
		t.Fatal(err)
	}
	return v
}
func campaignCommitTest(t *testing.T, a *app, token string, v adminCampaignView) (adminCampaignView, string) {
	t.Helper()
	key, err := adminCampaignUUID()
	if err != nil {
		t.Fatal(err)
	}
	body := campaignBody(t, map[string]string{"previewId": v.ID, "requestId": key, "confirmation": fmt.Sprintf("发送 %d 人", v.Counts.Eligible)})
	response := adminRequest(a, http.MethodPost, "/admin/api/mail/campaigns", token, body)
	wantStatus(t, response, 202)
	if err := json.Unmarshal(response.Body.Bytes(), &v); err != nil {
		t.Fatal(err)
	}
	return v, key
}
func campaignControlTest(t *testing.T, a *app, token, id, action string) adminCampaignView {
	t.Helper()
	r := adminRequest(a, http.MethodPost, "/admin/api/mail/campaigns/"+id+"/control", token, campaignBody(t, map[string]string{"action": action}))
	wantStatus(t, r, 200)
	var v adminCampaignView
	if err := json.Unmarshal(r.Body.Bytes(), &v); err != nil {
		t.Fatal(err)
	}
	return v
}

func TestAdminCampaignPreviewSnapshotValidationAndAuth(t *testing.T) {
	a, token, j, _ := campaignFixture(t)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/mail/catalog", "", ""), 401)
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/mail/preview", "", campaignBody(t, campaignInputTest(t, "all"))), 401)
	catalog := adminRequest(a, http.MethodGet, "/admin/api/mail/catalog", token, "")
	wantStatus(t, catalog, 200)
	if !strings.Contains(catalog.Body.String(), "波子汽水") {
		t.Fatal("global catalog missing Chinese name")
	}
	input := campaignInputTest(t, "all")
	v := campaignPreviewTest(t, a, token, input)
	if v.Counts.Targeted != 4 || v.Counts.Eligible != 2 || v.Counts.Skipped != 2 || v.Counts.Pending != 2 {
		t.Fatalf("incorrect accurate eligibility %+v", v.Counts)
	}
	if v2 := campaignPreviewTest(t, a, token, input); v2.ID != v.ID {
		t.Fatal("preview retry created second snapshot")
	}
	input.Title = "另一封邮件"
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/mail/preview", token, campaignBody(t, input)), 409)
	j.mu.Lock()
	if len(j.ledger) != 0 || len(j.requests) != 0 {
		t.Error("preview sent mail")
	}
	j.mu.Unlock()
	bad := campaignInputTest(t, "all")
	bad.Attachments = []adminMailAttachment{{Type: 3, ID: 99999999, Count: 1}}
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/mail/preview", token, campaignBody(t, bad)), 422)
	bad = campaignInputTest(t, "selected", campaignTestID(1), campaignTestID(1))
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/mail/preview", token, campaignBody(t, bad)), 400)
	bad = campaignInputTest(t, "all")
	b := campaignBody(t, bad)
	b = strings.TrimSuffix(b, "}") + `,"title":"重复字段"}`
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/mail/preview", token, b), 400)
	filter := campaignInputTest(t, "filtered")
	filter.Filter = adminCampaignFilter{Field: "email", Q: "SYNTHETIC-2", Verified: "yes"}
	filtered := campaignPreviewTest(t, a, token, filter)
	if filtered.Counts.Targeted != 1 || filtered.Counts.Eligible != 1 {
		t.Fatal("filtered campaign did not match account list semantics")
	}
	_, commitKey := campaignCommitTest(t, a, token, v)
	confirmedBody := campaignBody(t, map[string]string{"previewId": v.ID, "requestId": commitKey, "confirmation": "发送 2 人"})
	clock := a.now()
	a.now = func() time.Time { return clock.Add(20 * time.Minute) }
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/mail/campaigns", token, confirmedBody), 200)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/mail/campaigns/by-request/"+commitKey, token, ""), 200)
	newID := campaignTestID(5)
	a.store.state.Users[newID] = &account{ID: newID, PublicRID: 100005, Email: "new@example.invalid"}
	j.roles[newID] = true
	j.revisions[newID] = 5
	c := a.mailCampaigns.jobs[v.ID]
	if len(c.Recipients) != 4 {
		t.Fatal("new registration changed committed snapshot")
	}
	for _, r := range c.Recipients {
		if r.AccountID == newID {
			t.Fatal("snapshot admitted a later registration")
		}
	}
	for _, r := range v.Sample {
		if r.DeliveryID != "" {
			t.Fatal("private delivery key leaked")
		}
	}
}

func TestAdminCampaignIncompletePreviewAndCapacity(t *testing.T) {
	a, token, j, _ := campaignFixture(t)
	j.broken[campaignTestID(2)] = true
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/mail/preview", token, campaignBody(t, campaignInputTest(t, "all"))), 502)
	if len(a.mailCampaigns.jobs) != 0 {
		t.Fatal("failed role query generated partial preview")
	}
	files, err := os.ReadDir(a.mailCampaigns.dir)
	if err != nil || len(files) != 0 {
		t.Fatal("failed preview persisted data")
	}
	j.broken[campaignTestID(2)] = false
	for n := 5; n <= adminCampaignMaxRecipients+1; n++ {
		id := campaignTestID(n)
		a.store.state.Users[id] = &account{ID: id, PublicRID: 100000 + n, Email: "capacity@example.invalid"}
	}
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/mail/preview", token, campaignBody(t, campaignInputTest(t, "all"))), 413)
	if len(a.mailCampaigns.jobs) != 0 {
		t.Fatal("recipient capacity was silently truncated")
	}
}

func TestAdminCampaignRestartUnknownCASAndFailureRetry(t *testing.T) {
	a, token, j, data := campaignFixture(t)
	id1, id2 := campaignTestID(1), campaignTestID(2)
	j.modes[id1] = "unknown_once"
	j.modes[id2] = "cas_once"
	v := campaignPreviewTest(t, a, token, campaignInputTest(t, "selected", id1, id2))
	_, commitKey := campaignCommitTest(t, a, token, v)
	a.campaignDeliveryStep(context.Background())
	if a.mailCampaigns.jobs[v.ID].Recipients[0].Status != "sending" {
		t.Fatal("ambiguous successful send was classified as failure")
	}
	firstKey := a.mailCampaigns.jobs[v.ID].Recipients[0].DeliveryID
	reloaded, err := openAdminCampaignStore(data)
	if err != nil {
		t.Fatal(err)
	}
	a.mailCampaigns = reloaded
	clock := time.Now()
	a.now = func() time.Time { return clock.Add(10 * time.Second) }
	a.campaignDeliveryStep(context.Background())
	if r := a.mailCampaigns.jobs[v.ID].Recipients[0]; r.Status != "sent" || r.DeliveryID != firstKey || !strings.Contains(r.Message, "未重复") {
		t.Fatalf("unknown crash recovery %+v", r)
	}
	a.campaignDeliveryStep(context.Background())
	if a.mailCampaigns.jobs[v.ID].Recipients[1].Status != "sending" {
		t.Fatal("CAS did not keep stable retry state")
	}
	a.now = func() time.Time { return clock.Add(20 * time.Second) }
	a.campaignDeliveryStep(context.Background())
	if c := a.mailCampaigns.jobs[v.ID]; c.Status != "completed" || campaignCounts(c).Sent != 2 {
		t.Fatalf("CAS recovery did not finish %+v", campaignCounts(c))
	}
	j.mu.Lock()
	if len(j.ledger) != 2 || len(j.requests[id1]) != 2 || j.requests[id1][0] != j.requests[id1][1] || len(j.requests[id2]) != 2 || j.requests[id2][0] != j.requests[id2][1] {
		t.Error("retry changed request UUID or duplicated a delivered mail")
	}
	j.mu.Unlock()
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/mail/campaigns/by-request/"+commitKey, token, ""), 200)
	for n := 0; n < 3; n++ {
		a.campaignDeliveryStep(context.Background())
	}
	j.mu.Lock()
	if len(j.requests[id1]) != 2 || len(j.requests[id2]) != 2 {
		t.Error("success was sent again")
	}
	j.mu.Unlock()
	j.modes[id2] = "reject"
	second := campaignPreviewTest(t, a, token, campaignInputTest(t, "selected", id1, id2))
	campaignCommitTest(t, a, token, second)
	a.campaignDeliveryStep(context.Background())
	a.campaignDeliveryStep(context.Background())
	if counts := campaignCounts(a.mailCampaigns.jobs[second.ID]); counts.Sent != 1 || counts.Failed != 1 {
		t.Fatalf("failed receipt incorrect %+v", counts)
	}
	j.mu.Lock()
	before := len(j.requests[id1])
	j.modes[id2] = ""
	j.mu.Unlock()
	campaignControlTest(t, a, token, second.ID, "retry_failed")
	a.campaignDeliveryStep(context.Background())
	if campaignCounts(a.mailCampaigns.jobs[second.ID]).Sent != 2 {
		t.Fatal("definite failure retry did not deliver")
	}
	j.mu.Lock()
	if len(j.requests[id1]) != before {
		t.Error("retry_failed resent a previous success")
	}
	j.mu.Unlock()
	reloaded, err = openAdminCampaignStore(data)
	if err != nil {
		t.Fatal(err)
	}
	if campaignCounts(reloaded.jobs[second.ID]).Sent != 2 {
		t.Fatal("final sent state not persisted")
	}
}

func TestAdminCampaignPauseCancelInFlightAndPagination(t *testing.T) {
	a, token, j, _ := campaignFixture(t)
	id1, id2 := campaignTestID(1), campaignTestID(2)
	j.modes[id1] = "block"
	j.started = make(chan struct{})
	j.release = make(chan struct{})
	v := campaignPreviewTest(t, a, token, campaignInputTest(t, "selected", id1, id2))
	campaignCommitTest(t, a, token, v)
	done := make(chan struct{})
	go func() { defer close(done); a.campaignDeliveryStep(context.Background()) }()
	select {
	case <-j.started:
	case <-time.After(3 * time.Second):
		t.Fatal("mail never started")
	}
	paused := campaignControlTest(t, a, token, v.ID, "pause")
	if paused.Status != "paused" || paused.Counts.Sending != 1 || paused.Counts.Pending != 1 {
		t.Fatalf("pause in-flight state %+v", paused.Counts)
	}
	close(j.release)
	<-done
	a.campaignDeliveryStep(context.Background())
	j.mu.Lock()
	if len(j.requests[id2]) != 0 {
		t.Error("paused job began next recipient")
	}
	j.mu.Unlock()
	canceled := campaignControlTest(t, a, token, v.ID, "cancel")
	if canceled.Status != "canceled" || canceled.Counts.Sent != 1 || canceled.Counts.Canceled != 1 {
		t.Fatalf("cancel retracted delivered mail %+v", canceled.Counts)
	}
	a.campaignDeliveryStep(context.Background())
	j.mu.Lock()
	if len(j.requests[id2]) != 0 {
		t.Error("canceled job began pending recipient")
	}
	j.mu.Unlock()
	first := adminRequest(a, http.MethodGet, "/admin/api/mail/campaigns/"+v.ID+"?limit=1&offset=0&status=all", token, "")
	wantStatus(t, first, 200)
	var details adminCampaignView
	if err := json.Unmarshal(first.Body.Bytes(), &details); err != nil {
		t.Fatal(err)
	}
	if len(details.Recipients) != 1 || details.RecipientTotal != 2 || details.NextOffset == nil || *details.NextOffset != 1 || details.Recipients[0].DeliveryID != "" {
		t.Fatal("recipient pagination or private delivery key isolation")
	}
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/mail/campaigns/"+v.ID+"?limit=1&offset=1&status=all", token, ""), 200)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/mail/campaigns/"+v.ID+"?status=sent&status=failed", token, ""), 400)
	wantStatus(t, adminRequest(a, http.MethodPost, "/admin/api/mail/campaigns/"+v.ID+"/control", token, `{"action":"resume"}`), 409)
}

func TestAdminCampaignJournalRecoveryCorruptionAndExpiredPreview(t *testing.T) {
	a, token, _, data := campaignFixture(t)
	v := campaignPreviewTest(t, a, token, campaignInputTest(t, "selected", campaignTestID(1)))
	campaignCommitTest(t, a, token, v)
	path := filepath.Join(a.mailCampaigns.dir, v.ID+".jsonl")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.WriteString(`{"seq":2,"at":`)
	if err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	reloaded, err := openAdminCampaignStore(data)
	if err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(path)
	if err != nil || string(after) != string(before) || reloaded.jobs[v.ID].Status != "queued" {
		t.Fatal("incomplete append recovery did not retain exactly committed records")
	}
	f, err = os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = f.WriteString("{bad complete record}\n")
	_ = f.Close()
	if _, err = openAdminCampaignStore(data); err == nil {
		t.Fatal("corrupt complete journal record was silently discarded")
	}
	if err = os.WriteFile(path, before, 0o600); err != nil {
		t.Fatal(err)
	}
	expiring := campaignPreviewTest(t, a, token, campaignInputTest(t, "selected", campaignTestID(2)))
	clock := time.Now()
	a.now = func() time.Time { return clock.Add(16 * time.Minute) }
	campaignPreviewTest(t, a, token, campaignInputTest(t, "selected", campaignTestID(2)))
	if _, found := a.mailCampaigns.jobs[expiring.ID]; found {
		t.Fatal("expired unconfirmed preview consumed capacity")
	}
	if _, err = os.Stat(filepath.Join(a.mailCampaigns.dir, expiring.ID+".json")); !os.IsNotExist(err) {
		t.Fatal("expired preview manifest remained")
	}
	if a.mailCampaigns.jobs[v.ID] == nil {
		t.Fatal("preview cleanup removed a confirmed audit record")
	}
	manifest := filepath.Join(a.mailCampaigns.dir, v.ID+".json")
	body, err := os.ReadFile(manifest)
	if err != nil {
		t.Fatal(err)
	}
	var c adminCampaign
	if json.Unmarshal(body, &c) != nil {
		t.Fatal("manifest")
	}
	c.Recipients[0].DeliveryID = "bad-key"
	if err = os.WriteFile(manifest, []byte(campaignBody(t, c)), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err = openAdminCampaignStore(data); err == nil {
		t.Fatal("corrupt stable delivery key accepted at startup")
	}
}

func TestAdminCampaignPlainNotificationAndIllegalStateEvent(t *testing.T) {
	a, token, j, _ := campaignFixture(t)
	input := campaignInputTest(t, "selected", campaignTestID(1))
	input.Attachments = nil
	v := campaignPreviewTest(t, a, token, input)
	campaignCommitTest(t, a, token, v)
	a.campaignDeliveryStep(context.Background())
	j.mu.Lock()
	if j.attachments[campaignTestID(1)] != "[]" {
		t.Error("omitted attachments forwarded Java null instead of empty array")
	}
	j.mu.Unlock()
	c := a.mailCampaigns.jobs[v.ID]
	if c.Status != "completed" {
		t.Fatal("notification did not complete")
	}
	err := a.mailCampaigns.applyEvent(c, adminCampaignEvent{Seq: c.Seq + 1, At: a.now().UnixMilli(), Kind: "state", Status: "running"})
	if err == nil {
		t.Fatal("journal resurrected completed campaign without explicit failed retry")
	}
	err = a.mailCampaigns.applyEvent(c, adminCampaignEvent{Seq: c.Seq, At: a.now().UnixMilli(), Kind: "state", Status: "completed"})
	if err == nil {
		t.Fatal("duplicate journal sequence accepted")
	}
}

func TestAdminCampaignWorkerLifecycleAndStorageFailureStopsSending(t *testing.T) {
	a, token, j, _ := campaignFixture(t)
	v := campaignPreviewTest(t, a, token, campaignInputTest(t, "selected", campaignTestID(1)))
	campaignCommitTest(t, a, token, v)
	a.mailCampaigns.interval = 5 * time.Millisecond
	a.startAdminMailWorker()
	a.startAdminMailWorker()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		a.mailCampaigns.mu.Lock()
		done := a.mailCampaigns.jobs[v.ID].Status == "completed"
		a.mailCampaigns.mu.Unlock()
		if done {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	a.mailCampaigns.close()
	a.mailCampaigns.mu.Lock()
	sent := campaignCounts(a.mailCampaigns.jobs[v.ID]).Sent
	a.mailCampaigns.mu.Unlock()
	if sent != 1 {
		t.Fatal("single background worker did not finish")
	}
	j.mu.Lock()
	if len(j.requests[campaignTestID(1)]) != 1 {
		t.Error("starting worker twice duplicated delivery")
	}
	j.mu.Unlock()
	second := campaignPreviewTest(t, a, token, campaignInputTest(t, "selected", campaignTestID(2)))
	campaignCommitTest(t, a, token, second)
	path := filepath.Join(a.mailCampaigns.dir, second.ID+".jsonl")
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(path, 0o700); err != nil {
		t.Fatal(err)
	}
	a.campaignDeliveryStep(context.Background())
	if !a.mailCampaigns.fault {
		t.Fatal("unsafe journal path did not stop worker")
	}
	j.mu.Lock()
	if len(j.requests[campaignTestID(2)]) != 0 {
		t.Error("mail reached Java before durable inflight record")
	}
	j.mu.Unlock()
	detail := adminRequest(a, http.MethodGet, "/admin/api/mail/campaigns/"+second.ID, token, "")
	wantStatus(t, detail, 503)
	if !strings.Contains(detail.Body.String(), "mail_queue_unavailable") {
		t.Fatal("storage fault was hidden from operator")
	}
}

func TestAdminCampaignCorruptQueueIsolatedFromGameStartup(t *testing.T) {
	a, token, j, data := campaignFixture(t)
	v := campaignPreviewTest(t, a, token, campaignInputTest(t, "selected", campaignTestID(1)))
	campaignCommitTest(t, a, token, v)
	path := filepath.Join(a.mailCampaigns.dir, v.ID+".jsonl")
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = f.WriteString("{corrupt complete record}\n")
	_ = f.Close()
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err = a.Close(); err != nil {
		t.Fatal(err)
	}
	game, err := newApp(data, filepath.Join(filepath.Dir(data), "stories.json"))
	if err != nil {
		t.Fatalf("mail corruption took gateway offline: %v", err)
	}
	t.Cleanup(func() { _ = game.Close() })
	game.admin = &adminConfig{sessions: map[[32]byte]time.Time{sha256.Sum256([]byte(token)): time.Now().Add(time.Hour)}, rates: make(map[string]rateEntry)}
	if err = game.configureLegacyProxy(a.legacy.upstream.String(), strings.Repeat("x", 40)); err != nil {
		t.Fatal(err)
	}
	if !game.mailCampaigns.fault {
		t.Fatal("corrupt queue did not fail closed")
	}
	game.startAdminMailWorker()
	if game.mailCampaigns.cancel != nil {
		t.Fatal("disabled queue started worker")
	}
	wantStatus(t, request(game, http.MethodGet, "/health", "", ""), 200)
	player := registerTest(t, game, "queue-isolation@example.invalid")
	wantStatus(t, request(game, http.MethodGet, "/api/v1/me", player.Token, ""), 200)
	wantStatus(t, adminRequest(game, http.MethodGet, "/admin/api/accounts", token, ""), 200)
	wantStatus(t, adminRequest(game, http.MethodGet, "/admin/api/mail/catalog", token, ""), 200)
	wantStatus(t, adminRequest(game, http.MethodGet, "/admin/api/mail/campaigns", "", ""), 401)
	for _, path := range []string{"/admin/api/mail/campaigns", "/admin/api/mail/campaigns/" + v.ID, "/admin/api/mail/campaigns/by-request/123e4567-e89b-42d3-a456-426614174000"} {
		wantStatus(t, adminRequest(game, http.MethodGet, path, token, ""), 503)
	}
	for _, path := range []string{"/admin/api/mail/preview", "/admin/api/mail/campaigns", "/admin/api/mail/campaigns/" + v.ID + "/control"} {
		wantStatus(t, adminRequest(game, http.MethodPost, path, token, `{}`), 503)
	}
	j.mu.Lock()
	if len(j.requests) != 0 {
		t.Error("corrupt queue sent game mail")
	}
	j.mu.Unlock()
	after, err := os.ReadFile(path)
	if err != nil || string(after) != string(before) {
		t.Fatal("corrupt audit evidence was modified during isolation")
	}
}
