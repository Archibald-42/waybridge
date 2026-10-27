/* Self-contained: executed in Firefox's isolated content-script world. */
function WaybridgeExtract() {
  const visible = element => {
    const css = getComputedStyle(element);
    return element.getClientRects().length > 0 && css.display !== "none" && css.visibility !== "hidden" && !element.closest('[aria-hidden="true"]');
  };
  const clean = value => String(value || "").replace(/\r/g, "").trim();
  const label = element => {
    const ids = (element.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
    const named = ids.map(id => document.getElementById(id)?.innerText || "").join(" ");
    return clean(element.getAttribute("aria-label") || named ||
      (element.labels ? Array.from(element.labels, el => el.innerText).join(" ") : "") ||
      element.innerText || element.getAttribute("placeholder") || element.name || element.type);
  };
  const optionSelector = '[role="radio"],[role="checkbox"],input[type="radio"],input[type="checkbox"]';
  const questionCandidates = Array.from(document.querySelectorAll('[role="listitem"],fieldset'))
    .filter(el => visible(el) && el.querySelector('[role="heading"],legend,h2,h3'));
  const cards = questionCandidates.filter(el => !questionCandidates.some(other => other !== el && el.contains(other)));
  const questions = cards.map((card, index) => ({
    id: `q${String(index + 1).padStart(4, "0")}`,
    title: clean(card.querySelector('[role="heading"],legend,h2,h3')?.innerText),
    text: clean(card.innerText),
    options: Array.from(card.querySelectorAll(optionSelector)).filter(visible)
      .filter(el => !el.parentElement?.closest(optionSelector) || !card.contains(el.parentElement.closest(optionSelector)))
      .map((el, n) => ({id: `o${n + 1}`, kind: el.getAttribute("role") || el.type,
        label: label(el), selected: el.checked === true || el.getAttribute("aria-checked") === "true"}))
  }));
  const fieldSelector = 'input:not([type="password"]):not([type="hidden"]):not([type="file"]):not([type="submit"]):not([type="button"]),textarea,select,[role="radio"],[role="checkbox"]';
  const fields = Array.from(document.querySelectorAll(fieldSelector)).filter(visible).map(el => {
    const kind = el.getAttribute("role") || el.type || el.tagName.toLowerCase();
    const checkable = ["radio", "checkbox"].includes(kind);
    let value = "value" in el ? String(el.value) : label(el);
    if (el.tagName === "SELECT") value = Array.from(el.options).map(option => `${option.selected ? "✓ " : ""}${option.text}`).join("\n");
    return {kind, label: label(el), value, checked: checkable ? el.checked === true || el.getAttribute("aria-checked") === "true" : null};
  });
  const images = Array.from(document.images).filter(visible).map(el => {
    const rect = el.getBoundingClientRect();
    return {alt: clean(el.alt), x: Math.max(0, Math.round(rect.x + scrollX)), y: Math.max(0, Math.round(rect.y + scrollY)),
      width: Math.round(rect.width), height: Math.round(rect.height), loaded: el.complete && el.naturalWidth > 0};
  });
  const warnings = [];
  if (!questions.length) warnings.push("Отдельные вопросы не распознаны. Сохранены весь доступный текст и оригинальный вид раздела.");
  const unloaded = images.filter(image => !image.loaded).length;
  if (unloaded) warnings.push(`Не загрузились изображения: ${unloaded}. Оригинальный вид может быть неполным.`);
  if (Array.from(document.querySelectorAll('[role="combobox"],[role="listbox"]')).some(visible))
    warnings.push("На странице есть раскрывающийся список: не загруженные в документ варианты могут отсутствовать. Сохранён его текущий вид.");
  if (Array.from(document.querySelectorAll("iframe")).some(visible))
    warnings.push("Есть встроенный фрейм: его текст отдельно не извлечён; доступный вид включён в изображение.");
  const geometry = {width: Math.ceil(Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0, innerWidth)),
    height: Math.ceil(Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0, innerHeight)),
    scrollX: Math.max(0, Math.round(scrollX)), scrollY: Math.max(0, Math.round(scrollY)),
    viewportWidth: innerWidth, viewportHeight: innerHeight};
  return {page: {title: document.title, url: location.origin + location.pathname,
    text: clean(document.body?.innerText), questions, fields, images, geometry}, warnings};
}
