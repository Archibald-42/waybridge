/* Explicit opt-in. Bounded RAM queue; delivery is acknowledged by the paired PC. */
const Nordic = (() => {
  let enabled = false, generation = 0, capturing = false, sending = false;
  let queue = [], delivered = new Set(), timer = null, port = null;
  const applying = new Map();
  const imageWait = new Map();
  let problem = false;
  let message = "Nordic и автоэкспорт выключены.";
  const ready = browser.storage.local.get("nordicEnabled").then(value => {
    enabled = value.nordicEnabled === true;
  }).catch(() => { message = "Не удалось прочитать настройки. Режим выключен."; });
  function state() { return {nordic: enabled, autoMessage: message, autoProblem: problem,
    queued: queue.length, autoConfirm: Boolean(queue[0]?.review)}; }
  function badge() {
    browser.browserAction.setBadgeText({text: queue[0]?.review ? "?" : ""});
    browser.browserAction.setTitle({title: `Nordic Reader: ${message}`});
  }
  function isForm(tab) {
    if (!tab || tab.incognito) return false;
    return Boolean(WaybridgeFormURL(tab.url));
  }

  function apply(tabId) {
    if (applying.has(tabId)) return applying.get(tabId).then(() => apply(tabId));
    const operation = inject(tabId).finally(() => applying.delete(tabId));
    applying.set(tabId, operation); return operation;
  }
  async function inject(tabId, token = generation) {
    try {
      const tab = await browser.tabs.get(tabId);
      if (tab.incognito || !/^https?:\/\//.test(tab.url || "")) return;
      const exists = await browser.tabs.executeScript(tabId, {code: "globalThis.WaybridgeNordic?.version === 4"});
      if (!exists[0]) {
        if (!enabled || token !== generation) return;
        await browser.tabs.executeScript(tabId, {code: "globalThis.WaybridgeNordic?.set(false); true"});
        for (const file of ["forms.js", "darkreader.js", "extract.js", "section-key.js", "content.js"])
          await browser.tabs.executeScript(tabId, {file, runAt: "document_idle"});
      }
      // Read current mode after injection: disabling during injection must win.
      await browser.tabs.executeScript(tabId, {code: `globalThis.WaybridgeNordic?.set(${enabled}); true`});
    } catch (error) {
      const tab = await browser.tabs.get(tabId).catch(() => null);
      if (enabled && isForm(tab)) {
        problem = true; message = "Не удалось подключить форму: " + (error.message || String(error)); badge();
      }
    }
  }
  async function applyAll() {
    for (const tab of await browser.tabs.query({})) await apply(tab.id);
  }
  function native(snapshot) {
    return new Promise((resolve, reject) => {
      const connection = browser.runtime.connectNative(HOST);
      port = connection;
      let settled = false;
      const timeout = setTimeout(() => finish(new Error("Истекло время подтверждения ПК.")), 150000);
      function finish(error, result) {
        if (settled) return;
        settled = true; clearTimeout(timeout);
        if (port === connection) port = null;
        connection.disconnect();
        if (error) reject(error); else resolve(result);
      }
      connection.onMessage.addListener(result => finish(null, result));
      connection.onDisconnect.addListener(() => finish(new Error(connection.error?.message || "Соединение с ПК прервано.")));
      try { connection.postMessage({action: "send", snapshot}); }
      catch (error) { finish(error); }
    });
  }
  async function drain() {
    clearTimeout(timer);
    if (!enabled || sending || !queue.length) return;
    if (queue[0].review) {
      problem = true; message = "Нужно подтверждение: " + queue[0].snapshot.warnings.join(" "); badge(); return;
    }
    sending = true;
    const token = generation, item = queue[0];
    try {
      problem = false; message = "Передаю раздел на ПК…"; badge();
      const ack = await native(item.snapshot);
      if (token !== generation) return;
      if (!ack?.ok || ack.id !== item.snapshot.id) throw new Error(ack?.error || "Неверное подтверждение ПК.");
      queue.shift(); delivered.add(item.key);
      if (delivered.size > 64) delivered.delete(delivered.values().next().value);
      problem = false; message = "Раздел сохранён на ПК.";
    } catch (error) {
      if (token === generation) { problem = true; message = `${error.message} Повтор через 15 с; снимок сохранён в памяти.`; }
    } finally {
      sending = false;
      if (enabled) { badge(); timer = setTimeout(drain, queue[0] === item ? 15000 : 0); }
    }
  }
  async function section(key, sender, visit) {
    if (!enabled || !isForm(sender.tab) || !sender.tab.active) return {accepted: false};
    if (typeof key !== "string" || key.length > 1000000) return {accepted: false};
    const session = typeof visit === "string" && /^[A-Za-z0-9_-]{1,96}$/.test(visit) ? visit : String(sender.documentId || sender.tab.id);
    const identity = session + ":" + key;
    if (delivered.has(identity)) return {accepted: true, delivered: true};
    if (queue.some(item => item.key === identity)) return {accepted: true, delivered: false};
    const bytes = queue.reduce((sum, item) => sum + item.bytes, 0);
    if (busy || capturing || queue.length >= 3 || bytes > 32 * 1024 * 1024) {
      problem = true; message = "Очередь занята. Дождитесь сохранения разделов на ПК."; badge();
      return {accepted: false, retryAfter: 5000};
    }
    capturing = true; const token = generation;
    try {
      if (!await browser.permissions.contains({origins: ["<all_urls>"]})) throw new Error("Разрешение доступа к страницам отозвано.");
      const snapshot = await capture(sender.tab.id, () => token !== generation || !enabled, text => { message = text; badge(); });
      if (token !== generation) return {accepted: false};
      if (WaybridgeSectionKey(snapshot) !== key) return {accepted: false, retryAfter: 1800};
      const size = new TextEncoder().encode(JSON.stringify(snapshot)).length;
      if (bytes + size > 64 * 1024 * 1024) throw new Error("Очередь достигла 64 МиБ.");
      if (snapshot.page.images.some(image => !image.loaded)) {
        const started = imageWait.get(identity) || Date.now();
        imageWait.set(identity, started);
        if (imageWait.size > 8) imageWait.delete(imageWait.keys().next().value);
        if (Date.now() - started < 10000) {
          problem = false; message = "Ожидаю загрузки изображений…"; badge();
          return {accepted: false, retryAfter: 1000};
        }
      }
      imageWait.delete(identity);
      queue.push({key: identity, snapshot, bytes: size, review: snapshot.warnings.length > 0});
      if (queue[0].review) { problem = true; message = "Нужно подтверждение: " + queue[0].snapshot.warnings.join(" "); }
      badge(); void drain();
      return {accepted: true, delivered: false};
    } catch (error) {
      if (token === generation) { problem = true; message = error.message; badge(); }
      return {accepted: false, retryAfter: 5000};
    } finally { capturing = false; }
  }
  async function handle(request, sender) {
    await ready;
    if (request.action === "section") return section(request.key, sender, request.visit);
    if (request.action === "nordic-confirm") {
      if (queue[0]) queue[0].review = false;
      void drain(); return {ok: true};
    }
    if (request.action !== "nordic-set") return {ok: false};
    const value = request.enabled === true;
    if (value && !await browser.permissions.contains({origins: ["<all_urls>"]}))
      return {ok: false, error: "Разрешите доступ к страницам в Firefox."};
    // Persist before changing live state, so a failed write cannot claim success.
    await browser.storage.local.set({nordicEnabled: value});
    enabled = value; problem = false; generation++; clearTimeout(timer);
    queue = []; delivered.clear(); imageWait.clear();
    if (port) port.disconnect();
    message = enabled ? "Nordic включён. Активные разделы Google Forms отправляются на ПК." : "Nordic выключен. Очередь автоматической отправки очищена.";
    badge(); await applyAll(); return {ok: true};
  }
  browser.tabs.onUpdated.addListener((id, change) => {
    if (change.status === "complete" || change.url) void ready.then(() => { if (enabled) return apply(id); });
  });
  browser.tabs.onActivated.addListener(info => { void ready.then(() => { if (enabled) return apply(info.tabId); }); });
  void ready.then(async () => {
    if (enabled && !await browser.permissions.contains({origins: ["<all_urls>"]})) enabled = false;
    if (enabled) { message = "Nordic и автоэкспорт Forms включены."; badge(); await applyAll(); }
  });
  return {state, handle, get enabled() { return enabled; }, get capturing() { return capturing; }};
})();
