// Local UI contract checks. No production, AI, database or analytics requests.
// Run: node tests/ui_design.browser.cjs [--audit-only]
// Playwright + an installed Chrome are required; no package install is performed.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const auditOnly=process.argv.includes('--audit-only');
const checks=[],errors=[];
function check(name,ok,detail){checks.push({name,pass:!!ok,...(detail===undefined?{}:{detail})});}
function contrast(a,b){
 const lum=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4})
  .reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
 const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
}
(async()=>{
 const root=process.cwd(),out=fs.mkdtempSync(path.join(os.tmpdir(),'chatbot-design-qa-'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHATBOT_TEST_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
 let finishChat;
 const page=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());
  // No CDN or user traffic: only local assets and synthetic DOM content.
  if(url.hostname!=='chatbot-ui.test'){await route.fulfill({contentType:'text/javascript',body:''});return;}
  if(url.pathname==='/chat'){
   await new Promise(resolve=>{finishChat=resolve;});
   await route.fulfill({contentType:'application/json',body:JSON.stringify({status:'complete',answer:'로컬 전송 검사'})});return;
  }
  const rel=url.pathname==='/'?'static/index.html':decodeURIComponent(url.pathname.slice(1));
  const file=path.resolve(root,rel);
  if(!file.startsWith(path.resolve(root,'static')+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){
   await route.fulfill({status:404,body:''});return;
  }
  await route.fulfill({body:fs.readFileSync(file),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ttf':'font/ttf','.json':'application/json'})[path.extname(file)]||'application/octet-stream'});
 });
 await page.goto('http://chatbot-ui.test/');await page.evaluate(()=>document.fonts.ready);
 check('첫 안내 문의 없음',await page.locator('.contact-actions').count()===0);
 check('첫 안내의 기관 확인 고지 제거',await page.locator('#time-notice').count()===0);
 check('통계 고지는 말풍선 밖 작은 글씨',await page.locator('#analytics-notice').evaluate(el=>!el.closest('.message')&&getComputedStyle(el).fontSize==='11px'));
 check('브랜드 제목',await page.locator('#header-title').textContent()==='도봉구 영유아 복지정보자료집');
 const fontDisplays=await page.evaluate(()=>[...document.fonts].filter(f=>['SF Pro','ONE Mobile POP'].includes(f.family.replace(/["']/g,''))).map(f=>f.display));
 check('기존 로컬 폰트 swap',fontDisplays.length>=2&&fontDisplays.every(v=>v==='swap'),fontDisplays);
 await page.screenshot({path:path.join(out,'welcome-mobile.png')});
 for(const [width,height] of [[320,812],[390,844],[768,1024],[1280,900],[812,375]]){
  await page.setViewportSize({width,height});
  for(const lang of ['ko','en','vi','zh']){
   await page.evaluate(l=>changeLanguage(l),lang);
   const state=await page.evaluate(()=>{
    const welcome=document.getElementById('welcome-msg'),header=document.getElementById('header-title');
    return {page:document.documentElement.scrollWidth<=innerWidth,
     welcome:welcome.scrollWidth<=welcome.clientWidth+1,header:header.scrollWidth<=header.clientWidth+1,
     spans:welcome.children.length,flags:document.querySelectorAll('.language-flag').length};
   });
   check('첫 화면 reflow '+width+'x'+height+' '+lang,state.page&&state.welcome&&state.header&&state.spans===3&&state.flags===4,state);
  }
 }
 await page.setViewportSize({width:390,height:844});
 for(const lang of ['ko','en','vi','zh']){
  await page.evaluate(l=>changeLanguage(l),lang);
  if(await page.locator('#suggestion-toggle-btn').getAttribute('aria-expanded')==='false')await page.locator('#suggestion-toggle-btn').click();
  finishChat=null;
  if(lang==='ko'){
   await page.locator('#user-input').fill('보육료 지원');
   await page.locator('#send-btn').click();
  }else await page.locator('.suggestion-chip').first().click();
  await page.waitForFunction(()=>isChatBusy());
  const collapsed=await page.locator('#suggestion-container').evaluate(el=>el.classList.contains('hidden')&&el.inert&&getComputedStyle(el).opacity==='0');
  check(lang+' 전송 시작 시 추천 질문 자동 접기',collapsed&&await page.locator('#suggestion-toggle-btn').getAttribute('aria-expanded')==='false');
  for(let attempt=0;!finishChat&&attempt<200;attempt++)await new Promise(r=>setTimeout(r,10));
  assert.ok(finishChat,'로컬 요청이 도착해야 합니다');
  finishChat();
  await page.waitForFunction(()=>!isChatBusy());
  check(lang+' 답변 후에도 접힌 상태 유지',await page.locator('#suggestion-container').evaluate(el=>el.inert));
 }
 await page.evaluate(()=>{
  document.querySelectorAll('.message-row').forEach((el,i)=>{if(i>0)el.remove();});
  changeLanguage('ko');
 });
 await page.locator('#suggestion-toggle-btn').click();
 check('전송 이후 추천 질문 수동 펼치기',await page.locator('#suggestion-toggle-btn').getAttribute('aria-expanded')==='true');

 await page.evaluate(async()=>{
  const box=addMessageToBox('assistant','로컬 UI 점검 · 실제 검색 결과 아님');
  await renderChatResponse({status:'complete',answer:'로컬 UI 점검 · 실제 검색 결과 아님',last_result_ids:['fixture-a','fixture-b','fixture-c'],shown_count:2},box,'test',activeRequestSequence);
  // Trusted DOM fixture; never replace or bypass the application's sanitizer.
  const card=document.createElement('div');card.className='result-card';
  const title=document.createElement('h3');title.className='card-title';title.textContent='검증용 복지정보 카드';card.appendChild(title);
  const body=document.createElement('div');body.className='card-body';
  for(let i=0;i<14;i++){const p=document.createElement('p');p.textContent='지원 내용과 대상을 확인하는 테스트 문장입니다. '+i;body.appendChild(p);}
  card.appendChild(body);
  const footer=document.createElement('div');footer.className='card-footer';
  for(const name of ['detail-link','card-share-btn']){const b=document.createElement('button');b.className=name;b.textContent=name==='detail-link'?'자료 원문 보기':'공유';footer.appendChild(b);}
  card.appendChild(footer);box.prepend(card);
  window.uiTestBox=box;
  const loading=document.createElement('div');loading.className='loading-copy';
  const tip=document.createElement('p');tip.className='tip-text';loading.appendChild(tip);box.appendChild(loading);
  window.stopUiTips=startLoadingTips(box,'ko');
 });
 await page.locator('.result-card').waitFor({state:'visible'});
 const tipStyle=await page.locator('.tip-text').evaluate(el=>{
  const a=getComputedStyle(el),b=getComputedStyle(el.closest('.message'));
  return {fg:a.color.match(/[\d.]+/g).map(Number),bg:b.backgroundColor.match(/[\d.]+/g).map(Number),size:a.fontSize};
 });
 const ratio=contrast(tipStyle.fg,tipStyle.bg);
 check('로딩 팁 대비 4.5 이상',ratio>=4.5,Number(ratio.toFixed(2)));
 check('팁 크기 보존',tipStyle.size==='12px',tipStyle.size);
 check('장식 캐릭터는 읽지 않음',await page.locator('.header-icon:not([alt=""]),.bot-profile-icon:not([alt=""])').count()===0);
 const firstTip=await page.locator('.tip-text').textContent();
 await page.waitForTimeout(7200);
 check('동작 줄이기에서는 팁 자동 교체 없음',await page.locator('.tip-text').textContent()===firstTip);
 await page.evaluate(()=>{stopUiTips();document.querySelector('.loading-copy').remove();});
 await page.locator('.show-more-btn').scrollIntoViewIfNeeded();
 check('결과 더 보기 명칭',await page.locator('.show-more-btn').textContent()==='결과 더 보기');
 check('문의 구분선',await page.locator('.contact-actions').evaluate(el=>getComputedStyle(el).borderTopWidth)==='1px');
 check('버튼 최소 web 터치 크기',await page.locator('.show-more-btn').evaluate(el=>{const r=el.getBoundingClientRect();return r.width>=24&&r.height>=24;}));
 await page.screenshot({path:path.join(out,'answer-mobile.png')});
 await page.locator('.contact-actions summary').click();
 check('문의 링크는 기본 파란색이 아닌 기존 본문 톤',await page.locator('.contact-email').evaluate(el=>getComputedStyle(el).color)==='rgb(52, 64, 84)');
 check('긴 문의 안내 대신 이메일 주소만 표시',await page.locator('.contact-content p').textContent()==='chanyoung@devleop136.com');
 await page.evaluate(()=>{collapseSuggestions();document.getElementById('chat-box').scrollTop=document.getElementById('chat-box').scrollHeight;});
 await page.screenshot({path:path.join(out,'contact-mobile.png')});
 await page.locator('#suggestion-toggle-btn').click();
 const hiddenBefore=await page.evaluate(()=>{
  const box=document.getElementById('chat-box'),target=document.querySelector('.contact-copy');
  box.style.scrollBehavior='auto';box.scrollTop+=target.getBoundingClientRect().top-(innerHeight-90);
  return {target:target.getBoundingClientRect().bottom,limit:document.querySelector('.suggestion-container').getBoundingClientRect().top};
 });
 await page.keyboard.press('Tab');
 await page.locator('.contact-copy').focus();
 await page.waitForTimeout(100);
 const focusAfter=await page.locator('.contact-copy').evaluate(el=>{
  const r=el.getBoundingClientRect(),h=document.querySelector('.chat-topbar').getBoundingClientRect();
  const bar=document.querySelector('.suggestion-container').getBoundingClientRect();
  return {top:r.top,bottom:r.bottom,header:h.bottom,bottomLimit:bar.top,visible:el.matches(':focus-visible')};
 });
 check('키보드 포커스가 고정 영역에 가리지 않음',focusAfter.top>=focusAfter.header&&focusAfter.bottom<=focusAfter.bottomLimit,{before:hiddenBefore,after:focusAfter});
 // Text-only magnification, not a claim of Safari/device pinch-zoom testing.
 await page.evaluate(()=>{
  document.querySelectorAll('#header-title,#welcome-msg,.service-notice,.card-title,.card-body p,.show-more-btn,.contact-actions summary,.contact-content a,.contact-copy').forEach(el=>el.style.fontSize=parseFloat(getComputedStyle(el).fontSize)*2+'px');
 });
 await page.locator('.contact-copy').scrollIntoViewIfNeeded();
 check('200% 텍스트에서 본문 가로 넘침 없음',await page.evaluate(()=>[...document.querySelectorAll('#welcome-msg,.result-card,.contact-actions')].every(el=>el.scrollWidth<=el.clientWidth+1)));
 await page.screenshot({path:path.join(out,'text-200-mobile.png')});
 await page.setViewportSize({width:1280,height:900});await page.screenshot({path:path.join(out,'text-200-desktop.png')});
 check('브라우저 JS 예외 없음',errors.length===0,errors);
 console.log(JSON.stringify({out,checks},null,2));
 if(!auditOnly)assert.equal(checks.filter(c=>!c.pass).length,0,'UI contract failures: '+checks.filter(c=>!c.pass).map(c=>c.name).join(', '));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
