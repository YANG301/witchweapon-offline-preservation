"use strict";

// 玩家数据和管理令牌均仅保留在当前页内存。
window.adminData = (() => {
  const model = { id: "", generation: 0, backupRequest: 0, data: null, liveData: null, liveReadAt: 0, liveIssue: false, dirty: new Map(), group: "", query: "", limit: 40, resourceModes: new Map(), resourceCategories: new Map(), resourceLimits: new Map(), selectedServant: "", servantLimit: 24, stageLimit: 24, stageMode: "all", busy: false, pending: null, restore: null, backups: [], timer: 0 };
  const node = (tag, className, text) => element(tag, className, text);
  const clone = (value) => value === undefined ? null : JSON.parse(JSON.stringify(value));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const base = () => `/admin/api/accounts/${encodeURIComponent(model.id)}`;
  const numeric = (field) => ["integer", "number", "long", "int"].includes(field.type);
  const pretty = (value) => typeof value === "object" && value !== null ? JSON.stringify(value, null, 2) : String(value ?? "—");
  const title = (field) => field.label || field.key;
  const currentValue = (field) => model.dirty.has(field.key) ? model.dirty.get(field.key) : field.value;
  const amount = (value) => value === undefined || value === null ? "0" : String(value);
  const resourceChanged = (field, values, id) => amount(values[id]) !== amount((field.value || {})[id]);
  const sameResources = (a, b) => [...new Set([...Object.keys(a || {}), ...Object.keys(b || {})])].every((id) => amount(a?.[id]) === amount(b?.[id]));
  const groupName = (field) => field.group || "其他";
  const fieldMatches = (field) => `${title(field)} ${field.key} ${groupName(field)} ${field.entityName || ""}`.toLowerCase().includes(model.query);
  const editable = (control) => { control.dataset.editControl = "true"; return control; };
  const reasonValue = (id) => {
    const value = $(id).value.trim();
    if (Array.from(value).length < 8 || Array.from(value).length > 200 || new TextEncoder().encode(value).length > 512 || /[\p{Cc}\p{Cf}]/u.test(value)) throw new Error("请填写 8–200 字、最多 512 字节的操作原因。");
    return value;
  };

  function writable() { return !!model.data && !!model.liveData && !model.data.active && !model.liveData.active && !model.liveIssue && !model.busy; }
  function controls() {
    const enabled = writable();
    $("data-preview").disabled = !enabled || model.dirty.size === 0;
    $("data-reset").disabled = model.busy || model.dirty.size === 0;
    $("backup-create").disabled = !model.data || model.busy;
    $("save-reload").disabled = model.busy;
    $("backup-reload").disabled = model.busy;
    $("data-commit").disabled = !enabled || !model.pending;
    $("restore-commit").disabled = !enabled || !model.restore || model.dirty.size > 0;
    $("data-reason").disabled = !enabled;
    $("backup-reason").disabled = !model.data || model.busy;
    $("restore-reason").disabled = !enabled || !model.restore;
    $("data-cancel").disabled = model.busy;
    $("restore-cancel").disabled = model.busy;
    $("save-dirty-count").textContent = model.dirty.size ? `${model.dirty.size} 项未保存` : "没有未保存的修改";
    // 战斗中的存档仍可查询、切换分类和浏览目录，仅锁定写入控件。
    for (const input of $("save-fields").querySelectorAll("[data-edit-control]")) input.disabled = !enabled;
    updateQuickEditLock(!enabled, model.liveData ? liveState().editing : "读取存档后确认");
  }

  function notice(message) { showMessage($("save-notice"), message); }
  function invalidatePreview() { model.pending = null; $("change-review").hidden = true; }
  function track(field, value) {
    if (field.type === "map" ? sameResources(value, field.value) : same(value, field.value)) model.dirty.delete(field.key);
    else model.dirty.set(field.key, clone(value));
    invalidatePreview();
    renderGroups();
    controls();
  }

  function catalogEntries(field) {
    if (Array.isArray(field.catalog)) return field.catalog.map((entry) => ({ id: String(entry.id), label: entry.label || entry.name || String(entry.id), max: entry.max, category: entry.category || "", quality: entry.quality }));
    return Object.entries(field.catalog || {}).map(([id, value]) => ({ id, label: typeof value === "object" ? value.label || value.name || id : String(value), max: value?.max, category: value?.category || "", quality: value?.quality }));
  }

  function section(titleText, description = "") {
    const result = node("section", "data-section");
    const heading = node("div", "data-section-heading"); heading.append(node("h3", "", titleText));
    if (description) heading.append(node("p", "input-help", description));
    result.append(heading); return result;
  }

  function moreControl(container, shown, total, noun, next) {
    if (shown >= total) return;
    const more = node("div", "field-more"); more.append(node("span", "", `已显示 ${shown} / ${total} ${noun}`));
    const button = node("button", "button button-secondary button-small", "显示更多"); button.type = "button";
    button.addEventListener("click", next); more.append(button); container.append(more);
  }

  function scalarField(field, labelText = title(field), onChange = () => {}, compact = false) {
    const card = node("div", `data-field simple-field${compact ? " compact-field" : ""}${field.type === "json" ? " data-field-wide" : ""}`);
    card.classList.toggle("changed", model.dirty.has(field.key));
    const label = node("label", "", labelText);
    const value = currentValue(field);
    const input = editable(node(field.type === "json" ? "textarea" : "input"));
    input.id = `data-field-${field.key}`; label.htmlFor = input.id;
    input.setAttribute("aria-label", title(field));
    if (field.type === "boolean") { input.type = "checkbox"; input.checked = value === true; }
    else { input.value = field.type === "json" ? JSON.stringify(value ?? {}, null, 2) : String(value ?? ""); if (numeric(field)) { input.type = "text"; input.inputMode = "numeric"; } }
    if (field.type === "json") { input.className = "json-editor"; input.spellcheck = false; }
    input.addEventListener("input", () => {
      const next = field.type === "boolean" ? input.checked : input.value;
      if (field.type === "json") {
        try { const parsed = JSON.parse(next); input.setCustomValidity(""); track(field, parsed); }
        catch { input.setCustomValidity("请输入完整有效的 JSON。"); model.dirty.set(field.key, { __invalidJSON: next }); invalidatePreview(); controls(); }
      } else track(field, next);
      card.classList.toggle("changed", model.dirty.has(field.key)); onChange();
    });
    card.append(label, input);
    if (field.min !== undefined && field.max !== undefined) card.append(node("small", "field-hint", `${field.min}–${field.max}`));
    const technical = node("details", "field-technical"); technical.append(node("summary", "", "字段说明"));
    if (field.help) technical.append(node("p", "input-help", field.help));
    technical.append(node("code", "field-key", field.key)); card.append(technical);
    return card;
  }

  function resourceInfo(field) {
    const entries = catalogEntries(field);
    const byId = new Map(entries.map((entry) => [entry.id, entry]));
    const value = currentValue(field) || {};
    const ids = [...new Set([...byId.keys(), ...Object.keys(field.value || {}), ...Object.keys(value)])];
    ids.sort((a, b) => a.localeCompare(b, "zh-CN", { numeric: true }));
    const matched = ids.filter((id) => !model.query || fieldMatches(field) || `${id} ${byId.get(id)?.label || ""} ${byId.get(id)?.category || ""}`.toLowerCase().includes(model.query));
    return { entries, byId, value, ids, matched };
  }

  function renderMap(field, container, info) {
    const { entries, byId, value, matched } = info;
    const data = clone(value);
    const mode = model.resourceModes.get(field.key) || (model.query ? "all" : "owned");
    const category = model.resourceCategories.get(field.key) || "";
    const limit = model.resourceLimits.get(field.key) || 24;
    const mapWrap = node("div", "resource-workbench");
    const toolbar = node("div", "resource-toolbar");
    const filters = node("div", "resource-filters"); filters.setAttribute("aria-label", `${groupName(field)}展示范围`);
    const categories = [...new Set(entries.map((entry) => entry.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
    const withinCategory = (id) => !category || byId.get(id)?.category === category;
    const inMode = (id, viewMode) => viewMode === "all" || viewMode === "changed" && resourceChanged(field, data, id) || viewMode === "owned" && amount(data[id]) !== "0";
    const countFor = (viewMode) => matched.filter((id) => withinCategory(id) && inMode(id, viewMode)).length;
    const filterButtons = new Map();
    for (const [key, label] of [["owned", "已拥有"], ["all", "全部目录"], ["changed", "已修改"]]) {
      const button = node("button", `resource-filter${mode === key ? " active" : ""}`, `${label} ${countFor(key)}`);
      button.type = "button"; button.setAttribute("aria-pressed", String(mode === key));
      button.addEventListener("click", () => { model.resourceModes.set(field.key, key); model.resourceLimits.set(field.key, 24); renderFields(); });
      filterButtons.set(key, { button, label }); filters.append(button);
    }
    toolbar.append(filters);
    if (categories.length > 1) {
      const select = node("select", "resource-category"); select.setAttribute("aria-label", `${groupName(field)}种类`);
      const all = node("option", "", "全部种类"); all.value = ""; select.append(all);
      for (const name of categories) { const option = node("option", "", name); option.value = name; select.append(option); }
      select.value = category;
      select.addEventListener("change", () => { model.resourceCategories.set(field.key, select.value); model.resourceLimits.set(field.key, 24); renderFields(); });
      toolbar.append(select);
    }
    mapWrap.append(toolbar);
    const ids = matched.filter((id) => withinCategory(id) && inMode(id, mode));
    const rows = node("div", "resource-grid");
    const updateTotals = () => { for (const [key, { button, label }] of filterButtons) button.textContent = `${label} ${countFor(key)}`; };
    const setAmount = (id, next) => {
      if (next === "0" && !Object.hasOwn(field.value || {}, id)) delete data[id]; else data[id] = next;
      track(field, data); updateTotals();
    };
    for (const id of ids.slice(0, limit)) {
      const entry = byId.get(id) || { id, label: `${groupName(field)} ${id}` };
      const name = entry.label.endsWith(` (${id})`) ? entry.label.slice(0, -(` (${id})`).length) : entry.label;
      const card = node("article", "resource-card"); card.dataset.resourceId = id; card.classList.toggle("changed", resourceChanged(field, data, id));
      if (Number.isInteger(entry.quality)) card.dataset.quality = String(entry.quality);
      const heading = node("div", "resource-heading");
      const symbol = node("span", "resource-symbol", name.replace(/\([^)]*\)/g, "").trim().slice(0, 1) || "物"); symbol.setAttribute("aria-hidden", "true");
      const identity = node("div", "resource-identity"); identity.append(node("h4", "resource-name", name), node("small", "resource-id", `ID ${id}`));
      heading.append(symbol, identity); card.append(heading);
      const tags = node("div", "resource-tags");
      if (entry.category) tags.append(node("span", "resource-category-tag", entry.category));
      if (Number.isInteger(entry.quality)) tags.append(node("span", "resource-quality", `品质 ${entry.quality}`));
      const badge = node("span", "resource-state"); tags.append(badge); card.append(tags);
      const cap = entry.max !== undefined ? entry.max : field.max;
      card.append(node("p", "resource-current", `当前持有 ${amount((field.value || {})[id])}${cap !== undefined ? ` · 上限 ${cap}` : ""}`));
      const editor = node("div", "resource-quantity");
      const label = node("label", "", "目标数量");
      const input = editable(node("input")); input.type = "text"; input.inputMode = "numeric"; input.value = amount(data[id]); input.id = `resource-${field.key}-${id}`; label.htmlFor = input.id;
      input.setAttribute("aria-label", `${name}目标数量`);
      if (cap !== undefined) input.title = `数量上限 ${cap}`;
      editor.append(label, input); card.append(editor);
      const action = editable(node("button", "button button-quiet button-small resource-action")); action.type = "button";
      const refreshCard = () => {
        const held = amount(data[id]) !== "0";
        const changed = resourceChanged(field, data, id);
        card.classList.toggle("changed", changed);
        badge.textContent = changed ? "待保存" : held ? "已持有" : "未持有";
        action.textContent = held ? "数量归零" : "加入背包草稿";
        action.setAttribute("aria-label", held ? `将${name}数量归零` : `将${name}加入背包草稿`);
      };
      input.addEventListener("input", () => { setAmount(id, input.value); refreshCard(); });
      action.addEventListener("click", () => { setAmount(id, amount(data[id]) !== "0" ? "0" : "1"); renderFields(); });
      refreshCard(); card.append(action); rows.append(card);
    }
    if (!ids.length) {
      const empty = node("div", "resource-empty");
      empty.append(node("p", "muted", mode === "changed" ? "此范围内没有已修改的资源。" : mode === "owned" ? "此范围内没有已拥有的资源。" : "没有匹配的资源。"));
      if (mode !== "all" && matched.length) {
        const browse = node("button", "button button-secondary button-small", "浏览全部目录"); browse.type = "button";
        browse.addEventListener("click", () => { model.resourceModes.set(field.key, "all"); renderFields(); }); empty.append(browse);
      }
      rows.append(empty);
    }
    mapWrap.append(rows);
    moreControl(mapWrap, Math.min(ids.length, limit), ids.length, "件资源", () => { model.resourceLimits.set(field.key, limit + 24); renderFields(); });
    if (!entries.length) {
      const add = node("div", "resource-manual-add");
      const idInput = editable(node("input")); idInput.type = "text"; idInput.inputMode = "numeric"; idInput.placeholder = "资源 ID"; idInput.setAttribute("aria-label", `${groupName(field)}资源 ID`);
      const button = editable(node("button", "button button-secondary button-small", "加入背包草稿")); button.type = "button";
      button.addEventListener("click", () => { const id = idInput.value.trim(); if (!/^[1-9][0-9]*$/.test(id)) { showMessage($("data-error"), "请填写有效资源 ID。"); return; } if (amount(data[id]) === "0") { setAmount(id, "1"); model.resourceModes.set(field.key, "owned"); renderFields(); } });
      add.append(idInput, button); mapWrap.append(add);
    }
    container.append(mapWrap); return ids.length;
  }

  function entities(fields, prefix) {
    const result = new Map();
    for (const field of fields) {
      const match = field.key.match(new RegExp(`^${prefix}\\.([1-9][0-9]*)\\.([^.]*)$`));
      if (!match) continue;
      if (!result.has(match[1])) result.set(match[1], { id: match[1], fields: [], bySuffix: new Map() });
      const entity = result.get(match[1]); entity.fields.push(field); entity.bySuffix.set(match[2], field);
    }
    return [...result.values()].sort((a, b) => a.id.localeCompare(b.id, "zh-CN", { numeric: true }));
  }

  function entityName(entity, noun) {
    const named = entity.fields.find((field) => field.entityName)?.entityName;
    if (named) return named;
    const first = title(entity.fields[0]).split(/\s*·\s*/)[0];
    return first || `${noun} ${entity.id}`;
  }

  function entityMatches(entity) { return !model.query || entity.fields.some(fieldMatches); }
  function entityChanged(entity) { return entity.fields.some((field) => model.dirty.has(field.key)); }
  function entityValue(entity, suffix) { const field = entity.bySuffix.get(suffix); return field ? String(currentValue(field) ?? "—") : "—"; }
  function attributeName(field) { return title(field).split(/\s*·\s*/).at(-1); }

  function savedNumber(value, min = 0, max = Number.MAX_SAFE_INTEGER, integer = true) {
    if (typeof value !== "number" && (typeof value !== "string" || !/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value))) return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= min && number <= max && (!integer || Number.isSafeInteger(number)) ? number : null;
  }
  function liveReadOnly() {
    const data = model.liveData?.readOnly;
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  }
  function liveState() {
    const readOnly = liveReadOnly();
    const round = savedNumber(readOnly.mazeRound, 1, 13);
    const prepared = savedNumber(readOnly.mazePreparedRound, 1, 12);
    const battle = typeof readOnly.active === "boolean" ? readOnly.active : null;
    const preparedLock = battle === false && round !== null && round <= 12 && prepared === round && readOnly.mazeRoundSettled === false;
    const locked = model.liveData?.active === true;
    const editing = model.liveIssue ? "状态失效，需重新读取" : locked ? preparedLock ? "迷宫整备锁定" : battle === true ? "战斗中锁定" : "已锁定，原因待确认" : model.liveData ? "可编辑" : "等待读取";
    return { readOnly, round, battle, locked, preparedLock, editing };
  }
  function mazeRoster(readOnly, key) {
    const values = readOnly[key];
    if (!Array.isArray(values) || values.length > 64) return null;
    const ids = values.map((value) => typeof value === "number" && Number.isSafeInteger(value) ? String(value) : typeof value === "string" ? value : "");
    return ids.every((id) => /^[1-9][0-9]{0,18}$/.test(id)) && new Set(ids).size === ids.length ? ids : null;
  }
  function resetMaze() {
    $("maze-state-panel").hidden = true; $("maze-state-panel").dataset.state = "unknown";
    $("maze-state-status").textContent = "等待读取"; $("maze-state-read-at").textContent = "—";
    $("maze-state-facts").replaceChildren(); $("maze-roster-list").replaceChildren(); $("maze-party-list").replaceChildren(); $("maze-energy-list").replaceChildren();
    $("maze-roster-count").textContent = "— / 12"; $("maze-party-count").textContent = "— / 4";
    $("maze-state-note").textContent = ""; $("maze-state-teams").open = false;
  }
  function renderMaze() {
    if (!model.liveData) { resetMaze(); return; }
    const live = liveState(), readOnly = live.readOnly;
    // Names and state come from the last server response, never from dirty growth inputs.
    const names = new Map(entities(model.liveData.fields, "servants").map((entity) => [entity.id, entityName(entity, "魔女")]));
    const name = (id) => names.get(id) || `魔女 ${id}`;
    const roster = mazeRoster(readOnly, "mazeRoster"), party = mazeRoster(readOnly, "mazeParty");
    const energyIds = Object.keys(readOnly).filter((key) => /^mazeEnergy_[1-9][0-9]{0,18}$/.test(key)).map((key) => key.slice("mazeEnergy_".length));
    const members = [...new Set([...(roster || []), ...(party || []), ...energyIds])].sort((a, b) => a.localeCompare(b, "zh-CN", { numeric: true }));
    const corpus = ["迷宫 楼层 挑战 名单 编队 出战 生命 血量 能量 魔力 整备 敌人 宝箱 结算 重置 maze", ...members.map((id) => `${id} ${name(id)}`), ...Object.keys(readOnly).filter((key) => key.startsWith("maze"))].join(" ").toLowerCase();
    const visible = (!model.group || model.group === "迷宫进度") && (!model.query || corpus.includes(model.query));
    $("maze-state-panel").hidden = !visible;
    if (!visible) return;
    $("maze-state-panel").dataset.state = model.liveIssue ? "stale" : live.locked ? "locked" : "saved";
    $("maze-state-status").textContent = model.liveIssue ? "上次状态 · 需更新" : live.locked ? live.editing : "已保存状态";
    $("maze-state-read-at").textContent = `${model.liveIssue ? "上次成功读取" : "服务器存档"} · 版本 ${model.liveData.revision} · ${new Date(model.liveReadAt).toLocaleTimeString("zh-CN", { hour12: false })}${model.liveIssue ? " · 旧值仅供参考" : " · 草稿不会影响此处"}`;
    const facts = $("maze-state-facts"); facts.replaceChildren();
    const add = (label, value) => { const item = node("div"); item.append(node("dt", "", label), node("dd", "", value)); facts.append(item); };
    const hp = savedNumber(readOnly.mazeHP, 0.01, 1, false);
    const roleLevel = savedNumber(readOnly.mazePreparedRoleLevel, 1, 100), enemyLevel = savedNumber(readOnly.mazePreparedEnemyLevel, 1, 105);
    const pending = savedNumber(readOnly.mazePendingBonus, 0, 12), lastBonus = savedNumber(readOnly.mazeLastBonusRound, 0, 12);
    const resetDay = savedNumber(readOnly.mazeResetDay, 0, 1000000), resetsUsed = savedNumber(readOnly.mazeResetsUsed, 0, 1000000000);
    add("当前楼层", mazeRoundValue(readOnly.mazeRound));
    add("实际战斗", live.battle === null ? "状态未确认" : live.battle ? "进行中" : "空闲");
    add("剩余生命", hp === null ? "—" : `${(hp * 100).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}%`);
    add("整备角色等级", roleLevel === null ? "—" : `Lv ${roleLevel}`);
    add("整备敌人等级", enemyLevel === null ? "—" : `Lv ${enemyLevel}`);
    add("本轮结算", typeof readOnly.mazeRoundSettled === "boolean" ? readOnly.mazeRoundSettled ? "已结算" : "未结算" : "—");
    add("待领取宝箱", pending === 0 ? "无待领取记录" : pending !== null && pending % 3 === 0 && live.round === pending + 1 ? `第 ${pending} 层宝箱` : "—");
    add("已领取宝箱记录", lastBonus === 0 ? "尚未领取" : lastBonus !== null && lastBonus % 3 === 0 ? `第 ${lastBonus} 层宝箱` : "—");
    const resetDate = resetDay === null ? "—" : new Date(resetDay * 86400000 - 28800000).toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai" });
    add("每日重置记录", `${resetDate} · 已用 ${resetsUsed === null ? "—" : nf.format(resetsUsed)} 次`);
    if (Object.hasOwn(readOnly, "mazePreparedRound")) add("整备楼层", mazeRoundValue(savedNumber(readOnly.mazePreparedRound, 1, 12)));
    if (Object.hasOwn(readOnly, "mazeCompletedRuns")) { const completed = savedNumber(readOnly.mazeCompletedRuns); add("累计完成轮数", completed === null ? "—" : nf.format(completed)); }
    if (Object.hasOwn(readOnly, "mazeSupplyBoxes")) { const boxes = savedNumber(readOnly.mazeSupplyBoxes); add("补给箱记录", boxes === null ? "—" : nf.format(boxes)); }
    function renderParty(key, ids, max) {
      const list = $(`maze-${key}-list`); list.replaceChildren();
      $(`maze-${key}-count`).textContent = ids === null ? `— / ${max}` : `${ids.length} / ${max}${ids.length > max ? " · 旧记录" : ""}`;
      if (ids === null) list.append(node("p", "maze-empty", "尚无可确认的名单记录"));
      else if (!ids.length) list.append(node("p", "maze-empty", "名单为空"));
      else for (const id of ids) { const member = node("div", "maze-member"); member.append(node("strong", "", name(id)), node("small", "", `ID ${id}`)); list.append(member); }
    }
    renderParty("roster", roster, 12); renderParty("party", party, 4);
    const energies = $("maze-energy-list"); energies.replaceChildren();
    for (const id of members.slice(0, 64)) {
      const energy = savedNumber(readOnly[`mazeEnergy_${id}`], 0, 1000, false);
      const card = node("div", "maze-energy-card"); card.append(node("strong", "", name(id)));
      card.append(node("span", "", energy === null ? "— / 1000" : `${energy.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} / 1000`));
      const meter = node("progress"); meter.max = 1000; meter.hidden = energy === null; meter.setAttribute("aria-label", `${name(id)}跨层魔女能量`); if (energy !== null) meter.value = energy; card.append(meter); energies.append(card);
    }
    if (!members.length) energies.append(node("p", "maze-empty", "尚无已保存的魔女能量记录"));
    else if (members.length > 64) energies.append(node("p", "maze-empty", `记录共 ${members.length} 位，当前显示前 64 位。完整记录可在只读数据中查询。`));
    let note = model.liveIssue ? "最近读取失败，以上旧状态仅供参考；重新读取成功前暂停编辑。" : live.battle === null ? "实际战斗状态未确认；编辑权限继续以服务器锁定标记为准。" : live.battle ? "玩家正在战斗，可查询和备份；当前不可修改或恢复。" : live.preparedLock ? "玩家已进入迷宫整备，本轮结算前不可修改或恢复；当前并未标记为实际战斗中。" : live.locked ? "服务器已锁定编辑，具体原因暂未确认；可查询和备份。" : "这里展示已保存的本轮状态；下方三个可编辑数字仅是累计挑战统计，修改它们不会推进楼层或重新发奖。";
    if (readOnly.mazeRosterLocked === false) note += " 挑战名单尚未确认。";
    if (party && party.length > 4) note += " 单场队伍为旧记录，超过现有 4 人上限；按存档原值展示。";
    note += " 每日重置仅显示记录日和已用次数，不推算今日剩余。";
    $("maze-state-note").textContent = note;
  }

  function validateData(data) {
    if (!data || typeof data.revision !== "string" || !Array.isArray(data.fields) || typeof data.active !== "boolean" || data.fields.some((field) => !field || typeof field.key !== "string")) throw new Error("存档数据格式无效。");
  }
  function updateLive(data) {
    validateData(data); model.liveData = data; model.liveReadAt = Date.now(); model.liveIssue = false;
    const live = liveState(), detail = state.detail;
    if (detail?.account?.id === model.id && detail.legacy?.available) {
      const current = detail.legacy.state;
      for (const field of data.fields) if (["name", "gold", "exp", "mazeWins", "mazeAttempts", "mazeStars"].includes(field.key)) current[field.key] = field.key === "name" ? field.value : Number(field.value);
      current.mazeRound = live.round; current.active = live.battle;
      if (current.roleCreated) {
        $("detail-name").textContent = current.name; $("detail-avatar").textContent = Array.from(current.name)[0];
        if (detail.legacy.role) detail.legacy.role.name = current.name;
      }
      const facts = { "金币": countValue(current.gold), "角色经验": countValue(current.exp), "迷宫胜场": countValue(current.mazeWins), "迷宫楼层": mazeRoundValue(live.round), "战斗状态": live.battle === null ? "状态未确认" : live.battle ? "进行中" : "空闲", "编辑状态": live.editing };
      for (const row of $("detail-facts").children) { const label = row.querySelector("dt")?.textContent; if (Object.hasOwn(facts, label)) row.querySelector("dd").textContent = facts[label]; }
    }
    $("save-readonly").textContent = JSON.stringify(data.readOnly || {}, null, 2);
    renderMaze(); controls();
  }
  function freshness() {
    const live = liveState();
    $("save-revision").textContent = !model.data ? "存档暂不可用" : model.liveIssue ? `存档版本 ${model.data.revision} · 读取失败，旧值参考` : model.liveData?.revision !== model.data.revision ? `编辑基准 ${model.data.revision} · 最新存档 ${model.liveData.revision} · ${live.editing}` : `存档版本 ${model.data.revision} · ${live.editing}`;
    $("save-read-at").textContent = model.liveReadAt ? `${model.liveIssue ? "上次成功读取" : "读取于"} ${new Date(model.liveReadAt).toLocaleTimeString("zh-CN", { hour12: false })}` : "尚未成功读取存档";
  }
  function lockNotice() {
    const live = liveState();
    return live.battle === true && live.locked ? "玩家正在战斗，可查询或备份；当前不可修改或恢复。" : live.preparedLock && live.locked ? "玩家已进入迷宫整备，可查询或备份；本轮结算前不可修改或恢复。" : live.locked ? "服务器已锁定编辑，具体原因暂未确认；可查询或备份。" : "";
  }

  function renderServants(list, container) {
    const browser = node("div", "servant-browser");
    const navigation = node("div", "servant-navigation");
    const choices = node("div", "servant-list"); choices.setAttribute("aria-label", "选择已拥有的魔女");
    let selected = list.find((entity) => entity.id === model.selectedServant);
    if (!selected) { selected = list[0]; model.selectedServant = selected.id; }
    const shown = list.slice(0, model.servantLimit);
    if (!shown.some((entity) => entity.id === selected.id)) shown.unshift(selected);
    const summary = (entity) => `等级 ${entityValue(entity, "level")} · ${entityValue(entity, "star")} 星 · 阶级 ${entityValue(entity, "rank")}`;
    const choiceRefs = new Map();
    for (const entity of shown) {
      const button = node("button", `servant-choice${entity.id === selected.id ? " active" : ""}${entityChanged(entity) ? " changed" : ""}`); button.type = "button";
      button.setAttribute("aria-pressed", String(entity.id === selected.id)); button.dataset.servantId = entity.id;
      const avatar = node("span", "servant-avatar", Array.from(entityName(entity, "魔女"))[0]); avatar.setAttribute("aria-hidden", "true");
      const identity = node("span", "servant-choice-info");
      const stats = node("small", "servant-summary", summary(entity));
      identity.append(node("strong", "", entityName(entity, "魔女")), stats, node("small", "servant-id", `ID ${entity.id}`));
      button.append(avatar, identity); choiceRefs.set(entity.id, { button, stats });
      button.addEventListener("click", () => { model.selectedServant = entity.id; renderFields(); }); choices.append(button);
    }
    navigation.append(choices);
    moreControl(navigation, shown.length, list.length, "位魔女", () => { model.servantLimit += 24; renderFields(); });
    const detail = node("article", "servant-detail"); detail.dataset.servantId = selected.id;
    const heading = node("div", "servant-detail-heading");
    const headingName = node("div"); headingName.append(node("h4", "", entityName(selected, "魔女")), node("small", "servant-id", `ID ${selected.id} · 已拥有`));
    const status = node("span", "detail-chip", entityChanged(selected) ? "有未保存的修改" : "当前存档"); heading.append(headingName, status); detail.append(heading);
    const stats = node("p", "servant-detail-stats", `${summary(selected)} · 武器 ${entityValue(selected, "weaponLevel")} 级`); detail.append(stats);
    const changed = () => {
      const ref = choiceRefs.get(selected.id); ref.stats.textContent = summary(selected); ref.button.classList.toggle("changed", entityChanged(selected));
      status.textContent = entityChanged(selected) ? "有未保存的修改" : "当前存档";
      stats.textContent = `${summary(selected)} · 武器 ${entityValue(selected, "weaponLevel")} 级`;
    };
    const assigned = new Set();
    for (const [name, suffixes] of [["基础成长", ["level", "exp", "rank", "star", "equipMask"]], ["武器成长", ["weaponLevel", "weaponExp"]], ["好感度", ["favorLevel", "favorExp"]], ["技能等级", ["skill1", "skill2", "skill3", "skill4", "skill5"]]]) {
      const partFields = suffixes.map((suffix) => selected.bySuffix.get(suffix)).filter(Boolean);
      if (!partFields.length) continue;
      const part = node("section", "servant-field-section"); part.append(node("h5", "", name));
      const grid = node("div", "data-fields-grid servant-fields-grid");
      for (const field of partFields) { assigned.add(field.key); grid.append(scalarField(field, attributeName(field), changed)); }
      part.append(grid); detail.append(part);
    }
    const remaining = selected.fields.filter((field) => !assigned.has(field.key));
    if (remaining.length) { const grid = node("div", "data-fields-grid"); for (const field of remaining) grid.append(scalarField(field, attributeName(field), changed)); detail.append(grid); }
    browser.append(navigation, detail); container.append(browser);
  }

  function renderStages(list, container) {
    const filters = node("div", "resource-filters stage-filters"); filters.setAttribute("aria-label", "关卡进度展示范围");
    const cleared = (entity) => /^[1-9][0-9]*$/.test(entityValue(entity, "wins"));
    const matchesMode = (entity, mode) => mode === "all" || mode === "cleared" && cleared(entity) || mode === "new" && !cleared(entity) || mode === "changed" && entityChanged(entity);
    const filterRefs = new Map();
    for (const [mode, name] of [["all", "全部关卡"], ["cleared", "已通关"], ["new", "未通关"], ["changed", "已修改"]]) {
      const button = node("button", `resource-filter${model.stageMode === mode ? " active" : ""}`, `${name} ${list.filter((entity) => matchesMode(entity, mode)).length}`);
      button.type = "button"; button.setAttribute("aria-pressed", String(model.stageMode === mode));
      button.addEventListener("click", () => { model.stageMode = mode; model.stageLimit = 24; renderFields(); }); filterRefs.set(mode, { button, name }); filters.append(button);
    }
    container.append(filters);
    const matched = list.filter((entity) => matchesMode(entity, model.stageMode));
    const grid = node("div", "stage-grid");
    for (const entity of matched.slice(0, model.stageLimit)) {
      const card = node("article", "stage-card"); card.dataset.stageId = entity.id; card.classList.toggle("changed", entityChanged(entity));
      const heading = node("div", "stage-heading"); const status = node("span", "detail-chip", cleared(entity) ? "已通关" : "未通关");
      heading.append(node("h4", "", entityName(entity, "关卡")), status); card.append(heading);
      const fields = node("div", "stage-fields-grid");
      for (const field of entity.fields) fields.append(scalarField(field, attributeName(field), () => {
        card.classList.toggle("changed", entityChanged(entity)); status.textContent = cleared(entity) ? "已通关" : "未通关";
        for (const [mode, { button, name }] of filterRefs) button.textContent = `${name} ${list.filter((item) => matchesMode(item, mode)).length}`;
      }, true));
      card.append(fields); grid.append(card);
    }
    if (!matched.length) grid.append(node("p", "muted", "此范围内没有匹配的关卡。"));
    container.append(grid);
    moreControl(container, Math.min(matched.length, model.stageLimit), matched.length, "个关卡", () => { model.stageLimit += 24; renderFields(); });
    return matched.length;
  }

  function renderFields() {
    const wrap = $("save-fields"); wrap.replaceChildren();
    wrap.dataset.grouped = String(Boolean(model.group));
    const fields = (model.data?.fields || []).filter((field) => !model.group || groupName(field) === model.group);
    const scalars = fields.filter((field) => field.type !== "map" && !/^(servants|mainline)\./.test(field.key) && (!model.query || fieldMatches(field)));
    const maps = fields.filter((field) => field.type === "map").map((field) => ({ field, info: resourceInfo(field) })).filter(({ field, info }) => !model.query || fieldMatches(field) || info.matched.length);
    const servants = entities(fields, "servants").filter(entityMatches);
    const stages = entities(fields, "mainline").filter(entityMatches);
    const summaries = [];
    for (const group of new Set(scalars.map(groupName))) {
      const part = section(group);
      const grid = node("div", "data-fields-grid");
      for (const field of scalars.filter((field) => groupName(field) === group).slice(0, model.limit)) grid.append(scalarField(field));
      part.append(grid); wrap.append(part);
    }
    if (scalars.length) summaries.push(`${scalars.length} 项字段`);
    if (scalars.length > model.limit) moreControl(wrap, model.limit, scalars.length, "项字段", () => { model.limit += 40; renderFields(); });
    for (const { field, info } of maps) {
      const part = section(groupName(field), "先按名称、ID 或种类查找，再调整目标数量。所有变更先留在草稿中。");
      const count = renderMap(field, part, info); summaries.push(`${groupName(field)} ${count} 件`); wrap.append(part);
    }
    if (servants.length) { const part = section("魔女成长", "选择已拥有的魔女，集中编辑成长、武器、好感度与技能。"); renderServants(servants, part); wrap.append(part); summaries.push(`${servants.length} 位魔女`); }
    if (stages.length) { const part = section("主线关卡进度", "同一关卡的挑战、胜利与星数集中排列；首通奖励记录保留。"); const count = renderStages(stages, part); wrap.append(part); summaries.push(`${count} 个关卡`); }
    renderMaze();
    const mazeVisible = !!model.liveData && !$("maze-state-panel").hidden;
    if (!wrap.children.length) wrap.append(node("p", "muted", mazeVisible ? "此范围已找到迷宫只读状态，没有可编辑字段。" : model.data ? "没有匹配的数据。可换分类或清空搜索。" : "暂无可编辑存档。"));
    const heading = $("data-category-title"), description = $("data-category-description"), summary = $("data-results-summary");
    if (heading) heading.textContent = model.query ? "数据查询" : model.group || "全部玩家数据";
    if (description) description.textContent = model.query ? `按“${model.query}”查找${model.group ? ` · 当前分类：${model.group}` : "全部分类"}，切换结果会保留草稿。` : ({ "基本信息": "玩家资料与角色昵称。", "货币与资源": "账户资源集中排列，可精确调整数值。", "体力与成长": "角色经验、普通体力与活动体力。", "道具": "背包道具与完整游戏目录，可按种类筛选。", "装备": "装备库存与完整游戏目录。", "魔女成长": "按魔女查看成长信息与技能。", "主线关卡进度": "按关卡查看挑战、胜利与星数。", "迷宫进度": "查看已保存的本轮迷宫状态；仅累计胜场、挑战次数与星数可编辑。" }[model.group] || "按分类或名称、ID 查找数据，修改后统一预览并保存。");
    if (summary) summary.textContent = mazeVisible ? `已找到迷宫状态 · ${summaries.join(" · ") || "没有可编辑字段"}` : summaries.join(" · ") || "没有匹配结果";
    controls();
  }

  function renderGroups() {
    const wrap = $("field-groups"); wrap.replaceChildren();
    const fields = model.data?.fields || [];
    const groups = ["", ...new Set(fields.map(groupName))];
    if (!groups.includes(model.group)) model.group = "";
    for (const group of groups) {
      const button = node("button", `group-button${model.group === group ? " active" : ""}`, group || "全部数据");
      button.type = "button"; button.setAttribute("aria-pressed", String(model.group === group));
      const groupFields = fields.filter((field) => groupName(field) === group);
      const count = groupFields.length ? groupFields.some((field) => field.key.startsWith("servants.")) ? entities(groupFields, "servants").length : groupFields.some((field) => field.key.startsWith("mainline.")) ? entities(groupFields, "mainline").length : groupFields.some((field) => field.type === "map") ? groupFields.filter((field) => field.type === "map").reduce((total, field) => total + Object.values(currentValue(field) || {}).filter((value) => amount(value) !== "0").length, 0) : groupFields.length : 0;
      if (group) button.append(node("span", "group-count", String(count)));
      button.addEventListener("click", () => { model.group = group; model.limit = 40; renderGroups(); renderFields(); $("maze-state-teams").open = group === "迷宫进度"; }); wrap.append(button);
    }
  }

  function applyData(data) {
    validateData(data);
    if (!model.data && !model.query && !model.group) model.group = data.fields[0]?.group || "";
    model.data = data;
    if (state.detail?.account?.id === model.id && state.detail.legacy?.available) state.detail.legacy.revision = data.revision;
    updateLive(data); freshness(); notice(lockNotice());
    renderGroups(); renderFields();
  }

  async function load(preserveDraft = false) {
    const id = model.id, generation = model.generation;
    if (!id || !state.token) return false;
    try {
      const data = await api(`${base()}/save`);
      if (id !== model.id || generation !== model.generation || !state.token) return false;
      validateData(data);
      showMessage($("data-error"), "");
      if (model.dirty.size) {
        updateLive(data); freshness();
        notice(`${model.data && data.revision !== model.data.revision ? "玩家存档已更新。当前输入与编辑基准已保留，请读取最新数据并重新核对后保存。" : ""}${lockNotice()}`);
        return true;
      }
      applyData(data); return true;
    } catch (error) {
      if (id !== model.id || generation !== model.generation || !state.token) return false;
      showMessage($("data-error"), error.message);
      model.liveIssue = true; freshness(); renderMaze(); controls();
      for (const row of $("detail-facts").children) {
        const label = row.querySelector("dt")?.textContent;
        if (label === "编辑状态") row.querySelector("dd").textContent = "状态失效，需重新读取";
        if (["迷宫楼层", "战斗状态"].includes(label)) row.querySelector("dd").textContent = model.liveData ? `上次：${label === "迷宫楼层" ? mazeRoundValue(liveState().round) : liveState().battle === null ? "状态未确认" : liveState().battle ? "进行中" : "空闲"}（旧值参考）` : "状态未确认";
      }
      notice(model.liveData ? "最近读取失败，以上旧状态仅供参考；重新读取成功前暂停修改与恢复。" : "存档未成功读取，当前不能确认迷宫状态与编辑权限。");
      if (!model.data) renderFields();
      return false;
    }
  }

  function tab(name) {
    for (const button of document.querySelectorAll("[data-manager-tab]")) {
      const selected = button.dataset.managerTab === name;
      button.classList.toggle("active", selected); button.setAttribute("aria-pressed", String(selected));
    }
    for (const key of ["data", "backups", "mail"]) $(`${key === "data" ? "data" : key}-panel`).hidden = key !== name;
    if (name === "backups") void loadBackups();
  }

  function validatedChanges() {
    if (!writable()) throw new Error(model.liveIssue ? "最新存档状态未确认，请重新读取。" : lockNotice() || "暂不可编辑存档。");
    const changes = Object.fromEntries(model.dirty);
    if (Object.keys(changes).length > 128) throw new Error("每次最多修改 128 个字段，请分批保存。");
    for (const field of model.data.fields) {
      if (!Object.hasOwn(changes, field.key)) continue;
      const value = changes[field.key];
      if (value && typeof value === "object" && Object.hasOwn(value, "__invalidJSON")) throw new Error(`${title(field)}的 JSON 格式无效。`);
      if (field.type === "text") {
        const length = Array.from(String(value)).length;
        if (typeof value !== "string" || value.trim() !== value || /[\p{Cc}\p{Cf}]/u.test(value) || new TextEncoder().encode(value).length > 128 ||
            field.min !== undefined && length < Number(field.min) || field.max !== undefined && length > Number(field.max)) throw new Error(`${title(field)}需要 ${field.min || 2}–${field.max || 16} 个字符，且不能包含首尾空白或控制字符。`);
      }
      if (numeric(field)) {
        if (!/^(0|[1-9][0-9]*)$/.test(String(value))) throw new Error(`${title(field)}必须是非负整数。`);
        const number = BigInt(value);
        if (field.min !== undefined && number < BigInt(field.min) || field.max !== undefined && number > BigInt(field.max)) throw new Error(`${title(field)}超出了允许范围。`);
        changes[field.key] = String(value);
      }
      if (field.type === "map") {
        const caps = new Map(catalogEntries(field).map((entry) => [entry.id, entry.max]));
        const updates = {};
        // 只提交变更的 ID；既有存档里未修改的超上限数量不应阻止其他资源编辑。
        for (const id of new Set([...Object.keys(field.value || {}), ...Object.keys(value)])) {
          if (!resourceChanged(field, value, id)) continue;
          const next = amount(value[id]);
          if (!/^[1-9][0-9]*$/.test(id) || !/^(0|[1-9][0-9]*)$/.test(next)) throw new Error(`${title(field)}的资源 ID 或数量无效。`);
          if (field.max !== undefined && BigInt(next) > BigInt(field.max)) throw new Error(`${title(field)}的数量超出了允许范围。`);
          if (caps.get(id) !== undefined && BigInt(next) > BigInt(caps.get(id))) throw new Error(`${title(field)}中 ID ${id} 的数量超出上限 ${caps.get(id)}。`);
          updates[id] = next;
        }
        changes[field.key] = updates;
      }
    }
    if (!Object.keys(changes).length) throw new Error("没有需要保存的改动。");
    return { expectedRevision: model.data.revision, reason: reasonValue("data-reason"), changes };
  }

  function diffRows(container, changes) {
    container.replaceChildren();
    for (const change of changes) {
      let label = model.data?.fields?.find((field) => field.key === change.key)?.label || change.label || change.key;
      const resource = change.key.match(/^(items|equips)\.([1-9][0-9]*)$/);
      if (resource) {
        const field = model.data?.fields?.find((entry) => entry.key === resource[1]);
        if (field) label = catalogEntries(field).find((entry) => entry.id === resource[2])?.label || label;
      }
      const item = node("div", "diff-row"); item.append(node("strong", "", label));
      const values = node("div", "diff-values");
      const before = node("pre", "diff-before", pretty(change.before)); const after = node("pre", "diff-after", pretty(change.after));
      before.setAttribute("aria-label", "修改前"); after.setAttribute("aria-label", "修改后"); values.append(before, node("span", "", "→"), after); item.append(values); container.append(item);
    }
  }

  async function preview(event) {
    event.preventDefault(); if (model.busy || state.mailPending) return;
    showMessage($("data-error"), ""); showMessage($("data-success"), "");
    let payload;
    try { payload = validatedChanges(); } catch (error) { showMessage($("data-error"), error.message); return; }
    const id = model.id, generation = model.generation; model.busy = true; controls();
    try {
      const result = await api(`${base()}/save/preview`, { method: "POST", body: payload });
      if (id !== model.id || generation !== model.generation || !state.token) return;
      if (!Array.isArray(result?.changes) || typeof result.revision !== "string" || result.revision !== payload.expectedRevision) throw new Error("修改预览未通过校验，请读取最新数据。");
      if (!result.changes.length) throw new Error("这些输入与当前存档相同，无需保存。");
      model.pending = payload;
      diffRows($("change-review-list"), result.changes);
      $("change-review-note").textContent = `${result.changes.length} 个字段将写入所选玩家，保存前自动备份完整存档。`;
      $("change-review").hidden = false;
      $("change-review").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      if (id === model.id && generation === model.generation && state.token) {
        if (error.code === "active_battle") { model.liveIssue = true; controls(); await load(true); notice(lockNotice() || "服务器拒绝编辑：玩家正在战斗或迷宫整备中，当前输入已保留。请重新核对状态。"); }
        else if (error.status === 409) notice("预览期间存档发生变化，当前输入已保留。请先读取最新数据。");
        if (id === model.id && generation === model.generation && state.token) showMessage($("data-error"), error.message);
      }
    }
    finally { if (generation === model.generation) { model.busy = false; controls(); } }
  }

  async function commit() {
    if (!model.pending || !writable() || state.mailPending) return;
    const id = model.id, generation = model.generation, payload = model.pending; model.busy = true; controls();
    try {
      const result = await api(`${base()}/save`, { method: "PATCH", body: payload });
      if (id !== model.id || generation !== model.generation || !state.token) return;
      model.dirty.clear(); invalidatePreview(); $("data-reason").value = "";
      model.busy = false;
      await openAccount(id);
      if (!state.token || id !== state.selectedId) return;
      showMessage($("data-success"), `数据已保存，修改前备份：${result.backupId || "已记录"}。游戏内重新读取后生效。`);
      toast("已备份并保存玩家数据");
    } catch (error) {
      if (id !== model.id || generation !== model.generation || !state.token) return;
      invalidatePreview();
      const uncertain = !error.status || error.status >= 500;
      if (error.code === "active_battle") { model.liveIssue = true; controls(); await load(true); }
      if (id !== model.id || generation !== model.generation || !state.token) return;
      showMessage($("data-error"), uncertain ? "保存结果未确认。请读取最新存档核对；重新预览后才能再次提交。" : error.message);
      if (error.code === "active_battle") notice(lockNotice() || "服务器拒绝编辑：玩家正在战斗或迷宫整备中，草稿已保留。请重新核对状态。");
      else if (error.status === 409) notice("存档已更新，草稿已保留。请读取最新数据并重新核对。");
    } finally { if (generation === model.generation) { model.busy = false; controls(); } }
  }

  async function loadBackups() {
    const id = model.id, generation = model.generation; if (!id || !state.token) return;
    const request = ++model.backupRequest;
    try {
      const result = await api(`${base()}/backups`);
      if (id !== model.id || generation !== model.generation || request !== model.backupRequest || !state.token) return;
      if (!Array.isArray(result?.items)) throw new Error("备份列表格式无效。");
      model.backups = result.items; renderBackups();
    } catch (error) { if (id === model.id && generation === model.generation && state.token) showMessage($("backup-error"), error.message); }
  }

  function renderBackups() {
    const wrap = $("backup-list"); wrap.replaceChildren(); $("backup-count").textContent = model.backups.length ? String(model.backups.length) : "";
    if (!model.backups.length) { wrap.append(node("p", "muted", "还没有备份。可以先创建一份，之后每次管理修改前也会自动备份。")); return; }
    const kinds = { manual: "手动备份", patch: "修改前", edit: "修改前", restore: "恢复前", automatic: "修改前" };
    for (const backup of model.backups) {
      const card = node("article", "backup-card");
      const heading = node("div", "backup-heading");
      heading.append(node("strong", "", timeValue(Number(backup.createdAt))), node("span", "detail-chip", kinds[backup.kind] || "存档快照"));
      card.append(heading, node("p", "", backup.reason || "未记录说明"), node("small", "", `版本 ${backup.revision} · ${nf.format(Number(backup.bytes || 0))} 字节`), node("code", "backup-id", backup.id));
      const checksum = node("details", "backup-checksum"); checksum.append(node("summary", "", "SHA-256 校验值"), node("code", "", backup.sha256)); card.append(checksum);
      const actions = node("div", "backup-actions");
      const download = node("button", "button button-secondary button-small", "下载备份"); download.type = "button";
      download.addEventListener("click", () => { void downloadBackup(backup, download); });
      const restore = node("button", "button button-quiet button-small", "预览恢复"); restore.type = "button";
      restore.addEventListener("click", () => { void previewRestore(backup); });
      actions.append(download, restore); card.append(actions); wrap.append(card);
    }
  }

  async function rawBackup(backupId) {
    const response = await fetch(`${base()}/backups/${encodeURIComponent(backupId)}`, { headers: { Authorization: `Bearer ${state.token}`, Accept: "application/json" }, credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer" });
    if (!response.ok) { const payload = await response.json().catch(() => null); if (response.status === 401) clearSession(errorText(payload, response.status)); throw new Error(errorText(payload, response.status)); }
    return await response.text();
  }

  async function downloadBackup(backup, button) {
    const id = model.id, generation = model.generation; button.disabled = true;
    try {
      const text = await rawBackup(backup.id);
      if (id !== model.id || generation !== model.generation || !state.token) return;
      const url = URL.createObjectURL(new Blob([text], { type: "application/json;charset=utf-8" }));
      const link = node("a"); link.href = url; link.download = `魔女兵器存档-${id}-${backup.id}.json`; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("备份下载已发起，请在浏览器下载记录中查看。");
    } catch (error) { if (id === model.id && state.token) showMessage($("backup-error"), error.message); }
    finally { button.disabled = false; }
  }

  async function createBackup(event) {
    event.preventDefault(); if (!model.data || model.busy) return;
    showMessage($("backup-error"), ""); showMessage($("backup-success"), "");
    let reason;
    try { reason = reasonValue("backup-reason"); } catch (error) { showMessage($("backup-error"), error.message); return; }
    const id = model.id, generation = model.generation; model.busy = true; controls();
    try {
      const result = await api(`${base()}/backups`, { method: "POST", body: { expectedRevision: model.data.revision, reason } });
      if (id !== model.id || generation !== model.generation || !state.token) return;
      await loadBackups(); $("backup-reason").value = "";
      showMessage($("backup-success"), `备份已创建：${result.backup?.id || result.id || result.backupId || "已保存在服务器"}`);
    } catch (error) { if (id === model.id && state.token) showMessage($("backup-error"), error.message); }
    finally { if (generation === model.generation) { model.busy = false; controls(); } }
  }

  async function previewRestore(backup) {
    if (!writable() || state.mailPending) { showMessage($("backup-error"), "请先确认存档可修改，并处理待确认的邮件请求。"); return; }
    if (model.dirty.size) { showMessage($("backup-error"), "请先保存或撤销数据编辑草稿，再恢复备份。"); return; }
    const id = model.id, generation = model.generation; model.busy = true; controls();
    showMessage($("backup-error"), ""); showMessage($("backup-success"), "");
    try {
      // 服务端预览与恢复使用同一白名单，浏览器不重新解释完整存档中的超长整数。
      const result = await api(`${base()}/backups/${encodeURIComponent(backup.id)}/preview`, { method: "POST", body: { expectedRevision: model.data.revision, reason: "管理员核对历史存档恢复预览" } });
      if (id !== model.id || generation !== model.generation || !state.token) return;
      if (!Array.isArray(result?.changes) || typeof result.revision !== "string" || result.revision !== model.data.revision) throw new Error("恢复预览格式无效，请读取最新存档。");
      model.restore = result.changes.length ? { backup, revision: result.revision } : null;
      $("restore-info").textContent = `选定备份：${timeValue(Number(backup.createdAt))} · 版本 ${backup.revision}。${result.changes.length} 个可编辑字段将恢复，恢复前自动备份当前数据。`;
      if (!result.changes.length) $("restore-info").textContent = "这份备份的可编辑数据与当前存档一致，无需恢复。";
      diffRows($("restore-changes"), result.changes);
      $("restore-retained").textContent = `备份保存完整快照，网页恢复仅覆盖上方可编辑字段。本轮迷宫楼层、挑战名单与队伍、生命与能量、整备等级、结算、宝箱与每日重置记录保持当前；身份、奖励领取、邮件、公会与交易记录也保留${Array.isArray(result.retainedFields) ? `（共 ${result.retainedFields.length} 项）` : ""}。`;
      $("restore-reason").value = ""; $("restore-review").hidden = false;
      $("restore-review").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) { if (id === model.id && state.token) showMessage($("backup-error"), error.message); }
    finally { if (generation === model.generation) { model.busy = false; controls(); } }
  }

  async function restoreBackup() {
    if (!model.restore || !writable() || state.mailPending || model.dirty.size) return;
    let reason;
    try { reason = reasonValue("restore-reason"); } catch (error) { showMessage($("backup-error"), error.message); return; }
    const id = model.id, generation = model.generation, restore = model.restore; model.busy = true; controls();
    try {
      const result = await api(`${base()}/backups/${encodeURIComponent(restore.backup.id)}/restore`, { method: "POST", body: { expectedRevision: restore.revision, reason } });
      if (id !== model.id || generation !== model.generation || !state.token) return;
      model.restore = null; $("restore-review").hidden = true; model.busy = false;
      await openAccount(id);
      if (!state.token || id !== state.selectedId) return;
      showMessage($("backup-success"), `已恢复选定字段。恢复前备份：${result.backupId || "已保存在服务器"}。`);
      toast("已备份当前数据并完成恢复");
    } catch (error) {
      if (id === model.id && state.token) {
        model.restore = null; $("restore-review").hidden = true;
        showMessage($("backup-error"), !error.status || error.status >= 500 ? "恢复结果未确认，请读取最新数据并核对备份记录，勿重复提交。" : error.message);
      }
    } finally { if (generation === model.generation) { model.busy = false; controls(); } }
  }

  function resetDraft() { model.dirty.clear(); invalidatePreview(); $("data-reason").value = ""; showMessage($("data-error"), ""); renderFields(); }
  function reset() {
    clearInterval(model.timer); model.timer = 0; model.generation++; model.id = ""; model.data = null; model.liveData = null; model.liveReadAt = 0; model.liveIssue = false; model.dirty.clear(); model.pending = null; model.restore = null; model.busy = false; model.backups = [];
    model.resourceModes.clear(); model.resourceCategories.clear(); model.resourceLimits.clear(); model.selectedServant = ""; model.servantLimit = 24; model.stageLimit = 24; model.stageMode = "all";
    $("save-fields").replaceChildren(); $("save-readonly").textContent = ""; $("backup-list").replaceChildren(); $("backup-count").textContent = "";
    resetMaze(); $("save-readonly-disclosure").open = false; $("save-read-at").textContent = "尚未成功读取存档"; $("save-revision").textContent = "等待读取存档"; notice("");
    $("change-review").hidden = true; $("restore-review").hidden = true;
    for (const id of ["data-reason", "backup-reason", "restore-reason"]) $(id).value = "";
    for (const id of ["data-error", "data-success", "backup-error", "backup-success"]) showMessage($(id), "");
    controls();
  }

  async function open(id) {
    const auto = $("save-auto-refresh").checked;
    reset(); model.id = id; $("save-revision").textContent = "正在读取存档…"; $("save-fields").append(node("p", "muted", "正在读取玩家数据…"));
    await Promise.all([load(), loadBackups()]);
    if (id === model.id && auto) startPolling();
  }

  function startPolling() {
    clearInterval(model.timer);
    if (!$("save-auto-refresh").checked) return;
    model.timer = setInterval(() => { if (state.token && model.id && !model.busy && !document.hidden && !model.restore && !model.pending) void load(true); }, 15000);
  }

  function canLeave() {
    if (model.busy) { toast("正在处理当前玩家的操作，请稍候。"); return false; }
    if (model.dirty.size && !window.confirm(`当前玩家有 ${model.dirty.size} 项未保存的输入。确定放弃并重新读取或切换玩家吗？`)) return false;
    return true;
  }

  for (const button of document.querySelectorAll("[data-manager-tab]")) button.addEventListener("click", () => tab(button.dataset.managerTab));
  $("data-form").addEventListener("submit", (event) => { void preview(event); });
  $("data-reason").addEventListener("input", () => { invalidatePreview(); controls(); });
  $("data-reset").addEventListener("click", resetDraft);
  $("data-cancel").addEventListener("click", () => { invalidatePreview(); controls(); });
  $("data-commit").addEventListener("click", () => { void commit(); });
  $("save-reload").addEventListener("click", () => { if (!canLeave()) return; resetDraft(); model.restore = null; $("restore-review").hidden = true; void load(); });
  $("field-search").addEventListener("input", () => {
    model.query = $("field-search").value.trim().toLowerCase(); model.limit = 40; model.servantLimit = 24; model.stageLimit = 24; model.resourceLimits.clear();
    if (model.query) { model.group = ""; model.resourceModes.clear(); model.resourceCategories.clear(); model.stageMode = "all"; }
    renderGroups(); renderFields();
  });
  $("save-auto-refresh").addEventListener("change", startPolling);
  $("backup-form").addEventListener("submit", (event) => { void createBackup(event); });
  $("backup-reload").addEventListener("click", () => { showMessage($("backup-error"), ""); void loadBackups(); });
  $("restore-cancel").addEventListener("click", () => { model.restore = null; $("restore-review").hidden = true; controls(); });
  $("restore-commit").addEventListener("click", () => { void restoreBackup(); });
  return { open, reset, canLeave, isBusy: () => model.busy, hasUnsaved: () => model.dirty.size > 0 || model.busy };
})();
