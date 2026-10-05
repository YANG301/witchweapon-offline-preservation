package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAdminMailAuthenticatedDeliveryAndCatalog(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "mail-alice@example.com")
	bob := registerTest(t, a, "mail-bob@example.com")
	configureAdminTest(t, a)
	adminToken := loginAdminTest(t, a)
	var sent int
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-WW-Proxy-Secret") != strings.Repeat("x", 40) ||
			r.Header.Get("X-WW-Account-ID") != bob.Player.ID ||
			r.Header.Get("Authorization") != "" {
			t.Error("mail proxy did not isolate account and secret")
			w.WriteHeader(403)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		switch r.URL.Path {
		case "/__admin/mail/catalog":
			if r.Method != http.MethodGet {
				t.Error("catalog method")
			}
			_, _ = w.Write([]byte(`{"version":1,"entries":[{"type":13,"id":0,"name":"金币","maxCount":1000000},{"type":98,"id":0,"name":"钻石","maxCount":100000},{"type":3,"id":40320001,"name":"物品 40320001","maxCount":999}]}`))
		case "/__admin/mail/send":
			sent++
			if r.Method != http.MethodPost || r.Header.Get("Content-Type") != "application/x-www-form-urlencoded" {
				t.Error("mail send transport")
			}
			if err := r.ParseForm(); err != nil {
				t.Error(err)
			}
			if r.Form.Get("expectedRevision") != "5" ||
				r.Form.Get("requestId") != "123e4567-e89b-42d3-a456-426614174000" ||
				r.Form.Get("title") != "测试补给" || r.Form.Get("sender") != "新丰洲" ||
				r.Form.Get("content") != "这是本机隔离测试邮件。" ||
				r.Form.Get("reason") != "验证管理邮件与背包物资" {
				t.Error("mail send form mismatch")
			}
			var gifts []adminMailAttachment
			if err := json.Unmarshal([]byte(r.Form.Get("attachments")), &gifts); err != nil ||
				len(gifts) != 2 || gifts[0].Type != 13 || gifts[0].Count != 500 ||
				gifts[1].Type != 3 || gifts[1].ID != 40320001 {
				t.Error("mail attachment projection")
			}
			fmt.Fprintf(w, `{"id":"123456789","revision":"6","duplicate":%t}`, sent > 1)
		default:
			t.Errorf("unexpected mail path %q", r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, strings.Repeat("x", 40)); err != nil {
		t.Fatal(err)
	}
	path := "/admin/api/accounts/" + bob.Player.ID + "/mail"
	valid := `{"expectedRevision":"5","requestId":"123e4567-e89b-42d3-a456-426614174000","reason":"验证管理邮件与背包物资","title":"测试补给","sender":"新丰洲","content":"这是本机隔离测试邮件。","attachments":[{"type":13,"id":0,"count":500},{"type":3,"id":40320001,"count":1}]}`
	wantStatus(t, adminRequest(a, http.MethodPost, path, alice.Token, valid), 401)
	for _, invalid := range []string{
		strings.Replace(valid, `"count":500`, `"count":1000001`, 1),
		strings.Replace(valid, `"type":3,"id":40320001`, `"type":3,"id":0`, 1),
		strings.Replace(valid, `"requestId":"123e4567-e89b-42d3-a456-426614174000"`, `"requestId":"not-a-uuid"`, 1),
		strings.Replace(valid, `"title":"测试补给"`, `"title":"<b>测试</b>"`, 1),
		strings.Replace(valid, `"reason":"验证管理邮件与背包物资"`, `"reason":"太短"`, 1),
		strings.Replace(valid, `"attachments":[`, `"unknown":true,"attachments":[`, 1),
	} {
		wantStatus(t, adminRequest(a, http.MethodPost, path, adminToken, invalid), 400)
	}
	if sent != 0 {
		t.Fatal("invalid mail reached Java")
	}
	first := adminRequest(a, http.MethodPost, path, adminToken, valid)
	wantStatus(t, first, 200)
	if !strings.Contains(first.Body.String(), `"duplicate":false`) {
		t.Fatal("first send was not confirmed")
	}
	retry := adminRequest(a, http.MethodPost, path, adminToken, valid)
	wantStatus(t, retry, 200)
	if sent != 2 || !strings.Contains(retry.Body.String(), `"duplicate":true`) {
		t.Fatal("same request ID retry did not preserve upstream response")
	}
	catalog := adminRequest(a, http.MethodGet, path+"/catalog", adminToken, "")
	wantStatus(t, catalog, 200)
	if !strings.Contains(catalog.Body.String(), "波子汽水") ||
		strings.Contains(catalog.Body.String(), "mail-alice@example.com") {
		t.Fatal("catalog did not use preserved Chinese resource names")
	}
}
