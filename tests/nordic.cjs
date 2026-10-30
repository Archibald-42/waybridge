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
 vm.createContext(sandbox); vm.runInContext(source('forms.js'), sandbox); vm.runInContext(source('section-key.js'), sandbox);
 vm.runInContext(source('nordic.js'), sandbox);
 const control = vm.runInContext('Nordic', sandbox);
 // Export must work from startup while the stored theme is off.
 await control.handle({action:'nordic-confirm'}, {});
 return {control, sends, set(value) {current=value;}, fail(value) {fail=value;}, wait(value) {wait=value;},
  key: () => sandbox.WaybridgeSectionKey(current), disconnected: () => disconnected,
  async flush() {await new Promise(resolve => setImmediate(resolve));},
  async tick() {const callbacks=[...timers.values()];timers.clear();for(const fn of callbacks)fn();await this.flush();}};
}
(async () => {
 const sandbox = {URL};vm.createContext(sandbox);vm.runInContext(source('forms.js'),sandbox);
 const canonical = value => sandbox.WaybridgeFormURL(value);
 const legacyURL = 'https://docs.google.com/forms/viewform?embedded=true&id=fixture_1&hl=ru&token=secret#fragment';
 assert.equal(canonical(legacyURL),'https://docs.google.com/forms/d/fixture_1/viewform');
 assert.equal(canonical('https://docs.google.com/forms/u/0/viewform?id=fixture_1'),'https://docs.google.com/forms/d/fixture_1/viewform');
 assert.equal(canonical('https://docs.google.com/forms/d/e/fixture/viewform?usp=secret'),'https://docs.google.com/forms/d/e/fixture/viewform');
 for(const url of ['https://evil.example/forms/viewform?id=a','https://docs.google.com.evil.example/forms/viewform?id=a','https://docs.google.com/forms/d/a/edit','https://docs.google.com/forms/viewform','http://docs.google.com/forms/viewform?id=a','https://docs.google.com/forms/viewform?id=../../escape'])assert.equal(canonical(url),null,url);
 console.log('PASS modern and legacy respondent URLs, canonical form IDs, rejection of editor/missing IDs/foreign origins');
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
 assert.equal(run.control.state().autoConfirm,false);assert(run.sends.includes('three'));assert.equal(run.control.state().queued,0);
 run.wait(true);run.set(snapshot('four'));
 await run.control.handle({action:'section',key:run.key()},{tab:formTab});await run.flush();
 const before=run.disconnected();await run.control.handle({action:'nordic-set',enabled:false},{});await run.flush();
 assert.equal(run.control.state().queued,1);assert.equal(run.disconnected(),before);
 assert.equal(run.control.state().nordic,false);
 // The pending native send stays alive through the theme change.
 const busyKey=run.key();assert.equal((await run.control.handle({action:'section',key:busyKey},{tab:formTab})).accepted,true);
 run = await controller();
 run.set({...snapshot('legacy'), page:{...snapshot('legacy').page,url:'https://docs.google.com/forms/d/fixture_1/viewform'}});
 assert.equal((await run.control.handle({action:'section',key:run.key()},{tab:{...formTab,url:legacyURL}})).accepted,true);
 await run.flush();assert.deepEqual(run.sends,['legacy']);
 const again=await controller();
 assert.equal((await again.control.handle({action:'section',key:again.key(),visit:'first-visit'},{tab:formTab})).delivered,false);
 await again.flush();
 assert.equal((await again.control.handle({action:'section',key:again.key(),visit:'first-visit'},{tab:formTab})).delivered,true);
 assert.equal((await again.control.handle({action:'section',key:again.key(),visit:'second-visit'},{tab:formTab})).accepted,true);
 await again.flush();assert.equal(again.sends.length,2);
 const images=await controller();
 const incomplete=snapshot('image-loading');incomplete.page.images=[{alt:'Loading',loaded:false}];incomplete.warnings=['Image loading'];images.set(incomplete);
 assert.equal((await images.control.handle({action:'section',key:images.key(),visit:'image-visit'},{tab:formTab})).accepted,false);
 assert.equal(images.control.state().queued,0);assert.equal(images.control.state().autoConfirm,false);
 incomplete.page.images[0].loaded=true;incomplete.warnings=[];images.set(incomplete);
 assert.equal((await images.control.handle({action:'section',key:images.key(),visit:'image-visit'},{tab:formTab})).accepted,true);
 await images.flush();assert.equal(images.sends.length,1);
 console.log('PASS image loading retries before adding a partial snapshot to the queue');
 console.log('PASS each new visit is delivered; same-visit retries reuse the queued snapshot');
 console.log('PASS legacy sender reaches the acknowledged auto queue');
 console.log('PASS auto queue: domain restriction, dedup, same-ID retry, automatic warnings, theme-independent queue');
 const backlog=await controller();backlog.fail(true);
 for(const id of ['b1','b2','b3']){
  backlog.set(snapshot(id));await backlog.control.handle({action:'section',key:backlog.key()},{tab:formTab});await backlog.flush();
 }
 assert.equal(backlog.control.state().queued,3);
 backlog.set(snapshot('b4'));
 assert.equal((await backlog.control.handle({action:'section',key:backlog.key()},{tab:formTab})).accepted,false);
 assert(backlog.control.state().autoMessage.includes('offline'));
 await backlog.control.handle({action:'nordic-set',enabled:true},{});
 await backlog.control.handle({action:'nordic-set',enabled:false},{});
 assert.equal(backlog.control.state().queued,3);
 backlog.fail(false);
 for(let n=0;n<5;n++)await backlog.tick();
 assert.equal(backlog.control.state().queued,0);
 assert.equal((await backlog.control.handle({action:'section',key:backlog.key()},{tab:formTab})).accepted,true);
 await backlog.flush();assert.equal(backlog.control.state().queued,0);
 console.log('PASS queue saturation preserves the real error, theme toggles preserve pending jobs, reconnect drains backlog');
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage();
  await page.route('https://docs.google.com/**', route=>route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'fixtures/form.html'),'utf8').replaceAll('<fieldset>', '<div class="ss-form-question">').replaceAll('</fieldset>','</div>').replaceAll('<legend>','<div class="ss-q-title">').replaceAll('</legend>','</div>')}));
  await page.goto(legacyURL);
  await page.evaluate(() => {window.reports=[];window.browser={runtime:{sendMessage:async m=>{window.reports.push(m);return {accepted:true,delivered:true};}}};});
  await page.evaluate(() => {window.previousDisabled=false;window.WaybridgeNordic={set: value => {if(value===false)window.previousDisabled=true;}};});
  for(const name of ['forms.js','darkreader.js','extract.js','section-key.js','content.js'])await page.addScriptTag({content:source(name)});
  assert(await page.evaluate(() => window.previousDisabled));
  await page.evaluate(() => WaybridgeNordic.set(true));
  await page.waitForFunction(() => window.reports.length===1);
  assert(await page.evaluate(() => DarkReader.isEnabled()));
  const themed = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  assert.notEqual(themed,'rgb(255, 255, 255)');
  await page.evaluate(() => {document.querySelector('input[type="radio"]').checked=true;document.querySelector('textarea')?.dispatchEvent(new Event('input'));});
  await page.waitForTimeout(1700);assert.equal(await page.evaluate(() => window.reports.length),1);
  await page.evaluate(() => {document.querySelector('[role="heading"],legend,h2,h3,.ss-q-title').textContent='NEW SECTION';});
  await page.waitForFunction(() => window.reports.length===2);
  await page.evaluate(() => {document.querySelector('[role="heading"],legend,h2,h3,.ss-q-title').textContent='Вопрос B раньше вопроса A';});
  await page.waitForFunction(() => window.reports.length===3);
  const visits=await page.evaluate(() => window.reports.map(message=>message.visit));
  assert.equal(new Set(visits).size,3,'A -> B -> A must start three separate deliveries');
  await page.evaluate(() => WaybridgeNordic.set(false));
  assert.equal(await page.evaluate(() => DarkReader.isEnabled()),false);
  await page.evaluate(() => {document.querySelector('[role="heading"],legend,h2,h3,.ss-q-title').textContent='AFTER DISABLE';});
  await page.waitForFunction(() => window.reports.length===4);
  await page.evaluate(() => WaybridgeNordic.set(false,false));
  await page.evaluate(() => {document.querySelector('[role="heading"],legend,h2,h3,.ss-q-title').textContent='AFTER STOP';});
  await page.waitForTimeout(1000);assert.equal(await page.evaluate(() => window.reports.length),4);
  console.log('PASS real DOM: theme off keeps section export active; explicit controller stop ends export');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
