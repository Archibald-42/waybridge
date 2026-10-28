/* Auto-export queue and real-page Nordic lifecycle tests; no real Forms data. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {chromium} = require(process.env.WAYBRIDGE_PLAYWRIGHT || 'playwright');
const dir = path.join(__dirname, '../src/waybridge/browser/firefox');
const source = name => fs.readFileSync(path.join(dir, name), 'utf8');
const formTab = {id: 1, active: true, url: 'https://docs.google.com/forms/d/e/fixture/viewform'};
const snapshot = text => ({id: text, warnings: [], page: {url: formTab.url, title: text,
 questions: [{title: text, text, options: [{kind: 'radio', label: 'A', selected: false}]}], images: [], fields: []}});
async function controller() {
 let current = snapshot('one'), fail = false, wait = false, sends = [], disconnected = 0;
 const timers = new Map(); let next = 0;
 const sandbox = {console, URL, TextEncoder, busy: false, HOST: 'test',
  setTimeout: fn => {timers.set(++next, fn);return next;}, clearTimeout: id => timers.delete(id),
  capture: async () => structuredClone(current),
  browser: {storage: {local: {get: async () => ({}), set: async () => {}}},
   permissions: {contains: async () => true}, browserAction: {setBadgeText() {}, setTitle() {}},
   tabs: {query: async () => [], onUpdated: {addListener() {}}, onActivated: {addListener() {}}},
   runtime: {connectNative() {
    let receive, disconnect; const port = {
     onMessage: {addListener(fn) {receive = fn;}}, onDisconnect: {addListener(fn) {disconnect = fn;}},
     disconnect() {disconnected++;disconnect?.();},
     postMessage({snapshot}) {sends.push(snapshot.id);if (!wait) queueMicrotask(() => receive(fail ? {ok:false,error:'offline'} : {ok:true,id:snapshot.id}));}
    };return port;
   }}
  }};
 vm.createContext(sandbox); vm.runInContext(source('section-key.js'), sandbox);
 vm.runInContext(source('nordic.js'), sandbox);
 const control = vm.runInContext('Nordic', sandbox);
 await control.handle({action:'nordic-set',enabled:true}, {});
 return {control, sends, set(value) {current=value;}, fail(value) {fail=value;}, wait(value) {wait=value;},
  key: () => sandbox.WaybridgeSectionKey(current), disconnected: () => disconnected,
  async flush() {await new Promise(resolve => setImmediate(resolve));},
  async tick() {const callbacks=[...timers.values()];timers.clear();for(const fn of callbacks)fn();await this.flush();}};
}
(async () => {
 let run = await controller();
 assert.equal((await run.control.handle({action:'section',key:run.key()},{tab:{...formTab,url:'https://evil.example/forms/d/e/f/viewform'}})).accepted,false);
 assert.equal((await run.control.handle({action:'section',key:run.key()},{tab:formTab})).accepted,true);
 await run.flush();assert.deepEqual(run.sends,['one']);
 await run.control.handle({action:'section',key:run.key()},{tab:formTab});assert.equal(run.sends.length,1);
 run.set(snapshot('two'));run.fail(true);
 await run.control.handle({action:'section',key:run.key()},{tab:formTab});await run.tick();
 assert.equal(run.control.state().queued,1);run.fail(false);await run.tick();
 assert.equal(run.control.state().queued,0);assert.equal(run.sends.at(-1),'two');
 assert(run.sends.filter(id=>id==='two').length>=2);
 const warned=snapshot('three');warned.warnings=['unloaded image'];run.set(warned);
 await run.control.handle({action:'section',key:run.key()},{tab:formTab});await run.flush();
 assert(run.control.state().autoConfirm);assert(!run.sends.includes('three'));
 await run.control.handle({action:'nordic-confirm'},{});await run.flush();assert(run.sends.includes('three'));
 run.wait(true);run.set(snapshot('four'));
 await run.control.handle({action:'section',key:run.key()},{tab:formTab});await run.flush();
 const before=run.disconnected();await run.control.handle({action:'nordic-set',enabled:false},{});await run.flush();
 assert.equal(run.control.state().queued,0);assert(run.disconnected()>before);
 console.log('PASS auto queue: domain restriction, dedup, same-ID retry, warning review, cancellation');
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage();
  await page.route('https://docs.google.com/**', route=>route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'fixtures/form.html'),'utf8')}));
  await page.goto(formTab.url);
  await page.evaluate(() => {window.reports=[];window.browser={runtime:{sendMessage:async m=>{window.reports.push(m);return {accepted:true};}}};});
  for(const name of ['darkreader.js','extract.js','section-key.js','content.js'])await page.addScriptTag({content:source(name)});
  await page.evaluate(() => WaybridgeNordic.set(true));
  await page.waitForFunction(() => window.reports.length===1);
  assert(await page.evaluate(() => DarkReader.isEnabled()));
  const themed = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  assert.notEqual(themed,'rgb(255, 255, 255)');
  await page.evaluate(() => {document.querySelector('input[type="radio"]').checked=true;document.querySelector('textarea')?.dispatchEvent(new Event('input'));});
  await page.waitForTimeout(1700);assert.equal(await page.evaluate(() => window.reports.length),1);
  await page.evaluate(() => {document.querySelector('[role="heading"],legend,h2,h3').textContent='NEW SECTION';});
  await page.waitForFunction(() => window.reports.length===2);
  await page.evaluate(() => WaybridgeNordic.set(false));
  assert.equal(await page.evaluate(() => DarkReader.isEnabled()),false);
  await page.evaluate(() => {document.querySelector('[role="heading"],legend,h2,h3').textContent='AFTER DISABLE';});
  await page.waitForTimeout(1700);assert.equal(await page.evaluate(() => window.reports.length),2);
  console.log('PASS real DOM: Nordic palette, section observer, answer dedup, disable restores page and stops export');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
