// Local UI contract checks. No production, AI, database or analytics requests.
// Run: node tests/ui_design.browser.cjs [--audit-only]
// Playwright + an installed Chrome are required; no package install is performed.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const auditOnly=process.argv.includes('--audit-only');
// Optional read-only font verification: only the existing pinned Pretendard CDN is allowed.
const fontNetwork=process.argv.includes('--font-network');
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
  // No user traffic. Opt-in font mode allows only the already configured font CDN.
  if(fontNetwork&&route.request().method()==='GET'&&url.hostname==='cdn.jsdelivr.net'&&url.pathname.startsWith('/gh/orioncactus/pretendard@v1.3.8/')){await route.continue();return;}
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

 if(fontNetwork){
  const cdp=await page.context().newCDPSession(page);
  await cdp.send('DOM.enable');await cdp.send('CSS.enable');
  const {root}=await cdp.send('DOM.getDocument');
  const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:root.nodeId,selector:'#welcome-title'});
  const {fonts}=await cdp.send('CSS.getPlatformFontsForNode',{nodeId});
  check('실제 첫 제목 Pretendard ExtraBold 웹폰트 사용',fonts.some(f=>f.isCustomFont&&/Pretendard/i.test(f.familyName)&&/ExtraBold/i.test(f.postScriptName)&&f.glyphCount>0),fonts);
  await cdp.detach();
 }
 check('첫 안내 문의 없음',await page.locator('.contact-actions').count()===0);
 check('첫 안내의 기관 확인 고지 제거',await page.locator('#time-notice').count()===0);
 check('통계 고지는 기본 접힘·말풍선 밖 작은 글씨',await page.locator('#analytics-notice').evaluate(el=>!el.closest('.message')&&!el.closest('details').open&&getComputedStyle(el).fontSize==='11px'));
 check('시작 화면은 말풍선이 아님',await page.locator('#welcome-panel .message').count()===0);
 check('첫 안내 장식 제거·상단 캐릭터 유지',await page.locator('#welcome-panel img, #welcome-panel svg').count()===0&&await page.locator('img[src="/static/header-icon.png"]').count()===1);
 check('입력창 아래 주의 문구 10px·대비 유지',await page.locator('#privacy-notice').evaluate(el=>getComputedStyle(el).fontSize==='10px'&&getComputedStyle(el).color==='rgb(102, 112, 133)'));

 check('시작 설명은 쉼표 뒤 지정 줄바꿈',await page.locator('#welcome-msg').evaluate(el=>el.textContent.includes(',\n')&&getComputedStyle(el).whiteSpace==='pre-line'));

 check('한국어 첫 제목 지정 두 줄',await page.locator('#welcome-title').evaluate(el=>el.textContent==='우리 아이에게\n필요한 지원을 찾아보세요'&&getComputedStyle(el).whiteSpace==='pre-line'&&Math.abs(el.getBoundingClientRect().height-2*parseFloat(getComputedStyle(el).lineHeight))<1));
 check('첫 설명 12px·줄 높이 16.2px',await page.locator('#welcome-msg').evaluate(el=>getComputedStyle(el).fontSize==='12px'&&getComputedStyle(el).lineHeight==='16.2px'));
 check('첫 제목 굵기·조밀한 행간',await page.locator('#welcome-title').evaluate(el=>getComputedStyle(el).fontWeight==='800'&&getComputedStyle(el).webkitTextStrokeWidth==='0px'&&getComputedStyle(el).fontFamily.startsWith('Pretendard')&&getComputedStyle(el).lineHeight==='27.6px'));
 check('정보 수집 안내 명칭',await page.locator('#analytics-label').textContent()==='정보 수집 안내');
 check('브랜드 제목',await page.locator('#header-title').textContent()==='도봉구 영유아 복지정보자료집');
 const fontDisplays=await page.evaluate(()=>[...document.fonts].filter(f=>['SF Pro'].includes(f.family.replace(/["']/g,''))).map(f=>f.display));
 check('기존 로컬 폰트 swap',fontDisplays.length>=1&&fontDisplays.every(v=>v==='swap'),fontDisplays);
 check('ONE Mobile POP 등록·프리로드 없음',await page.evaluate(()=>![...document.fonts].some(f=>f.family.includes('ONE Mobile'))&&![...document.querySelectorAll('link[rel="preload"]')].some(l=>l.href.includes('ONE'))));
 check('추천 질문 텍스트·투명 영역·개별 글라스',await page.evaluate(()=>{
  const tray=getComputedStyle(document.getElementById('suggestion-container'));
  return tray.backgroundColor==='rgba(0, 0, 0, 0)'&&tray.backgroundImage==='none'&&tray.backdropFilter==='none'&&[...document.querySelectorAll('.suggestion-chip')].every(el=>!/[\u{1F300}-\u{1FAFF}]/u.test(el.textContent)&&getComputedStyle(el).backdropFilter==='blur(10px)');
 }));
 check('상단 Pretendard 및 좌측 정렬',await page.evaluate(()=>{
  const name=document.getElementById('header-title'),bar=document.querySelector('.chat-topbar .chat-header'),icon=document.querySelector('.header-icon');
  return getComputedStyle(name).fontFamily.startsWith('Pretendard')&&getComputedStyle(name).fontWeight==='600'&&Math.abs(icon.getBoundingClientRect().left-bar.getBoundingClientRect().left-24)<1;
 }));
 const chipColors=await page.locator('.suggestion-chip').first().evaluate(el=>{
  const s=getComputedStyle(el);return {fg:s.color.match(/[\d.]+/g).map(Number),bg:s.backgroundColor.match(/[\d.]+/g).map(Number)};
 });
 const chipAlpha=chipColors.bg[3]??1,chipWorstBg=chipColors.bg.slice(0,3).map(v=>v*chipAlpha);
 check('글라스 버튼 검정 배경 합성 대비 4.5 이상',contrast(chipColors.fg,chipWorstBg)>=4.5);
 check('상단 배경만 아래로 투명해지고 경계선 없음',await page.evaluate(()=>{
  const el=document.querySelector('.chat-topbar'),a=getComputedStyle(el),b=getComputedStyle(el,'::before');
  return a.backgroundColor==='rgba(0, 0, 0, 0)'&&a.borderBottomWidth==='0px'&&a.opacity==='1'&&a.maskImage==='none'&&b.maskImage.includes('65%')&&b.maskImage.includes('100%')&&b.backgroundColor==='rgba(249, 250, 251, 0.98)'&&b.maskImage.includes('rgba(0, 0, 0, 0)')&&b.pointerEvents==='none';
 }));
 check('입력창 외부 투명·주의 문구 간격 2px',await page.evaluate(()=>{
  const footer=document.querySelector('.chat-input-box'),style=getComputedStyle(footer);
  const input=document.querySelector('.composer-controls').getBoundingClientRect(),notice=document.getElementById('privacy-notice').getBoundingClientRect();
  return style.backgroundColor==='rgba(0, 0, 0, 0)'&&style.borderTopWidth==='0px'&&style.backdropFilter==='none'&&Math.abs(notice.top-input.bottom-2)<.1;
 }));
 await page.screenshot({path:path.join(out,'welcome-mobile.png')});
 for(const [width,height] of [[320,812],[390,844],[768,1024],[1280,900],[812,375]]){
  await page.setViewportSize({width,height});
  for(const lang of ['ko','en','vi','zh']){
   await page.evaluate(async l=>{
    changeLanguage(l);
    // Each case measures the initial screen, not scroll carried over from an opened disclosure.
    document.activeElement?.blur();
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    document.getElementById('chat-box').scrollTo({top:0,behavior:'instant'});
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    document.getElementById('chat-box').scrollTo({top:0,behavior:'instant'});
   },lang);
   const state=await page.evaluate(()=>{
    const welcome=document.getElementById('welcome-msg'),header=document.getElementById('header-title');
    return {page:document.documentElement.scrollWidth<=innerWidth,
     welcome:welcome.scrollWidth<=welcome.clientWidth+1,header:header.scrollWidth<=header.clientWidth+1,
     titleSize:parseFloat(getComputedStyle(document.getElementById('welcome-title')).fontSize),flags:document.querySelectorAll('.language-flag').length};
   });
   check('첫 화면 reflow '+width+'x'+height+' '+lang,state.page&&state.welcome&&state.header&&state.titleSize===24&&state.flags===4,state);

   check('첫 안내와 국기 시작 높이 정렬 '+width+' '+lang,await page.evaluate(()=>Math.abs(document.getElementById('welcome-title').getBoundingClientRect().top-document.querySelector('.lang-btn').getBoundingClientRect().top)<=8));
   const toggleLayout=await page.evaluate(()=>{
    const tray=document.getElementById('suggestion-container'),toggle=document.getElementById('suggestion-toggle-btn');
    const r=tray.getBoundingClientRect(),t=toggle.getBoundingClientRect(),chip=tray.firstElementChild.getBoundingClientRect();
    return {gap:t.left-r.right,centers:Math.abs((chip.top+chip.bottom-t.top-t.bottom)/2),width:r.width,
     weight:getComputedStyle(toggle.querySelector('.toggle-text')).fontWeight,icon:getComputedStyle(toggle.querySelector('.toggle-icon')).width,
     glass:getComputedStyle(toggle).backdropFilter};
   });
   check('접기 버튼 분리·중앙 정렬 '+width+' '+lang,toggleLayout.gap>=7&&toggleLayout.centers<1&&toggleLayout.width>100&&toggleLayout.weight==='500'&&toggleLayout.icon==='12px'&&toggleLayout.glass==='blur(10px)',toggleLayout);
   await page.locator('.suggestion-chip').first().focus();
   for(let chipIndex=1;chipIndex<await page.locator('.suggestion-chip').count();chipIndex++)await page.keyboard.press('Tab');
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const lastReachable=await page.locator('.suggestion-chip').last().evaluate(el=>{
    const r=el.getBoundingClientRect(),tray=el.parentElement.getBoundingClientRect(),t=document.getElementById('suggestion-toggle-btn').getBoundingClientRect();
    return {left:r.left,right:r.right,trayLeft:tray.left,trayRight:tray.right,toggleLeft:t.left,scroll:el.parentElement.scrollLeft};
   });
   check('마지막 추천 질문 키보드 접근 '+width+' '+lang,lastReachable.left>=lastReachable.trayLeft&&lastReachable.right<=lastReachable.trayRight+1&&lastReachable.right<lastReachable.toggleLeft,lastReachable);
   await page.evaluate(()=>{document.activeElement?.blur();document.getElementById('suggestion-container').scrollLeft=0;});
   check('첫 안내 좌측 24px 정렬 '+width+' '+lang,await page.evaluate(()=>Math.abs(document.getElementById('welcome-title').getBoundingClientRect().left-document.querySelector('.chat-container').getBoundingClientRect().left-24)<1));
   const brand=await page.evaluate(()=>{
    const bar=document.querySelector('.chat-topbar'),name=document.getElementById('header-title'),icon=document.querySelector('.header-icon');
    const b=bar.getBoundingClientRect(),n=name.getBoundingClientRect(),i=icon.getBoundingClientRect(),style=getComputedStyle(bar);
    return {height:b.height,font:parseFloat(getComputedStyle(name).fontSize),icon:i.width,
     contained:n.top>=b.top&&n.bottom<=b.bottom&&n.left>=b.left&&n.right<=b.right,
     glass:getComputedStyle(bar,'::before').backdropFilter.includes('blur('),visible:style.visibility==='visible'&&style.opacity==='1'};
   });
   check('작은 상단 브랜드·글라스 보존 '+width+' '+lang,brand.height>=50&&brand.font===15&&brand.icon===24&&brand.contained&&brand.glass&&brand.visible,brand);
   await page.locator('.analytics-disclosure summary').click();
   check('통계 안내/개인정보 reflow '+width+' '+lang,await page.evaluate(()=>[document.getElementById('analytics-notice'),document.getElementById('privacy-notice')].every(el=>el.scrollWidth<=el.clientWidth+1)));
   await page.locator('.analytics-disclosure summary').click();
   check('입력창/추천 질문 영역 분리 '+width+' '+lang,await page.evaluate(()=>{
    const footer=document.querySelector('.chat-input-box').getBoundingClientRect();
    const tray=document.getElementById('suggestion-container').getBoundingClientRect();
    const input=document.getElementById('user-input').getBoundingClientRect();
    return tray.bottom<=footer.top+1&&input.top>=footer.top&&input.bottom<=footer.bottom&&input.right<=footer.right;
   }));
  }
 }
 await page.setViewportSize({width:1280,height:900});await page.evaluate(()=>changeLanguage('ko'));
 await page.screenshot({path:path.join(out,'welcome-desktop.png')});
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
  document.querySelectorAll('.message-row').forEach(el=>el.remove());
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
 check('문의는 답변 바깥 같은 행에 표시',await page.locator('.contact-actions').evaluate(el=>!el.closest('.message')&&el.parentElement.classList.contains('message-row')));
 check('문의는 답변 아래 배치',await page.locator('.contact-actions').evaluate(el=>el.getBoundingClientRect().top>=el.parentElement.querySelector('.message').getBoundingClientRect().bottom));
 check('버튼 최소 web 터치 크기',await page.locator('.show-more-btn').evaluate(el=>{const r=el.getBoundingClientRect();return r.width>=24&&r.height>=24;}));
 await page.screenshot({path:path.join(out,'answer-mobile.png')});
 await page.setViewportSize({width:1280,height:900});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 check('데스크톱 답변 아래 입력창 표시',await page.locator('#user-input').evaluate(el=>{
  const r=el.getBoundingClientRect(),style=getComputedStyle(el);
  return r.height>0&&r.top>=0&&r.bottom<=innerHeight&&style.visibility==='visible';
 }));
 await page.screenshot({path:path.join(out,'answer-desktop.png')});
 await page.setViewportSize({width:390,height:844});
 await page.locator('.contact-actions summary').click();
 for(const width of [320,390,600]){
  await page.setViewportSize({width,height:844});
  for(const lang of ['ko','en','vi','zh']){
   await page.evaluate(l=>{
    const row=window.uiTestBox.closest('.message-row');
    row.querySelector('.contact-actions').remove();
    addContactActions(window.uiTestBox,l);
    row.querySelector('.contact-actions').open=true;
   },lang);
   check('문의 메뉴 reflow '+width+' '+lang,await page.locator('.contact-actions').evaluate(el=>{
    const a=el.querySelector('a'),b=el.querySelector('button');
    return el.scrollWidth<=el.clientWidth+1&&a.getBoundingClientRect().height>=24&&b.getBoundingClientRect().height>=24&&!el.closest('[aria-live]');
   }));
  }
 }
 await page.setViewportSize({width:390,height:844});
 await page.evaluate(()=>{
  uiTestBox.closest('.message-row').querySelector('.contact-actions').remove();
  addContactActions(uiTestBox,'ko');
  uiTestBox.closest('.message-row').querySelector('.contact-actions').open=true;
 });
 check('문의 링크는 기본 파란색이 아닌 기존 본문 톤',await page.locator('.contact-email').evaluate(el=>getComputedStyle(el).color)==='rgb(52, 64, 84)');
 check('주소 링크 한 개와 복사 버튼만 표시',await page.locator('.contact-email').textContent()==='chanyoung@devleop136.com'&&await page.locator('.contact-content p').count()===0);
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
  document.querySelectorAll('#header-title,#welcome-title,#welcome-msg,.input-notice,.analytics-disclosure,.service-notice,.card-title,.card-body p,.show-more-btn,.contact-actions summary,.contact-content a,.contact-copy').forEach(el=>el.style.fontSize=parseFloat(getComputedStyle(el).fontSize)*2+'px');
 });
 await page.locator('.contact-copy').scrollIntoViewIfNeeded();
 check('200% 텍스트에서 본문 가로 넘침 없음',await page.evaluate(()=>[...document.querySelectorAll('#welcome-title,#welcome-msg,.input-notice,.result-card,.contact-actions')].every(el=>el.scrollWidth<=el.clientWidth+1)));
 await page.screenshot({path:path.join(out,'text-200-mobile.png')});
 await page.setViewportSize({width:1280,height:900});await page.screenshot({path:path.join(out,'text-200-desktop.png')});
 check('브라우저 JS 예외 없음',errors.length===0,errors);
 console.log(JSON.stringify({out,checks},null,2));
 if(!auditOnly)assert.equal(checks.filter(c=>!c.pass).length,0,'UI contract failures: '+checks.filter(c=>!c.pass).map(c=>c.name).join(', '));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
