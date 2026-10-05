package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"testing"
	"time"
)

type adminAccountListResponse struct {
	Items        []adminAccountSummary `json:"items"`
	Total        int                   `json:"total"`
	AccountTotal int                   `json:"accountTotal"`
	Limit        int                   `json:"limit"`
	NextCursor   string                `json:"nextCursor"`
}

func adminAccountListFixture(count int) *app {
	s := &store{state: diskState{Users: make(map[string]*account)}}
	for i := 0; i < count; i++ {
		id := fmt.Sprintf("%022d", i)
		email := fmt.Sprintf("user%03d@example.com", i)
		if i >= 220 {
			email = fmt.Sprintf("group%03d@example.com", i)
		}
		s.state.Users[id] = &account{ID: id, PublicRID: publicRIDMin + i,
			Email: email, EmailVerified: i%2 == 0}
	}
	return &app{store: s}
}

func adminAccountListCall(t *testing.T, a *app, query string, status int) adminAccountListResponse {
	t.Helper()
	r := httptest.NewRequest(http.MethodGet, "/admin/api/accounts"+query, nil)
	w := httptest.NewRecorder()
	a.adminAccounts(w, r, [32]byte{}, time.Time{})
	wantStatus(t, w, status)
	var response adminAccountListResponse
	if status == 200 {
		if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
			t.Fatal(err)
		}
	}
	return response
}

func TestAdminAccountListFiltersSearchAllAccounts(t *testing.T) {
	a := adminAccountListFixture(237)
	// Matching accounts are beyond the first 100 records in the original
	// account-ID order. Filtering must run before pagination.
	filtered := adminAccountListCall(t, a, "?q=GROUP&field=email&verified=yes&sort=rid_desc&limit=100", 200)
	if filtered.Total != 9 || filtered.AccountTotal != 237 || len(filtered.Items) != 9 || filtered.NextCursor != "" {
		t.Fatalf("unexpected filtered results: %+v", filtered)
	}
	for i, item := range filtered.Items {
		if !item.EmailVerified || !strings.HasPrefix(item.Email, "group") || (i > 0 && item.PublicRID >= filtered.Items[i-1].PublicRID) {
			t.Fatalf("filter or order not applied: %+v", filtered.Items)
		}
	}
	noMatch := adminAccountListCall(t, a, "?q=missing&verified=no", 200)
	if noMatch.Items == nil || len(noMatch.Items) != 0 || noMatch.Total != 0 || noMatch.AccountTotal != 237 || noMatch.NextCursor != "" {
		t.Fatalf("empty search should retain the overall account count: %+v", noMatch)
	}
}

func TestAdminAccountListFieldSelection(t *testing.T) {
	a := adminAccountListFixture(10)
	a.store.state.Users[fmt.Sprintf("%022d", 6)].Email = "100005@example.com"
	for _, test := range []struct {
		field string
		want  int
	}{
		{"all", 2}, {"rid", 1}, {"email", 1}, {"id", 0},
	} {
		result := adminAccountListCall(t, a, "?q=100005&field="+test.field, 200)
		if result.Total != test.want {
			t.Fatalf("field %s returned %d accounts, want %d", test.field, result.Total, test.want)
		}
	}
	upperID := strings.Repeat("A", 22)
	a.store.state.Users[upperID] = &account{ID: upperID, PublicRID: 200000, Email: "MiXeD@example.com"}
	for _, query := range []string{"?q=mixed&field=email", "?q=" + strings.ToLower(upperID) + "&field=id"} {
		result := adminAccountListCall(t, a, query, 200)
		if result.Total != 1 || result.Items[0].ID != upperID {
			t.Fatalf("case-insensitive field search did not find account: %+v", result)
		}
	}
}

func TestAdminAccountListPageSizesAndRIDPagination(t *testing.T) {
	a := adminAccountListFixture(237)
	for _, limit := range []int{20, 50, 100, 200} {
		result := adminAccountListCall(t, a, "?limit="+strconv.Itoa(limit), 200)
		if len(result.Items) != limit || result.Limit != limit || result.Total != 237 || result.NextCursor == "" {
			t.Fatalf("page size %d was not respected: %+v", limit, result)
		}
	}
	for _, order := range []string{"rid_asc", "rid_desc"} {
		seen := make(map[string]bool)
		cursor := ""
		previousRID := 0
		for page := 0; page < 20; page++ {
			result := adminAccountListCall(t, a, "?limit=20&sort="+order+"&cursor="+url.QueryEscape(cursor), 200)
			if result.Total != 237 || result.AccountTotal != 237 {
				t.Fatal("pagination changed result counts")
			}
			for _, item := range result.Items {
				if seen[item.ID] || (previousRID != 0 && ((order == "rid_asc" && item.PublicRID <= previousRID) || (order == "rid_desc" && item.PublicRID >= previousRID))) {
					t.Fatalf("pagination repeated or reordered an account: %+v", item)
				}
				seen[item.ID] = true
				previousRID = item.PublicRID
			}
			if result.NextCursor == "" {
				break
			}
			cursor = result.NextCursor
		}
		if len(seen) != 237 {
			t.Fatalf("%s pagination found %d accounts, want 237", order, len(seen))
		}
	}
}

func TestAdminAccountListCursorSurvivesAccountRemoval(t *testing.T) {
	a := adminAccountListFixture(10)
	first := adminAccountListCall(t, a, "?sort=rid_desc&limit=3", 200)
	delete(a.store.state.Users, first.Items[2].ID)
	second := adminAccountListCall(t, a, "?sort=rid_desc&limit=3&cursor="+url.QueryEscape(first.NextCursor), 200)
	if second.Total != 9 || len(second.Items) != 3 || second.Items[0].PublicRID != publicRIDMin+6 {
		t.Fatalf("removed cursor account caused a repeat or skipped page: %+v", second)
	}
}

func TestAdminAccountListRejectsInvalidFilterQueries(t *testing.T) {
	a := adminAccountListFixture(1)
	for _, query := range []string{
		"?limit=0", "?limit=201", "?limit=all", "?field=nickname", "?verified=true", "?sort=id_desc",
		"?field=id&field=email", "?verified=no&verified=yes", "?sort=rid_asc&sort=rid_desc",
		"?unknown=x", "?q=x;q=y", "?q=%FF", "?q=%00", "?cursor=../",
		"?sort=rid_asc&cursor=" + strings.Repeat("A", 22),
		"?cursor=100000:" + strings.Repeat("A", 22),
		"?sort=rid_desc&cursor=0100000:" + strings.Repeat("A", 22),
		"?sort=rid_desc&cursor=99999:" + strings.Repeat("A", 22),
		"?sort=rid_desc&cursor=100000:" + strings.Repeat("A", 22) + ":extra",
	} {
		t.Run(query, func(t *testing.T) { adminAccountListCall(t, a, query, 400) })
	}
}
