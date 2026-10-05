package main

import "testing"

func TestAdminCatalogMetadataPreservesAllowedEntriesAndLimits(t *testing.T) {
	save := adminDataSave{Fields: []adminDataField{
		{Key: "servants.10010301.level", Label: "魔女 10010301 · 等级", Value: []byte(`"5"`)},
		{Key: "servants.99999999.level", Label: "魔女 99999999 · 等级", Value: []byte(`"6"`)},
		{Key: "items", Catalog: []adminDataCatalogEntry{{ID: "40130001", Label: "道具 40130001", Max: "321"}, {ID: "1411001", Label: "保持未知类型", Max: "12"}}},
		{Key: "equips", Catalog: []adminDataCatalogEntry{{ID: "1411001", Label: "装备 1411001", Max: "98"}}},
	}}
	if !adminLocalizeDataCatalog(&save) {
		t.Fatal("metadata could not be loaded")
	}
	if save.Fields[0].EntityID != "10010301" || save.Fields[0].EntityName != "薇拉" || save.Fields[0].Label != "薇拉 (10010301) · 等级" || string(save.Fields[0].Value) != `"5"` {
		t.Fatal("servant identity was not localized without altering the value")
	}
	if save.Fields[1].EntityID != "99999999" || save.Fields[1].EntityName != "" || save.Fields[1].Label != "魔女 99999999 · 等级" {
		t.Fatal("unknown servant acquired a guessed name")
	}
	item, equip, unknown := save.Fields[2].Catalog[0], save.Fields[3].Catalog[0], save.Fields[2].Catalog[1]
	if len(save.Fields[2].Catalog) != 2 || len(save.Fields[3].Catalog) != 1 || item.ID != "40130001" || item.Max != "321" || item.Category != "魔女材料" || item.Quality != 3 || equip.Max != "98" || equip.Category != "魔女装备" || equip.Quality != 1 {
		t.Fatal("metadata altered legal IDs, limits or original item qualities")
	}
	if unknown.Label != "保持未知类型" || unknown.Category != "" || unknown.Quality != 0 {
		t.Fatal("metadata crossed inventory types")
	}
}

func TestAdminChangeLabelsLocalizeWithoutChangingDiff(t *testing.T) {
	changes := []adminDataChange{
		{Key: "servants.10010301.level", Label: "魔女 10010301 · 等级", Before: "5", After: "6"},
		{Key: "items.40130001", Label: "道具 40130001", Before: "9007199254740993", After: "2"},
		{Key: "equips.1411001", Label: "装备 1411001", Before: "0", After: "3"},
		{Key: "gold", Label: "金币", Before: "123", After: "456"},
	}
	if !adminLocalizeDataChanges(changes) {
		t.Fatal("change metadata could not be loaded")
	}
	if changes[0].Label != "薇拉 (10010301) · 等级" || changes[0].Key != "servants.10010301.level" || changes[0].Before != "5" || changes[0].After != "6" ||
		changes[1].Label != "旧神印记 (40130001)" || changes[1].Before != "9007199254740993" || changes[1].After != "2" ||
		changes[2].Label != "剑玉 (1411001)" || changes[3].Label != "金币" {
		t.Fatal("localization changed diff data or crossed resource types")
	}
}
