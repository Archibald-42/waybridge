/* Real DOM tests plus extension-background orchestration against browser mocks. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const http = require('node:http');
const {webcrypto} = require('node:crypto');
const {chromium} = require(process.env.WAYBRIDGE_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const assets = path.join(root, 'src/waybridge/browser/firefox');
const extractionSource = fs.readFileSync(path.join(assets, 'extract.js'), 'utf8');
const backgroundSource = fs.readFileSync(path.join(assets, 'background.js'), 'utf8');
(async () => {
 const fixture = fs.readFileSync(path.join(__dirname, 'fixtures/form.html'));
 const server = http.createServer((req, res) => {res.writeHead(200, {'Content-Type':'text/html; charset=utf-8'});res.end(fixture);});
 await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
 let browser;
 try {
  browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:900,height:700}});
  await page.goto(`http://127.0.0.1:${server.address().port}/form?not-exported=secret#fragment`);
  const extract = () => page.evaluate(`${extractionSource}; WaybridgeExtract()`);
  const doc = await extract();
  assert.equal(doc.page.questions.length,2);
  assert.equal(doc.page.questions[0].title,'Вопрос B раньше вопроса A');
  assert.deepEqual(doc.page.questions[0].options.map(o => o.label),['Третий вариант','Первый вариант','Второй вариант']);
  assert.deepEqual(doc.page.questions[0].options.map(o => o.selected),[false,true,false]);
  assert.equal(doc.page.fields.find(f => f.label==='Ответ текстом').value,'current edited value');
  assert(!JSON.stringify(doc).includes('hidden-token-must-not-be-exported'));
  assert(!JSON.stringify(doc).includes('password-must-not-be-exported'));
  assert(!doc.page.text.includes('Hidden question must not be exported'));
  assert(!doc.page.url.includes('secret'));
  assert(doc.page.geometry.height>4096);
  assert(doc.page.text.includes('КОНЕЦ ТЕКУЩЕГО РАЗДЕЛА'));
  console.log('PASS real DOM: shuffled order, current values, offscreen text, password/hidden exclusions');

  let savedSnapshot;
  async function context({failOnce=false,mutate=false,warn=false,permission=true}={}) {
   let handler;let reads=0;let sends=0;let ids=[];
   const sandbox={crypto:webcrypto,TextEncoder,console,browser:{
    browserAction:{setBadgeText:()=>{},setTitle:()=>{}},
    permissions:{contains:async()=>permission},
    tabs:{query:async()=>[{id:1,url:page.url()}],executeScript:async()=>{
      const value=await extract();reads++;
      if(mutate&&reads>1)value.page.text+='CHANGED';
      if(warn)value.warnings.push('Test warning: incomplete image');
      return [value];
     },captureTab:async(id,options)=>{
      const image=await page.screenshot({clip:options.rect,fullPage:true});
      return 'data:image/png;base64,'+image.toString('base64');
     }},
    runtime:{onMessage:{addListener:fn=>{handler=fn;}},sendNativeMessage:async(host,message)=>{
      sends++;ids.push(message.snapshot.id);savedSnapshot=structuredClone(message.snapshot);
      if(failOnce&&sends===1)throw new Error('simulated network outage');
      return {ok:true,id:message.snapshot.id};
     }}
   }};
   vm.createContext(sandbox);vm.runInContext(extractionSource,sandbox);vm.runInContext(backgroundSource,sandbox);
   return {call:action=>handler({action}),stats:()=>({reads,sends,ids})};
  }
  let run=await context();const first=await run.call('export');assert.equal(first.ok,true,first.error);
  assert.equal(run.stats().sends,1);assert.equal(savedSnapshot.tiles.length,2);
  assert.equal((await run.call('status')).stage,'sent');
  if(process.env.WAYBRIDGE_PAGE_FIXTURE)fs.writeFileSync(process.env.WAYBRIDGE_PAGE_FIXTURE,JSON.stringify(savedSnapshot));
  console.log('PASS full document tiles and successful send');
  run=await context({failOnce:true});assert.equal((await run.call('export')).ok,false);
  assert.equal((await run.call('retry')).ok,true);assert.equal(run.stats().sends,2);
  assert.equal(run.stats().ids[0],run.stats().ids[1]);
  console.log('PASS retry retains same immutable snapshot ID');
  run=await context({mutate:true});assert.equal((await run.call('export')).ok,false);assert.equal(run.stats().sends,0);
  console.log('PASS document changed during capture: no transmission');
  run=await context({warn:true});assert.equal((await run.call('export')).ok,true);assert.equal(run.stats().sends,0);
  assert.equal((await run.call('status')).confirm,true);
  assert.equal((await run.call('confirm')).ok,true);assert.equal(run.stats().sends,1);
  console.log('PASS incomplete capture requires explicit confirmation');
  run=await context({permission:false});assert.equal((await run.call('export')).ok,false);assert.equal(run.stats().reads,0);
  console.log('PASS missing capture permission does not access page');
 } finally {if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
