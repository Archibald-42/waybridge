/* Shared by tab recognition, section observation and snapshot URL sanitization. */
function WaybridgeFormURL(value) {
  try {
    const url = new URL(value);
    if (url.origin !== "https://docs.google.com") return null;
    if (/^\/forms\/(?:u\/\d+\/)?d\/(?:e\/)?[A-Za-z0-9_-]+\/(?:viewform|formResponse)\/?$/.test(url.pathname))
      return url.origin + url.pathname.replace(/\/$/, "");
    // Legacy public/embedded forms identify the document in the id parameter.
    const legacy = url.pathname.match(/^\/forms\/(?:u\/\d+\/)?(viewform|formResponse)\/?$/);
    const id = url.searchParams.get("id");
    if (legacy && id && /^[A-Za-z0-9_-]{1,256}$/.test(id))
      return `${url.origin}/forms/d/${id}/${legacy[1]}`;
  } catch (_) { /* Not a valid respondent URL. */ }
  return null;
}
