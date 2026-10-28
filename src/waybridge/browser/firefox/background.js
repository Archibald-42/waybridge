/* Manual exports and the common immutable snapshot capture pipeline. */
const HOST = "org.waybridge.page_export";
const LIMIT = 32 * 1024 * 1024;
let pending = null;
let busy = false;
let status = {stage: "idle", message: "Готов к экспорту текущего раздела.", retry: false, confirm: false};

function report(stage, message, extra = {}) {
  status = {stage, message, retry: Boolean(pending), confirm: false,
    snapshot: pending ? `${pending.page.title} · ${pending.created_at}` : "", ...extra};
  browser.browserAction.setBadgeText({text: busy ? "…" : stage === "sent" ? "OK" : stage === "error" ? "!" : ""});
  browser.browserAction.setTitle({title: `Waybridge: ${message}`});
}
async function extract(tabId) {
  const result = await browser.tabs.executeScript(tabId, {code: `(${WaybridgeExtract.toString()})()`});
  if (result.length !== 1) throw new Error("Не удалось прочитать основной документ вкладки.");
  return result[0];
}
async function capture(tabId = null, cancelled = () => false, progress = message => report("capturing", message)) {
  const tabs = await browser.tabs.query(tabId === null ? {active: true, currentWindow: true} : {active: true});
  const selected = tabId === null ? tabs[0] : tabs.find(item => item.id === tabId);
  if (tabId !== null && !selected) throw new Error("Вкладка больше не активна.");
  if (!selected || !/^https?:\/\//.test(selected.url || "")) throw new Error("Откройте обычную HTTP/HTTPS-страницу для экспорта.");
  if (selected.incognito) throw new Error("Экспорт из приватных вкладок отключён: снимок сохраняется на ПК.");
  const before = await extract(selected.id);
  const {width, height} = before.page.geometry;
  if (width > 8192 || height > 100000 || width * height > 80000000) throw new Error("Раздел слишком большой для одного снимка. Предельная площадь — 80 млн пикселей.");
  const tiles = [];
  let encodedBytes = 0;
  for (let y = 0; y < height; y += 4096) {
    if (cancelled()) throw new Error("Автоэкспорт отключён.");
    progress(`Снимаю раздел: ${Math.round(y / height * 100)}%.`);
    const tileHeight = Math.min(4096, height - y);
    const png = await browser.tabs.captureTab(selected.id, {format: "png", rect: {x: 0, y, width, height: tileHeight}, scale: 1});
    if (!png.startsWith("data:image/png;base64,")) throw new Error("Firefox не вернул PNG.");
    tiles.push({x: 0, y, width, height: tileHeight, png});
    encodedBytes += png.length;
    if (encodedBytes > LIMIT) throw new Error("Снимок превышает 32 МиБ. Раздел не отправлен.");
  }
  if (cancelled()) throw new Error("Автоэкспорт отключён.");
  const after = await extract(selected.id);
  if (JSON.stringify(before) !== JSON.stringify(after)) throw new Error("Страница изменилась во время экспорта. Повторите после завершения изменений.");
  const snapshot = {format: "waybridge-page/1", id: crypto.randomUUID().replaceAll("-", ""),
    created_at: new Date().toISOString(), scope: "current-section", ...before, tiles};
  if (new TextEncoder().encode(JSON.stringify(snapshot)).length > LIMIT) throw new Error("Снимок превышает 32 МиБ вместе с текстом.");
  return snapshot;
}
async function deliver() {
  if (!pending) throw new Error("Нет подготовленного снимка. Выполните новый экспорт.");
  report("sending", "Передаю на ПК и жду подтверждения сохранения…");
  const result = await browser.runtime.sendNativeMessage(HOST, {action: "send", snapshot: pending});
  if (!result?.ok || result.id !== pending.id) throw new Error(result?.error || "Неверное подтверждение приёмника.");
  const count = pending.page.questions.length;
  pending = null;
  report("sent", `Снимок сохранён на ПК. Вопросов: ${count}.`, {retry: false});
}
browser.runtime.onMessage.addListener(async (message, sender) => {
  if (message.action?.startsWith("nordic-") || message.action === "section") return Nordic.handle(message, sender);
  if (message.action === "status") return {...status, busy, ...(typeof Nordic !== "undefined" ? Nordic.state() : {})};
  if (busy || (typeof Nordic !== "undefined" && Nordic.capturing)) return {ok: false, error: "Экспорт уже выполняется."};
  if (!["export", "retry", "confirm"].includes(message.action)) return {ok: false, error: "Неизвестная команда."};
  busy = true;
  try {
    if (message.action === "export") {
      // Request permission in popup click handler; here no permission prompts.
      if (!await browser.permissions.contains({origins: ["<all_urls>"]})) throw new Error("Для полного изображения раздела требуется разрешение захвата вкладок.");
      pending = null;
      report("capturing", "Читаю содержимое открытого раздела…");
      pending = await capture();
      if (pending.warnings.length) {
        report("review", pending.warnings.join("\n"), {confirm: true, retry: false});
        return {ok: true};
      }
    }
    await deliver();
    return {ok: true};
  } catch (error) {
    report("error", error.message || String(error));
    return {ok: false, error: status.message};
  } finally {
    busy = false;
    browser.browserAction.setBadgeText({text: status.stage === "sent" ? "OK" : status.stage === "error" ? "!" : status.stage === "review" ? "?" : typeof Nordic !== "undefined" && Nordic.enabled ? "ON" : ""});
  }
});
