/* Isolated-profile Firefox WebDriver BiDi integration; user profiles stay untouched. */
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const http=require('node:http');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'waybridge-firefox-test-'));
 const fixture=fs.readFileSync(path.join(__dirname,'fixtures/form.html'));
 let reportResolve;const reported=new Promise(resolve=>{reportResolve=resolve;});
 const server=http.createServer((req,res)=>{
  if(req.url==='/__report'){let body='';req.on('data',c=>{body+=c;});req.on('end',()=>{res.end('ok');reportResolve(JSON.parse(body));});return;}
  res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});res.end(fixture);
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const ext=path.join(folder,'extension');fs.mkdirSync(ext);
 for(const name of fs.readdirSync(path.join(root,'src/waybridge/browser/firefox')))fs.copyFileSync(path.join(root,'src/waybridge/browser/firefox',name),path.join(ext,name));
 const manifest=JSON.parse(fs.readFileSync(path.join(ext,'manifest.json')));
 manifest.permissions.push('<all_urls>');manifest.optional_permissions=[];
 fs.writeFileSync(path.join(ext,'manifest.json'),JSON.stringify(manifest));
 const profile=path.join(folder,'profile');fs.mkdirSync(profile);
 fs.writeFileSync(path.join(profile,'user.js'),'user_pref("remote.experimental.enabled", true);\n');
 let proc,ws;let next=0;const pending=new Map();
 try{
  proc=spawn(process.env.WAYBRIDGE_FIREFOX || 'firefox',['--headless','--no-remote','--profile',profile,'--remote-debugging-port','0'],{stdio:['ignore','ignore','pipe']});
  const endpoint=await new Promise((resolve,reject)=>{
   let log='';const timeout=setTimeout(()=>reject(new Error('Firefox BiDi startup timed out: '+log.slice(-1500))),20000);
   proc.stderr.on('data',chunk=>{log+=chunk;const match=log.match(/WebDriver BiDi listening on (ws:\/\/127\.0\.0\.1:\d+)/);if(match){clearTimeout(timeout);resolve(match[1]+'/session');}});
   proc.once('exit',code=>{clearTimeout(timeout);reject(new Error('Firefox exited: '+code+' '+log.slice(-1500)));});
  });
  ws=new WebSocket(endpoint);
  await new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
  ws.addEventListener('message',event=>{
   const message=JSON.parse(event.data);const waiter=pending.get(message.id);
   if(waiter){pending.delete(message.id);clearTimeout(waiter.timeout);message.type==='error'?waiter.reject(new Error(message.error+': '+message.message)):waiter.resolve(message.result);}
  });
  const command=(method,params)=>new Promise((resolve,reject)=>{
   const id=++next;const timeout=setTimeout(()=>{pending.delete(id);reject(new Error('Timeout '+method));},30000);
   pending.set(id,{resolve,reject,timeout});ws.send(JSON.stringify({id,method,params}));
  });
  console.log('Firefox', (await command('session.new',{capabilities:{}})).capabilities.browserVersion);
  const target=await command('browsingContext.create',{type:'tab'});
  await command('browsingContext.navigate',{context:target.context,url:`http://127.0.0.1:${server.address().port}/fixture`,wait:'complete'});
  const reportURL=`http://127.0.0.1:${server.address().port}/__report`;
  const integration=`
  (async()=>{
   try{
    const bundle=await capture();
    const ack=${process.env.WAYBRIDGE_TEST_NATIVE==='1' ? "await browser.runtime.sendNativeMessage(HOST,{action:'send',snapshot:bundle})" : 'null'};
    await fetch(${JSON.stringify(reportURL)},{method:'POST',body:JSON.stringify({bundle,ack})});
   }catch(error){await fetch(${JSON.stringify(reportURL)},{method:'POST',body:JSON.stringify({error:error.message,stack:error.stack})});}
  })();`;
  fs.appendFileSync(path.join(ext,'background.js'),integration);
  console.log('INSTALL',JSON.stringify(await command('webExtension.install',{extensionData:{type:'path',path:ext}})));
  let reportTimer;const result=await Promise.race([reported,new Promise((_,reject)=>{reportTimer=setTimeout(()=>reject(new Error('Firefox capture timed out')),25000);})]);clearTimeout(reportTimer);
  assert(!result.error,JSON.stringify(result));
  const bundle=result.bundle;
  if(process.env.WAYBRIDGE_FIREFOX_FIXTURE)fs.writeFileSync(process.env.WAYBRIDGE_FIREFOX_FIXTURE,JSON.stringify(bundle));
  assert(bundle.tiles.length>=2);assert(bundle.page.questions[0].options[0].label==='Третий вариант');
  console.log('FIREFOX_CAPTURE_PASSED',bundle.page.geometry.width,bundle.page.geometry.height,bundle.tiles.length);
  if(process.env.WAYBRIDGE_TEST_NATIVE==='1'){
   assert(result.ack.ok,JSON.stringify(result.ack));assert.equal(result.ack.id,bundle.id);
   console.log('FIREFOX_NATIVE_DELIVERY_PASSED',result.ack.id);
  }
 }finally{
  if(ws)ws.close();
  for(const waiter of pending.values())clearTimeout(waiter.timeout);
  if(proc&&proc.exitCode===null){proc.kill('SIGTERM');await new Promise(r=>proc.once('exit',r));}
  await new Promise(r=>server.close(r));fs.rmSync(folder,{recursive:true,force:true});
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
