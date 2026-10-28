/* One controller per document, including repeated tab activations. */
(() => {
  if (globalThis.WaybridgeNordic?.version === 3) return;
  if (globalThis.WaybridgeNordic) void globalThis.WaybridgeNordic.set(false);
  let enabled = false, timer = null, inFlight = false, lastKey = null, scheduledAt = 0;
  const form = () => Boolean(WaybridgeFormURL(location.href));
  function schedule(delay = 1400) {
    clearTimeout(timer);
    if (enabled && form() && !document.hidden) {
      const now = Date.now();
      if (delay === 1400) {
        if (!scheduledAt) scheduledAt = now;
        delay = Math.min(delay, Math.max(0, 5000 - (now - scheduledAt)));
      } else scheduledAt = 0;
      timer = setTimeout(check, delay);
    }
  }
  async function check() {
    scheduledAt = 0;
    if (!enabled || document.hidden) return;
    if (inFlight) { schedule(1000); return; }
    inFlight = true;
    try {
      const key = WaybridgeSectionKey(WaybridgeExtract());
      if (key === lastKey) return;
      const result = await browser.runtime.sendMessage({action: "section", key});
      if (enabled && result?.accepted) lastKey = key;
      else if (enabled) schedule(result?.retryAfter || 5000);
    } catch (_) { schedule(5000); }
    finally { inFlight = false; }
  }
  const observer = new MutationObserver(records => {
    // Theme-generated styles and editable answers are not new sections.
    if (records.some(r => {
      const el = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      if (r.type === "attributes" && (r.attributeName.startsWith("data-darkreader") ||
          el?.classList.contains("darkreader"))) return false;
      return el && !el.closest('style,script,input,textarea,[contenteditable="true"]') &&
        (r.type !== "childList" || [...r.addedNodes, ...r.removedNodes].some(n =>
          n.nodeType !== 1 || !n.matches('style,script,link.darkreader')));
    })) schedule();
  });
  async function set(value) {
    enabled = Boolean(value); lastKey = null; scheduledAt = 0;
    clearTimeout(timer); observer.disconnect();
    if (enabled) {
      DarkReader.setFetchMethod(url => fetch(url, {credentials: "omit"}));
      DarkReader.enable({mode: 1, brightness: 100, contrast: 100, sepia: 0,
        darkSchemeBackgroundColor: "#2e3440", darkSchemeTextColor: "#d8dee9",
        selectionColor: "#5e81ac"});
      if (form()) observer.observe(document.documentElement, {subtree: true, childList: true,
        characterData: true, attributes: true, attributeFilter: ["hidden", "aria-hidden", "src", "class", "style"]});
      schedule();
    } else DarkReader.disable();
  }
  globalThis.WaybridgeNordic = {version: 3, set};
  document.addEventListener("visibilitychange", () => schedule());
  document.addEventListener("load", () => schedule(), true);
  document.addEventListener("error", () => schedule(), true);
})();
