// Local synthetic-data browser QA. Never opens Production or sends email/AI requests.
const fs=require('node:fs'),http=require('node:http'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
 const errors=[];const root=process.cwd();
 const days=Array.from({length:30},(_,i)=>{
   const date=new Date('2026-09-01T00:00:00Z');date.setUTCDate(date.getUTCDate()+i);
   return {day:date.toISOString().slice(0,10),stats:{questions:10+i,answered:7+i,empty:1,errors:1,clarify:1,
     source_clicks:3,more:2,sessions:8,cache_hits:4,cache_eligible:8,
     categories:{'의료/재활':4+i,'돌봄/양육':3,'교육/보육':2,'미분류':1},
     languages:{ko:7+i,en:1,vi:1,zh:1},sources:{direct:5+i,qr:4,unknown:1},inputs:{typed:6+i,suggestion:4},
     latency_cached:{'<1초':2,'1–3초':2},latency_fresh:{'3–5초':1+i,'5–10초':1,'10–20초':1}}};
 });
 const server=http.createServer((req,res)=>{
   const name=req.url.split('?')[0];
   if(name==='/admin/analytics/data'){
     res.setHeader('Content-Type','application/json');
     if(req.headers['x-admin-secret']!=='local-test-only'){res.statusCode=401;res.end('{}');return;}
     res.end(JSON.stringify({days,enabled:true,updated_at:new Date().toISOString(),first_recorded_day:'2026-09-01',project_host:'LOCAL TEST DATA'}));return;
   }
   const file=name==='/admin/analytics'?'dashboard/analytics.html':
     ['/static/analytics.css','/static/analytics-dashboard.js','/static/header-icon.png'].includes(name)?name.slice(1):null;
   if(!file){res.statusCode=404;res.end();return;}
   res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.png')?'image/png':'text/html');
   res.end(fs.readFileSync(path.join(root,file)));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHATBOT_TEST_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const out=fs.mkdtempSync(path.join(os.tmpdir(),'chatbot-analytics-qa-'));
 try{
   const page=await browser.newPage({viewport:{width:1366,height:1000}});
   page.on('pageerror',e=>errors.push(e.message));
   await page.goto('http://127.0.0.1:'+server.address().port+'/admin/analytics');
   assert.equal(await page.locator('#report').isVisible(),false);
   await page.fill('#secret','local-test-only');
   await page.locator('button[type=submit]').click();await page.waitForSelector('#report:not([hidden])');
   await page.fill('#start','2026-09-01');await page.fill('#end','2026-09-30');
   await page.locator('#refresh').click();await page.waitForFunction(()=>document.getElementById('period-title').textContent.includes('2026-09-01'));
   assert.equal(await page.locator('#trend svg').count(),1);assert.equal(await page.locator('#languages svg').count(),1);
   assert.equal(await page.locator('#secret').inputValue(),'');
   await page.locator('h1').evaluate(el=>el.textContent='테스트 데이터 · 운영 실적 아님');
   await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
   await page.setViewportSize({width:375,height:812});await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   assert.ok(Number((await page.locator('#trend svg').getAttribute('viewBox')).split(' ')[2])<400);
   const download=page.waitForEvent('download');await page.locator('#csv').click();
   assert.match((await download).suggestedFilename(),/^chatbot-2026/);
   await page.route('**/admin/analytics/data?*',async route=>{await new Promise(r=>setTimeout(r,300));await route.continue();});
   await page.locator('#refresh').click();
   await page.locator('#logout').click();
   await page.waitForTimeout(700);
   assert.equal(await page.locator('#report').isVisible(),false);
   assert.equal(await page.locator('#trend svg').count(),0);
   assert.deepEqual(errors,[]);
   console.log(JSON.stringify({passed:true,desktop:path.join(out,'desktop.png'),mobile:path.join(out,'mobile.png')}));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exit(1);});
