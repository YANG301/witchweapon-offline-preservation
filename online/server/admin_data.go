package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const adminDataRequestLimit = 512 << 10
const adminDataResponseLimit = 32 << 20
const adminDataMaxChanges = 128
const adminDataMaxResourceChanges = 2000
const adminDataMaxValueChanges = 2000
const adminDataMaxFields = 20000

var adminDataFieldKey = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_.]{0,127}$`)
var adminDataCatalogID = regexp.MustCompile(`^[1-9][0-9]{0,18}$`)
var adminBackupID = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
var adminSnapshotSHA = regexp.MustCompile(`^[0-9a-f]{64}$`)

type adminDataInput struct {
	ExpectedRevision string                     `json:"expectedRevision"`
	Reason           string                     `json:"reason"`
	Changes          map[string]json.RawMessage `json:"changes"`
}

type adminBackupInput struct {
	ExpectedRevision string `json:"expectedRevision"`
	Reason           string `json:"reason"`
}

type adminDataField struct {
	Key        string                  `json:"key"`
	Label      string                  `json:"label"`
	Group      string                  `json:"group"`
	Type       string                  `json:"type"`
	Value      json.RawMessage         `json:"value"`
	Min        string                  `json:"min,omitempty"`
	Max        string                  `json:"max,omitempty"`
	Help       string                  `json:"help,omitempty"`
	Catalog    []adminDataCatalogEntry `json:"catalog,omitempty"`
	EntityID   string                  `json:"entityId,omitempty"`
	EntityName string                  `json:"entityName,omitempty"`
}

type adminDataCatalogEntry struct {
	ID       string `json:"id"`
	Label    string `json:"label"`
	Max      string `json:"max"`
	Category string `json:"category,omitempty"`
	Quality  int    `json:"quality,omitempty"`
}

type adminDataSave struct {
	Version  int                        `json:"version"`
	Revision string                     `json:"revision"`
	Fields   []adminDataField           `json:"fields"`
	ReadOnly map[string]json.RawMessage `json:"readOnly"`
	Active   bool                       `json:"active"`
}

type adminDataChange struct {
	Key    string `json:"key"`
	Label  string `json:"label"`
	Before string `json:"before"`
	After  string `json:"after"`
}

type adminDataPreview struct {
	Revision    string            `json:"revision"`
	Changes     []adminDataChange `json:"changes"`
	ChangeCount int               `json:"changeCount"`
}

type adminBackupPreview struct {
	Revision       string            `json:"revision"`
	Changes        []adminDataChange `json:"changes"`
	ChangeCount    int               `json:"changeCount"`
	RetainedFields []string          `json:"retainedFields,omitempty"`
}

type adminDataPatch struct {
	Revision    string `json:"revision"`
	BackupID    string `json:"backupId"`
	ChangeCount int    `json:"changeCount"`
}

type adminBackupItem struct {
	ID        string `json:"id"`
	CreatedAt int64  `json:"createdAt"`
	Revision  string `json:"revision"`
	Reason    string `json:"reason"`
	Kind      string `json:"kind"`
	SHA256    string `json:"sha256"`
	Bytes     int64  `json:"bytes"`
}

type adminBackupList struct {
	Items []adminBackupItem `json:"items"`
}

type adminBackupCreated struct {
	Backup adminBackupItem `json:"backup"`
}

type adminBackupRestored struct {
	Revision       string   `json:"revision"`
	BackupID       string   `json:"backupId"`
	RestoredFrom   string   `json:"restoredFrom"`
	RestoredFields []string `json:"restoredFields"`
	RetainedFields []string `json:"retainedFields"`
}

func (a *app) mountAdminData() {
	a.mux.HandleFunc("GET /admin/api/accounts/{id}/save", a.adminAuth(a.adminGetSave))
	a.mux.HandleFunc("POST /admin/api/accounts/{id}/save/preview", a.adminAuth(a.adminPreviewSave))
	a.mux.HandleFunc("PATCH /admin/api/accounts/{id}/save", a.adminAuth(a.adminSaveData))
	a.mux.HandleFunc("GET /admin/api/accounts/{id}/backups", a.adminAuth(a.adminListBackups))
	a.mux.HandleFunc("POST /admin/api/accounts/{id}/backups", a.adminAuth(a.adminCreateBackup))
	a.mux.HandleFunc("GET /admin/api/accounts/{id}/backups/{backup}", a.adminAuth(a.adminDownloadBackup))
	a.mux.HandleFunc("POST /admin/api/accounts/{id}/backups/{backup}/preview", a.adminAuth(a.adminPreviewBackup))
	a.mux.HandleFunc("POST /admin/api/accounts/{id}/backups/{backup}/restore", a.adminAuth(a.adminRestoreBackup))
}

func (a *app) adminDataAccount(w http.ResponseWriter, r *http.Request, backup bool) (string, bool) {
	if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
		fail(w, 400, "invalid_request", "存档管理路径无效。")
		return "", false
	}
	id := r.PathValue("id")
	if !adminAccountID.MatchString(id) {
		fail(w, 404, "not_found", "没有找到该账号。")
		return "", false
	}
	if _, exists := a.store.player(id); !exists {
		fail(w, 404, "not_found", "没有找到该账号。")
		return "", false
	}
	if backup && !adminBackupID.MatchString(r.PathValue("backup")) {
		fail(w, 404, "backup_not_found", "没有找到该账号的备份。")
		return "", false
	}
	return id, true
}

func validAdminDataRevision(revision string) bool {
	n, err := strconv.ParseUint(revision, 10, 63)
	return err == nil && strconv.FormatUint(n, 10) == revision
}

func validAdminDataText(value string, min, max, maxBytes int) bool {
	if !utf8.ValidString(value) || len(value) > maxBytes || strings.TrimSpace(value) != value {
		return false
	}
	n := utf8.RuneCountInString(value)
	return n >= min && n <= max && strings.IndexFunc(value, func(ch rune) bool {
		return unicode.IsControl(ch) || unicode.Is(unicode.Cf, ch)
	}) < 0
}

func validAdminDataOperation(revision, reason string) bool {
	return validAdminDataRevision(revision) && validAdminDataText(reason, 8, 200, 512)
}

func adminDataString(value json.RawMessage) (string, bool) {
	var text *string
	if json.Unmarshal(value, &text) != nil || text == nil {
		return "", false
	}
	return *text, true
}

// Detect duplicate keys before decoding. Preview and commit must interpret the
// exact same document, independent of the Java and Go JSON implementations.
func validAdminDataJSON(body []byte, rejectSensitive bool) bool {
	if !utf8.Valid(body) {
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.UseNumber()
	tokens := 0
	var value func(int) bool
	value = func(depth int) bool {
		if depth > 32 || tokens > 250000 {
			return false
		}
		tokens++
		token, err := decoder.Token()
		if err != nil {
			return false
		}
		delim, structured := token.(json.Delim)
		if !structured {
			return true
		}
		switch delim {
		case '{':
			seen := make(map[string]bool)
			for decoder.More() {
				keyToken, err := decoder.Token()
				key, ok := keyToken.(string)
				if err != nil || !ok || seen[key] {
					return false
				}
				seen[key] = true
				if rejectSensitive {
					switch strings.ToLower(strings.ReplaceAll(key, "_", "")) {
					case "password", "passwordhash", "passwordsalt", "proxysecret", "refreshtoken", "authorization", "admincredential":
						return false
					}
				}
				if !value(depth + 1) {
					return false
				}
			}
			end, err := decoder.Token()
			return err == nil && end == json.Delim('}')
		case '[':
			for decoder.More() {
				if !value(depth + 1) {
					return false
				}
			}
			end, err := decoder.Token()
			return err == nil && end == json.Delim(']')
		default:
			return false
		}
	}
	if !value(0) {
		return false
	}
	_, err := decoder.Token()
	return err == io.EOF
}

func decodeAdminData(w http.ResponseWriter, r *http.Request, target any) bool {
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		fail(w, 415, "invalid_request", "请使用 JSON 格式提交存档操作。")
		return false
	}
	r.Body = http.MaxBytesReader(w, r.Body, adminDataRequestLimit)
	body, err := io.ReadAll(r.Body)
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			fail(w, 413, "request_too_large", "存档修改内容过长。")
		} else {
			fail(w, 400, "invalid_request", "存档操作无法读取。")
		}
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if !validAdminDataJSON(body, false) || decoder.Decode(target) != nil || decoder.Decode(new(any)) != io.EOF {
		fail(w, 400, "invalid_request", "存档操作格式无效、字段重复或包含未知字段。")
		return false
	}
	return true
}

func adminDecodeDataResponse(body []byte, target any) bool {
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	return validAdminDataJSON(body, true) && decoder.Decode(target) == nil && decoder.Decode(new(any)) == io.EOF
}

func adminDataHasFields(body []byte, keys ...string) bool {
	var object map[string]json.RawMessage
	if json.Unmarshal(body, &object) != nil || object == nil {
		return false
	}
	for _, key := range keys {
		value, exists := object[key]
		if !exists || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return false
		}
	}
	return true
}

func (a *app) adminDataRequest(w http.ResponseWriter, r *http.Request, id, method, path string, form url.Values, backup bool) ([]byte, bool) {
	var input io.Reader
	if form != nil {
		input = strings.NewReader(form.Encode())
	}
	response, err := a.adminJavaRequest(r, id, method, path, input)
	if err != nil {
		fail(w, 502, "legacy_unavailable", "游戏存档服务暂时不可用，请刷新存档和备份列表后核对操作结果。")
		return nil, false
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		switch response.StatusCode {
		case http.StatusNotFound:
			if backup {
				fail(w, 404, "backup_not_found", "没有找到该账号的备份。")
			} else {
				fail(w, 409, "save_not_started", "该账号尚无游戏存档。")
			}
		case http.StatusConflict:
			errorBody, _ := io.ReadAll(io.LimitReader(response.Body, 4097))
			var upstreamError struct {
				Error string `json:"error"`
			}
			if len(errorBody) <= 4096 && json.Unmarshal(errorBody, &upstreamError) == nil && upstreamError.Error == "active_battle" {
				fail(w, 409, "active_battle", "该玩家正在战斗或迷宫整备中，当前状态结算完成后可修改或恢复存档。")
			} else {
				fail(w, 409, "revision_conflict", "存档已更新，请刷新后重试。")
			}
		case http.StatusBadRequest, http.StatusUnprocessableEntity:
			fail(w, 422, "invalid_change", "该操作未通过游戏存档校验。")
		default:
			fail(w, 502, "legacy_unavailable", "游戏存档服务未确认操作结果，请刷新后核对。")
		}
		return nil, false
	}
	mediaType, _, typeErr := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if typeErr != nil || mediaType != "application/json" || response.ContentLength > adminDataResponseLimit {
		fail(w, 502, "legacy_invalid", "游戏存档响应格式或大小无效。")
		return nil, false
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, adminDataResponseLimit+1))
	if err != nil || len(body) > adminDataResponseLimit {
		fail(w, 502, "legacy_invalid", "游戏存档响应无法读取或超出大小限制。")
		return nil, false
	}
	return body, true
}

func validAdminDataSave(save adminDataSave) bool {
	if save.Version != 1 || !validAdminDataRevision(save.Revision) || save.ReadOnly == nil || len(save.Fields) < 1 || len(save.Fields) > adminDataMaxFields {
		return false
	}
	seen := make(map[string]bool, len(save.Fields))
	for _, field := range save.Fields {
		if !adminDataFieldKey.MatchString(field.Key) || seen[field.Key] ||
			field.EntityID != "" || field.EntityName != "" ||
			!validAdminDataText(field.Label, 1, 200, 600) || !validAdminDataText(field.Group, 1, 80, 240) ||
			!validAdminDataText(field.Help, 0, 500, 1500) {
			return false
		}
		seen[field.Key] = true
		switch field.Type {
		case "text":
			text, ok := adminDataString(field.Value)
			if !ok || !validAdminDataText(text, 0, 200, 600) || len(field.Catalog) != 0 {
				return false
			}
		case "integer":
			text, ok := adminDataString(field.Value)
			if !ok || len(field.Catalog) != 0 {
				return false
			}
			current, e1 := strconv.ParseInt(text, 10, 64)
			minimum, e2 := strconv.ParseInt(field.Min, 10, 64)
			maximum, e3 := strconv.ParseInt(field.Max, 10, 64)
			if e1 != nil || e2 != nil || e3 != nil || minimum < 0 || maximum < minimum || current < 0 ||
				strconv.FormatInt(current, 10) != text || strconv.FormatInt(minimum, 10) != field.Min || strconv.FormatInt(maximum, 10) != field.Max {
				return false
			}
		case "map":
			var values map[string]string
			if json.Unmarshal(field.Value, &values) != nil || values == nil || len(values) > 10000 || len(field.Catalog) < 1 || len(field.Catalog) > 10000 {
				return false
			}
			catalogIDs := make(map[string]bool, len(field.Catalog))
			for _, entry := range field.Catalog {
				if !adminDataCatalogID.MatchString(entry.ID) || catalogIDs[entry.ID] || !validAdminDataText(entry.Label, 1, 200, 600) || !validAdminDataRevision(entry.Max) || entry.Category != "" || entry.Quality != 0 {
					return false
				}
				catalogIDs[entry.ID] = true
			}
			for key, count := range values {
				if !adminDataCatalogID.MatchString(key) || !validAdminDataRevision(count) {
					return false
				}
			}
		default:
			return false
		}
	}
	return true
}

func (a *app) adminGetSave(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	id, ok := a.adminDataAccount(w, r, false)
	if !ok {
		return
	}
	body, ok := a.adminDataRequest(w, r, id, http.MethodGet, "/__admin/save", nil, false)
	if !ok {
		return
	}
	var save adminDataSave
	if !adminDecodeDataResponse(body, &save) || !adminDataHasFields(body, "version", "revision", "fields", "readOnly", "active") || !validAdminDataSave(save) {
		fail(w, 502, "legacy_invalid", "游戏存档字段目录无效。")
		return
	}
	if !adminLocalizeDataCatalog(&save) {
		fail(w, 500, "internal_error", "物资名称目录暂时不可用。")
		return
	}
	writeJSON(w, 200, save)
}

func adminLocalizeDataCatalog(save *adminDataSave) bool {
	data, err := adminAssets.ReadFile("admin/mail_catalog_names.json")
	if err != nil {
		return false
	}
	var names map[string]string
	if json.Unmarshal(data, &names) != nil {
		return false
	}
	metadataBytes, err := adminAssets.ReadFile("admin/catalog_metadata.json")
	if err != nil {
		return false
	}
	var metadata struct {
		SchemaVersion int `json:"schemaVersion"`
		Servants      map[string]struct {
			Name string `json:"name"`
		} `json:"servants"`
		Items map[string]struct {
			Category string `json:"category"`
			Quality  int    `json:"quality"`
		} `json:"items"`
		Equips map[string]struct {
			Category string `json:"category"`
			Quality  int    `json:"quality"`
		} `json:"equips"`
	}
	if json.Unmarshal(metadataBytes, &metadata) != nil || metadata.SchemaVersion != 1 || metadata.Servants == nil || metadata.Items == nil || metadata.Equips == nil {
		return false
	}
	for i := range save.Fields {
		field := &save.Fields[i]
		if strings.HasPrefix(field.Key, "servants.") {
			parts := strings.Split(field.Key, ".")
			if len(parts) == 3 && adminDataCatalogID.MatchString(parts[1]) {
				field.EntityID = parts[1]
				if name := metadata.Servants[parts[1]].Name; validAdminDataText(name, 1, 150, 450) {
					field.EntityName = name
					if _, suffix, found := strings.Cut(field.Label, " · "); found {
						field.Label = name + " (" + parts[1] + ") · " + suffix
					}
				}
			}
		}
		kind := ""
		switch field.Key {
		case "items":
			kind = "3:"
		case "equips":
			kind = "2:"
		default:
			continue
		}
		for j := range field.Catalog {
			entry := &field.Catalog[j]
			if name := names[kind+entry.ID]; validAdminDataText(name, 1, 150, 450) {
				entry.Label = name + " (" + entry.ID + ")"
			}
			resourceMetadata := metadata.Items[entry.ID]
			if field.Key == "equips" {
				resourceMetadata = metadata.Equips[entry.ID]
			}
			if validAdminDataText(resourceMetadata.Category, 1, 80, 240) {
				entry.Category = resourceMetadata.Category
			}
			if resourceMetadata.Quality >= 1 && resourceMetadata.Quality <= 5 {
				entry.Quality = resourceMetadata.Quality
			}
		}
	}
	return true
}

// Preview labels use the same display catalog as the editor. Keys and exact
// before/after strings stay unchanged after the upstream response is validated.
func adminLocalizeDataChanges(changes []adminDataChange) bool {
	save := adminDataSave{Fields: make([]adminDataField, len(changes))}
	for i, change := range changes {
		field := adminDataField{Key: change.Key, Label: change.Label}
		parts := strings.Split(change.Key, ".")
		if len(parts) == 2 && (parts[0] == "items" || parts[0] == "equips") {
			field.Key = parts[0]
			field.Catalog = []adminDataCatalogEntry{{ID: parts[1], Label: change.Label}}
		}
		save.Fields[i] = field
	}
	if !adminLocalizeDataCatalog(&save) {
		return false
	}
	for i, field := range save.Fields {
		changes[i].Label = field.Label
		if len(field.Catalog) == 1 {
			changes[i].Label = field.Catalog[0].Label
		}
	}
	return true
}

func (a *app) adminPreviewSave(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	a.adminChangeSave(w, r, true)
}

func (a *app) adminSaveData(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	a.adminChangeSave(w, r, false)
}

func (a *app) adminChangeSave(w http.ResponseWriter, r *http.Request, preview bool) {
	id, ok := a.adminDataAccount(w, r, false)
	if !ok {
		return
	}
	var input adminDataInput
	if !decodeAdminData(w, r, &input) {
		return
	}
	if !validAdminDataOperation(input.ExpectedRevision, input.Reason) || len(input.Changes) < 1 || len(input.Changes) > adminDataMaxChanges {
		fail(w, 400, "invalid_request", "版本、操作原因或修改字段数量无效。")
		return
	}
	flattened := make(map[string]string)
	for key, value := range input.Changes {
		if !adminDataFieldKey.MatchString(key) {
			fail(w, 400, "invalid_request", "修改字段或内容无效；数字请使用十进制字符串。")
			return
		}
		text, isString := adminDataString(value)
		if isString {
			if !validAdminDataText(text, 0, 200, 600) {
				fail(w, 400, "invalid_request", "修改字段内容无效。")
				return
			}
			if _, duplicate := flattened[key]; duplicate {
				fail(w, 400, "invalid_request", "同一数据项不能重复修改。")
				return
			}
			flattened[key] = text
		} else {
			var counts map[string]string
			if (key != "items" && key != "equips") || json.Unmarshal(value, &counts) != nil || len(counts) < 1 || len(counts) > adminDataMaxResourceChanges {
				fail(w, 400, "invalid_request", "道具和装备应按目录编号提交数量字符串。")
				return
			}
			for entryID, count := range counts {
				if !adminDataCatalogID.MatchString(entryID) || !validAdminDataRevision(count) {
					fail(w, 400, "invalid_request", "道具或装备编号与数量无效。")
					return
				}
				flatKey := key + "." + entryID
				if _, duplicate := flattened[flatKey]; duplicate {
					fail(w, 400, "invalid_request", "同一道具或装备不能重复修改。")
					return
				}
				flattened[flatKey] = count
			}
		}
	}
	if len(flattened) > adminDataMaxValueChanges {
		fail(w, 400, "invalid_request", "一次修改的数据项过多，请分批处理。")
		return
	}
	changes, _ := json.Marshal(input.Changes)
	if len(changes) > 262144 {
		fail(w, 413, "request_too_large", "存档修改内容过长，请分批处理。")
		return
	}
	form := url.Values{"expectedRevision": {input.ExpectedRevision}, "reason": {input.Reason}, "changes": {string(changes)}}
	path := "/__admin/save/patch"
	if preview {
		path = "/__admin/save/preview"
	}
	body, ok := a.adminDataRequest(w, r, id, http.MethodPost, path, form, false)
	if !ok {
		return
	}
	if preview {
		var result adminDataPreview
		if !adminDecodeDataResponse(body, &result) || !adminDataHasFields(body, "revision", "changes", "changeCount") || result.Changes == nil || result.Revision != input.ExpectedRevision || result.ChangeCount < 0 ||
			result.ChangeCount > len(flattened) || len(result.Changes) != result.ChangeCount {
			fail(w, 502, "legacy_invalid", "存档服务返回了无效的预览结果。")
			return
		}
		seen := make(map[string]bool, len(result.Changes))
		for _, change := range result.Changes {
			requested, exists := flattened[change.Key]
			if !exists || seen[change.Key] || change.After != requested || change.Before == change.After ||
				!validAdminDataText(change.Label, 1, 200, 600) || !validAdminDataText(change.Before, 0, 200, 600) {
				fail(w, 502, "legacy_invalid", "存档服务返回了无效的修改字段。")
				return
			}
			seen[change.Key] = true
		}
		if !adminLocalizeDataChanges(result.Changes) {
			fail(w, 500, "internal_error", "物资名称目录暂时不可用。")
			return
		}
		writeJSON(w, 200, result)
		return
	}
	var result adminDataPatch
	expected, _ := strconv.ParseUint(input.ExpectedRevision, 10, 63)
	if !adminDecodeDataResponse(body, &result) || !adminDataHasFields(body, "revision", "backupId", "changeCount") || !validAdminDataRevision(result.Revision) || result.ChangeCount < 0 || result.ChangeCount > len(flattened) ||
		(result.ChangeCount == 0 && (result.Revision != input.ExpectedRevision || result.BackupID != "")) ||
		(result.ChangeCount > 0 && (expected == uint64(1<<63-1) || result.Revision != strconv.FormatUint(expected+1, 10) || !adminBackupID.MatchString(result.BackupID))) {
		fail(w, 502, "legacy_invalid", "存档服务未正确确认保存结果，请刷新存档与备份后核对。")
		return
	}
	writeJSON(w, 200, result)
}

func validAdminBackup(item adminBackupItem) bool {
	return adminBackupID.MatchString(item.ID) && item.CreatedAt > 0 && validAdminDataRevision(item.Revision) &&
		validAdminDataText(item.Reason, 1, 200, 512) && validAdminDataText(item.Kind, 1, 40, 80) &&
		adminSnapshotSHA.MatchString(item.SHA256) && item.Bytes > 0 && item.Bytes <= adminDataResponseLimit
}

func (a *app) adminListBackups(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	id, ok := a.adminDataAccount(w, r, false)
	if !ok {
		return
	}
	body, ok := a.adminDataRequest(w, r, id, http.MethodGet, "/__admin/backups", nil, false)
	if !ok {
		return
	}
	var list adminBackupList
	if !adminDecodeDataResponse(body, &list) || list.Items == nil || len(list.Items) > 10000 {
		fail(w, 502, "legacy_invalid", "存档备份列表格式无效。")
		return
	}
	seen := make(map[string]bool, len(list.Items))
	for _, item := range list.Items {
		if !validAdminBackup(item) || seen[item.ID] {
			fail(w, 502, "legacy_invalid", "存档备份信息无效。")
			return
		}
		seen[item.ID] = true
	}
	writeJSON(w, 200, list)
}

func (a *app) adminCreateBackup(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	id, ok := a.adminDataAccount(w, r, false)
	if !ok {
		return
	}
	var input adminBackupInput
	if !decodeAdminData(w, r, &input) {
		return
	}
	if !validAdminDataOperation(input.ExpectedRevision, input.Reason) {
		fail(w, 400, "invalid_request", "备份版本或操作原因无效。")
		return
	}
	form := url.Values{"expectedRevision": {input.ExpectedRevision}, "reason": {input.Reason}}
	body, ok := a.adminDataRequest(w, r, id, http.MethodPost, "/__admin/backups/create", form, false)
	if !ok {
		return
	}
	var result adminBackupCreated
	if !adminDecodeDataResponse(body, &result) || !validAdminBackup(result.Backup) || result.Backup.Revision != input.ExpectedRevision || result.Backup.Reason != input.Reason {
		fail(w, 502, "legacy_invalid", "存档服务未正确确认备份信息。")
		return
	}
	writeJSON(w, 200, result)
}

func (a *app) adminDownloadBackup(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	id, ok := a.adminDataAccount(w, r, true)
	if !ok {
		return
	}
	backupID := r.PathValue("backup")
	body, ok := a.adminDataRequest(w, r, id, http.MethodPost, "/__admin/backups/read", url.Values{"backupId": {backupID}}, true)
	if !ok {
		return
	}
	var object map[string]json.RawMessage
	if !validAdminDataJSON(body, true) || json.Unmarshal(body, &object) != nil || object == nil {
		fail(w, 502, "legacy_invalid", "存档备份内容无效。")
		return
	}
	// Do not decode and re-encode snapshots: their exact bytes and large integer
	// values must survive the download unchanged.
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Content-Disposition", `attachment; filename="witchweapon-`+id+"-"+backupID+`.json"`)
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

func (a *app) adminPreviewBackup(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	id, ok := a.adminDataAccount(w, r, true)
	if !ok {
		return
	}
	var input adminBackupInput
	if !decodeAdminData(w, r, &input) {
		return
	}
	if !validAdminDataOperation(input.ExpectedRevision, input.Reason) {
		fail(w, 400, "invalid_request", "恢复预览版本或操作原因无效。")
		return
	}
	form := url.Values{"expectedRevision": {input.ExpectedRevision}, "reason": {input.Reason}, "backupId": {r.PathValue("backup")}}
	body, ok := a.adminDataRequest(w, r, id, http.MethodPost, "/__admin/backups/preview", form, true)
	if !ok {
		return
	}
	var result adminBackupPreview
	if !adminDecodeDataResponse(body, &result) || !adminDataHasFields(body, "revision", "changes", "changeCount") || result.Revision != input.ExpectedRevision || result.Changes == nil ||
		len(result.Changes) > adminDataMaxFields || result.ChangeCount != len(result.Changes) || len(result.RetainedFields) > adminDataMaxFields {
		fail(w, 502, "legacy_invalid", "存档服务返回了无效的恢复预览。")
		return
	}
	seen := make(map[string]bool, len(result.Changes))
	for _, change := range result.Changes {
		if !adminDataFieldKey.MatchString(change.Key) || seen[change.Key] || change.Before == change.After ||
			!validAdminDataText(change.Label, 1, 200, 600) || !validAdminDataText(change.Before, 0, 200, 600) || !validAdminDataText(change.After, 0, 200, 600) {
			fail(w, 502, "legacy_invalid", "恢复预览字段无效。")
			return
		}
		seen[change.Key] = true
	}
	for _, key := range result.RetainedFields {
		if !adminDataFieldKey.MatchString(key) {
			fail(w, 502, "legacy_invalid", "恢复预览保留字段无效。")
			return
		}
	}
	if !adminLocalizeDataChanges(result.Changes) {
		fail(w, 500, "internal_error", "物资名称目录暂时不可用。")
		return
	}
	writeJSON(w, 200, result)
}

func (a *app) adminRestoreBackup(w http.ResponseWriter, r *http.Request, _ [32]byte, _ time.Time) {
	id, ok := a.adminDataAccount(w, r, true)
	if !ok {
		return
	}
	var input adminBackupInput
	if !decodeAdminData(w, r, &input) {
		return
	}
	if !validAdminDataOperation(input.ExpectedRevision, input.Reason) {
		fail(w, 400, "invalid_request", "恢复版本或操作原因无效。")
		return
	}
	backupID := r.PathValue("backup")
	form := url.Values{"expectedRevision": {input.ExpectedRevision}, "reason": {input.Reason}, "backupId": {backupID}}
	body, ok := a.adminDataRequest(w, r, id, http.MethodPost, "/__admin/backups/restore", form, true)
	if !ok {
		return
	}
	var result adminBackupRestored
	expected, _ := strconv.ParseUint(input.ExpectedRevision, 10, 63)
	if !adminDecodeDataResponse(body, &result) || !validAdminDataRevision(result.Revision) || result.RestoredFields == nil || result.RestoredFrom != backupID ||
		(len(result.RestoredFields) == 0 && (result.Revision != input.ExpectedRevision || result.BackupID != "")) ||
		(len(result.RestoredFields) > 0 && (expected == uint64(1<<63-1) || result.Revision != strconv.FormatUint(expected+1, 10) || !adminBackupID.MatchString(result.BackupID) || result.BackupID == backupID)) {
		fail(w, 502, "legacy_invalid", "存档服务未正确确认恢复结果，请刷新存档与备份后核对。")
		return
	}
	for _, keys := range [][]string{result.RestoredFields, result.RetainedFields} {
		if len(keys) > adminDataMaxFields {
			fail(w, 502, "legacy_invalid", "恢复字段列表超出大小限制。")
			return
		}
		for _, key := range keys {
			if !adminDataFieldKey.MatchString(key) {
				fail(w, 502, "legacy_invalid", "恢复字段列表无效。")
				return
			}
		}
	}
	writeJSON(w, 200, result)
}
