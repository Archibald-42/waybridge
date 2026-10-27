const statusElement = document.getElementById("status");
const buttons = ["export", "retry", "confirm"].map(id => document.getElementById(id));
async function refresh() {
  try {
    const state = await browser.runtime.sendMessage({action: "status"});
    statusElement.textContent = state.message;
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
