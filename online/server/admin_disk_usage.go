package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"time"
	"unicode/utf8"
)

const (
	adminDiskUsageMaxSize    = 16 * 1024
	adminDiskUsageRefresh    = 300
	adminDiskUsageMaxAge     = 15 * time.Minute
	adminDiskUsageFutureSkew = time.Minute
	adminDiskUsagePublishLag = 2 * time.Minute
	adminDiskUsageMaxInteger = uint64(1<<53 - 1)
)

type adminDiskUsageRaw struct {
	contents   []byte
	modifiedAt time.Time
	err        error
}

type adminDiskUsageItem struct {
	ID             string  `json:"id"`
	Label          string  `json:"label"`
	Available      bool    `json:"available"`
	Status         string  `json:"status"`
	AllocatedBytes *uint64 `json:"allocatedBytes"`
	FileCount      *uint64 `json:"fileCount"`
	Detail         string  `json:"detail"`
}

type adminDiskUsageBreakdown struct {
	Available               bool                 `json:"available"`
	Status                  string               `json:"status"`
	SampledAt               *time.Time           `json:"sampledAt"`
	RefreshIntervalSeconds  int                  `json:"refreshIntervalSeconds"`
	AllocatedBytes          *uint64              `json:"allocatedBytes"`
	ConfirmedAllocatedBytes *uint64              `json:"confirmedAllocatedBytes"`
	Items                   []adminDiskUsageItem `json:"items"`
}

var adminDiskUsageCategories = [...]struct{ id, label, detail string }{
	{"programs", "服务程序", "网关、游戏、聊天及热更新服务程序，按实际分配空间统计。"},
	{"runtime", "运行与维护环境", "Java 专用运行环境与游戏 HTTPS 证书维护工具。"},
	{"resources", "游戏资源", "游戏服务使用的资源包和基础配置文件。"},
	{"updates", "热更新资源", "客户端使用的热更新资源。"},
	{"player_data", "账号与玩家存档", "游戏账号、玩家存档与聊天持久数据。"},
	{"admin_data", "管理备份与邮件记录", "管理备份、审计与邮件任务记录。"},
	{"recovery", "发布与恢复备份", "服务器发布和恢复使用的备份。"},
	{"logs", "专用访问日志", "游戏及管理入口的专用访问日志；系统共享日志未计入。"},
}

type adminDiskUsageSnapshotItem struct {
	ID             string  `json:"id"`
	Status         string  `json:"status"`
	AllocatedBytes *uint64 `json:"allocatedBytes"`
	FileCount      *uint64 `json:"fileCount"`
}

type adminDiskUsageSnapshot struct {
	SchemaVersion           int                          `json:"schemaVersion"`
	SampledAt               time.Time                    `json:"sampledAt"`
	RefreshIntervalSeconds  int                          `json:"refreshIntervalSeconds"`
	Status                  string                       `json:"status"`
	AllocatedBytes          *uint64                      `json:"allocatedBytes"`
	ConfirmedAllocatedBytes *uint64                      `json:"confirmedAllocatedBytes"`
	Items                   []adminDiskUsageSnapshotItem `json:"items"`
}

func adminDiskUsageUnavailable(status string) adminDiskUsageBreakdown {
	result := adminDiskUsageBreakdown{Status: status, RefreshIntervalSeconds: adminDiskUsageRefresh, Items: make([]adminDiskUsageItem, 0, len(adminDiskUsageCategories))}
	for _, category := range adminDiskUsageCategories {
		result.Items = append(result.Items, adminDiskUsageItem{ID: category.id, Label: category.label, Status: "unavailable", Detail: category.detail + " 此分类暂时无法完成统计。"})
	}
	return result
}

func parseAdminDiskUsage(raw adminDiskUsageRaw, now time.Time) adminDiskUsageBreakdown {
	if raw.err != nil {
		status := "unavailable"
		if errors.Is(raw.err, errAdminMonitorUnsupported) {
			status = "unsupported"
		}
		return adminDiskUsageUnavailable(status)
	}
	if len(raw.contents) == 0 || len(raw.contents) > adminDiskUsageMaxSize || !utf8.Valid(raw.contents) || !adminDiskUsageUniqueJSON(raw.contents) {
		return adminDiskUsageUnavailable("unavailable")
	}
	// Required fields are checked case-sensitively. encoding/json by itself
	// accepts duplicate keys and case-insensitive struct field names.
	var top map[string]json.RawMessage
	if json.Unmarshal(raw.contents, &top) != nil || !adminDiskUsageExactKeys(top, "schemaVersion", "sampledAt", "refreshIntervalSeconds", "status", "allocatedBytes", "confirmedAllocatedBytes", "items") {
		return adminDiskUsageUnavailable("unavailable")
	}
	var items []map[string]json.RawMessage
	if json.Unmarshal(top["items"], &items) != nil || len(items) != len(adminDiskUsageCategories) {
		return adminDiskUsageUnavailable("unavailable")
	}
	for _, item := range items {
		if !adminDiskUsageExactKeys(item, "id", "status", "allocatedBytes", "fileCount") {
			return adminDiskUsageUnavailable("unavailable")
		}
	}
	var snapshot adminDiskUsageSnapshot
	decoder := json.NewDecoder(bytes.NewReader(raw.contents))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&snapshot) != nil || decoder.Decode(new(any)) != io.EOF || snapshot.SchemaVersion != 1 || snapshot.RefreshIntervalSeconds != adminDiskUsageRefresh || snapshot.SampledAt.IsZero() || raw.modifiedAt.IsZero() || snapshot.Status != "ok" && snapshot.Status != "partial" {
		return adminDiskUsageUnavailable("unavailable")
	}
	if snapshot.SampledAt.After(now.Add(adminDiskUsageFutureSkew)) || raw.modifiedAt.After(now.Add(adminDiskUsageFutureSkew)) || snapshot.SampledAt.Sub(raw.modifiedAt) > adminDiskUsagePublishLag || raw.modifiedAt.Sub(snapshot.SampledAt) > adminDiskUsagePublishLag {
		return adminDiskUsageUnavailable("unavailable")
	}
	byID := make(map[string]adminDiskUsageSnapshotItem, len(snapshot.Items))
	var sum uint64
	complete, hasConfirmed := true, false
	for _, item := range snapshot.Items {
		known := false
		for _, category := range adminDiskUsageCategories {
			if item.ID == category.id {
				known = true
				break
			}
		}
		if _, duplicate := byID[item.ID]; !known || duplicate || item.Status != "ok" && item.Status != "partial" && item.Status != "unavailable" {
			return adminDiskUsageUnavailable("unavailable")
		}
		byID[item.ID] = item
		if item.Status == "unavailable" {
			if item.AllocatedBytes != nil || item.FileCount != nil {
				return adminDiskUsageUnavailable("unavailable")
			}
			complete = false
			continue
		}
		if item.AllocatedBytes == nil || item.FileCount == nil || *item.AllocatedBytes > adminDiskUsageMaxInteger || *item.FileCount > adminDiskUsageMaxInteger || *item.AllocatedBytes > adminDiskUsageMaxInteger-sum {
			return adminDiskUsageUnavailable("unavailable")
		}
		sum += *item.AllocatedBytes
		hasConfirmed = true
		complete = complete && item.Status == "ok"
	}
	if snapshot.ConfirmedAllocatedBytes == nil || *snapshot.ConfirmedAllocatedBytes != sum || complete && (snapshot.Status != "ok" || snapshot.AllocatedBytes == nil || *snapshot.AllocatedBytes != sum) || !complete && (snapshot.Status != "partial" || snapshot.AllocatedBytes != nil) {
		return adminDiskUsageUnavailable("unavailable")
	}
	result := adminDiskUsageUnavailable(snapshot.Status)
	sampledAt := snapshot.SampledAt.UTC()
	result.SampledAt = &sampledAt
	result.Available = hasConfirmed
	result.AllocatedBytes, result.ConfirmedAllocatedBytes = snapshot.AllocatedBytes, snapshot.ConfirmedAllocatedBytes
	for index, category := range adminDiskUsageCategories {
		item := byID[category.id]
		result.Items[index].Status = item.Status
		result.Items[index].Available = item.Status != "unavailable"
		result.Items[index].AllocatedBytes, result.Items[index].FileCount = item.AllocatedBytes, item.FileCount
		result.Items[index].Detail = category.detail
		if item.Status == "partial" {
			result.Items[index].Detail += " 此分类统计不完整，当前数值仅为已确认下限。"
		} else if item.Status == "unavailable" {
			result.Items[index].Detail += " 此分类暂时无法完成统计。"
		}
	}
	if !hasConfirmed {
		result.Status = "unavailable"
		result.ConfirmedAllocatedBytes = nil
	}
	if now.Sub(sampledAt) > adminDiskUsageMaxAge || now.Sub(raw.modifiedAt) > adminDiskUsageMaxAge {
		result.Available, result.Status = false, "stale"
	}
	return result
}

func adminDiskUsageExactKeys(fields map[string]json.RawMessage, keys ...string) bool {
	if len(fields) != len(keys) {
		return false
	}
	for _, key := range keys {
		if _, exists := fields[key]; !exists {
			return false
		}
	}
	return true
}

func adminDiskUsageUniqueJSON(contents []byte) bool {
	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.UseNumber()
	if !adminDiskUsageJSONValue(decoder, 0) {
		return false
	}
	_, err := decoder.Token()
	return err == io.EOF
}

func adminDiskUsageJSONValue(decoder *json.Decoder, depth int) bool {
	if depth > 8 {
		return false
	}
	token, err := decoder.Token()
	if err != nil {
		return false
	}
	delimiter, compound := token.(json.Delim)
	if !compound {
		return true
	}
	switch delimiter {
	case '{':
		keys := make(map[string]bool)
		for decoder.More() {
			keyToken, err := decoder.Token()
			key, valid := keyToken.(string)
			if err != nil || !valid || keys[key] || len(keys) >= 16 {
				return false
			}
			keys[key] = true
			if !adminDiskUsageJSONValue(decoder, depth+1) {
				return false
			}
		}
		closing, err := decoder.Token()
		return err == nil && closing == json.Delim('}')
	case '[':
		count := 0
		for decoder.More() {
			count++
			if count > len(adminDiskUsageCategories) || !adminDiskUsageJSONValue(decoder, depth+1) {
				return false
			}
		}
		closing, err := decoder.Token()
		return err == nil && closing == json.Delim(']')
	}
	return false
}

func adminDiskUsageAlert(value adminDiskUsageBreakdown) *adminMonitorAlert {
	if value.Status == "ok" {
		return nil
	}
	detail := "游戏数据占用统计暂时不可用，请检查统计任务；根分区容量监控仍独立提供。"
	if value.Status == "partial" {
		detail = "部分游戏目录未完成统计；当前分类数值仅为已确认下限，完整合计暂不可用。"
	} else if value.Status == "stale" {
		detail = "游戏数据占用统计已超过 15 分钟未更新；旧明细仅供参考，请检查统计任务。"
	} else if value.Status == "unsupported" {
		detail = "当前系统不支持游戏数据占用统计；此功能用于 Linux 游戏服务器。"
	}
	return &adminMonitorAlert{"storage_inventory", "warning", "游戏数据占用统计异常", detail}
}
