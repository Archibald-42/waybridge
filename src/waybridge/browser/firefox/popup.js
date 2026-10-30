const toggle = document.getElementById("nordic");
const notice = document.getElementById("notice");
const message = document.getElementById("auto-status");
const access = document.getElementById("export-access");
let localError = "";
let changing = false;

async function refresh() {
  try {
    const state = await browser.runtime.sendMessage({action: "status"});
    if (!changing) toggle.checked = Boolean(state.nordic);
    const allowed = await browser.permissions.contains({origins: ["<all_urls>"]});
    access.hidden = allowed;
    const problem = state.autoProblem;
    notice.hidden = !localError && !problem;
    message.textContent = localError || state.autoMessage || "";

  } catch (error) {
    notice.hidden = false;
    message.textContent = error.message;

  }
}
toggle.addEventListener("change", async () => {
  changing = true; toggle.disabled = true; localError = "";
  try {
    if (toggle.checked && !await browser.permissions.request({origins: ["<all_urls>"]}))
      throw new Error("Firefox не предоставил разрешение для этого режима.");
    const result = await browser.runtime.sendMessage({action: "nordic-set", enabled: toggle.checked});
    if (!result.ok) throw new Error(result.error || "Не удалось изменить режим.");
  } catch (error) { localError = error.message; }
  finally { changing = false; toggle.disabled = false; await refresh(); }
});
access.addEventListener("click", async () => {
  access.disabled = true;
  try {
    if (!await browser.permissions.request({origins: ["<all_urls>"]})) throw new Error("Разрешение Firefox не предоставлено.");
    const result = await browser.runtime.sendMessage({action: "nordic-access"});
    if (!result.ok) throw new Error(result.error || "Не удалось подключить страницы.");
    localError = "";
  } catch (error) { localError = error.message; }
  finally { access.disabled = false; await refresh(); }
});
refresh();
setInterval(refresh, 500);
