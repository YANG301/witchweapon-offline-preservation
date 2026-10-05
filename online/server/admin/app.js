"use strict";

// 管理令牌只保留在本页运行内存。不要改为 localStorage、sessionStorage 或 URL 参数。
const DEFAULT_PAGE_SIZE = 100;
const GOLD_MAX = 1000000000;
const state = {
  token: "",
  expiresAt: "",
  selectedId: "",
  detail: null,
  query: "",
  searchField: "all",
  verified: "all",
  sort: "rid_desc",
  pageSize: DEFAULT_PAGE_SIZE,
  listLoading: false,
  cursor: "",
  previousCursors: [],
  nextCursor: "",
  accountTotal: null,
  listGeneration: 0,
  detailGeneration: 0,
  mailCatalog: [],
  mailPending: null,
  mailSending: false,
  activeSection: "players",
};

const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat("zh-CN");
let toastTimer = 0;
let expirationTimer = 0;

function textValue(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function countValue(value) {
  return typeof value === "number" && Number.isFinite(value) ? nf.format(value) : "—";
}

function timeValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return "—";
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? "—" : time.toLocaleString("zh-CN", { hour12: false });
}

function mazeRoundValue(value) {
  const valid = typeof value === "number" && Number.isInteger(value) || typeof value === "string" && /^(?:[1-9]|1[0-3])$/.test(value);
  const round = valid ? Number(value) : 0;
  return round === 13 ? "本轮完成" : round >= 1 && round <= 12 ? `第 ${round} 层 / 12` : "—";
}

function showMessage(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

function toast(message) {
  const item = $("toast");
  item.textContent = message;
  item.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { item.hidden = true; }, 4200);
}

function setConnection(connected, label) {
  const indicator = $("service-status");
  indicator.classList.toggle("online", connected);
  indicator.classList.toggle("error", label === "连接失败");
  $("status-text").textContent = label;
}

function showDashboard(open) {
  $("auth-view").hidden = open;
  $("dashboard-view").hidden = !open;
  $("lock-button").hidden = !open;
  setConnection(open, open ? "已连接" : "等待验证");
  if (open) window.adminServerMonitor?.start();
}

function switchAdminSection(section) {
  if (!state.token || !["players", "mail", "monitor"].includes(section) || state.activeSection === section) return;
  if (state.mailSending || window.adminData?.isBusy() || window.adminMailCenter?.isBusy()) {
    toast("正在处理管理操作，请等待结果后切换。");
    return;
  }
  if (state.mailPending) {
    toast("单人邮件结果尚未确认，请在当前玩家的游戏邮件页按原请求核对后切换。");
    return;
  }
  state.activeSection = section;
  $("players-view").hidden = section !== "players";
  $("mail-center-view").hidden = section !== "mail";
  $("server-monitor-view").hidden = section !== "monitor";
  for (const button of document.querySelectorAll("[data-admin-section]")) {
    const active = button.dataset.adminSection === section;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  if (section === "mail") window.adminMailCenter?.onOpen();
  else window.adminMailCenter?.onClose();
  if (section === "monitor") window.adminServerMonitor?.onOpen();
}

function clearSession(message = "") {
  window.adminServerMonitor?.reset();
  window.adminData?.reset();
  window.adminMailCenter?.reset();
  state.activeSection = "players";
  $("players-view").hidden = false;
  $("mail-center-view").hidden = true;
  $("server-monitor-view").hidden = true;
  for (const button of document.querySelectorAll("[data-admin-section]")) {
    const active = button.dataset.adminSection === "players";
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  clearTimeout(expirationTimer);
  state.token = "";
  state.expiresAt = "";
  state.selectedId = "";
  state.detail = null;
  state.query = "";
  state.searchField = "all";
  state.verified = "all";
  state.sort = "rid_desc";
  state.pageSize = DEFAULT_PAGE_SIZE;
  state.listLoading = false;
  state.cursor = "";
  state.previousCursors = [];
  state.nextCursor = "";
  state.accountTotal = null;
  state.listGeneration++;
  state.detailGeneration++;
  state.mailCatalog = [];
  state.mailPending = null;
  state.mailSending = false;
  $("admin-password").value = "";
  $("admin-password").type = "password";
  $("reveal-password").textContent = "显示";
  $("reveal-password").setAttribute("aria-label", "显示密码");
  $("account-search").value = "";
  $("account-search-field").value = "all";
  $("account-verified").value = "all";
  $("account-sort").value = "rid_desc";
  $("account-page-size").value = String(DEFAULT_PAGE_SIZE);
  $("prev-page").disabled = true;
  $("next-page").disabled = true;
  $("account-rows").replaceChildren();
  $("detail-facts").replaceChildren();
  $("detail-name").textContent = "—";
  $("detail-email").textContent = "—";
  $("detail-id").textContent = "—";
  $("detail-content").hidden = true;
  $("detail-placeholder").hidden = false;
  for (const id of ["edit-name", "edit-gold", "edit-reason"]) $(id).value = "";
  for (const id of ["mail-title", "mail-content", "mail-reason"]) $(id).value = "";
  $("mail-sender").value = "新丰洲";
  $("mail-recipient").textContent = "—";
  $("mail-attachments").replaceChildren();
  for (const id of ["mail-sender", "mail-title", "mail-content", "mail-reason",
    "mail-add-attachment", "mail-send-button", "mail-reset-button"]) $(id).disabled = true;
  showMessage($("mail-error"), "");
  showMessage($("mail-success"), "");
  $("total-accounts").textContent = "—";
  $("visible-accounts").textContent = "—";
  $("list-count").textContent = "—";
  $("page-info").textContent = "—";
  showDashboard(false);
  showMessage($("auth-error"), message);
  if (message) $("admin-password").focus();
}

function scheduleExpiry() {
  clearTimeout(expirationTimer);
  if (!state.expiresAt) return;
  const remaining = Date.parse(state.expiresAt) - Date.now();
  if (!Number.isFinite(remaining)) return;
  if (remaining <= 0) {
    clearSession("管理会话已过期，请重新进入。");
    return;
  }
  expirationTimer = setTimeout(() => {
    if (state.token) scheduleExpiry();
  }, Math.min(remaining, 2147483647));
}

function errorText(body, status) {
  const detail = body && body.error;
  if (typeof detail === "string" && detail.length < 240) return detail;
  if (detail && typeof detail.message === "string" && detail.message.length < 240) return detail.message;
  if (typeof body?.message === "string" && body.message.length < 240) return body.message;
  if (status === 401) return "管理会话已过期，请重新进入。";
  if (status === 403) return "服务器拒绝了本次管理操作。";
  if (status === 409) return "存档刚被修改，请刷新账号数据后重试。";
  if (status === 429) return "请求过于频繁，请稍后重试。";
  return `请求失败（HTTP ${status}）。`;
}

async function api(path, options = {}) {
  const { method = "GET", body, authenticated = true } = options;
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (authenticated) {
    if (!state.token) throw new Error("请重新进入管理后台。");
    headers.Authorization = `Bearer ${state.token}`;
  }
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
  } catch {
    setConnection(false, "连接失败");
    throw new Error("无法连接服务器。请检查网络连接和游戏后端状态。");
  }
  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const message = errorText(payload, response.status);
    if (authenticated && response.status === 401) clearSession(message);
    const error = new Error(message);
    error.status = response.status;
    error.code = typeof payload?.error?.code === "string" && /^[a-z_]{1,64}$/.test(payload.error.code) ? payload.error.code : "";
    throw error;
  }
  return payload;
}

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = textValue(value);
  return node;
}

function renderRows(items) {
  const rows = $("account-rows");
  rows.replaceChildren();
  for (const account of items) {
    if (!account || typeof account.id !== "string" || typeof account.email !== "string") continue;
    const tr = element("tr");
    if (account.id === state.selectedId) tr.classList.add("selected");
    const accountCell = element("td");
    accountCell.append(element("strong", "", account.email), element("small", "", `RID ${textValue(account.publicRid)} · ${account.id}`));
    const statusCell = element("td");
    statusCell.append(element("span", account.emailVerified ? "verified-status" : "muted", account.emailVerified ? "已验证" : "未验证"));
    const actionCell = element("td", "table-action");
    const button = element("button", "row-button", "详情 →");
    button.type = "button";
    tr.dataset.accountId = account.id;
    button.addEventListener("click", () => { void openAccount(account.id); });
    actionCell.append(button);
    tr.append(accountCell, statusCell, actionCell);
    rows.append(tr);
  }
  $("list-empty").hidden = rows.children.length !== 0;
}

async function loadAccounts(cursor = state.cursor, previousCursors = [...state.previousCursors]) {
  const generation = ++state.listGeneration;
  const params = new URLSearchParams({
    limit: String(state.pageSize), field: state.searchField, verified: state.verified, sort: state.sort,
  });
  if (state.query) params.set("q", state.query);
  if (cursor) params.set("cursor", cursor);
  state.listLoading = true;
  $("prev-page").disabled = true;
  $("next-page").disabled = true;
  $("account-rows").setAttribute("aria-busy", "true");
  $("page-info").textContent = "正在加载…";
  try {
    const data = await api(`/admin/api/accounts?${params}`);
    if (generation !== state.listGeneration || !state.token) return;
    const items = Array.isArray(data?.items) ? data.items : [];
    const total = Number.isSafeInteger(data?.total) && data.total >= 0 ? data.total : null;
    if (Number.isSafeInteger(data?.accountTotal) && data.accountTotal >= 0) state.accountTotal = data.accountTotal;
    else if (!state.query && state.verified === "all" && total !== null) state.accountTotal = total;
    state.cursor = cursor;
    state.previousCursors = previousCursors;
    state.nextCursor = typeof data?.nextCursor === "string" ? data.nextCursor : "";
    renderRows(items);
    $("total-accounts").textContent = countValue(state.accountTotal);
    $("visible-accounts").textContent = countValue(total);
    $("list-count").textContent = String(items.length);
    const pageCount = total === null ? "—" : Math.max(1, Math.ceil(total / state.pageSize));
    $("page-info").textContent = `第 ${state.previousCursors.length + 1} / ${pageCount} 页 · 本页 ${items.length} 个 · 共 ${countValue(total)} 个`;
    $("list-empty").textContent = state.query || state.verified !== "all" ? "没有符合筛选条件的账号" : "暂无账号";
    $("prev-page").disabled = state.previousCursors.length === 0;
    $("next-page").disabled = !state.nextCursor;
    setConnection(true, "已连接");
  } catch (error) {
    if (generation !== state.listGeneration || !state.token) return;
    renderRows([]);
    $("page-info").textContent = "加载失败";
    toast(error.message);
  } finally {
    if (generation === state.listGeneration) {
      state.listLoading = false;
      $("account-rows").setAttribute("aria-busy", "false");
    }
  }
}

function applyAccountFilters() {
  state.query = $("account-search").value.trim();
  state.searchField = $("account-search-field").value;
  state.verified = $("account-verified").value;
  state.sort = $("account-sort").value;
  const size = Number($("account-page-size").value);
  state.pageSize = [20, 50, 100, 200].includes(size) ? size : DEFAULT_PAGE_SIZE;
  state.cursor = "";
  state.previousCursors = [];
  state.nextCursor = "";
  void loadAccounts();
}

function fact(label, value) {
  const item = element("div");
  item.append(element("dt", "", label), element("dd", "", value));
  return item;
}

function renderDetail(data) {
  const account = data?.account;
  if (!account || typeof account.id !== "string") throw new Error("账号详情格式不正确。");
  const legacy = data.legacy || {};
  const legacyState = legacy.available && legacy.state && typeof legacy.state === "object" ? legacy.state : null;
  const legacyRole = legacy.available && legacy.role && typeof legacy.role === "object" ? legacy.role : null;
  const apkRoleExists = legacyRole?.exists === true || legacyState?.roleCreated === true;
  const name = apkRoleExists
    ? textValue(legacyState?.name || legacyRole?.name, "APK 昵称未知")
    : legacy.available ? "APK 角色未创建" :
      legacy.reason === "not_started" ? "尚无游戏存档" : "APK 存档暂不可用";
  $("detail-name").textContent = name;
  $("detail-email").textContent = textValue(account.email);
  $("detail-id").textContent = account.id;
  $("detail-avatar").textContent = apkRoleExists ? Array.from(name)[0] : "W";
  $("detail-chip").textContent = legacy.available ? "存档可读取" :
    legacy.reason === "not_started" ? "尚无游戏存档" : "存档暂不可用";

  const facts = $("detail-facts");
  facts.replaceChildren(
    fact("玩家 RID", textValue(account.publicRid)),
    fact("APK 角色", apkRoleExists ? "已创建" : legacy.available ? "未创建" :
      legacy.reason === "not_started" ? "尚未进入游戏" : "暂不可用"),
    fact("内部 APK 角色 ID", apkRoleExists ? textValue(legacyRole?.roleId || legacyState?.roleId) : "—"),
    fact("Unity 试验角色", textValue(account.role?.nickname, "未创建")),
    fact("金币", legacyState ? countValue(legacyState.gold) : "—"),
    fact("角色经验", legacyState ? countValue(legacyState.exp) : "—"),
    fact("主线胜场", legacyState ? countValue(legacyState.wins) : "—"),
    fact("迷宫胜场", legacyState ? countValue(legacyState.mazeWins) : "—"),
    fact("迷宫楼层", legacyState ? mazeRoundValue(legacyState.mazeRound) : "—"),
    fact("抽卡次数", legacyState ? countValue(legacyState.drawCount) : "—"),
    fact("Unity 试验剧情进度", countValue(Array.isArray(account.progress) ? account.progress.length : 0)),
    fact("邮箱归属验证", account.emailVerified ? "已验证" : "未验证"),
    fact("战斗状态", typeof legacyState?.active === "boolean" ? (legacyState.active ? "进行中" : "空闲") : "状态未确认"),
    fact("编辑状态", "读取存档后确认"),
    fact("存档建立时间", legacyState ? timeValue(legacyState.createdAt) : "—"),
    fact("最近战斗结算", legacyState ? timeValue(legacyState.lastSettlementAt) : "—")
  );

  const canEdit = !!legacyState && typeof legacy.revision === "string" &&
    typeof legacyState.name === "string" && Number.isSafeInteger(legacyState.gold) && legacyState.gold >= 0;
  $("edit-name").value = canEdit ? legacyState.name : "";
  $("edit-gold").value = canEdit ? String(legacyState.gold) : "";
  $("edit-reason").value = "";
  updateQuickEditLock(true, "读取存档后确认");
  showMessage($("edit-error"), canEdit ? "" :
    legacy.reason === "not_started" ? "该账号尚未进入原版游戏，暂时没有可编辑的存档。" :
    "游戏存档暂不可编辑。请先检查原协议服务是否可用。");
  showMessage($("edit-success"), "");
  const canMail = canEdit && legacyState.roleCreated === true;
  state.mailPending = null;
  state.mailCatalog = [
    { type: 13, id: 0, name: "金币", maxCount: 1000000 },
    { type: 98, id: 0, name: "钻石", maxCount: 100000 },
  ];
  $("mail-recipient").textContent = `${textValue(account.email)}（${account.id}）`;
  $("mail-sender").value = "新丰洲";
  $("mail-title").value = "";
  $("mail-content").value = "";
  $("mail-reason").value = "";
  $("mail-attachments").replaceChildren();
  for (const id of ["mail-sender", "mail-title", "mail-content", "mail-reason",
    "mail-add-attachment", "mail-send-button", "mail-reset-button"]) $(id).disabled = !canMail;
  showMessage($("mail-error"), canMail ? "" : "该账号尚未创建原版角色，暂不能接收游戏邮件。");
  showMessage($("mail-success"), "");
  $("detail-placeholder").hidden = true;
  $("detail-content").hidden = false;
}

async function openAccount(id) {
  if (!state.token) return;
  if (window.adminData && !window.adminData.canLeave(id)) return;
  if (state.mailPending) {
    const message = "上次邮件发送结果尚未确认。请在当前账号原样重试，或核对信箱后点“清空邮件”放弃该请求编号。";
    showMessage($("mail-error"), message);
    toast(message);
    return;
  }
  state.selectedId = id;
  const generation = ++state.detailGeneration;
  $("detail-chip").textContent = "读取中";
  $("detail-placeholder").hidden = false;
  $("detail-placeholder").querySelector("strong").textContent = "读取账号数据…";
  $("detail-content").hidden = true;
  for (const tr of $("account-rows").children) tr.classList.remove("selected");
  try {
    const data = await api(`/admin/api/accounts/${encodeURIComponent(id)}`);
    if (generation !== state.detailGeneration || !state.token) return;
    state.detail = data;
    renderDetail(data);
    void window.adminData?.open(id);
    if (data?.legacy?.available && data.legacy.state?.roleCreated === true) void loadMailCatalog(id, generation);
    for (const tr of $("account-rows").children) {
      if (tr.dataset.accountId === id) tr.classList.add("selected");
    }
  } catch (error) {
    if (generation !== state.detailGeneration || !state.token) return;
    state.detail = null;
    $("detail-chip").textContent = "读取失败";
    $("detail-placeholder").querySelector("strong").textContent = "读取失败";
    $("detail-placeholder").querySelector("span").textContent = error.message;
    toast(error.message);
  }
}

function resetEdit() {
  const legacy = state.detail?.legacy;
  if (!legacy?.available || !legacy.state) return;
  $("edit-name").value = textValue(legacy.state.name, "");
  $("edit-gold").value = textValue(legacy.state.gold, "");
  $("edit-reason").value = "";
  showMessage($("edit-error"), "");
  showMessage($("edit-success"), "");
}

function updateQuickEditLock(locked = true, message = "读取存档后确认") {
  state.quickEditLocked = locked;
  state.quickEditLockMessage = message;
  const legacy = state.detail?.legacy, saved = legacy?.state;
  const ready = !!legacy?.available && !!saved && typeof legacy.revision === "string" &&
    typeof saved.name === "string" && Number.isSafeInteger(saved.gold) && saved.gold >= 0;
  const disabled = !ready || locked || state.quickSaving === true;
  for (const id of ["edit-name", "edit-gold", "edit-reason", "save-button", "reset-button"]) $(id).disabled = disabled;
  $("edit-name").disabled = disabled || saved?.roleCreated !== true;
  $("edit-name").title = saved?.roleCreated !== true ? "此账号尚未创建原版角色" : locked ? message : "";
}

function validateEdits() {
  const current = state.detail?.legacy;
  if (!current || !current.available || typeof current.revision !== "string" || !current.state) {
    throw new Error("游戏存档暂不可编辑。");
  }
  if (state.quickEditLocked !== false || state.quickSaving) throw new Error(state.quickEditLockMessage || "请先读取存档并确认可编辑。");
  const changes = {};
  const name = $("edit-name").value.trim();
  const rawGold = $("edit-gold").value.trim();
  const reason = $("edit-reason").value.trim();
  if (current.state.roleCreated === true && name !== current.state.name) {
    const nameLength = Array.from(name).length;
    if (nameLength < 2 || nameLength > 16 || new TextEncoder().encode(name).length > 128) {
      throw new Error("昵称需要 2–16 个字符，最多 128 字节。");
    }
    changes.name = name;
  }
  if (rawGold !== String(current.state.gold)) {
    if (!/^(0|[1-9][0-9]*)$/.test(rawGold)) throw new Error("金币必须是非负整数。");
    const gold = Number(rawGold);
    if (!Number.isSafeInteger(gold) || gold > GOLD_MAX) throw new Error("金币不能超过 10 亿。");
    changes.gold = gold;
  }
  if (Object.keys(changes).length === 0) throw new Error("没有需要保存的改动。");
  const length = Array.from(reason).length;
  if (length < 8 || length > 200) throw new Error("请填写 8–200 字的修改原因。");
  return { expectedRevision: current.revision, changes, reason };
}

async function saveEdits(event) {
  event.preventDefault();
  showMessage($("edit-error"), "");
  showMessage($("edit-success"), "");
  if (state.mailPending) {
    showMessage($("edit-error"), "请先确认或清空上次邮件发送请求，再修改账号数据。");
    return;
  }
  let payload;
  try { payload = validateEdits(); }
  catch (error) { showMessage($("edit-error"), error.message); return; }
  const id = state.selectedId;
  state.quickSaving = true; updateQuickEditLock(state.quickEditLocked, state.quickEditLockMessage);
  try {
    await api(`/admin/api/accounts/${encodeURIComponent(id)}/legacy`, { method: "PATCH", body: payload });
    if (id !== state.selectedId || !state.token) return;
    await openAccount(id);
    showMessage($("edit-success"), "已写入服务器存档。游戏内重新读取数据后生效。");
    toast("账号数据已保存");
    void loadAccounts();
  } catch (error) {
    if (!state.token) return;
    const conflict = error.status === 409;
    const uncertain = error.status === 502 || error.status === 503 || !error.status;
    if (conflict || uncertain) await openAccount(id);
    const message = conflict
      ? error.code === "active_battle" ? error.message : "存档数据已变化，请核对刷新后的账号详情再修改。"
      : uncertain
        ? "修改结果未确认；已重新读取账号详情，请核对昵称和金币后再操作。"
        : error.message;
    showMessage($("edit-error"), message);
    if (uncertain) toast(message);
  } finally {
    state.quickSaving = false;
    if (state.token && id === state.selectedId) updateQuickEditLock(state.quickEditLocked, state.quickEditLockMessage);
  }
}

function mailEntry(type, id) {
  return state.mailCatalog.find((entry) => entry.type === type && entry.id === id);
}

function updateMailAttachment(row) {
  const type = Number(row.querySelector(".mail-type").value);
  const idSelect = row.querySelector(".mail-id");
  const countInput = row.querySelector(".mail-count");
  const search = row.querySelector(".mail-catalog-search");
  const isCatalog = type === 3 || type === 2;
  search.hidden = !isCatalog;
  const query = isCatalog ? search.value.trim().toLowerCase() : "";
  const previous = idSelect.value;
  idSelect.replaceChildren();
  const entries = state.mailCatalog.filter((entry) => entry.type === type && (!query || `${entry.name} ${entry.id}`.toLowerCase().includes(query)));
  if (!entries.length) {
    const option = element("option", "", query ? "没有匹配的物资，请更换名称或 ID" : "物资目录尚未加载");
    option.value = "";
    idSelect.append(option);
    idSelect.disabled = true;
    countInput.removeAttribute("max");
    return;
  }
  if (isCatalog) {
    const placeholder = element("option", "", `请选择物资 · ${entries.length} 项匹配`);
    placeholder.value = "";
    idSelect.append(placeholder);
  }
  for (const entry of entries) {
    const option = element("option", "", type === 13 || type === 98 ? entry.name : `${entry.name} · ${entry.id}`);
    option.value = String(entry.id);
    idSelect.append(option);
  }
  idSelect.disabled = type === 13 || type === 98 || state.mailSending;
  if (entries.some((entry) => String(entry.id) === previous)) idSelect.value = previous;
  const selected = mailEntry(type, Number(idSelect.value));
  if (!selected) { countInput.removeAttribute("max"); return; }
  countInput.max = String(selected?.maxCount ?? 1);
  if (Number(countInput.value) > Number(countInput.max)) countInput.value = countInput.max;
}

function addMailAttachment() {
  const container = $("mail-attachments");
  if (state.mailSending || container.children.length >= 5 || $("mail-add-attachment").disabled) return;
  const row = element("div", "mail-attachment-row");
  const type = element("select", "mail-type");
  type.setAttribute("aria-label", "物资类型");
  for (const [value, label] of [[13, "金币"], [98, "钻石"], [3, "物品"], [2, "装备"]]) {
    const option = element("option", "", label);
    option.value = String(value);
    type.append(option);
  }
  const id = element("select", "mail-id");
  id.setAttribute("aria-label", "物资名称");
  const search = element("input", "mail-catalog-search");
  search.type = "search";
  search.placeholder = "按道具、装备名称或 ID 查找";
  search.setAttribute("aria-label", "搜索附件物资");
  search.autocomplete = "off";
  const count = element("input", "mail-count");
  count.setAttribute("aria-label", "数量");
  count.type = "number";
  count.min = "1";
  count.step = "1";
  count.value = "1";
  const remove = element("button", "button button-quiet button-small", "移除");
  remove.type = "button";
  remove.addEventListener("click", () => { if (state.mailSending) return; row.remove(); $("mail-add-attachment").disabled = false; });
  type.addEventListener("change", () => { search.value = ""; updateMailAttachment(row); });
  search.addEventListener("input", () => { updateMailAttachment(row); });
  id.addEventListener("change", () => { updateMailAttachment(row); });
  row.append(type, search, id, count, remove);
  container.append(row);
  updateMailAttachment(row);
  $("mail-add-attachment").disabled = container.children.length >= 5;
}

async function loadMailCatalog(id, generation) {
  try {
    const data = await api(`/admin/api/accounts/${encodeURIComponent(id)}/mail/catalog`);
    if (generation !== state.detailGeneration || state.selectedId !== id || !state.token) return;
    if (data?.version !== 1 || !Array.isArray(data.entries)) throw new Error("物资目录格式不正确。");
    state.mailCatalog = data.entries.filter((entry) =>
      Number.isSafeInteger(entry.type) && Number.isSafeInteger(entry.id) &&
      typeof entry.name === "string" && Number.isSafeInteger(entry.maxCount));
    for (const row of $("mail-attachments").children) updateMailAttachment(row);
  } catch (error) {
    if (generation !== state.detailGeneration || state.selectedId !== id || !state.token) return;
    toast(`物资目录未加载：${error.message}；仍可选择金币或钻石。`);
  }
}

function mailDraft() {
  const legacy = state.detail?.legacy;
  if (!legacy?.available || legacy.state?.roleCreated !== true || typeof legacy.revision !== "string") {
    throw new Error("该账号尚不能接收游戏邮件。");
  }
  const sender = $("mail-sender").value;
  const title = $("mail-title").value;
  const content = $("mail-content").value;
  const reason = $("mail-reason").value;
  const texts = [[sender, 1, 24, "发件人"], [title, 1, 60, "标题"],
    [content, 1, 1000, "正文"], [reason, 8, 200, "操作原因"]];
  for (const [value, min, max, label] of texts) {
    if (value.trim() !== value || Array.from(value).length < min || Array.from(value).length > max || /[<>]/.test(value)) {
      throw new Error(`${label}长度或格式不正确。请勿使用首尾空格及尖括号。`);
    }
  }
  const attachments = [];
  const unique = new Set();
  for (const row of $("mail-attachments").children) {
    const type = Number(row.querySelector(".mail-type").value);
    const id = Number(row.querySelector(".mail-id").value);
    const rawCount = row.querySelector(".mail-count").value.trim();
    if (!/^[1-9][0-9]*$/.test(rawCount)) throw new Error("附件数量必须是正整数。");
    const count = Number(rawCount);
    const entry = mailEntry(type, id);
    if (!entry || !Number.isSafeInteger(count) || count > entry.maxCount) {
      throw new Error("附件物资或数量不在原版资源目录中。");
    }
    const key = `${type}:${id}`;
    if (unique.has(key)) throw new Error("同一封邮件不能重复选择同一种物资。");
    unique.add(key);
    attachments.push({ type, id, count });
  }
  return { sender, title, content, reason, attachments };
}

function resetMail() {
  if (state.mailSending) return;
  if (state.mailPending && !window.confirm("上次发送结果尚未确认。请先核对玩家信箱；确定要放弃同一请求编号吗？")) return;
  state.mailPending = null;
  $("mail-sender").value = "新丰洲";
  for (const id of ["mail-title", "mail-content", "mail-reason"]) $(id).value = "";
  $("mail-attachments").replaceChildren();
  $("mail-add-attachment").disabled = false;
  showMessage($("mail-error"), "");
  showMessage($("mail-success"), "");
}

async function sendMail(event) {
  event.preventDefault();
  if (state.mailSending) return;
  if (window.adminData?.isBusy()) { showMessage($("mail-error"), "正在处理玩家数据，请稍后发送邮件。"); return; }
  showMessage($("mail-error"), "");
  showMessage($("mail-success"), "");
  let draft;
  try { draft = mailDraft(); }
  catch (error) { showMessage($("mail-error"), error.message); return; }
  const id = state.selectedId;
  const generation = state.detailGeneration;
  const signature = JSON.stringify(draft);
  if (state.mailPending && (state.mailPending.id !== id || state.mailPending.signature !== signature)) {
    showMessage($("mail-error"), "上次发送结果未确认。请原样重试，或先核对玩家信箱再清空邮件。");
    return;
  }
  if (!state.mailPending) {
    const descriptions = draft.attachments.map((gift) =>
      `${mailEntry(gift.type, gift.id)?.name || gift.id} × ${gift.count}`).join("、") || "无附件";
    if (!window.confirm(`确认发送给 ${state.detail?.account?.email || id}？\n标题：${draft.title}\n附件：${descriptions}`)) return;
    if (!window.crypto?.randomUUID) {
      showMessage($("mail-error"), "当前浏览器无法生成安全请求编号，请使用 HTTPS 管理入口。");
      return;
    }
    state.mailPending = {
      id, signature,
      payload: { ...draft, expectedRevision: state.detail.legacy.revision, requestId: window.crypto.randomUUID() },
    };
  }
  state.mailSending = true;
  const controls = [...$("mail-form").querySelectorAll("input, textarea, select, button")].map((control) => ({ control, disabled: control.disabled }));
  for (const { control } of controls) control.disabled = true;
  try {
    const result = await api(`/admin/api/accounts/${encodeURIComponent(id)}/mail`, {
      method: "POST", body: state.mailPending.payload,
    });
    if (!state.token || id !== state.selectedId || generation !== state.detailGeneration) return;
    state.mailPending = null;
    state.mailSending = false;
    await openAccount(id);
    if (!state.token || id !== state.selectedId) return;
    showMessage($("mail-success"), `已投递到原版信箱（邮件编号 ${result.id}）。附件需玩家在游戏内领取。`);
    toast("游戏邮件已发送");
  } catch (error) {
    if (!state.token || id !== state.selectedId || generation !== state.detailGeneration) return;
    const uncertain = !error.status || error.status === 502 || error.status === 503;
    if (!uncertain) state.mailPending = null;
    showMessage($("mail-error"), uncertain
      ? "发送结果暂不能确认。请保留内容并点击同一个发送按钮重试，不要另建一封。"
      : error.message);
  } finally {
    if (generation === state.detailGeneration) {
      state.mailSending = false;
      if (state.token && id === state.selectedId) for (const { control, disabled } of controls) if (control.isConnected) control.disabled = disabled;
    }
  }
}

async function login(event) {
  event.preventDefault();
  const username = $("admin-username").value.trim();
  const passwordInput = $("admin-password");
  const password = passwordInput.value;
  showMessage($("auth-error"), "");
  $("auth-submit").disabled = true;
  try {
    if (!username || !password) throw new Error("请输入用户名和密码。");
    const result = await api("/admin/api/login", { method: "POST", body: { username, password }, authenticated: false });
    if (!result || typeof result.token !== "string" || !result.token) throw new Error("登录响应格式不正确。");
    state.token = result.token;
    state.expiresAt = typeof result.expiresAt === "string" ? result.expiresAt : "";
    scheduleExpiry();
    if (!state.token) return;
    showDashboard(true);
    passwordInput.value = "";
    await loadAccounts();
  } catch (error) {
    showMessage($("auth-error"), error.status === 401 ? "用户名或密码错误。" : error.message);
  } finally {
    $("auth-submit").disabled = false;
  }
}

async function logout() {
  if (state.mailSending) { toast("邮件正在发送，请等待结果后再退出。"); return; }
  if (window.adminMailCenter && !window.adminMailCenter.canLeave()) return;
  if (window.adminData && !window.adminData.canLeave()) return;
  if (state.mailPending && !window.confirm("邮件发送结果尚未确认。退出会丢失原请求编号，可能无法安全重试。确定退出吗？")) return;
  const oldToken = state.token;
  clearSession();
  if (!oldToken) return;
  try {
    await fetch("/admin/api/logout", { method: "POST", headers: { Authorization: `Bearer ${oldToken}` }, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" });
  } catch { /* 本地会话已经清除。 */ }
}

$("auth-form").addEventListener("submit", (event) => { void login(event); });
$("lock-button").addEventListener("click", () => { void logout(); });
$("reveal-password").addEventListener("click", () => {
  const input = $("admin-password");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  $("reveal-password").textContent = show ? "隐藏" : "显示";
  $("reveal-password").setAttribute("aria-label", show ? "隐藏密码" : "显示密码");
});
$("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  applyAccountFilters();
});
for (const id of ["account-search-field", "account-verified", "account-sort", "account-page-size"]) {
  $(id).addEventListener("change", applyAccountFilters);
}
$("reset-account-filters").addEventListener("click", () => {
  $("account-search").value = "";
  $("account-search-field").value = "all";
  $("account-verified").value = "all";
  $("account-sort").value = "rid_desc";
  $("account-page-size").value = String(DEFAULT_PAGE_SIZE);
  applyAccountFilters();
});
$("prev-page").addEventListener("click", () => {
  if (state.listLoading || state.previousCursors.length === 0) return;
  void loadAccounts(state.previousCursors[state.previousCursors.length - 1], state.previousCursors.slice(0, -1));
});
$("next-page").addEventListener("click", () => {
  if (state.listLoading || !state.nextCursor) return;
  void loadAccounts(state.nextCursor, [...state.previousCursors, state.cursor]);
});
$("refresh-button").addEventListener("click", () => {
  void loadAccounts();
  if (state.selectedId) void openAccount(state.selectedId);
});
$("reset-button").addEventListener("click", resetEdit);
$("edit-form").addEventListener("submit", (event) => { void saveEdits(event); });
$("mail-add-attachment").addEventListener("click", addMailAttachment);
$("mail-reset-button").addEventListener("click", resetMail);
$("mail-form").addEventListener("submit", (event) => { void sendMail(event); });
for (const button of document.querySelectorAll("[data-admin-section]")) {
  button.addEventListener("click", () => switchAdminSection(button.dataset.adminSection));
}
$("open-mail-center").addEventListener("click", () => switchAdminSection("mail"));
document.addEventListener("visibilitychange", () => {
  if (state.token && state.expiresAt) scheduleExpiry();
});
window.addEventListener("beforeunload", (event) => {
  if (!state.mailPending && !state.mailSending && !window.adminData?.hasUnsaved() && !window.adminMailCenter?.hasUnsaved()) return;
  event.preventDefault();
  event.returnValue = "";
});
showDashboard(false);
