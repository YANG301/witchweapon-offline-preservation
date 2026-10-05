"use strict";

// 管理会话、邮件草稿和未确认请求仅保留在页面内存；已提交任务由服务器持久保存。
window.adminMailCenter = (() => {
  const ROOT = "/admin/api/mail";
  const statusLabels = {
    preview: "等待确认", queued: "等待投递", running: "正在投递", paused: "已暂停",
    completed: "投递完成", canceled: "已取消", pending: "等待投递", sending: "正在核实",
    sent: "已送达", failed: "投递失败", skipped: "未满足收件条件",
  };
  const scopeLabels = { all: "全服玩家", filtered: "按账号条件筛选", selected: "指定玩家" };
  const model = {
    open: false, generation: 0, busy: false, catalog: [], catalogLoaded: false,
    selected: new Map(), searchGeneration: 0, preview: null, previewRequest: null,
    pending: null, detail: null, detailGeneration: 0, detailRequest: 0, detailLoading: false, offset: 0,
    nextOffset: null, historyCursor: "", historyPrevious: [], historyNext: "",
    historyRequest: 0, historyLoading: false, timer: 0, previewTimer: 0,
  };

  function message(id, value) { showMessage($(id), value); }
  function amount(value) { return Number.isSafeInteger(value) && value >= 0 ? nf.format(value) : "—"; }
  function date(value) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleString("zh-CN", { hour12: false });
  }
  function expiry(value) { return new Date(value).getTime(); }
  function status(value) { return statusLabels[value] || "状态待核实"; }
  function badge(value) { return element("span", `campaign-status campaign-status-${value}`, status(value)); }
  function accountName(item) { return item.name || item.email || item.accountId || item.id || "玩家"; }
  function catalogEntry(type, id) { return model.catalog.find((entry) => entry.type === type && entry.id === id); }
  function attachmentLabel(gift) { return `${catalogEntry(gift.type, gift.id)?.name || `物资 ${gift.id}`} × ${amount(gift.count)}`; }
  function renderAttachments(node, gifts) {
    node.replaceChildren();
    if (!gifts?.length) { node.append(element("span", "campaign-attachment-chip", "无附件")); return; }
    for (const gift of gifts) node.append(element("span", "campaign-attachment-chip", attachmentLabel(gift)));
  }
  function newRequestID() {
    if (!window.crypto?.randomUUID) throw new Error("当前浏览器无法生成安全请求编号，请使用 HTTPS 管理入口。");
    return window.crypto.randomUUID();
  }
  function isCurrent(generation) { return generation === model.generation && !!state.token; }
  function clearPoll() { clearTimeout(model.timer); model.timer = 0; }
  function schedulePoll() {
    clearPoll();
    if (!model.open || document.hidden || !state.token || !model.detail || model.busy || model.detail.serviceError) return;
    const counts = model.detail.counts || {};
    if (!["queued", "running"].includes(model.detail.status) && !(counts.sending > 0)) return;
    model.timer = setTimeout(() => { void loadDetail(model.detail.id, model.offset, false); }, 5000);
  }
  function hasUnsaved() {
    return !!model.pending || !!model.preview || !!model.selected.size || !!$("campaign-attachments").children.length ||
      ["campaign-title", "campaign-content", "campaign-reason"].some((id) => $(id).value.length > 0) ||
      $("campaign-sender").value !== "新丰洲" || $("campaign-recipient-mode").value !== "selected" ||
      $("campaign-filter-query").value.length > 0 || $("campaign-filter-verified").value !== "all";
  }
  function updateDraftState() { $("campaign-draft-state").textContent = model.pending ? "待核实提交" : model.preview ? "待确认" : hasUnsaved() ? "草稿" : "未提交"; }
  function updateControls() {
    const locked = model.busy || !!model.preview || !!model.pending;
    for (const control of $("campaign-form").querySelectorAll("input, textarea, select, button")) control.disabled = locked;
    $("campaign-add-attachment").disabled = locked || !model.catalogLoaded || $("campaign-attachments").children.length >= 5;
    for (const row of $("campaign-attachments").children) {
      const type = Number(row.querySelector(".campaign-attachment-type").value);
      const id = row.querySelector(".campaign-attachment-id");
      id.disabled = locked || type === 13 || type === 98 || !id.querySelector("option[value]:not([value=''])");
    }
    $("campaign-confirmation").disabled = model.busy || !!model.pending;
    const eligible = model.preview?.counts?.eligible;
    $("campaign-create-button").disabled = model.busy || !!model.pending || !Number.isSafeInteger(eligible) || eligible <= 0 ||
      $("campaign-confirmation").value.trim() !== String(eligible) || expiry(model.preview.expiresAt) <= Date.now();
    $("campaign-review-back").disabled = model.busy || !!model.pending;
    for (const id of ["campaign-pending-check", "campaign-pending-retry"]) $(id).disabled = model.busy;
    for (const control of $("campaign-detail-actions").querySelectorAll("button")) control.disabled = model.busy || model.detailLoading || !!model.detail?.serviceError;
    $("campaign-recipient-prev").disabled = model.busy || model.detailLoading || model.offset <= 0;
    $("campaign-recipient-next").disabled = model.busy || model.detailLoading || model.nextOffset === null;
    $("campaign-history-prev").disabled = model.historyLoading || model.historyPrevious.length === 0;
    $("campaign-history-next").disabled = model.historyLoading || !model.historyNext;
    $("campaign-recipient-status").disabled = model.busy || model.detailLoading;
    $("campaign-form").setAttribute("aria-busy", String(model.busy));
    updateDraftState();
  }

  function renderTargetMode() {
    const mode = $("campaign-recipient-mode").value;
    $("campaign-filter-controls").hidden = mode !== "filter";
    $("campaign-selection-controls").hidden = mode !== "selected";
    $("campaign-target-help").textContent = mode === "all"
      ? "将核对全部账号；只向已经创建游戏角色的玩家投递。新注册账号不会追加到已确认的名单。"
      : mode === "filter" ? "使用账号目录的筛选规则生成固定名单；尚未创建角色的账号会单独列为跳过。"
        : "查询后选择玩家；玩家 RID 会解析为账号 ID，预览时再核对收件资格。";
  }
  function renderSelected() {
    const list = $("campaign-selected-accounts");
    list.replaceChildren();
    if (!model.selected.size) list.append(element("p", "muted mail-center-help", "尚未选择收件人。"));
    for (const [id, account] of model.selected) {
      const chip = element("div", "campaign-selected-account");
      chip.append(element("span", "", `${accountName(account)} · RID ${account.publicRid ?? "—"}`));
      const remove = element("button", "button button-quiet button-small", "移除");
      remove.type = "button";
      remove.setAttribute("aria-label", `移除收件人 ${accountName(account)}`);
      remove.disabled = model.busy || !!model.preview || !!model.pending;
      remove.addEventListener("click", () => {
        if (model.busy || model.preview || model.pending) return;
        model.selected.delete(id); renderSelected(); updateResultButtons(); model.previewRequest = null; updateDraftState();
      });
      chip.append(remove); list.append(chip);
    }
  }
  function updateResultButtons() {
    for (const button of $("campaign-account-results").querySelectorAll("button[data-account-id]")) {
      const selected = model.selected.has(button.dataset.accountId);
      button.disabled = selected || model.busy || !!model.preview || !!model.pending;
      button.textContent = selected ? "已选择" : "选择";
    }
  }
  async function searchAccounts() {
    if (model.busy || model.preview || model.pending) return;
    const q = $("campaign-account-query").value.trim();
    message("campaign-selection-error", "");
    if (!q) { message("campaign-selection-error", "请输入玩家 RID、账号 ID 或邮箱进行查询。"); return; }
    const generation = model.generation, request = ++model.searchGeneration;
    $("campaign-account-search").disabled = true;
    const query = new URLSearchParams({ q, field: $("campaign-account-field").value, verified: "all", sort: "rid_desc", limit: "20" });
    try {
      const data = await api(`/admin/api/accounts?${query}`);
      if (!isCurrent(generation) || request !== model.searchGeneration) return;
      const list = $("campaign-account-results"); list.replaceChildren();
      if (!Array.isArray(data?.items)) throw new Error("玩家查询响应格式不正确。");
      list.append(element("p", "muted mail-center-help", `找到 ${amount(data.total)} 个账号${data.nextCursor ? "，当前仅显示前 20 个，请缩小查询条件" : ""}。`));
      for (const account of data.items) {
        const row = element("div", "campaign-account-result"), copy = element("div", "campaign-account-identity");
        copy.append(element("strong", "", account.email || "未设置邮箱"), element("small", "", `RID ${account.publicRid ?? "—"} · ${account.id}`));
        const choose = element("button", "button button-secondary button-small", "选择"); choose.type = "button"; choose.dataset.accountId = account.id;
        choose.addEventListener("click", () => {
          if (model.busy || model.preview || model.pending) return;
          if (model.selected.size >= 5000) { message("campaign-selection-error", "单个邮件任务最多选择 5,000 个账号。"); return; }
          model.selected.set(account.id, account); model.previewRequest = null; renderSelected(); updateResultButtons(); updateDraftState();
        });
        row.append(copy, choose); list.append(row);
      }
      updateResultButtons();
    } catch (error) {
      if (isCurrent(generation) && request === model.searchGeneration) message("campaign-selection-error", error.message);
    } finally {
      if (isCurrent(generation) && request === model.searchGeneration) $("campaign-account-search").disabled = model.busy || !!model.preview || !!model.pending;
    }
  }

  function updateAttachment(row) {
    const type = Number(row.querySelector(".campaign-attachment-type").value);
    const search = row.querySelector(".campaign-attachment-search"), select = row.querySelector(".campaign-attachment-id"), count = row.querySelector(".campaign-attachment-count");
    const previous = select.value, searchable = type === 2 || type === 3;
    search.hidden = !searchable;
    const q = searchable ? search.value.trim().toLowerCase() : "";
    const entries = model.catalog.filter((entry) => entry.type === type && (!q || `${entry.name} ${entry.id}`.toLowerCase().includes(q)));
    select.replaceChildren();
    if (searchable || !entries.length) {
      const option = element("option", "", entries.length ? `选择物资 · ${amount(entries.length)} 项` : "没有匹配的物资"); option.value = ""; select.append(option);
    }
    for (const entry of entries) { const option = element("option", "", searchable ? `${entry.name} · ${entry.id}` : entry.name); option.value = String(entry.id); select.append(option); }
    if (entries.some((entry) => String(entry.id) === previous)) select.value = previous;
    const selected = catalogEntry(type, Number(select.value));
    if (selected) { count.max = String(selected.maxCount); if (Number(count.value) > selected.maxCount) count.value = String(selected.maxCount); }
    else count.removeAttribute("max");
    updateControls();
  }
  function addAttachment() {
    if (model.busy || model.preview || model.pending || !model.catalogLoaded || $("campaign-attachments").children.length >= 5) return;
    const row = element("div", "campaign-attachment-row");
    const type = element("select", "campaign-attachment-type"); type.setAttribute("aria-label", "附件类型");
    for (const [value, label] of [[13, "金币"], [98, "钻石"], [3, "物品"], [2, "装备"]]) { const option = element("option", "", label); option.value = String(value); type.append(option); }
    const search = element("input", "campaign-attachment-search"); search.type = "search"; search.placeholder = "搜索道具、装备名称或 ID"; search.setAttribute("aria-label", "搜索附件物资"); search.autocomplete = "off";
    const select = element("select", "campaign-attachment-id"); select.setAttribute("aria-label", "附件物资");
    const count = element("input", "campaign-attachment-count"); count.type = "number"; count.min = "1"; count.step = "1"; count.value = "1"; count.setAttribute("aria-label", "每位玩家获得的附件数量");
    const remove = element("button", "button button-quiet button-small", "移除"); remove.type = "button";
    remove.addEventListener("click", () => { if (model.busy || model.preview || model.pending) return; row.remove(); model.previewRequest = null; updateControls(); });
    type.addEventListener("change", () => { search.value = ""; updateAttachment(row); });
    search.addEventListener("input", () => { updateAttachment(row); });
    select.addEventListener("change", () => { updateAttachment(row); });
    row.append(type, search, select, count, remove); $("campaign-attachments").append(row); model.previewRequest = null; updateAttachment(row);
  }
  async function loadCatalog() {
    const generation = model.generation;
    $("campaign-catalog-status").textContent = "正在加载物资目录…";
    try {
      const data = await api(`${ROOT}/catalog`);
      if (!isCurrent(generation)) return;
      if (data?.version !== 1 || !Array.isArray(data.entries)) throw new Error("物资目录格式不正确。");
      model.catalog = data.entries.filter((entry) => Number.isSafeInteger(entry.type) && Number.isSafeInteger(entry.id) && typeof entry.name === "string" && Number.isSafeInteger(entry.maxCount) && entry.maxCount > 0);
      model.catalogLoaded = true;
      $("campaign-catalog-status").textContent = `已加载 ${amount(model.catalog.length)} 项合法物资。附件将在预览时再次校验。`;
      for (const row of $("campaign-attachments").children) updateAttachment(row);
      if (model.detail) renderAttachments($("campaign-detail-attachments"), model.detail.mail?.attachments);
    } catch (error) {
      if (!isCurrent(generation)) return;
      $("campaign-catalog-status").textContent = `物资目录暂不可用：${error.message}；可以先编写无附件通知，重新进入邮件中心会重试加载。`;
    } finally { if (isCurrent(generation)) updateControls(); }
  }
  function validateText(value, min, max, bytes, name, allowNewline = false) {
    if (value.trim() !== value || Array.from(value).length < min || Array.from(value).length > max ||
      new TextEncoder().encode(value).length > bytes || /[<>\p{Cf}]/u.test(value) ||
      (allowNewline ? /[\u0000-\u0009\u000b-\u001f\u007f-\u009f]/u : /[\u0000-\u001f\u007f-\u009f]/u).test(value)) {
      throw new Error(`${name}需 ${min}–${max} 个字，请勿使用首尾空格、尖括号或隐藏控制字符。`);
    }
  }
  function readDraft() {
    const mail = { sender: $("campaign-sender").value, title: $("campaign-title").value, content: $("campaign-content").value, reason: $("campaign-reason").value, attachments: [] };
    validateText(mail.sender, 1, 24, 128, "发件人"); validateText(mail.title, 1, 60, 256, "标题");
    validateText(mail.content, 1, 1000, 4096, "正文", true); validateText(mail.reason, 8, 200, 512, "发送原因");
    const unique = new Set();
    for (const row of $("campaign-attachments").children) {
      const type = Number(row.querySelector(".campaign-attachment-type").value), id = Number(row.querySelector(".campaign-attachment-id").value);
      const raw = row.querySelector(".campaign-attachment-count").value.trim(), count = Number(raw), entry = catalogEntry(type, id);
      if (!/^[1-9][0-9]*$/.test(raw) || !Number.isSafeInteger(count) || !entry || count > entry.maxCount) throw new Error("请从合法目录选择附件，并填写不超过上限的正整数数量。");
      if (unique.has(`${type}:${id}`)) throw new Error("同一封邮件不能重复添加同一种物资。");
      unique.add(`${type}:${id}`); mail.attachments.push({ type, id, count });
    }
    const mode = $("campaign-recipient-mode").value;
    const draft = { scope: mode === "filter" ? "filtered" : mode, ...mail };
    if (draft.scope === "filtered") draft.filter = { q: $("campaign-filter-query").value.trim(), field: $("campaign-filter-field").value, verified: $("campaign-filter-verified").value };
    if (draft.scope === "selected") {
      draft.accountIds = [...model.selected.keys()];
      if (!draft.accountIds.length) throw new Error("请先查询并选择至少一位收件人。");
    }
    return draft;
  }
  function renderCounts(node, counts, preview = false) {
    node.replaceChildren();
    const labels = preview ? [["targeted", "匹配账号"], ["eligible", "可收件玩家"], ["skipped", "跳过账号"]]
      : [["eligible", "收件玩家"], ["sent", "已送达"], ["pending", "等待投递"], ["sending", "正在核实"], ["failed", "失败"], ["canceled", "取消"], ["skipped", "跳过"]];
    for (const [key, label] of labels) { const item = element("div", "campaign-count"); item.append(element("span", "", label), element("strong", "", amount(counts?.[key]))); node.append(item); }
  }
  function renderPreview(data) {
    model.preview = data;
    $("campaign-review").hidden = false; $("campaign-form").hidden = true; $("campaign-pending").hidden = true;
    renderCounts($("campaign-review-summary"), data.counts, true);
    $("campaign-review-sender").textContent = `发件人 / ${data.mail.sender}`;
    $("campaign-review-mail-title").textContent = data.mail.title; $("campaign-review-content").textContent = data.mail.content;
    $("campaign-review-reason").textContent = `发送原因：${data.mail.reason}`;
    renderAttachments($("campaign-review-attachments"), data.mail.attachments);
    const recipients = $("campaign-review-recipients"); recipients.replaceChildren();
    recipients.append(element("strong", "", `${scopeLabels[data.scope] || "收件范围"} · 名单样本`));
    for (const item of data.sample || []) {
      const row = element("div", "campaign-recipient-sample"); row.append(element("span", "", `${accountName(item)} · RID ${item.publicRid ?? "—"}`), badge(item.status));
      if (item.message) row.append(element("small", "", item.message)); recipients.append(row);
    }
    $("campaign-confirmation").value = "";
    $("campaign-review-expiry").textContent = `预览有效至 ${date(data.expiresAt)}。创建后会在后台持续投递，关闭网页不会撤销任务。`;
    clearTimeout(model.previewTimer);
    model.previewTimer = setTimeout(() => {
      if (model.preview !== data) return;
      updateControls();
      $("campaign-review-expiry").textContent = "本次预览已过期。请返回修改并重新预览，核对当前收件名单。";
    }, Math.max(0, expiry(data.expiresAt) - Date.now() + 20));
    if (!(data.counts.eligible > 0)) message("campaign-error", "没有满足收件条件的玩家。请返回修改范围或核对玩家是否已创建角色。");
    updateControls(); $("campaign-review-title").setAttribute("tabindex", "-1"); $("campaign-review-title").focus();
  }
  async function previewMail(event) {
    event?.preventDefault(); if (model.busy || model.preview || model.pending) return;
    message("campaign-error", ""); message("campaign-success", "");
    let draft;
    try {
      draft = readDraft();
      const signature = JSON.stringify(draft);
      if (!model.previewRequest || model.previewRequest.signature !== signature) model.previewRequest = { signature, payload: { ...draft, requestId: newRequestID() } };
    } catch (error) { message("campaign-error", error.message); return; }
    const generation = model.generation;
    model.busy = true; updateControls(); $("campaign-preview-button").textContent = "正在核对角色与收件名单…";
    try {
      const data = await api(`${ROOT}/preview`, { method: "POST", body: model.previewRequest.payload });
      if (!isCurrent(generation)) return;
      if (!data?.id || data.status !== "preview" || !data.mail || !Number.isSafeInteger(data.counts?.eligible) || !Number.isFinite(expiry(data.expiresAt))) throw new Error("预览结果格式不正确，请重新核对收件名单。");
      renderPreview(data);
    } catch (error) { if (isCurrent(generation)) message("campaign-error", error.message); }
    finally {
      if (isCurrent(generation)) { model.busy = false; $("campaign-preview-button").textContent = "预览收件名单与邮件"; updateControls(); }
    }
  }
  function resetComposer(confirmed = false) {
    if (model.busy) return;
    if (model.pending) { message("campaign-error", "请先查询或按原请求重试，核实这次提交结果后再创建另一封邮件。"); return; }
    if (!confirmed && hasUnsaved() && !window.confirm("清空当前邮件草稿和预览？已提交的任务不会受影响。")) return;
    $("campaign-form").reset(); $("campaign-form").hidden = false; $("campaign-review").hidden = true; $("campaign-pending").hidden = true;
    $("campaign-attachments").replaceChildren(); $("campaign-account-results").replaceChildren();
    model.selected.clear(); model.preview = null; model.previewRequest = null; clearTimeout(model.previewTimer); model.previewTimer = 0;
    message("campaign-error", ""); message("campaign-success", ""); message("campaign-selection-error", ""); renderSelected(); renderTargetMode(); updateControls();
  }
  function renderPending() {
    $("campaign-pending").hidden = !model.pending;
    if (model.pending) { $("campaign-pending-id").textContent = model.pending.payload.requestId; $("campaign-review").hidden = true; }
    updateControls();
  }
  async function acceptCreated(data, generation) {
    if (!isCurrent(generation)) return;
    if (!data?.id || data.status === "preview" || !data.counts || !data.mail) throw new Error("提交响应尚未确认，请查询原请求结果。");
    model.pending = null; model.busy = false; resetComposer(true); model.busy = true; updateControls();
    message("campaign-success", `投递任务已创建，将向 ${amount(data.counts.eligible)} 位玩家逐一投递。已送达的邮件无法撤回。`);
    model.detail = data; model.offset = 0; model.nextOffset = null; ++model.detailGeneration; renderDetail(data);
    await Promise.allSettled([loadHistory(), loadDetail(data.id, 0, true)]);
    if (isCurrent(generation)) { toast("邮件投递任务已创建"); schedulePoll(); }
  }
  async function createCampaign(retry = false) {
    if (model.busy) return;
    message("campaign-error", "");
    try {
      if (!model.pending) {
        const preview = model.preview;
        if (!preview || !(preview.counts.eligible > 0) || $("campaign-confirmation").value.trim() !== String(preview.counts.eligible)) throw new Error("请输入预览中的收件人数进行确认。");
        if (expiry(preview.expiresAt) <= Date.now()) throw new Error("预览已过期，请返回重新预览收件名单。");
        model.pending = { payload: { previewId: preview.id, requestId: newRequestID(), confirmation: `发送 ${preview.counts.eligible} 人` } };
      } else if (!retry) return;
    } catch (error) { message("campaign-error", error.message); return; }
    const generation = model.generation; model.busy = true; updateControls();
    try {
      const data = await api(`${ROOT}/campaigns`, { method: "POST", body: model.pending.payload });
      await acceptCreated(data, generation);
    } catch (error) {
      if (!isCurrent(generation)) return;
      const uncertain = !error.status || error.status >= 500;
      if (!uncertain) { model.pending = null; $("campaign-review").hidden = false; }
      message("campaign-error", uncertain ? "服务器响应未确认。原请求编号已保留，请查询结果或原样重试，勿另建相同奖励邮件。" : error.message);
      renderPending();
    } finally { if (isCurrent(generation)) { model.busy = false; updateControls(); schedulePoll(); } }
  }
  async function checkPending() {
    if (!model.pending || model.busy) return;
    const generation = model.generation; model.busy = true; updateControls(); message("campaign-error", "");
    try {
      const data = await api(`${ROOT}/campaigns/by-request/${encodeURIComponent(model.pending.payload.requestId)}`);
      await acceptCreated(data, generation);
    } catch (error) {
      if (isCurrent(generation)) message("campaign-error", error.status === 404 ? "尚未查到该请求创建的任务。请按原请求重试；保持同一个请求编号可避免重复投递。" : error.message);
    } finally { if (isCurrent(generation)) { model.busy = false; updateControls(); } }
  }

  async function loadHistory(cursor = "", previous = []) {
    const generation = model.generation, request = ++model.historyRequest;
    model.historyLoading = true; updateControls(); message("campaign-history-error", "");
    const query = new URLSearchParams({ limit: "20" }); if (cursor) query.set("cursor", cursor);
    try {
      const data = await api(`${ROOT}/campaigns?${query}`);
      if (!isCurrent(generation) || request !== model.historyRequest) return;
      if (!Array.isArray(data?.items)) throw new Error("投递记录格式不正确。");
      model.historyCursor = cursor; model.historyPrevious = previous; model.historyNext = data.nextCursor || "";
      $("campaign-history-count").textContent = `${amount(data.total)} 个任务`;
      $("campaign-history-page").textContent = data.items.length ? `本页 ${amount(data.items.length)} 个任务 · 最近创建在前` : "暂无已确认的投递任务";
      const list = $("campaign-history-list"); list.replaceChildren();
      if (!data.items.length) list.append(element("p", "empty-state", "暂无邮件任务，先编写并预览邮件。"));
      for (const item of data.items) {
        const card = element("button", "campaign-history-card"); card.type = "button"; card.dataset.campaignId = item.id;
        card.classList.toggle("active", item.id === model.detail?.id);
        const heading = element("div", "campaign-history-heading"); heading.append(element("strong", "", item.mail?.title || item.title || "邮件任务"), badge(item.status));
        card.append(heading, element("p", "", `${scopeLabels[item.scope] || "玩家邮件"} · ${amount(item.counts?.eligible)} 人`));
        const counts = item.counts || {}, total = counts.eligible || 0;
        const progress = element("progress", "campaign-progress"); progress.max = Math.max(total, 1); progress.value = (counts.sent || 0) + (counts.failed || 0) + (counts.canceled || 0); progress.setAttribute("aria-label", "已处理收件人数");
        card.append(progress, element("small", "", `送达 ${amount(counts.sent)} · 失败 ${amount(counts.failed)} · 等待 ${amount(counts.pending)} · ${date(item.createdAt)}`));
        card.addEventListener("click", () => { if (model.busy) return; void loadDetail(item.id, 0, true); }); list.append(card);
      }
    } catch (error) {
      if (isCurrent(generation) && request === model.historyRequest) message("campaign-history-error", error.message);
    } finally { if (isCurrent(generation) && request === model.historyRequest) { model.historyLoading = false; updateControls(); } }
  }
  function renderDetail(data) {
    $("campaign-detail").hidden = false; $("campaign-detail-id").textContent = `任务 ${data.id} · ${date(data.createdAt)} · ${status(data.status)}`;
    $("campaign-detail-title").textContent = "投递任务详情"; renderCounts($("campaign-detail-stats"), data.counts);
    $("campaign-detail-sender").textContent = `发件人 / ${data.mail?.sender || "—"}`;
    $("campaign-detail-mail-title").textContent = data.mail?.title || "—"; $("campaign-detail-content").textContent = data.mail?.content || "—";
    $("campaign-detail-reason").textContent = `发送原因：${data.mail?.reason || "—"}`; renderAttachments($("campaign-detail-attachments"), data.mail?.attachments);
    $("campaign-detail-note").textContent = data.status === "paused" ? "暂停后不再开始新的投递；当前正在处理的 1 封仍可能送达。已送达邮件不会重发。"
      : data.status === "canceled" ? "已取消尚未开始的投递。当前正在核实的邮件仍可能送达，已经送达的邮件无法撤回。"
        : data.status === "completed" ? "本轮投递已处理完毕；如有失败，可单独重试失败收件人。奖励由玩家在游戏内领取。"
          : "任务在服务器后台投递。关闭网页不会停止任务；暂停或取消仅影响尚未开始的投递。";
    message("campaign-detail-error", data.serviceError ? `任务已停止自动推进：${data.serviceError}。请刷新核实，勿新建重复邮件。` : "");
    const actions = $("campaign-detail-actions"); actions.replaceChildren();
    const add = (action, label, kind = "button-secondary") => { const button = element("button", `button ${kind}`, label); button.type = "button"; button.addEventListener("click", () => { void controlCampaign(action); }); actions.append(button); };
    if (["queued", "running"].includes(data.status)) add("pause", "暂停后续投递");
    if (data.status === "paused") add("resume", "继续投递");
    if (["queued", "running", "paused"].includes(data.status) && data.counts?.pending > 0) add("cancel", "取消等待中的投递", "button-quiet");
    if (data.status === "completed" && data.counts?.failed > 0) add("retry_failed", `重试 ${amount(data.counts.failed)} 位失败玩家`);
    renderRecipients(data); updateControls();
  }
  function renderRecipients(data) {
    const rows = $("campaign-recipient-rows"); rows.replaceChildren();
    for (const item of data.recipients || []) {
      const row = element("tr"), player = element("td"), result = element("td"), note = element("td");
      player.append(element("strong", "", accountName(item)), element("small", "", `RID ${item.publicRid ?? "—"}`), element("small", "", item.accountId));
      result.append(badge(item.status), element("small", "", `尝试 ${amount(item.attempts || 0)} 次`));
      note.append(element("span", "", item.message || (item.status === "sent" ? `邮件编号 ${item.mailId ?? "—"}` : "—")));
      if (item.updatedAt) note.append(element("small", "", date(item.updatedAt))); row.append(player, result, note); rows.append(row);
    }
    if (!data.recipients?.length) { const row = element("tr"), cell = element("td", "campaign-recipient-empty", "当前状态没有收件人记录。"); cell.colSpan = 3; row.append(cell); rows.append(row); }
    const total = Number.isSafeInteger(data.recipientTotal) ? data.recipientTotal : data.counts?.targeted || 0;
    const count = data.recipients?.length || 0;
    $("campaign-recipient-page").textContent = count ? `第 ${amount(model.offset + 1)}–${amount(model.offset + count)} 位 / 共 ${amount(total)} 位` : `共 ${amount(total)} 位`;
    model.nextOffset = Number.isSafeInteger(data.nextOffset) && data.nextOffset > model.offset && data.nextOffset < total ? data.nextOffset : null;
  }
  async function loadDetail(id, offset = 0, newSelection = false) {
    if (!id) return;
    const generation = model.generation;
    if (newSelection || id !== model.detail?.id) { ++model.detailGeneration; $("campaign-recipient-status").value = "all"; clearPoll(); }
    const detailGeneration = model.detailGeneration, request = ++model.detailRequest;
    model.detailLoading = true; $("campaign-detail-reload").disabled = true; updateControls();
    const query = new URLSearchParams({ limit: "50", offset: String(offset), status: $("campaign-recipient-status").value });
    try {
      const data = await api(`${ROOT}/campaigns/${encodeURIComponent(id)}?${query}`);
      if (!isCurrent(generation) || detailGeneration !== model.detailGeneration || request !== model.detailRequest) return;
      if (data?.id !== id || !data.mail || !data.counts || (data.recipients !== undefined && !Array.isArray(data.recipients))) throw new Error("投递任务详情格式不正确。");
      data.recipients ||= [];
      model.detail = data; model.offset = offset; renderDetail(data);
      for (const card of $("campaign-history-list").querySelectorAll("[data-campaign-id]")) {
        const selected = card.dataset.campaignId === id; card.classList.toggle("active", selected);
        if (!selected) continue;
        const oldBadge = card.querySelector(".campaign-status"); if (oldBadge) oldBadge.replaceWith(badge(data.status));
        const progress = card.querySelector("progress");
        if (progress) { progress.max = Math.max(data.counts.eligible || 0, 1); progress.value = (data.counts.sent || 0) + (data.counts.failed || 0) + (data.counts.canceled || 0); }
        const note = card.querySelector("small"); if (note) note.textContent = `送达 ${amount(data.counts.sent)} · 失败 ${amount(data.counts.failed)} · 等待 ${amount(data.counts.pending)} · ${date(data.createdAt)}`;
      }
      if (newSelection) { $("campaign-detail-title").setAttribute("tabindex", "-1"); $("campaign-detail-title").focus(); }
    } catch (error) {
      if (isCurrent(generation) && detailGeneration === model.detailGeneration && request === model.detailRequest) message("campaign-detail-error", error.message);
    } finally {
      if (isCurrent(generation) && detailGeneration === model.detailGeneration && request === model.detailRequest) { model.detailLoading = false; $("campaign-detail-reload").disabled = false; updateControls(); schedulePoll(); }
    }
  }
  async function controlCampaign(action) {
    if (model.busy || model.detailLoading || !model.detail || model.detail.serviceError) return;
    const data = model.detail;
    if (action === "cancel" && !window.confirm(`取消此任务尚未开始的 ${amount(data.counts.pending)} 封邮件？已送达的邮件无法撤回，当前 1 封仍可能完成。`)) return;
    if (action === "retry_failed" && !window.confirm(`仅重试此任务中 ${amount(data.counts.failed)} 位失败玩家？已经送达的邮件不会再次投递。`)) return;
    const generation = model.generation, detailGeneration = model.detailGeneration;
    model.busy = true; ++model.detailRequest; clearPoll(); updateControls(); message("campaign-detail-error", "");
    try {
      const result = await api(`${ROOT}/campaigns/${encodeURIComponent(data.id)}/control`, { method: "POST", body: { action } });
      if (!isCurrent(generation) || detailGeneration !== model.detailGeneration) return;
      model.detail = result; renderDetail(result);
      await Promise.allSettled([loadHistory(), loadDetail(data.id, model.offset)]);
    } catch (error) {
      if (!isCurrent(generation) || detailGeneration !== model.detailGeneration) return;
      await loadDetail(data.id, model.offset);
      if (isCurrent(generation) && detailGeneration === model.detailGeneration) message("campaign-detail-error", !error.status || error.status >= 500 ? "操作结果未确认，已重新查询任务状态。请核对后再操作。" : error.message);
    } finally { if (isCurrent(generation)) { model.busy = false; updateControls(); schedulePoll(); } }
  }

  async function onOpen() {
    model.open = true;
    if (!state.token) return;
    const actions = [loadHistory(model.historyCursor, model.historyPrevious)];
    if (!model.catalogLoaded) actions.push(loadCatalog());
    if (model.detail) actions.push(loadDetail(model.detail.id, model.offset));
    await Promise.allSettled(actions); schedulePoll();
  }
  function onClose() { model.open = false; clearPoll(); }
  function canLeave() {
    if (model.busy) { toast("邮件操作正在处理，请等待当前结果后再退出。"); return false; }
    if (!hasUnsaved()) return true;
    return window.confirm(model.pending ? "本次提交结果尚未确认。退出会清除页面中的原请求编号；重新登录后请先在投递记录中核对任务，避免另建重复邮件。确定退出？" : "退出会清除未提交的邮件草稿；已创建的投递任务会继续在服务器执行。确定退出？");
  }
  function reset() {
    ++model.generation; ++model.searchGeneration; ++model.historyRequest; ++model.detailGeneration; ++model.detailRequest;
    clearPoll(); model.open = false; model.busy = false; model.catalog = []; model.catalogLoaded = false; model.preview = null; model.previewRequest = null; model.pending = null;
    model.detail = null; model.detailLoading = false; model.offset = 0; model.nextOffset = null; model.historyCursor = ""; model.historyPrevious = []; model.historyNext = ""; model.historyLoading = false;
    resetComposer(true); $("campaign-detail").hidden = true;
    for (const id of ["campaign-history-list", "campaign-recipient-rows", "campaign-detail-actions", "campaign-detail-stats", "campaign-review-recipients", "campaign-review-summary", "campaign-detail-attachments", "campaign-review-attachments"]) $(id).replaceChildren();
    for (const id of ["campaign-error", "campaign-success", "campaign-history-error", "campaign-detail-error", "campaign-selection-error"]) message(id, "");
    $("campaign-history-count").textContent = "—"; $("campaign-history-page").textContent = "最近创建的任务"; $("campaign-catalog-status").textContent = "";
    for (const id of ["campaign-review-sender", "campaign-review-mail-title", "campaign-review-content", "campaign-review-reason", "campaign-pending-id", "campaign-detail-id", "campaign-detail-sender", "campaign-detail-mail-title", "campaign-detail-content", "campaign-detail-reason", "campaign-detail-note"]) $(id).textContent = "";
    $("campaign-detail-reload").disabled = false; updateControls();
  }

  $("campaign-form").addEventListener("submit", (event) => { void previewMail(event); });
  $("campaign-form").addEventListener("input", () => { model.previewRequest = null; updateDraftState(); });
  $("campaign-form").addEventListener("change", () => { model.previewRequest = null; updateDraftState(); });
  $("campaign-recipient-mode").addEventListener("change", renderTargetMode);
  $("campaign-account-field").addEventListener("change", () => { $("campaign-account-query").placeholder = $("campaign-account-field").value === "rid" ? "输入玩家 RID 查找" : "输入账号 ID 或邮箱查找"; });
  $("campaign-account-search").addEventListener("click", () => { void searchAccounts(); });
  $("campaign-account-query").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); void searchAccounts(); } });
  $("campaign-template").addEventListener("change", () => {
    const value = $("campaign-template").value; if (!value) return;
    if ($("campaign-title").value && !window.confirm("用所选模板替换当前标题？正文和附件保持原样。")) { $("campaign-template").value = ""; return; }
    $("campaign-title").value = `【${value}】`; $("campaign-title").focus(); model.previewRequest = null; updateDraftState();
  });
  $("campaign-add-attachment").addEventListener("click", addAttachment);
  $("campaign-reset-button").addEventListener("click", () => resetComposer());
  $("campaign-review-back").addEventListener("click", () => {
    if (model.busy || model.pending) return;
    model.preview = null; model.previewRequest = null; clearTimeout(model.previewTimer); model.previewTimer = 0; $("campaign-review").hidden = true; $("campaign-form").hidden = false; message("campaign-error", ""); updateControls(); renderSelected();
  });
  $("campaign-confirmation").addEventListener("input", updateControls);
  $("campaign-create-button").addEventListener("click", () => { void createCampaign(); });
  $("campaign-pending-check").addEventListener("click", () => { void checkPending(); });
  $("campaign-pending-retry").addEventListener("click", () => { void createCampaign(true); });
  $("campaign-history-reload").addEventListener("click", () => { void loadHistory(); if (model.detail) void loadDetail(model.detail.id, model.offset); });
  $("campaign-history-prev").addEventListener("click", () => { if (model.historyLoading || !model.historyPrevious.length) return; void loadHistory(model.historyPrevious.at(-1), model.historyPrevious.slice(0, -1)); });
  $("campaign-history-next").addEventListener("click", () => { if (model.historyLoading || !model.historyNext) return; void loadHistory(model.historyNext, [...model.historyPrevious, model.historyCursor]); });
  $("campaign-detail-reload").addEventListener("click", () => { if (model.detail) void loadDetail(model.detail.id, model.offset); });
  $("campaign-recipient-status").replaceChildren();
  for (const value of ["all", "pending", "sending", "sent", "failed", "skipped", "canceled"]) { const option = element("option", "", value === "all" ? "全部收件人" : status(value)); option.value = value; $("campaign-recipient-status").append(option); }
  $("campaign-recipient-status").addEventListener("change", () => { if (model.detail) void loadDetail(model.detail.id, 0); });
  $("campaign-recipient-prev").addEventListener("click", () => { if (!model.busy && model.detail && model.offset > 0) void loadDetail(model.detail.id, Math.max(0, model.offset - 50)); });
  $("campaign-recipient-next").addEventListener("click", () => { if (!model.busy && model.detail && model.nextOffset !== null) void loadDetail(model.detail.id, model.nextOffset); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) clearPoll(); else if (model.open && model.detail && state.token) void loadDetail(model.detail.id, model.offset); });
  window.addEventListener("beforeunload", (event) => { if (!hasUnsaved() && !model.busy) return; event.preventDefault(); event.returnValue = ""; });
  renderSelected(); renderTargetMode(); updateControls();
  return { onOpen, onClose, reset, canLeave, isBusy: () => model.busy, hasUnsaved };
})();
