package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAdminLegacyEditLockDistinguishedFromRevisionConflict(t *testing.T) {
	a, _, _ := fixture(t)
	account := registerTest(t, a, "maze-edit-lock@example.com")
	configureAdminTest(t, a)
	token := loginAdminTest(t, a)
	upstreamBody := ""
	java := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/__admin/patch" || r.Header.Get("X-WW-Account-ID") != account.Player.ID {
			t.Error("unexpected account or upstream operation")
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusConflict)
		fmt.Fprint(w, upstreamBody)
	}))
	defer java.Close()
	if err := a.configureLegacyProxy(java.URL, strings.Repeat("x", 40)); err != nil {
		t.Fatal(err)
	}
	payload := `{"expectedRevision":"1","changes":{"gold":2},"reason":"检查迷宫整备期间的修改保护"}`
	for _, testCase := range []struct{ name, body, code string }{
		{"maze preparation lock", `{"error":"active_battle","message":"private-upstream-detail"}`, "active_battle"},
		{"revision conflict", `{"error":"revision_conflict","message":"private-upstream-detail"}`, "revision_conflict"},
		{"malformed rejection", `{"error":"active_battle"`, "revision_conflict"},
		{"oversized rejection", `{"error":"active_battle","padding":"` + strings.Repeat("x", 4096) + `"}`, "revision_conflict"},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			upstreamBody = testCase.body
			response := adminRequest(a, http.MethodPatch, "/admin/api/accounts/"+account.Player.ID+"/legacy", token, payload)
			wantStatus(t, response, http.StatusConflict)
			body := response.Body.String()
			if !strings.Contains(body, `"code":"`+testCase.code+`"`) || strings.Contains(body, "private-upstream-detail") {
				t.Fatalf("unsafe or incorrect edit rejection: %s", body)
			}
			if testCase.code == "active_battle" && !strings.Contains(body, "迷宫整备") {
				t.Fatal("maze preparation explanation is missing")
			}
		})
	}
}
