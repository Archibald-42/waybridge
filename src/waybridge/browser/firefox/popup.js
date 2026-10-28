const toggle = document.getElementById("nordic");
const notice = document.getElementById("notice");
const message = document.getElementById("auto-status");
const confirm = document.getElementById("auto-confirm");
let localError = "";
let changing = false;

async function refresh() {
  try {
    const state = await browser.runtime.sendMessage({action: "status"});
    if (!changing) toggle.checked = Boolean(state.nordic);
    const problem = state.autoConfirm || (state.nordic &&
      /прерван|истекло|ошиб|отозвано|не удалось|неверное|достигла|занята|повтор через/i.test(state.autoMessage || ""));
    notice.hidden = !localError && !problem;
    message.textContent = localError || state.autoMessage || "";
    confirm.hidden = !state.autoConfirm;
  } catch (error) {
    notice.hidden = false;
    message.textContent = error.message;
    confirm.hidden = true;
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
confirm.addEventListener("click", async () => {
  confirm.disabled = true;
  try {
    const result = await browser.runtime.sendMessage({action: "nordic-confirm"});
    if (!result.ok) throw new Error(result.error || "Не удалось подтвердить отправку.");
    localError = "";
  } catch (error) { localError = error.message; }
  finally { confirm.disabled = false; await refresh(); }
});
refresh();
setInterval(refresh, 500);
