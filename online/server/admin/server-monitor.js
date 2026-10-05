"use strict";

// 只读监控；管理令牌与最近 60 个采样点仅存在当前页面内存。
window.adminServerMonitor = (() => {
  const REFRESH_MS = 5000;
  const STALE_MS = 20000;
  const WINDOW_MS = 300000;
  const STORAGE_STALE_MS = 900000;
  const STORAGE_CATEGORIES = [
    ["programs", "服务程序"], ["runtime", "运行与维护环境"], ["resources", "游戏资源"], ["updates", "热更新资源"],
    ["player_data", "账号与玩家存档"], ["admin_data", "管理备份与邮件记录"], ["recovery", "发布与恢复备份"], ["logs", "专用访问日志"],
  ];
  const STORAGE_STATUSES = new Set(["ok", "partial", "stale", "unavailable", "unsupported"]);
  const LEVELS = new Set(["ok", "warning", "critical", "unavailable"]);
  const labels = { ok: "资源正常", warning: "需要关注", critical: "严重告警", unavailable: "无法确认状态", pending: "等待采集" };
  const model = { running: false, generation: 0, busy: false, pollTimer: 0, freshnessTimer: 0, controller: null, sample: null, points: [], issue: null, alertKey: "", storageKey: "" };
  const node = (id) => document.getElementById(id);
  const percent = (value) => `${value.toFixed(1)}%`;
  const validPercent = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;
  const validBytes = (value) => Number.isSafeInteger(value) && value >= 0;
  function bytes(value) {
    if (!validBytes(value)) return "—";
    if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GiB`;
    if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MiB`;
    return `${nf.format(value)} B`;
  }
  function time(value) { return new Date(value).toLocaleTimeString("zh-CN", { hour12: false }); }
  function current(generation) { return model.running && generation === model.generation && !!state.token && !document.hidden; }
  function clearTimers() { clearTimeout(model.pollTimer); clearInterval(model.freshnessTimer); model.pollTimer = 0; model.freshnessTimer = 0; }
  function validateMetric(metric, cpu = false) {
    if (!metric || typeof metric.available !== "boolean") return false;
    if (!metric.available) return true;
    if (!validPercent(metric.usagePercent)) return false;
    if (cpu) return metric.iowaitPercent === undefined || validPercent(metric.iowaitPercent);
    return validBytes(metric.totalBytes) && metric.totalBytes > 0 && validBytes(metric.availableBytes) &&
      validBytes(metric.usedBytes) && metric.availableBytes <= metric.totalBytes && metric.usedBytes <= metric.totalBytes;
  }
  function validate(data) {
    if (!data || !LEVELS.has(data.status) || typeof data.sampledAt !== "string" || !Number.isFinite(Date.parse(data.sampledAt)) ||
      !validateMetric(data.cpu, true) || !validateMetric(data.memory) || !validateMetric(data.disk) || data.disk.mount !== "/" ||
      !Array.isArray(data.alerts) || data.alerts.length > 32 || !data.alerts.every((item) => item &&
        ["warning", "critical"].includes(item.level) && typeof item.id === "string" && typeof item.title === "string" && typeof item.detail === "string")) {
      throw new Error("服务器返回的监控数据不完整，无法确认当前状态。");
    }
    return data;
  }
  function dataIssue() {
    if (model.issue) return model.issue;
    if (!model.sample) return null;
    const age = Date.now() - Date.parse(model.sample.sampledAt);
    if (age > STALE_MS) return { id: "monitor-stale", level: "critical", title: "监控数据已过期", detail: "超过 20 秒没有新的服务器采样，当前读数仅供参考，正在尝试重新读取。" };
    if (age < -30000) return { id: "monitor-clock", level: "critical", title: "无法确认采样时间", detail: "服务器与当前电脑时间相差较大，无法确认监控数据的新鲜度。" };
    return null;
  }
  function alerts(issue) {
    const result = issue ? [issue] : [];
    if (model.sample) result.push(...model.sample.alerts);
    if (!issue && model.sample) {
      for (const [key, title] of [["cpu", "CPU"], ["memory", "内存"], ["disk", "根磁盘"]]) {
        if (key === "cpu" && model.sample.cpu.reason === "warming_up") continue;
        if (!model.sample[key].available && !result.some((item) => item.id.includes(key))) result.push({ id: `monitor-${key}-unavailable`, level: "critical", title: `${title}采集失败`, detail: `目前无法读取${title}数据，不能确认资源是否正常。` });
      }
      if (model.sample.status === "unavailable" && !result.length) result.push({ id: "monitor-unavailable", level: "critical", title: "部分资源无法采集", detail: "服务器未能提供完整监控数据，请稍后刷新并检查服务器。" });
      if (["warning", "critical"].includes(model.sample.status) && !result.length) result.push({ id: "monitor-server-alert", level: model.sample.status, title: "服务器资源需要关注", detail: "服务器已报告资源异常，请查看当前资源读数。" });
    }
    return result;
  }
  function resourceLevel(key, metric) {
    if (!metric?.available) return "pending";
    const related = model.sample.alerts.filter((item) => item.id.toLowerCase().includes(key));
    if (related.some((item) => item.level === "critical")) return "critical";
    if (related.some((item) => item.level === "warning")) return "warning";
    if (key === "memory") return metric.usagePercent >= 95 ? "critical" : metric.usagePercent >= 85 ? "warning" : "ok";
    if (key === "disk") return metric.usagePercent >= 90 ? "critical" : metric.usagePercent >= 80 ? "warning" : "ok";
    return "ok";
  }
  function renderCard(key, issue) {
    const metric = model.sample?.[key];
    const available = !!metric?.available;
    const warming = key === "cpu" && metric?.reason === "warming_up";
    const unavailable = metric && !available && !warming;
    const level = issue || unavailable ? "unavailable" : resourceLevel(key, metric);
    node(`monitor-${key}-card`).dataset.level = level;
    node(`monitor-${key}-state`).textContent = issue ? "读数待更新" : available ? (level === "ok" ? key === "cpu" && metric.usagePercent >= 80 ? "高负载观察中" : "正常" : labels[level]) : metric ? (warming ? "采样中" : "无法采集") : "等待采集";
    node(`monitor-${key}-value`).textContent = available ? percent(metric.usagePercent) : "—";
    const meter = node(`monitor-${key}-meter`);
    // 未知值不能以 0% 表示；没有样本时隐藏进度条。
    meter.hidden = !available;
    if (available) meter.value = metric.usagePercent;
    else meter.removeAttribute("value");
    let detail = "尚未采集";
    if (metric && !available) detail = warming ? "正在建立 CPU 采样，请等待下一次更新。" : "服务器暂时无法读取该项数据。";
    if (available) detail = key === "cpu" ? (validPercent(metric.iowaitPercent) ? `磁盘等待 ${percent(metric.iowaitPercent)}` : "使用率按两次服务器采样的差值计算") : `可用 ${bytes(metric.availableBytes)} / 总计 ${bytes(metric.totalBytes)}`;
    node(`monitor-${key}-detail`).textContent = detail;
  }
  function svgElement(tag, attributes, value) {
    const item = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, attribute] of Object.entries(attributes)) item.setAttribute(key, String(attribute));
    if (value !== undefined) item.textContent = value;
    return item;
  }
  function renderChart(key) {
    const chart = node(`monitor-${key}-chart`);
    const desc = node(`monitor-${key}-chart-summary`);
    chart.replaceChildren(desc);
    const end = model.sample ? Date.parse(model.sample.sampledAt) : Date.now();
    const start = end - WINDOW_MS;
    for (const value of [0, 25, 50, 75, 100]) {
      const y = 182 - value * 1.52;
      chart.append(svgElement("line", { x1: 45, x2: 622, y1: y, y2: y, class: "monitor-chart-grid" }));
      chart.append(svgElement("text", { x: 35, y: y + 4, "text-anchor": "end", class: "monitor-chart-label" }, `${value}%`));
    }
    for (const fraction of [0, .5, 1]) chart.append(svgElement("text", { x: 45 + fraction * 577, y: 210, "text-anchor": fraction === 0 ? "start" : fraction === 1 ? "end" : "middle", class: "monitor-chart-label" }, time(start + fraction * WINDOW_MS)));
    let path = "", previous = null, count = 0, latest = null;
    for (const point of model.points) {
      const value = point[key];
      if (point.at < start || point.at > end || value === null) { previous = null; continue; }
      const x = 45 + (point.at - start) / WINDOW_MS * 577;
      const y = 182 - value * 1.52;
      path += `${previous && point.at - previous.at <= REFRESH_MS * 2 ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)} `;
      previous = point; latest = { x, y, value }; count++;
    }
    if (path) chart.append(svgElement("path", { d: path.trim(), class: "monitor-chart-line" }));
    if (latest) chart.append(svgElement("circle", { cx: latest.x, cy: latest.y, r: 3, class: "monitor-chart-point" }));
    node(`monitor-${key}-chart-empty`).hidden = count > 0;
    node(`monitor-${key}-trend-start`).textContent = time(start);
    const currentValue = model.sample?.[key]?.available ? model.sample[key].usagePercent : null;
    node(`monitor-${key}-trend-current`).textContent = `${dataIssue() ? "上次" : "当前"} ${currentValue === null ? "—" : percent(currentValue)}`;
    desc.textContent = count ? `最近 5 分钟内有 ${count} 个有效采样点，最新有效读数 ${percent(latest.value)}。空白或断线处表示没有有效采样。` : "尚无有效采样。";
  }
  function renderAlerts(items, level) {
    const key = JSON.stringify({ items, level });
    if (key === model.alertKey) return;
    model.alertKey = key;
    const list = node("monitor-alert-list"); list.replaceChildren();
    node("monitor-alert-count").textContent = model.sample || model.issue ? `${items.length} 项告警` : "等待采集";
    if (!items.length) list.append(element("p", "monitor-alert-empty", model.sample ? "当前没有资源告警。" : "正在读取服务器数据…"));
    for (const item of items) {
      const article = element("article", "monitor-alert-item"); article.dataset.level = item.level;
      article.append(element("span", "monitor-alert-level", item.level === "critical" ? "严重" : "提醒"));
      const copy = element("div", "monitor-alert-copy"); copy.append(element("h4", "", item.title), element("p", "", item.detail)); article.append(copy); list.append(article);
    }
    const banner = node("monitor-global-alert"); banner.hidden = !items.length; banner.dataset.level = level;
    if (items.length) {
      node("monitor-global-title").textContent = `${level === "critical" || level === "unavailable" ? "服务器告警" : "服务器资源提醒"} · ${items.length} 项`;
      node("monitor-global-detail").textContent = items.slice(0, 3).map((item) => item.title).join("；") + (items.length > 3 ? "；查看全部告警" : "。请查看监控详情。");
    } else { node("monitor-global-title").textContent = ""; node("monitor-global-detail").textContent = ""; }
  }
  function validStorage(data) {
    const nullableBytes = (value) => value === null || validBytes(value);
    return data && typeof data.available === "boolean" && STORAGE_STATUSES.has(data.status) &&
      (data.sampledAt === null || typeof data.sampledAt === "string" && Number.isFinite(Date.parse(data.sampledAt))) &&
      (!["ok", "partial", "stale"].includes(data.status) || data.sampledAt !== null) &&
      nullableBytes(data.allocatedBytes) && nullableBytes(data.confirmedAllocatedBytes) && Array.isArray(data.items) && data.items.length <= STORAGE_CATEGORIES.length &&
      new Set(data.items.map((item) => item?.id)).size === data.items.length && data.items.every((item) => item &&
        STORAGE_CATEGORIES.some(([id]) => id === item.id) && typeof item.available === "boolean" && ["ok", "partial", "unavailable"].includes(item.status) &&
        nullableBytes(item.allocatedBytes) && nullableBytes(item.fileCount) && typeof item.detail === "string");
  }
  function renderStorage(issue) {
    const raw = model.sample?.disk.breakdown;
    const invalid = raw !== undefined && !validStorage(raw);
    const data = !invalid ? raw : null;
    const age = data?.sampledAt ? Date.now() - Date.parse(data.sampledAt) : null;
    const stale = data?.status === "stale" || age !== null && age > STORAGE_STALE_MS;
    const clockMismatch = age !== null && age < -30000;
    const status = stale ? "stale" : clockMismatch || invalid ? "unavailable" : data?.status || "unavailable";
    const reference = stale || !!issue || clockMismatch;
    const key = JSON.stringify({ data, invalid, status, reference, diskTotal: model.sample?.disk.available ? model.sample.disk.totalBytes : null });
    if (key === model.storageKey) return;
    model.storageKey = key;
    const stateLabels = { ok: "统计完整", partial: "部分统计", stale: "统计已过期", unavailable: "无法统计", unsupported: "当前环境不支持" };
    const badge = node("monitor-storage-state"); badge.dataset.status = reference && status === "ok" ? "stale" : status;
    badge.textContent = !raw && !invalid ? "尚未统计" : reference && status === "ok" ? "上次统计 · 待更新" : stateLabels[status];
    const complete = status === "ok" && data?.available && validBytes(data.allocatedBytes);
    const hasStatistics = !!data?.sampledAt && ["ok", "partial", "stale"].includes(data.status);
    const confirmed = hasStatistics && validBytes(data?.confirmedAllocatedBytes) ? data.confirmedAllocatedBytes : null;
    const total = complete ? data.allocatedBytes : reference && hasStatistics && validBytes(data?.allocatedBytes) ? data.allocatedBytes : confirmed;
    const lowerBound = !complete && !(reference && hasStatistics && validBytes(data?.allocatedBytes));
    node("monitor-storage-total-label").textContent = reference ? "上次统计占用（参考）" : lowerBound && total !== null ? "已确认游戏占用下限" : "游戏相关磁盘占用";
    node("monitor-storage-total").textContent = total === null ? "—" : `${lowerBound ? "至少 " : ""}${bytes(total)}`;
    const disk = model.sample?.disk;
    node("monitor-storage-ratio").textContent = total !== null && disk?.available && disk.totalBytes > 0 ? `${reference ? "参考：" : ""}占整盘容量${lowerBound ? "至少 " : " "}${percent(total / disk.totalBytes * 100)}` : "占整盘容量 —";
    node("monitor-storage-sampled-at").textContent = data?.sampledAt ? `统计于 ${new Date(data.sampledAt).toLocaleString("zh-CN", { hour12: false })}` : "尚无统计时间";
    node("monitor-storage-summary-note").textContent = total === null ? "尚无可确认的游戏占用总量。" : reference ? "此为上次统计，仅供参考；当前占用需等待更新确认。" : lowerBound ? "部分目录未完成统计，总量仍可能增加。" : "包含程序、资源、存档及游戏专用管理数据。";
    let notice = "";
    if (invalid) notice = "占用分布数据不完整，无法确认游戏占用；CPU、内存与根磁盘监控仍独立更新。";
    else if (clockMismatch) notice = "统计时间与当前电脑时间相差较大，无法确认分布的新鲜度；读数仅供参考。";
    else if (stale) notice = "占用分布超过 15 分钟未更新；保留的旧数据仅供参考，不代表当前磁盘占用。";
    else if (issue && data) notice = "监控连接异常，以下为上次占用分布；网络与采集恢复后会重新读取。";
    else if (status === "partial") notice = "部分目录无法完成统计。已确认占用是下限；分类比例仅针对已统计游戏占用，不代表完整游戏总量。";
    else if (status === "unsupported") notice = "当前服务器运行环境不支持这项目录统计。";
    else if (status === "unavailable") notice = raw ? "暂时无法读取占用分布，请等待服务器完成统计后刷新。" : "尚未取得占用分布。服务器完成统计后会自动显示，未知占用不会记为 0。";
    node("monitor-storage-notice").hidden = !notice; node("monitor-storage-notice").textContent = notice;
    const list = node("monitor-storage-items"); list.replaceChildren();
    // 分类条只以明确标注的已统计总量为分母；不推算根盘“其它系统”占用。
    const denominator = confirmed !== null ? confirmed : total;
    for (const [id, label] of STORAGE_CATEGORIES) {
      const item = data?.items.find((candidate) => candidate.id === id);
      const known = !!item && validBytes(item.allocatedBytes) && hasStatistics && (item.available || item.status === "partial" || reference);
      const partial = item?.status === "partial";
      const row = element("article", "monitor-storage-item"); row.dataset.status = !known ? "unavailable" : reference ? "stale" : partial ? "partial" : "ok";
      const heading = element("div", "monitor-storage-item-heading");
      const title = element("div", "monitor-storage-item-title"); title.append(element("strong", "", label));
      if (reference && known || partial || !known) title.append(element("span", "", !known ? "未统计" : reference ? "上次统计" : "部分统计"));
      const amount = element("div", "monitor-storage-item-amount"); amount.append(element("strong", "", known ? `${partial ? "至少 " : ""}${bytes(item.allocatedBytes)}` : "—"));
      const share = known && denominator !== null && denominator > 0 ? item.allocatedBytes / denominator * 100 : known && item.allocatedBytes === 0 && denominator === 0 ? 0 : null;
      amount.append(element("span", "", share === null ? "占已统计游戏占用 —" : `占已统计游戏占用 ${percent(share)}`));
      heading.append(title, amount); row.append(heading);
      const meter = element("progress", ""); meter.max = 100; meter.hidden = share === null;
      meter.setAttribute("aria-label", `${label}占已统计游戏占用的比例`); if (share !== null) meter.value = Math.min(100, share); row.append(meter);
      const detail = element("p", "monitor-storage-item-detail");
      const fileCount = known && validBytes(item?.fileCount) ? `${partial ? "至少 " : ""}${nf.format(item.fileCount)} 个文件` : "文件数未统计";
      detail.textContent = item ? `${fileCount}${item.detail ? ` · ${item.detail}` : ""}` : "尚无该分类的统计数据"; row.append(detail); list.append(row);
    }
  }
  function render(charts = false) {
    const issue = dataIssue();
    const items = alerts(issue);
    const level = issue || model.sample?.status === "unavailable" ? "unavailable" : items.some((item) => item.level === "critical") ? "critical" : items.length ? "warning" : model.sample?.cpu.available ? "ok" : "pending";
    node("monitor-overall-status").textContent = level === "pending" && model.sample ? "CPU 采样中" : labels[level]; node("monitor-overall-status").dataset.level = level;
    for (const key of ["cpu", "memory", "disk"]) renderCard(key, issue);
    for (const key of ["cpu", "memory"]) node(`monitor-${key}-trend-current`).textContent = `${issue ? "上次" : "当前"} ${model.sample?.[key]?.available ? percent(model.sample[key].usagePercent) : "—"}`;
    node("monitor-update-time").textContent = model.sample ? `最近采样 ${new Date(model.sample.sampledAt).toLocaleString("zh-CN", { hour12: false })}${issue ? " · 读数待更新" : ""}` : "尚未读取服务器数据";
    node("monitor-refresh-state").textContent = document.hidden ? "页面隐藏，已暂停请求" : model.busy ? "正在读取服务器…" : "页面可见时每 5 秒刷新";
    node("monitor-refresh").disabled = model.busy || !model.running;
    node("monitor-data-warning").hidden = !issue; node("monitor-data-warning").textContent = issue ? `${issue.title}：${issue.detail}` : "";
    renderAlerts(items, level);
    renderStorage(issue);
    if (charts) { renderChart("cpu"); renderChart("memory"); }
  }
  function schedule() {
    clearTimeout(model.pollTimer);
    if (model.running && state.token && !document.hidden) model.pollTimer = setTimeout(() => { void poll(); }, REFRESH_MS);
  }
  async function poll() {
    if (!model.running || !state.token || document.hidden || model.busy) return;
    clearTimeout(model.pollTimer); model.pollTimer = 0;
    const generation = model.generation;
    const controller = new AbortController(); model.controller = controller; model.busy = true; render();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch("/admin/api/monitor", { method: "GET", headers: { Accept: "application/json", Authorization: `Bearer ${state.token}` }, cache: "no-store", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer", signal: controller.signal });
      if (!current(generation)) return;
      if (response.status === 401) { clearSession("管理会话已过期，请重新进入。监控已停止。"); return; }
      if (!response.ok) throw new Error(`监控请求失败（HTTP ${response.status}），无法确认服务器状态。`);
      const data = validate(await response.json());
      if (!current(generation)) return;
      const at = Date.parse(data.sampledAt);
      model.sample = data; model.issue = null;
      if (!model.points.length || at > model.points.at(-1).at) {
        model.points.push({ at, cpu: data.cpu.available ? data.cpu.usagePercent : null, memory: data.memory.available ? data.memory.usagePercent : null });
        model.points = model.points.filter((point) => point.at >= at - WINDOW_MS).slice(-60);
      }
      render(true);
    } catch (error) {
      if (!current(generation)) return;
      model.issue = { id: "monitor-fetch", level: "critical", title: "监控连接异常", detail: controller.signal.aborted ? "监控请求超过 8 秒没有完成，无法确认当前服务器状态；保留的旧读数仅供参考。" : error instanceof SyntaxError ? "服务器返回的监控数据无法读取，无法确认当前状态。" : error.message === "Failed to fetch" || !navigator.onLine ? "网络连接中断，无法确认当前服务器状态；保留的旧读数仅供参考。" : error.message || "无法读取服务器监控，请检查网络连接。" };
      render();
    } finally {
      clearTimeout(timeout);
      if (generation === model.generation) { model.busy = false; model.controller = null; if (model.running) { render(); schedule(); } }
    }
  }
  function reset() {
    ++model.generation; clearTimers(); model.controller?.abort(); model.controller = null;
    model.running = false; model.busy = false; model.sample = null; model.points = []; model.issue = null; model.alertKey = ""; model.storageKey = "";
    render(true); node("monitor-global-alert").hidden = true;
  }
  function startFreshness() {
    clearInterval(model.freshnessTimer);
    if (model.running && !document.hidden) model.freshnessTimer = setInterval(() => { if (model.running && state.token && !document.hidden) render(); }, 1000);
  }
  function start() { reset(); model.running = true; startFreshness(); render(); void poll(); }
  function onOpen() { if (model.running) { render(true); void poll(); } }
  node("monitor-refresh").addEventListener("click", () => { void poll(); });
  node("monitor-open-alert").addEventListener("click", () => switchAdminSection("monitor"));
  document.addEventListener("visibilitychange", () => {
    if (!model.running) return;
    if (document.hidden) { ++model.generation; clearTimers(); model.controller?.abort(); model.controller = null; model.busy = false; render(); }
    else { startFreshness(); render(true); void poll(); }
  });
  window.addEventListener("offline", () => {
    if (!model.running || document.hidden) return;
    model.issue = { id: "monitor-offline", level: "critical", title: "网络已断开", detail: "当前页面无法连接服务器，不能确认资源是否正常。网络恢复后会重新采样。" }; render();
  });
  window.addEventListener("online", () => { if (model.running && !document.hidden) void poll(); });
  reset();
  return { start, reset, onOpen };
})();
