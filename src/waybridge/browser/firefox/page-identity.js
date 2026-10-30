/* Section identity excludes answers, selection and scroll position. */
function WaybridgeSectionKey(doc) {
  const page = doc.page;
  return JSON.stringify({url: page.url, title: page.title,
    questions: page.questions.map(q => ({title: q.title, text: q.text,
      options: q.options.map(o => ({label: o.label, kind: o.kind}))})),
    images: page.images.map(i => ({alt: i.alt, loaded: i.loaded})),
    fallback: page.questions.length ? "" : page.text});
}
