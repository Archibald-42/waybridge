const statusElement = document.getElementById("status");
const buttons = ["export", "retry", "confirm"].map(id => document.getElementById(id));
async function refresh() {
  try {
    const state = await browser.runtime.sendMessage({action: "status"});
    statusElement.textContent = state.message;
    document.getElementById("nordic").checked = Boolean(state.nordic);
    document.getElementById("auto-status").textContent = `${state.autoMessage || "Режим выключен."} В очереди: ${state.queued || 0}.`;
    document.getElementById("auto-confirm").hidden = !state.autoConfirm;
    document.getElementById("snapshot").textContent = state.snapshot ? "Подготовлен: " + state.snapshot : "";
    buttons.forEach(button => {button.disabled = state.busy;});
    document.getElementById("retry").hidden = !state.retry;
    document.getElementById("confirm").hidden = !state.confirm;
  } catch (error) {statusElement.textContent = error.message;}
}
buttons.forEach(button => button.addEventListener("click", async () => {
  buttons.forEach(item => {item.disabled = true;});
  try {
    if (button.id === "export" && !await browser.permissions.request({origins: ["<all_urls>"]})) {
      statusElement.textContent = "Без разрешения Firefox не позволяет снять весь раздел.";
      return;
    }
    browser.runtime.sendMessage({action: button.id}).catch(error => {statusElement.textContent = error.message;});
  } catch (error) {statusElement.textContent = error.message;}
  finally {await refresh();}
}));
refresh();
setInterval(refresh,500);

document.getElementById("nordic").addEventListener("change", async event => {
  const checkbox = event.target;
  checkbox.disabled = true;
  try {
    if (checkbox.checked && !await browser.permissions.request({origins: ["<all_urls>"]})) {
      checkbox.checked = false;
      statusElement.textContent = "Разрешение необходимо для оформления сайтов и захвата разделов.";
      return;
    }
    const result = await browser.runtime.sendMessage({action: "nordic-set", enabled: checkbox.checked});
    if (!result.ok) throw new Error(result.error);
  } catch (error) { statusElement.textContent = error.message; }
  finally { checkbox.disabled = false; await refresh(); }
});
document.getElementById("auto-confirm").addEventListener("click", async () => {
  await browser.runtime.sendMessage({action: "nordic-confirm"});
  await refresh();
});
