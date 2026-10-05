package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
)

const testDataBackup = "10000000-0000-4000-8000-000000000001"
const testDataPrePatch = "10000000-0000-4000-8000-000000000002"
const testDataPreRestore = "10000000-0000-4000-8000-000000000003"
const testDataReason = "测试管理员修复玩家资源数据"

func testDataBackupJSON(revision string) string {
	return fmt.Sprintf(`{"id":%q,"createdAt":1800000000000,"revision":%q,"reason":%q,"kind":"manual","sha256":%q,"bytes":50}`,
		testDataBackup, revision, testDataReason, strings.Repeat("a", 64))
}

func TestAdminDataCatalogUsesChineseResourceNames(t *testing.T) {
	save := adminDataSave{Fields: []adminDataField{
		{Key: "items", Type: "map", Catalog: []adminDataCatalogEntry{
			{ID: "40130001", Label: "道具 40130001", Max: "99"},
			{ID: "1411001", Label: "未知道具保留原标识", Max: "9"},
		}},
		{Key: "equips", Type: "map", Catalog: []adminDataCatalogEntry{
			{ID: "1411001", Label: "装备 1411001", Max: "9"},
		}},
	}}
	if !adminLocalizeDataCatalog(&save) {
		t.Fatal("Chinese resource names could not be loaded")
	}
	if save.Fields[0].Catalog[0].Label != "旧神印记 (40130001)" || save.Fields[1].Catalog[0].Label != "剑玉 (1411001)" ||
		save.Fields[0].Catalog[1].Label != "未知道具保留原标识" || save.Fields[0].Catalog[0].Max != "99" {
		t.Fatal("catalog names crossed resource types or changed resource limits")
	}
}

func TestAdminDataLifecycleAndProxyIsolation(t *testing.T) {
	a, _, _ := fixture(t)
	alice := registerTest(t, a, "admin-data-alice@example.com")
	bob := registerTest(t, a, "admin-data-bob@example.com")
	configureAdminTest(t, a)
	token := loginAdminTest(t, a)
	base := "/admin/api/accounts/" + alice.Player.ID
	revision := int64(7)
	patches, restores, backups, previews := 0, 0, 0, 0
	snapshot := []byte("{\"gold\":9007199254740993,\"saveRevision\":7}\n")
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-WW-Account-ID") != alice.Player.ID || r.Header.Get("X-WW-Proxy-Secret") != strings.Repeat("x", 40) ||
			r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" || r.URL.RawQuery != "" {
			t.Error("management request crossed an account or header boundary")
			w.WriteHeader(403)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		if r.Method == http.MethodPost {
			if r.Header.Get("Content-Type") != "application/x-www-form-urlencoded" || r.ParseForm() != nil {
				t.Error("invalid Java management form")
			}
			if r.URL.Path != "/__admin/backups/read" {
				if r.Form.Get("expectedRevision") != strconv.FormatInt(revision, 10) {
					w.WriteHeader(409)
					fmt.Fprint(w, `{"error":"save_conflict"}`)
					return
				}
				if r.Form.Get("reason") != testDataReason {
					t.Error("missing operation reason")
				}
			}
		}
		switch r.URL.Path {
		case "/__admin/save":
			if r.Method != http.MethodGet {
				t.Error("save read is not GET")
			}
			fmt.Fprintf(w, `{"version":1,"revision":%q,"active":false,"readOnly":{"roleId":"42","drawCount":"9007199254740993"},"fields":[{"key":"name","label":"昵称","group":"基本信息","type":"text","value":"测试角色"},{"key":"gold","label":"金币","group":"货币与资源","type":"integer","value":"9007199254740993","min":"0","max":"9223372036854775807"},{"key":"items","label":"道具","group":"道具","type":"map","value":{"100":"2"},"help":"按目录修改","catalog":[{"id":"100","label":"测试道具","max":"999"}]}]}`, strconv.FormatInt(revision, 10))
		case "/__admin/save/preview", "/__admin/save/patch":
			var changes map[string]json.RawMessage
			if json.Unmarshal([]byte(r.Form.Get("changes")), &changes) != nil || string(changes["gold"]) != `"1234"` || string(changes["items"]) != `{"100":"3"}` {
				t.Errorf("changes did not preserve typed map strings: %s", r.Form.Get("changes"))
			}
			if r.URL.Path == "/__admin/save/preview" {
				previews++
				fmt.Fprintf(w, `{"revision":%q,"changeCount":2,"changes":[{"key":"gold","label":"金币","before":"9007199254740993","after":"1234"},{"key":"items.100","label":"测试道具 (100)","before":"2","after":"3"}]}`, strconv.FormatInt(revision, 10))
			} else {
				patches++
				revision++
				fmt.Fprintf(w, `{"revision":%q,"backupId":%q,"changeCount":2}`, strconv.FormatInt(revision, 10), testDataPrePatch)
			}
		case "/__admin/backups":
			fmt.Fprintf(w, `{"items":[%s]}`, testDataBackupJSON("7"))
		case "/__admin/backups/create":
			backups++
			fmt.Fprintf(w, `{"backup":%s}`, testDataBackupJSON(strconv.FormatInt(revision, 10)))
		case "/__admin/backups/read":
			if r.Form.Get("backupId") != testDataBackup {
				t.Error("wrong backup owner or ID")
			}
			_, _ = w.Write(snapshot)
		case "/__admin/backups/preview":
			previews++
			fmt.Fprintf(w, `{"revision":%q,"changeCount":1,"changes":[{"key":"gold","label":"金币","before":"1234","after":"9007199254740993"}],"retainedFields":["mail"]}`, strconv.FormatInt(revision, 10))
		case "/__admin/backups/restore":
			if r.Form.Get("backupId") != testDataBackup {
				t.Error("restore did not send selected backup")
			}
			if restores > 0 {
				fmt.Fprintf(w, `{"revision":%q,"backupId":"","restoredFrom":%q,"restoredFields":[],"retainedFields":["mail"]}`, strconv.FormatInt(revision, 10), testDataBackup)
				return
			}
			restores++
			revision++
			fmt.Fprintf(w, `{"revision":%q,"backupId":%q,"restoredFrom":%q,"restoredFields":["gold"],"retainedFields":["mail"]}`, strconv.FormatInt(revision, 10), testDataPreRestore, testDataBackup)
		default:
			t.Errorf("unexpected management path %s", r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, strings.Repeat("x", 40)); err != nil {
		t.Fatal(err)
	}
	wantStatus(t, adminRequest(a, http.MethodGet, base+"/save", alice.Token, ""), 401)
	read := adminRequest(a, http.MethodGet, base+"/save", token, "")
	wantStatus(t, read, 200)
	if !strings.Contains(read.Body.String(), `"value":"9007199254740993"`) || !strings.Contains(read.Body.String(), `"value":{"100":"2"}`) {
		t.Fatal("save field precision or map values were changed")
	}
	operation := fmt.Sprintf(`{"expectedRevision":"7","reason":%q}`, testDataReason)
	wantStatus(t, adminRequest(a, http.MethodPost, base+"/backups", token, operation), 200)
	wantStatus(t, adminRequest(a, http.MethodGet, base+"/backups", token, ""), 200)
	download := adminRequest(a, http.MethodGet, base+"/backups/"+testDataBackup, token, "")
	wantStatus(t, download, 200)
	if !bytes.Equal(download.Body.Bytes(), snapshot) || !strings.Contains(download.Header().Get("Content-Disposition"), testDataBackup+".json") {
		t.Fatal("backup download was re-encoded or filename is unsafe")
	}
	changes := fmt.Sprintf(`{"expectedRevision":"7","reason":%q,"changes":{"gold":"1234","items":{"100":"3"}}}`, testDataReason)
	wantStatus(t, adminRequest(a, http.MethodPost, base+"/save/preview", token, changes), 200)
	if revision != 7 || patches != 0 || restores != 0 || backups != 1 {
		t.Fatal("preview unexpectedly changed state or created an extra backup")
	}
	wantStatus(t, adminRequest(a, http.MethodPatch, base+"/save", token, changes), 200)
	wantStatus(t, adminRequest(a, http.MethodPatch, base+"/save", token, changes), 409)
	restoreOperation := fmt.Sprintf(`{"expectedRevision":"8","reason":%q}`, testDataReason)
	wantStatus(t, adminRequest(a, http.MethodPost, base+"/backups/"+testDataBackup+"/preview", token, restoreOperation), 200)
	if revision != 8 || restores != 0 {
		t.Fatal("restore preview changed state")
	}
	wantStatus(t, adminRequest(a, http.MethodPost, base+"/backups/"+testDataBackup+"/restore", token, restoreOperation), 200)
	noopRestore := fmt.Sprintf(`{"expectedRevision":"9","reason":%q}`, testDataReason)
	wantStatus(t, adminRequest(a, http.MethodPost, base+"/backups/"+testDataBackup+"/restore", token, noopRestore), 200)
	if revision != 9 || patches != 1 || restores != 1 || previews != 2 || backups != 1 {
		t.Fatalf("unexpected operation totals revision=%d patches=%d restores=%d previews=%d backups=%d", revision, patches, restores, previews, backups)
	}
	for _, path := range []string{"/__admin/save", "/__admin/backups", "/__admin/backups/read", "/__admin/backups/restore"} {
		wantStatus(t, request(a, http.MethodPost, "/api/v1/legacy"+path, bob.Token, ""), 404)
	}
}

func TestAdminDataInvalidInputNeverReachesJava(t *testing.T) {
	a, _, _ := fixture(t)
	account := registerTest(t, a, "admin-invalid@example.com")
	configureAdminTest(t, a)
	token := loginAdminTest(t, a)
	requests := 0
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		requests++
		w.WriteHeader(500)
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, strings.Repeat("x", 40)); err != nil {
		t.Fatal(err)
	}
	base := "/admin/api/accounts/" + account.Player.ID
	for _, body := range []string{
		`{"expectedRevision":"01","reason":"测试管理员修复玩家数据","changes":{"gold":"1"}}`,
		`{"expectedRevision":"1","reason":"短理由","changes":{"gold":"1"}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"gold":1}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"gold":null}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"gold":"1"},"extra":"secret"}`,
		`{"expectedRevision":"1","expectedRevision":"2","reason":"测试管理员修复玩家数据","changes":{"gold":"1"}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"gold":"1","gold":"2"}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"items":{"100":"1","100":"2"}}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"items":{"100":"1"},"items.100":"2"}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"items":{"100":1}}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"items":{"100":"-1"}}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"items":{"100":"01"}}}`,
		`{"expectedRevision":"1","reason":"测试管理员修复玩家数据","changes":{"roleId":{"100":"1"}}}`,
	} {
		wantStatus(t, adminRequest(a, http.MethodPatch, base+"/save", token, body), 400)
	}
	wantStatus(t, adminRequest(a, http.MethodPatch, base+"/save", token, strings.Repeat(" ", adminDataRequestLimit+1)), 413)
	wantStatus(t, adminRequest(a, http.MethodGet, base+"/save?file=secret", token, ""), 400)
	wantStatus(t, adminRequest(a, http.MethodGet, base+"/backups/not-a-uuid", token, ""), 404)
	wantStatus(t, adminRequest(a, http.MethodGet, base+"/backups/..%2fconfig", token, ""), 400)
	wantStatus(t, adminRequest(a, http.MethodGet, "/admin/api/accounts/"+strings.Repeat("a", 22)+"/save", token, ""), 404)
	origin := httptest.NewRequest(http.MethodPatch, "http://127.0.0.1:18080"+base+"/save", strings.NewReader(`{}`))
	origin.RemoteAddr = "127.0.0.1:51000"
	origin.Header.Set("Authorization", "Bearer "+token)
	origin.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	a.ServeHTTP(w, origin)
	wantStatus(t, w, 404)
	if requests != 0 {
		t.Fatalf("%d invalid management requests reached Java", requests)
	}
}

func TestAdminDataRejectsBadUpstreamAndExplainsActiveBattle(t *testing.T) {
	a, _, _ := fixture(t)
	account := registerTest(t, a, "admin-response@example.com")
	configureAdminTest(t, a)
	token := loginAdminTest(t, a)
	status, contentType, body := 200, "application/json", `{"version":1,"revision":"1","active":false,"readOnly":{},"fields":[]}`
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", contentType)
		w.WriteHeader(status)
		fmt.Fprint(w, body)
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, strings.Repeat("x", 40)); err != nil {
		t.Fatal(err)
	}
	base := "/admin/api/accounts/" + account.Player.ID
	for _, invalid := range []string{
		body,
		`{"version":1,"revision":"1","active":false,"readOnly":{},"fields":[{"key":"gold","label":"金币","group":"资源","type":"integer","value":1,"min":"0","max":"999"}]}`,
		`{"version":1,"revision":"1","active":false,"readOnly":{"passwordHash":"secret"},"fields":[{"key":"name","label":"昵称","group":"基本","type":"text","value":"角色"}]}`,
		`{"version":1,"revision":"1","active":false,"readOnly":{},"extra":"secret","fields":[{"key":"name","label":"昵称","group":"基本","type":"text","value":"角色"}]}`,
		`{"version":1,"revision":"1","active":false,"readOnly":{},"fields":[{"key":"name","label":"昵称","group":"基本","type":"text","value":null}]}`,
	} {
		body = invalid
		wantStatus(t, adminRequest(a, http.MethodGet, base+"/save", token, ""), 502)
	}
	contentType = "application/jsonp"
	wantStatus(t, adminRequest(a, http.MethodGet, base+"/save", token, ""), 502)
	contentType, body = "application/json", strings.Repeat(" ", adminDataResponseLimit+1)
	wantStatus(t, adminRequest(a, http.MethodGet, base+"/backups/"+testDataBackup, token, ""), 502)
	body = `{"gold":1,"nested":{"password":"never return"}}`
	wantStatus(t, adminRequest(a, http.MethodGet, base+"/backups/"+testDataBackup, token, ""), 502)
	status, body = 409, `{"error":"active_battle"}`
	operation := fmt.Sprintf(`{"expectedRevision":"1","reason":%q,"changes":{"gold":"2"}}`, testDataReason)
	result := adminRequest(a, http.MethodPatch, base+"/save", token, operation)
	wantStatus(t, result, 409)
	if !strings.Contains(result.Body.String(), `"code":"active_battle"`) {
		t.Fatalf("active battle rejection lost its reason: %s", result.Body.String())
	}
}
