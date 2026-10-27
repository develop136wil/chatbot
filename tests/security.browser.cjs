// Real sanitizer + real browser. Every request uses local files or is blocked.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const chrome=process.env.CHATBOT_TEST_BROWSER||(process.platform==='win32'?'C:/Program Files/Google/Chrome/Application/chrome.exe':undefined);
 const browser=await chromium.launch({headless:true,...(chrome?{executablePath:chrome}:{})});
 try{
  const page=await browser.newPage(); let dialogs=0;
  page.on('dialog',async d=>{dialogs++;await d.dismiss();});
  await page.route('**/*',async route=>{
   const u=new URL(route.request().url());
   if(u.hostname!=='chatbot-security.test'){await route.abort();return;}
   const file=path.resolve(u.pathname==='/'?'static/index.html':'.'+decodeURIComponent(u.pathname));
   if(!file.startsWith(path.resolve('static')+path.sep)||!fs.existsSync(file)){await route.fulfill({status:404,body:''});return;}
   await route.fulfill({body:fs.readFileSync(file),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ttf':'font/ttf'})[path.extname(file)]||'application/octet-stream'});
  });
  await page.goto('http://chatbot-security.test/');
  assert.equal(await page.evaluate(()=>DOMPurify.version),require('../package.json').dependencies.dompurify);
  const results=await page.evaluate(()=>{
   const fixtures=[
    '<img src=x onerror="window.__executed=true"><script>window.__executed=true</script>',
    '<svg><g onload="window.__executed=true"></g></svg>',
    '<a href="javascript:alert(1)">bad</a><iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<math><mtext><table><mglyph><style><!--</style><img title="--><img src=x onerror=alert(1)>">',
    '<textarea title="</textarea><img src=x onerror=alert(1)>">text</textarea>',
   ];
   return fixtures.map(input=>{
    const host=document.createElement('div');
    host.innerHTML=sanitizeAssistantHtml(input);
    document.body.append(host);
    const unsafe=[...host.querySelectorAll('*')].some(el=>['SCRIPT','IFRAME'].includes(el.tagName)||[...el.attributes].some(a=>/^on/i.test(a.name)||(/^(href|src|xlink:href)$/i.test(a.name)&&/^\s*javascript:/i.test(a.value))));
    host.remove();return !unsafe;
   });
  });
  assert.ok(results.every(Boolean));
  assert.equal(await page.evaluate(()=>window.__executed===true),false);
  assert.equal(dialogs,0);
  assert.ok(await page.evaluate(()=>{
   const html='<div class="result-card"><h3>영유아 발달검사</h3><p>18–36개월 · 100,000원</p><a href="https://example.org" target="_blank" rel="noopener">자료 원문</a><button data-copy="원문">공유</button></div>';
   const host=document.createElement('div');host.innerHTML=formatAssistantAnswer(html);
   return host.querySelector('.result-card')&&host.textContent.includes('100,000원')&&host.querySelector('button').getAttribute('data-copy')==='원문'&&host.querySelector('a').getAttribute('href')==='https://example.org';
  }));
  assert.ok(await page.evaluate(()=>{
   const saved=window.DOMPurify;window.DOMPurify=undefined;
   const input='<img src=x onerror=alert(1)>',host=document.createElement('div');
   host.innerHTML=sanitizeAssistantHtml(input);window.DOMPurify=saved;
   return host.textContent===input&&host.querySelector('img')===null;
  }));
  console.log('Security browser checks passed: real sanitizer, hostile markup, card preservation, safe fallback.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
