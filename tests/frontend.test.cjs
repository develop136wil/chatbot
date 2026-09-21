const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function element() {
    return { style:{setProperty(name,value){this[name]=value}}, value:'', children:[], className:'', textContent:'', innerHTML:'',
        classList:{add(){}, remove(){}, contains(){return false}, toggle(){}},
        attributes:{}, events:{}, addEventListener(name,fn){(this.events[name] ||= []).push(fn)}, setAttribute(name,value){this.attributes[name]=value}, querySelector(){return null},
        querySelectorAll(){return []}, appendChild(child){this.children.push(child)},
        append(){}, remove(){}, blur(){}, focus(){}, click(){} };
}
function setup(options={}) {
    const elements = new Map();
    if (options.toggle) elements.set('suggestion-toggle-btn',options.toggle);
    const document = {
        getElementById(id) { if (!elements.has(id)) elements.set(id,element()); return elements.get(id) },
        createElement:element, querySelector(selector){return options.selectors?.[selector] || null}, querySelectorAll(){return []},
        addEventListener(){}, body:element(), documentElement:element()
    };
    const windowEvents={};
    const window={visualViewport:options.visualViewport,currentLang:'ko',addEventListener(name,fn){(windowEvents[name] ||= []).push(fn)},location:{href:'https://test.invalid'}};
    window.self=window.top=window;
    const context=vm.createContext({
        window, windowEvents, document, navigator:{}, console:{log(){}}, AbortController, DOMException,
        setTimeout,clearTimeout,setInterval,clearInterval,requestAnimationFrame:fn=>fn(),
        fetch:async()=>{throw new Error('Unexpected network')},
    });
    vm.runInContext(fs.readFileSync('static/ui-text.js','utf8'),context);
    vm.runInContext(fs.readFileSync('static/script.js','utf8'),context);
    vm.runInContext('typeWriterEffect = async (el,html) => { el.innerHTML=html; }; formatAssistantAnswer = text => text;',context);
    return context;
}

test('전체 스크립트는 visualViewport 없는 환경에서도 로드된다',()=>{
    const c=setup();
    assert.equal(c.window.isChatBusy(),false);
});
test('초기화 응답은 실제 내역·문서 ID·커서를 모두 지운다',async()=>{
    const c=setup(); c.box=element();
    vm.runInContext("chatHistory=[{role:'user',content:'old'}]; currentResultIds=['old']; currentShownCount=2; pendingContext='old';",c);
    await vm.runInContext("renderChatResponse({status:'complete',action:'reset',answer:'초기화'},box,'초기화',0)",c);
    assert.equal(vm.runInContext("chatHistory.length+currentResultIds.length+currentShownCount",c),0);
    assert.equal(vm.runInContext("pendingContext",c),null);
});
test('응답 공통 경로가 버튼 번역·더 보기·이메일 문의를 처리한다',async()=>{
    const c=setup(); c.box=element(); c.localized=0;
    vm.runInContext("translateCardButtons=()=>{localized++};",c);
    await vm.runInContext("renderChatResponse({status:'complete',answer:'answer',last_result_ids:['a','b','c'],shown_count:2,job_id:'fresh-id'},box,'질문',0)",c);
    assert.equal(c.localized,1);
    assert.equal(c.box.children[0].className,'show-more-btn');
    assert.equal(c.box.children[1].className,'contact-actions');
});
test('이전 요청의 늦은 응답이 새 화면을 덮지 않는다',async()=>{
    const c=setup(); c.box=element();
    await vm.runInContext("renderChatResponse({status:'complete',answer:'old'},box,'질문',99)",c);
    assert.equal(c.box.innerHTML,'');
});
test('처리 중 중복 제출은 요청을 보내지 않는다',async()=>{
    const c=setup(); let count=0;
    c.fetch=async()=>{count++;throw new Error('should not run')};
    vm.runInContext("isChatLoading=true; userInput.value='지원';",c);
    await vm.runInContext("handleFormSubmit()",c);
    await vm.runInContext("handleButtonClick('지원')",c);
    assert.equal(count,0);
});
test('polling은 pending 다음 완료를 순차 처리한다',async()=>{
    const c=setup(); let active=0, peak=0, count=0;
    c.fetch=async()=>{active++;peak=Math.max(peak,active);count++;active--;return {ok:true,json:async()=>({status:count===1?'pending':'complete',answer:'ok'})}};
    const result=await vm.runInContext("pollForResult('id',new AbortController().signal)",c);
    assert.equal(result.status,'complete');assert.equal(count,2);assert.equal(peak,1);
});
test('베트남어 다음 요청을 명시적 더 보기로 인식한다',()=>{
    assert.equal(vm.runInContext("SHOW_MORE_KEYWORDS.has('tiếp theo')",setup()),true);
});

test('입력창 높이 증가만큼 답변 하단 여백도 늘어난다', () => {
    const c=setup();
    const small=vm.runInContext('overlayMetrics(66,61,36,true)',c);
    const large=vm.runInContext('overlayMetrics(140,61,36,true)',c);
    assert.equal(small.bottomPadding,143);
    assert.equal(large.bottomPadding-small.bottomPadding,74);
});
test('추천 질문을 접어도 토글 버튼 높이를 확보한다', () => {
    const c=setup();
    const metrics=vm.runInContext('overlayMetrics(66,61,36,false)',c);
    assert.equal(metrics.bottomPadding,130);
    assert.ok(metrics.bottomPadding > metrics.footer+36);
});
test('레이아웃 갱신은 읽던 과거 답변의 스크롤 위치를 유지한다', () => {
    const footer=element(), suggestions=element(), toggle=element();
    footer.getBoundingClientRect=()=>({height:140});
    suggestions.getBoundingClientRect=()=>({height:61});
    toggle.getBoundingClientRect=()=>({height:36});
    const c=setup({selectors:{'.chat-input-box':footer,'.suggestion-container':suggestions},toggle});
    vm.runInContext('chatBox.scrollHeight=2000;chatBox.clientHeight=500;chatBox.scrollTop=200;syncInputOverlay()',c);
    assert.equal(vm.runInContext('chatBox.scrollTop',c),200);
    assert.equal(c.document.documentElement.style['--chat-footer-height'],'140px');
    assert.equal(c.document.documentElement.style['--chat-bottom-padding'],'217px');
});
test('4개 언어의 더 보기 버튼이 각각 표시된다', async () => {
    for (const [lang,label] of Object.entries({ko:'결과 더 보기',en:'More results',vi:'Xem thêm kết quả',zh:'查看更多结果'})) {
        const c=setup();c.window.currentLang=lang;c.box=element();
        await vm.runInContext("renderChatResponse({status:'complete',answer:'ok',last_result_ids:['a','b','c'],shown_count:2},box,'q',0)",c);
        assert.equal(c.box.children[0].textContent,label);
    }
});
test('전송 시 동일 질문 캐시와 더 보기에 필요한 이전 ID를 보존한다', async () => {
    const c=setup();
    vm.runInContext("currentResultIds=['a','b'];currentShownCount=2;userInput.value='지원'; addMessageToBox=()=>({});fetchChatResponse=async body=>{window.sent=body};",c);
    await vm.runInContext('handleFormSubmit()',c);
    vm.runInContext('setLoadingState(false)',c);
    assert.equal(c.window.sent.action,'ask');
    assert.deepEqual(Array.from(c.window.sent.last_result_ids),['a','b']);
    assert.equal(c.window.sent.shown_count,2);
});
test('타이핑 대기 중 요청이 바뀌면 이전 결과로 대화 상태를 덮지 않는다', async () => {
    const c=setup();c.box=element();
    vm.runInContext('typeWriterEffect=async()=>{activeRequestSequence=1};',c);
    await vm.runInContext("renderChatResponse({status:'complete',answer:'old',last_result_ids:['old']},box,'q',0)",c);
    assert.equal(vm.runInContext('chatHistory.length+currentResultIds.length',c),0);
});
test('HTTP 오류 후 로딩 잠금이 해제되고 오류 문구를 보여준다', async () => {
    const c=setup();c.box=element();
    c.fetch=async()=>({ok:false,status:503});
    vm.runInContext('addMessageToBox=()=>box;isChatLoading=true;',c);
    await vm.runInContext("fetchChatResponse({question:'q'})",c);
    assert.equal(c.window.isChatBusy(),false);
    assert.match(c.box.textContent,/오류/);
});

test('공유 취소는 클립보드 복사로 이어지지 않는다', async () => {
    const c=setup(); let copies=0;
    c.navigator.share=async()=>{throw new DOMException('Cancelled','AbortError')};
    c.navigator.clipboard={writeText:async()=>{copies++}};
    await c.shareCard({dataset:{copy:'card'}});
    assert.equal(copies,0);
});
test('공유 기능이 없으면 선택한 언어로 복사 완료를 알린다', async () => {
    const c=setup();c.window.currentLang='vi';let copied;
    c.navigator.clipboard={writeText:async value=>{copied=value}};
    vm.runInContext('showToast=text=>{window.notice=text};',c);
    await c.shareCard({dataset:{copy:'card'}});
    assert.equal(copied,'card');
    assert.equal(c.window.notice,c.window.CHAT_UI_TEXT.vi.copied);
});
test('토스트 구현은 하나이며 부모 영역을 숨기는 스타일이 없다', () => {
    const script=fs.readFileSync('static/script.js','utf8');
    const css=fs.readFileSync('static/style.css','utf8');
    assert.equal((script.match(/function showToast\(/g)||[]).length,1);
    const blocks=Array.from(css.matchAll(/#toast-container\s*\{([^}]+)\}/g));
    assert.equal(blocks.length,1);
    assert.match(blocks[0][1],/visibility:\s*visible/);
    assert.match(blocks[0][1],/opacity:\s*1/);
});
test('오류 재시도는 원래 질문과 대화 문맥을 한 번만 전송한다', async () => {
    const c=setup();c.box=element();let calls=0, body;
    c.fetch=async (_url,init)=>{calls++;body=JSON.parse(init.body);return calls===1?{ok:false,status:503}:{ok:true,json:async()=>({status:'complete',answer:'ok'})}};
    vm.runInContext("addMessageToBox=()=>box;currentQuestion='지원';chatHistory=[{role:'user',content:'지원'}];",c);
    await vm.runInContext("fetchChatResponse({question:'지원',language:'ko',chat_history:[]})",c);
    assert.equal(calls,1); // no automatic retry
    assert.equal(c.box.children[0].className,'retry-btn');
    await c.box.children[0].onclick();
    assert.equal(calls,2);
    assert.equal(body.question,'지원');
    assert.deepEqual(body.chat_history,[]);
    assert.equal(vm.runInContext("chatHistory.filter(x=>x.role==='user').length",c),1);
});
test('서버의 일일 제한에는 재시도 버튼을 표시하지 않는다', async () => {
    const c=setup();c.box=element();
    c.fetch=async()=>({ok:true,json:async()=>({status:'error',message:'limit',retryable:false})});
    vm.runInContext('addMessageToBox=()=>box;',c);
    await c.fetchChatResponse({question:'q',language:'en'});
    assert.equal(c.box.children.filter(child=>child.className==='retry-btn').length,0);
    assert.equal(c.box.children[0].className,'contact-actions');
    assert.equal(c.box.textContent,'limit');
});
test('HTTP 429 안내와 Retry-After 대기 시간을 지킨다', async () => {
    const c=setup();c.box=element();let calls=0;
    c.fetch=async()=>{calls++;return {ok:false,status:429,headers:{get:()=> '60'}}};
    vm.runInContext('addMessageToBox=()=>box;showToast=text=>{window.notice=text};',c);
    await c.fetchChatResponse({question:'q',language:'ko'});
    assert.match(c.box.textContent,/요청이 많/);
    await c.box.children[0].onclick();
    assert.equal(calls,1);
    assert.match(c.window.notice,/60s/);
});
test('다른 요청이 시작된 뒤 이전 오류 버튼은 재전송하지 않는다', async () => {
    const c=setup();c.box=element();let count=0;
    vm.runInContext("showRequestError(box,{message:'failed'},{question:'q',language:'ko'},'q',0);activeRequestSequence=1;",c);
    c.fetch=async()=>{count++};
    await c.box.children[0].onclick();
    assert.equal(count,0);
});
test('요청 제한 대기 값은 잘못되거나 음수면 안전하게 처리한다', () => {
    const c=setup();
    assert.equal(c.retryDelay('garbage'),0);
    assert.equal(c.retryDelay('-3'),0);
    assert.equal(c.retryDelay('10'),10000);
    assert.equal(c.retryDelay('9999999999'),3600000);
});
test('모든 언어에 동일한 정적 안내 키가 있다', () => {
    const c=setup();
    const dict=c.window.CHAT_UI_TEXT;
    const keys=Object.keys(dict.ko).sort();
    for(const lang of ['en','vi','zh']) assert.deepEqual(Object.keys(dict[lang]).sort(),keys);
    for(const text of Object.values(dict)) {
        assert.ok(text.processing && text.slow && text.offline && text.retry && text.detail);
        assert.doesNotMatch(text.processing,/자격|요건|포장|15~30/);
    }
});
function loadHome(c) {
    const html=fs.readFileSync('static/index.html','utf8');
    const code=html.match(/<script>\s*(const translations =[\s\S]+?)<\/script>/)[1];
    vm.runInContext(code,c);
}
test('저장된 언어가 새로고침 후 복원되고 접근성 이름도 바뀐다', () => {
    const c=setup();const writes=[];
    c.localStorage={getItem:()=> 'vi',setItem:(...args)=>writes.push(args)};
    loadHome(c);c.window.onload();
    assert.equal(c.window.currentLang,'vi');
    assert.equal(c.document.documentElement.lang,'vi');
    assert.equal(c.document.getElementById('user-input').attributes['aria-label'],c.window.CHAT_UI_TEXT.vi.input_label);
    assert.equal(c.document.getElementById('scroll-bottom-btn').textContent,'↓');
    assert.equal(c.document.getElementById('scroll-bottom-btn').attributes['aria-label'],c.window.CHAT_UI_TEXT.vi.scroll_bottom);
    assert.ok(writes.length);
});
test('언어 저장소 접근이 차단되어도 첫 화면이 정상 초기화된다', () => {
    const c=setup();
    c.localStorage={getItem(){throw new Error('blocked')},setItem(){throw new Error('blocked')}};
    loadHome(c);c.window.onload();
    assert.equal(c.window.currentLang,'ko');
});
test('잘못된 저장 언어를 사용하지 않고 처리 중 언어 변경을 막는다', () => {
    const c=setup();c.localStorage={getItem:()=> '__proto__',setItem(){}};
    loadHome(c);c.window.onload();
    assert.equal(c.window.currentLang,'ko');
    vm.runInContext('isChatLoading=true;',c);
    c.changeLanguage('en');
    assert.equal(c.window.currentLang,'ko');
});
test('오프라인·온라인 이벤트가 선택 언어 안내를 사용한다', () => {
    const c=setup();c.window.currentLang='zh';
    vm.runInContext('showToast=text=>{window.notice=text};',c);
    c.windowEvents.offline[0]();
    assert.equal(c.window.notice,c.window.CHAT_UI_TEXT.zh.offline);
    c.windowEvents.online[0]();
    assert.equal(c.window.notice,c.window.CHAT_UI_TEXT.zh.online);
});
test('언어 선택은 로컬 국기와 접근성 이름을 유지하며 제목 높이를 측정한다', () => {
    const html=fs.readFileSync('static/index.html','utf8');
    assert.match(html,/class="chat-topbar"/);
    assert.match(html,/Tiếng Việt/);
    for (const flag of ['kr','us','vn','cn']) assert.ok(html.includes('/static/flags/'+flag+'.svg'));
    const header=element();header.getBoundingClientRect=()=>({height:172});
    const c=setup({selectors:{'.chat-topbar':header}});
    c.syncHeaderHeight();
    assert.equal(c.document.documentElement.style['--chat-top-height'],'172px');
});

test('라이트 모드만 선언하고 다크 시스템 테마 분기를 제거한다', () => {
    const css=fs.readFileSync('static/style.css','utf8');
    const html=fs.readFileSync('static/index.html','utf8');
    const js=fs.readFileSync('static/script.js','utf8');
    assert.match(css,/:root\s*\{[^}]*color-scheme:\s*only light;/);
    assert.match(html,/<meta name="color-scheme" content="only light">/);
    assert.ok(html.indexOf('name="color-scheme"') < html.indexOf('rel="stylesheet"'));
    for (const source of [css,html,js]) assert.doesNotMatch(source,/prefers-color-scheme\s*:\s*dark/i);
    assert.match(html,/style\.css\?v=2026\.09\.21-type-glass/);
});

test('라이트 고정 후에도 동작 줄이기와 사용자 고대비 설정을 방해하지 않는다', () => {
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    assert.doesNotMatch(css,/forced-color-adjust\s*:\s*none/i);
    assert.match(css,/button:focus-visible/);
});

test('앱 설치 화면과 브라우저 테마 색상이 라이트 설정과 일치한다', () => {
    const manifest=JSON.parse(fs.readFileSync('static/manifest.json','utf8'));
    const html=fs.readFileSync('static/index.html','utf8');
    assert.equal(manifest.theme_color.toUpperCase(),'#FFFFFF');
    assert.equal(manifest.background_color.toUpperCase(),'#FFFFFF');
    assert.match(html,/<meta name="theme-color" content="#FFFFFF">/);
});

function overlaySetup(options={}) {
    const footer=element(), suggestions=element(), toggle=element();
    footer.getBoundingClientRect=()=>({height:80});
    suggestions.getBoundingClientRect=()=>({height:60});
    toggle.getBoundingClientRect=()=>({height:36,width:options.width || 112});
    return setup({...options,selectors:{'.chat-input-box':footer,'.suggestion-container':suggestions},toggle});
}

test('추천 질문을 펼쳐도 읽던 과거 답변으로부터 이동하지 않는다', () => {
    const c=overlaySetup();
    vm.runInContext('chatBox.scrollHeight=2000;chatBox.clientHeight=500;chatBox.scrollTop=200;syncSuggestionOverlay()',c);
    assert.equal(vm.runInContext('chatBox.scrollTop',c),200);
});

test('하단을 읽고 있으면 추천 질문 여백 갱신 후에도 하단을 유지한다', () => {
    const c=overlaySetup();
    vm.runInContext('chatBox.scrollHeight=2000;chatBox.clientHeight=500;chatBox.scrollTop=1480;syncSuggestionOverlay()',c);
    assert.equal(vm.runInContext('chatBox.scrollTop',c),2000);
});

test('화면 높이 변경은 과거 답변을 강제로 맨 아래로 스크롤하지 않는다', () => {
    let resize;
    const c=overlaySetup({visualViewport:{addEventListener(name,fn){if(name==='resize')resize=fn}}});
    vm.runInContext('chatBox.scrollHeight=2000;chatBox.clientHeight=300;chatBox.scrollTop=200',c);
    resize();
    assert.equal(vm.runInContext('chatBox.scrollTop',c),200);
});

test('추천 질문 스크롤 영역은 번역된 접기 버튼과 분리한다', () => {
    for(const width of [72,154]) {
        const c=overlaySetup({width});
        c.syncInputOverlay();
        assert.equal(c.document.documentElement.style['--suggestion-toggle-width'],width+'px');
    }
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/#suggestion-container\s*\{[^}]*width: calc\(min\(100%, 600px\) - var\(--suggestion-toggle-width, 100px\) - 24px\)/);
    assert.match(css,/#suggestion-container\s*\{[^}]*mask-image:\s*none/);
});

test('작은 화면에서도 입력 글자는 16px이고 포커스는 진한 파란색이다', () => {
    const css=fs.readFileSync('static/style.css','utf8');
    const inputs=Array.from(css.matchAll(/#user-input\s*\{([^}]+)\}/g));
    assert.ok(inputs.length>=2);
    for(const [,rule] of inputs) assert.match(rule,/font-size:\s*16px/);
    assert.match(css,/textarea:focus-visible\s*\{[^}]*outline:\s*3px solid #175CD3 !important/);
    assert.doesNotMatch(css,/outline:[^;]*var\(--accent-color\)/);
});

test('최신 답변 이동은 동작 줄이기 설정을 존중한다', () => {
    const js=fs.readFileSync('static/script.js','utf8');
    assert.match(js,/behavior: window\.matchMedia\?\.\('\(prefers-reduced-motion: reduce\)'\)\.matches \? 'auto' : 'smooth'/);
});

function assertInputDisabled(c, expected) {
    for (const id of ['user-input','send-btn','mic-btn'])
        assert.equal(c.document.getElementById(id).disabled,expected,id);
}
test('오프라인에서 요청 종료 후 재연결하면 입력·전송·마이크가 함께 복구된다', () => {
    const c=setup();
    c.navigator.onLine=false;
    c.setLoadingState(false);
    assertInputDisabled(c,true);
    c.navigator.onLine=true;
    c.windowEvents.online[0]();
    assertInputDisabled(c,false);
});

test('처리 중 재연결은 요청 잠금을 풀거나 요청을 다시 보내지 않는다', () => {
    const c=setup();
    c.setLoadingState(true);
    c.navigator.onLine=false;
    c.windowEvents.offline[0]();
    assertInputDisabled(c,true);
    c.navigator.onLine=true;
    c.windowEvents.online[0]();
    assertInputDisabled(c,true);
    assert.equal(c.window.isChatBusy(),true);
    c.setLoadingState(false);
    assertInputDisabled(c,false);
});

test('오프라인 전환 시 모든 입력 버튼을 잠그고 입력 내용은 보존한다', () => {
    const c=setup();
    c.setLoadingState(false);
    c.document.getElementById('user-input').value='입력 중인 질문';
    c.navigator.onLine=false;
    c.windowEvents.offline[0]();
    assertInputDisabled(c,true);
    c.setLoadingState(false);
    assert.equal(c.document.getElementById('user-input').placeholder,c.window.CHAT_UI_TEXT.ko.offline);
    assert.equal(c.document.getElementById('user-input').value,'입력 중인 질문');
});

function pressInputKey(c, overrides={}) {
    let prevented=false;
    const event={key:'Enter',shiftKey:false,isComposing:false,keyCode:13,
        preventDefault(){prevented=true},...overrides};
    for (const fn of c.document.getElementById('user-input').events.keydown) fn(event);
    return prevented;
}
function keyboardSetup() {
    const c=setup();
    vm.runInContext('window.submissions=0;handleFormSubmit=()=>{window.submissions++}',c);
    return c;
}
test('한글 조합 중 Enter는 기본 동작을 막거나 질문을 보내지 않는다', () => {
    const c=keyboardSetup();
    assert.equal(pressInputKey(c,{isComposing:true}),false);
    assert.equal(c.window.submissions,0);
});
test('조합 호환 키코드 229도 입력 확정에 맡긴다', () => {
    const c=keyboardSetup();
    assert.equal(pressInputKey(c,{keyCode:229}),false);
    assert.equal(c.window.submissions,0);
});
test('조합이 끝난 Enter는 한 번 전송하며 Shift+Enter는 줄바꿈을 유지한다', () => {
    const c=keyboardSetup();
    assert.equal(pressInputKey(c,{shiftKey:true}),false);
    assert.equal(c.window.submissions,0);
    assert.equal(pressInputKey(c),true);
    assert.equal(c.window.submissions,1);
});

function offlineContext() {
    const c=setup();
    c.navigator.onLine=false;
    vm.runInContext("window.sentCount=0;showToast=text=>{window.notice=text};fetchChatResponse=async()=>{window.sentCount++};userInput.value='보존할 질문';chatHistory=[{role:'user',content:'이전 질문'}];pendingContext='기존 문맥';",c);
    return c;
}
function assertOfflineUnchanged(c) {
    assert.equal(c.window.sentCount,0);
    assert.equal(c.document.getElementById('user-input').value,'보존할 질문');
    assert.equal(vm.runInContext('chatHistory.length',c),1);
    assert.equal(vm.runInContext('pendingContext',c),'기존 문맥');
    assert.equal(c.window.isChatBusy(),false);
}
test('오프라인 직접 전송은 요청·입력 삭제·대화 변경 전에 차단한다',async()=>{
    const c=offlineContext();
    await c.handleFormSubmit();
    assertOfflineUnchanged(c);
    assert.equal(c.window.notice,c.window.CHAT_UI_TEXT.ko.offline);
});
test('오프라인 명확화 버튼도 기존 문맥을 잃지 않는다',async()=>{
    const c=offlineContext();
    await c.handleButtonClick('돌봄');
    assertOfflineUnchanged(c);
});
test('오프라인 추천 질문은 입력을 덮거나 지연 전송을 예약하지 않는다',()=>{
    const c=offlineContext();let timers=0;
    c.setTimeout=()=>{timers++};
    c.sendSuggestion('추천 질문');
    assertOfflineUnchanged(c);
    assert.equal(timers,0);
});
test('오프라인 더 보기 버튼은 입력을 덮거나 새 대화를 만들지 않는다',async()=>{
    const c=offlineContext();c.box=element();
    await vm.runInContext("renderChatResponse({status:'complete',answer:'답변',last_result_ids:['a','b','c'],shown_count:2},box,'질문',0)",c);
    const before=vm.runInContext('chatHistory.length',c);
    c.box.children[0].onclick();
    assert.equal(c.window.sentCount,0);
    assert.equal(c.document.getElementById('user-input').value,'보존할 질문');
    assert.equal(vm.runInContext('chatHistory.length',c),before);
});
test('오프라인 재시도는 버튼을 영구 잠그지 않고 복구 후 수동 클릭만 전송한다',async()=>{
    const c=offlineContext();c.box=element();
    vm.runInContext("showRequestError(box,{message:'오류'},{question:'원래 질문',language:'ko'},'원래 질문',0)",c);
    const button=c.box.children[0];
    await button.onclick();
    assertOfflineUnchanged(c);
    assert.notEqual(button.disabled,true);
    c.navigator.onLine=true;
    c.windowEvents.online[0]();
    assert.equal(c.window.sentCount,0);
    await button.onclick();
    assert.equal(c.window.sentCount,1);
});
test('오프라인 첫 화면 초기화도 전송·마이크를 잠근다',()=>{
    const c=offlineContext();
    for(const fn of c.windowEvents.load) fn();
    assertInputDisabled(c,true);
    assert.equal(c.document.getElementById('user-input').placeholder,c.window.CHAT_UI_TEXT.ko.offline);
});
test('오프라인 중 언어 변경은 해당 언어의 연결 안내를 유지한다',()=>{
    const c=offlineContext();c.localStorage={getItem:()=>null,setItem(){}};
    loadHome(c);
    c.changeLanguage('vi');
    assert.equal(c.document.getElementById('user-input').placeholder,c.window.CHAT_UI_TEXT.vi.offline);
    assertInputDisabled(c,true);
});

function lengthContext(lang='ko') {
    const c=setup(); c.window.currentLang=lang;
    vm.runInContext("window.sentCount=0;showToast=text=>{window.notice=text};fetchChatResponse=async body=>{window.sentCount++;window.sent=body};addMessageToBox=()=>({});chatHistory=[{role:'user',content:'previous'}];pendingContext='context';",c);
    return c;
}

test('4개 언어에서 전송 한도 초과 시 입력·대화·문맥을 보존한다',async()=>{
    for(const lang of ['ko','en','vi','zh']) {
        const c=lengthContext(lang);
        const suffixLength=vm.runInContext("Array.from(buildServerQuestion('')).length",c);
        const value='가'.repeat(2001-suffixLength);
        c.document.getElementById('user-input').value=value;
        await c.handleFormSubmit();
        assert.equal(c.window.sentCount,0);
        assert.equal(c.document.getElementById('user-input').value,value);
        assert.equal(vm.runInContext('chatHistory.length',c),1);
        assert.equal(vm.runInContext('pendingContext',c),'context');
        assert.equal(c.window.isChatBusy(),false);
        assert.equal(c.window.notice,c.window.CHAT_UI_TEXT[lang].question_too_long.replace('{limit}',String(2000-suffixLength)));
    }
});

test('언어 지시문 포함 정확히 2000자인 질문은 전송된다',async()=>{
    for(const lang of ['ko','en','vi','zh']) {
        const c=lengthContext(lang);
        const suffixLength=vm.runInContext("Array.from(buildServerQuestion('')).length",c);
        c.document.getElementById('user-input').value='가'.repeat(2000-suffixLength);
        await c.handleFormSubmit();
        assert.equal(c.window.sentCount,1);
        assert.equal(Array.from(c.window.sent.question).length,2000);
        assert.equal(c.window.sent.language,lang);
        assert.equal(c.document.getElementById('user-input').value,'');
    }
});

test('이모지 길이는 UTF-16 단위가 아닌 서버와 같은 코드 포인트로 센다',async()=>{
    const c=lengthContext();
    c.document.getElementById('user-input').value='😀'.repeat(2000);
    await c.handleFormSubmit();
    assert.equal(c.window.sentCount,1);
    assert.equal(Array.from(c.window.sent.question).length,2000);
    const rejected=lengthContext();
    rejected.document.getElementById('user-input').value='😀'.repeat(2001);
    await rejected.handleFormSubmit();
    assert.equal(rejected.window.sentCount,0);
});

test('긴 명확화 질문도 버튼과 기존 문맥을 삭제하지 않는다',async()=>{
    const c=lengthContext('vi');
    vm.runInContext("pendingContext='a'.repeat(1990);window.cleared=0;clearButtons=()=>{window.cleared++};userInput.value='draft';",c);
    await c.handleButtonClick('childcare');
    assert.equal(c.window.sentCount,0);
    assert.equal(c.window.cleared,0);
    assert.equal(vm.runInContext('pendingContext.length',c),1990);
    assert.equal(c.document.getElementById('user-input').value,'draft');
    assert.equal(c.window.isChatBusy(),false);
});

test('짧은 명확화 질문과 언어 지시문은 기존대로 전송한다',async()=>{
    const c=lengthContext('en');
    await c.handleButtonClick('childcare');
    assert.equal(c.window.sentCount,1);
    assert.equal(c.window.sent.question,'context childcare \n\n(System: Please answer strictly in English.)');
    assert.equal(vm.runInContext('pendingContext',c),null);
});

test('질문 길이 제한은 서버 상수와 동일하다',()=>{
    const match=fs.readFileSync('main.py','utf8').match(/^MAX_QUESTION_LENGTH = (\d+)$/m);
    assert.ok(match);
    assert.equal(vm.runInContext('MAX_QUESTION_LENGTH',setup()),Number(match[1]));
});

function pollingContext() {
    const c=setup();
    c.boxes=[];
    c.createBox=()=>{const box=element();c.boxes.push(box);return box;};
    vm.runInContext("addMessageToBox=()=>createBox();renderChatResponse=async data=>{window.completed=data};currentQuestion='지원';chatHistory=[{role:'user',content:'지원'}];",c);
    return c;
}
function response(data) { return {ok:true,json:async()=>data}; }

test('조회 실패 후 재시도는 기존 작업 GET만 보내고 새 질문 POST를 만들지 않는다',async()=>{
    const c=pollingContext(), calls=[];
    c.fetch=async(url,options)=>{
        calls.push([url,options?.method || 'GET']);
        if(calls.length===1) return response({job_id:'existing-job'});
        if(calls.length===2) return {ok:false,status:503};
        return response({status:'complete',answer:'done'});
    };
    await c.fetchChatResponse({question:'지원',language:'ko'});
    assert.equal(c.boxes[0].children[0].textContent,c.window.CHAT_UI_TEXT.ko.retry_result);
    await c.boxes[0].children[0].onclick();
    assert.deepEqual(calls,[['/chat','POST'],['/get_result/existing-job','GET'],['/get_result/existing-job','GET']]);
    assert.equal(c.window.completed.job_id,'existing-job');
    assert.equal(vm.runInContext('chatHistory.length',c),1);
    assert.equal(c.window.isChatBusy(),false);
});

test('여러 번 조회가 실패해도 동일 작업 ID를 유지한다',async()=>{
    const c=pollingContext(), calls=[];
    c.fetch=async(url)=>{
        calls.push(url);
        if(calls.length===1) return response({job_id:'keep'});
        throw new TypeError('network unavailable');
    };
    await c.fetchChatResponse({question:'지원'});
    await c.boxes[0].children[0].onclick();
    await c.boxes[1].children[0].onclick();
    assert.deepEqual(calls,['/chat','/get_result/keep','/get_result/keep','/get_result/keep']);
    assert.equal(c.window.isChatBusy(),false);
});

test('조회 시간 초과 후에도 새 작업 대신 기존 결과를 확인한다',async()=>{
    const c=pollingContext(), calls=[];
    c.fetch=async(url)=>{
        calls.push(url);
        if(calls.length===1) return response({job_id:'slow'});
        if(calls.length===2) throw new DOMException('timeout','AbortError');
        return response({status:'complete',answer:'done'});
    };
    await c.fetchChatResponse({question:'지원'});
    assert.equal(c.boxes[0].textContent,c.window.CHAT_UI_TEXT.ko.timeout);
    await c.boxes[0].children[0].onclick();
    assert.deepEqual(calls,['/chat','/get_result/slow','/get_result/slow']);
});

test('잘못된 조회 JSON 또는 상태도 기존 작업의 재조회만 허용한다',async()=>{
    for(const bad of [{ok:true,json:async()=>{throw new SyntaxError('invalid JSON')}},
                      response({status:'unexpected'})]) {
        const c=pollingContext();let posts=0,gets=0;
        c.fetch=async(url)=>{
            if(url==='/chat'){posts++;return response({job_id:'valid-job'});}
            gets++;return gets===1 ? bad : response({status:'complete',answer:'done'});
        };
        await c.fetchChatResponse({question:'지원'});
        await c.boxes[0].children[0].onclick();
        assert.equal(posts,1);assert.equal(gets,2);
    }
});

test('작업의 명시적인 실패가 확인된 경우에만 일반 재전송 정책을 적용한다',async()=>{
    const c=pollingContext();let posts=0,gets=0;
    c.fetch=async(url)=>{
        if(url==='/chat'){posts++;return response({job_id:'job-'+posts});}
        gets++;
        return gets===1 ? response({status:'error',message:'failed',retryable:true})
                        : response({status:'complete',answer:'done'});
    };
    await c.fetchChatResponse({question:'지원'});
    assert.equal(c.boxes[0].children[0].textContent,c.window.CHAT_UI_TEXT.ko.retry);
    await c.boxes[0].children[0].onclick();
    assert.equal(posts,2);assert.equal(gets,2);
});

test('작업의 무료 한도 오류는 재시도 버튼을 만들지 않는다',async()=>{
    const c=pollingContext();
    c.fetch=async(url)=>response(url==='/chat' ? {job_id:'quota'} : {status:'error',message:'quota',retryable:false});
    await c.fetchChatResponse({question:'지원'});
    assert.equal(c.boxes[0].children.filter(child=>child.className==='retry-btn').length,0);
        assert.equal(c.boxes[0].children[0].className,'contact-actions');
    assert.equal(c.window.isChatBusy(),false);
});

test('404 또는 410 결과 조회는 자동 재전송 없이 안내한다',async()=>{
    for(const status of [404,410]){
        const c=pollingContext();let posts=0;
        c.fetch=async(url)=>{
            if(url==='/chat'){posts++;return response({job_id:'missing'});}
            return {ok:false,status};
        };
        await c.fetchChatResponse({question:'지원'});
        assert.equal(c.boxes[0].textContent,c.window.CHAT_UI_TEXT.ko.result_unavailable);
        assert.equal(c.boxes[0].children.filter(child=>child.className==='retry-btn').length,0);
        assert.equal(c.boxes[0].children[0].className,'contact-actions');
        assert.equal(posts,1);
    }
});

test('결과 조회 429의 Retry-After를 지킨 후 기존 결과만 다시 조회한다',async()=>{
    const c=pollingContext();let now=1000,gets=0,posts=0;
    c.Date={now:()=>now,parse:Date.parse};
    vm.runInContext('showToast=()=>{}',c);
    c.fetch=async(url)=>{
        if(url==='/chat'){posts++;return response({job_id:'limited'});}
        gets++;
        return gets===1 ? {ok:false,status:429,headers:{get:()=> '2'}}
                        : response({status:'complete',answer:'done'});
    };
    await c.fetchChatResponse({question:'지원'});
    await c.boxes[0].children[0].onclick();
    assert.equal(gets,1);
    now=3001;
    await c.boxes[0].children[0].onclick();
    assert.equal(posts,1);assert.equal(gets,2);
});

test('오래된 결과 재조회 버튼은 새 대화 시작 후 작동하지 않는다',async()=>{
    const c=pollingContext();let count=0;
    c.fetch=async(url)=>{count++;return url==='/chat' ? response({job_id:'old'}) : {ok:false,status:503};};
    await c.fetchChatResponse({question:'지원'});
    vm.runInContext('activeRequestSequence++',c);
    await c.boxes[0].children[0].onclick();
    assert.equal(count,2);
});

test('결과 재조회 버튼은 4개 언어에서 구분해 표시한다',()=>{
    for(const lang of ['ko','en','vi','zh']){
        const c=pollingContext(), box=element();
        c.showRequestError(box,{message:'error'},{question:'q',language:lang},'q',0,0,'job');
        assert.equal(box.children[0].textContent,c.window.CHAT_UI_TEXT[lang].retry_result);
        assert.notEqual(box.children[0].textContent,c.window.CHAT_UI_TEXT[lang].retry);
    }
});

test('폴링 대기 중 취소는 타이머와 이벤트 리스너를 정리한다',async()=>{
    const c=pollingContext();let listener=null,removed=0,cleared=0;
    const signal={aborted:false,addEventListener(name,fn){listener=fn;},
                  removeEventListener(){removed++;}};
    c.setTimeout=()=>17;
    c.clearTimeout=id=>{if(id===17)cleared++;};
    const pending=c.waitForPoll(signal);
    listener();
    await assert.rejects(pending,{name:'AbortError'});
    assert.equal(removed,1);assert.equal(cleared,1);
});

test('이미 취소된 폴링은 네트워크 요청 없이 종료한다',async()=>{
    const c=pollingContext();let count=0;
    c.fetch=async()=>{count++;throw new Error('unexpected');};
    const controller=new AbortController();controller.abort();
    await assert.rejects(c.pollForResult('job',controller.signal),{name:'AbortError'});
    assert.equal(count,0);
});

test('결과 렌더링 실패도 이미 완료된 작업을 다시 실행하지 않는다',async()=>{
    const c=pollingContext();let posts=0,gets=0;
    vm.runInContext("renderChatResponse=async()=>{throw new Error('render failed')}",c);
    c.fetch=async(url)=>{
        if(url==='/chat'){posts++;return response({job_id:'completed'});}
        gets++;return response({status:'complete',answer:'done'});
    };
    await c.fetchChatResponse({question:'지원'});
    await c.boxes[0].children[0].onclick();
    assert.equal(posts,1);assert.equal(gets,2);
});

test('재조회 중 오프라인이면 GET도 새 POST도 보내지 않는다',async()=>{
    const c=pollingContext();let count=0;
    vm.runInContext('showToast=()=>{}',c);
    c.fetch=async(url)=>{count++;return url==='/chat' ? response({job_id:'offline'}) : {ok:false,status:503};};
    await c.fetchChatResponse({question:'지원'});
    c.navigator.onLine=false;
    await c.boxes[0].children[0].onclick();
    assert.equal(count,2);
    assert.equal(c.window.isChatBusy(),false);
});

test('시작 화면·제목·설치 앱의 한국어 이름이 일치한다',()=>{
    const c=setup(),html=fs.readFileSync('static/index.html','utf8');
    const manifest=JSON.parse(fs.readFileSync('static/manifest.json','utf8'));
    const name=c.window.CHAT_UI_TEXT.ko.title;
    assert.equal(name,'도봉구 영유아 복지정보자료집');
    assert.ok(html.includes('<title>'+name+'</title>'));
    assert.ok(html.includes('class="splash-title">'+name+'</h1>'));
    assert.ok(html.includes('id="header-title">'+name+'</span>'));
    assert.equal(manifest.name,name);
});

test('글라스 제목의 상위 영역이 불투명한 배경으로 효과를 덮지 않는다',()=>{
    const css=fs.readFileSync('static/style.css','utf8');
    const top=css.match(/\.chat-topbar\s*\{([^}]+)\}/)[1];
    assert.match(top,/background: transparent; border: 0/);
    const surface=css.match(/\.chat-topbar::before\s*\{([^}]+)\}/)[1];
    assert.match(surface,/background: rgba\(249, 250, 251, .98\)/);
    assert.match(surface,/mask-image: linear-gradient\(to bottom, #000 0%, #000 65%, transparent 100%\)/);
    assert.match(surface,/pointer-events: none/);
    assert.match(surface,/backdrop-filter: var\(--glass-blur\)/);
    assert.doesNotMatch(top,/background: var\(--bg-color\)/);
    assert.match(css,/\.message\.user p\s*\{[^}]*white-space: pre-wrap/);
});

test('육아 팁은 네 언어에서 무작위로 순환하고 바로 같은 팁을 반복하지 않는다',()=>{
    for(const lang of ['ko','en','vi','zh']){
        const c=setup(),tip=element(),box=element();
        box.querySelector=()=>tip;
        let tick,cleared=false;
        c.setInterval=(fn,ms)=>{assert.equal(ms,7000);tick=fn;return 51;};
        c.clearInterval=id=>{assert.equal(id,51);cleared=true;};
        const stop=c.startLoadingTips(box,lang);
        const first=tip.textContent;tick();
        assert.notEqual(tip.textContent,first);
        assert.ok(tip.textContent.startsWith(c.window.CHAT_UI_TEXT[lang].tip_label+'\n'));
        assert.ok(c.window.CHAT_UI_TEXT[lang].tips.length>=8);
        stop();assert.equal(cleared,true);
    }
});

test('답변 성공·HTTP 실패·취소 모두 팁 타이머를 정리한다',async()=>{
    for(const result of ['complete','http','abort']){
        const c=setup(),box=element(),tip=element();
        box.querySelector=selector=>selector==='.tip-text' ? tip : null;
        let stopped=0;
        c.setInterval=()=>92;c.clearInterval=id=>{if(id===92)stopped++;};
        c.box=box;
        vm.runInContext("addMessageToBox=()=>box;renderChatResponse=async()=>{};",c);
        c.fetch=async()=>{
            if(result==='abort') throw new DOMException('cancel','AbortError');
            return result==='http' ? {ok:false,status:503} : response({status:'complete',answer:'ok'});
        };
        await c.fetchChatResponse({question:'지원'});
        assert.equal(stopped,1);
    }
});

test('원래 질문의 줄바꿈은 전송 시 보존한다',async()=>{
    const c=lengthContext();
    c.document.getElementById('user-input').value='첫째 줄\n둘째 줄';
    await c.handleFormSubmit();
    assert.equal(c.window.sent.question,'첫째 줄\n둘째 줄');
});

test('상단 국기 영역은 텍스트 레일과 구분되고 시작 화면은 입력을 막지 않는다',()=>{
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/\.chat-box\s*\{[^}]*padding-right: 60px/);
    assert.match(css,/#splash-screen\s*\{[^}]*pointer-events: none/);
    const c=setup();
    for(const value of Object.values(c.window.CHAT_UI_TEXT)) {
        assert.ok(value.welcome_title && value.welcome && value.privacy_notice && value.analytics_label);
        assert.doesNotMatch(value.welcome,/<[^>]+>/);
    }
});


test('로딩 팁은 원본 3줄 스켈레톤과 14px 진행 문구·12px 팁을 유지한다',()=>{
    const js=fs.readFileSync('static/script.js','utf8');
    const loading=js.split("const loading = addMessageToBox")[1].split("const stopTips")[0];
    assert.equal((loading.match(/class="skeleton-box"/g)||[]).length,3);
    assert.ok(loading.includes('width:85%'));
    assert.ok(loading.includes('class="loading-copy"'));
    const css=fs.readFileSync('static/style.css','utf8');
    const action=css.match(/\.message\.assistant \.loading-copy \.action-text\s*\{([^}]+)\}/)[1];
    const tip=css.match(/\.message\.assistant \.loading-copy \.tip-text\s*\{([^}]+)\}/)[1];
    for(const rule of ['font-size: 14px','font-weight: 600','color: #333','margin: 0 0 8px']) assert.ok(action.includes(rule));
    for(const rule of ['font-size: 12px','font-weight: 400','color: var(--text-secondary)','margin: 0','line-height: 1.6']) assert.ok(tip.includes(rule));
    assert.doesNotMatch(css,/\.tip-text\s*\{[^}]*margin-top:\s*12px/);
});


test('더 보기는 작은 보조 버튼 크기와 명시적인 button 타입을 유지한다',async()=>{
    const css=fs.readFileSync('static/style.css','utf8');
    const rule=css.match(/\.show-more-btn\s*\{([^}]+)\}/)[1];
    for(const token of ['font-size: 13px','min-height: 32px','padding: 5px 12px','width: fit-content','max-width: 100%']) assert.ok(rule.includes(token));
    const c=setup(),box=element();
    await c.renderChatResponse({status:'complete',answer:'ok',last_result_ids:['1','2','3'],total_found:3},box,'질문',0);
    assert.equal(box.children[0].type,'button');
});

test('최신 답변 화살표는 모든 언어의 접근성 이름과 툴팁을 유지한다',()=>{
    const c=setup();loadHome(c);
    for(const lang of ['ko','en','vi','zh']){
        c.changeLanguage(lang);
        const button=c.document.getElementById('scroll-bottom-btn');
        assert.equal(button.textContent,'↓');
        assert.equal(button.attributes['aria-label'],c.window.CHAT_UI_TEXT[lang].scroll_bottom);
        assert.equal(button.attributes.title,c.window.CHAT_UI_TEXT[lang].scroll_bottom);
    }
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/#scroll-bottom-btn\s*\{[^}]*position: absolute; left: auto; right: 12px/);
    assert.match(css,/@media \(max-height: 480px\)[\s\S]*?#scroll-bottom-btn \{ display: none; \}/);
});

test('카드 소제목은 내용 변경 없이 정확한 독립 레이블에만 적용한다',()=>{
    const c=setup();
    for(const label of ['운영 목적:','기본검사(무료):','Purpose:','Basic assessment (free):','Mục đích:','Kiểm tra cơ bản (miễn phí):','服务目的：','基本检查（免费）：']){
        const classes=[];const item={textContent:label,nextElementSibling:{},classList:{add:x=>classes.push(x)}};
        const box={querySelectorAll:()=>[item]};
        c.decorateCardSubheadings(box);c.decorateCardSubheadings(box);
        assert.ok(classes.every(x=>x==='card-subheading'));
        assert.equal(classes.length,2);assert.equal(item.textContent,label);
    }
});

test('일반 문장·링크·마지막 빈 소제목은 소제목으로 바꾸지 않는다',()=>{
    const c=setup();let changed=0;
    const rows=['운영 목적: 서비스를 지원합니다.','지원 안내','https://example.org:','기본검사(유료):']
      .map(text=>({textContent:text,nextElementSibling:{},classList:{add:()=>changed++}}));
    rows.push({textContent:'운영 목적:',nextElementSibling:null,classList:{add:()=>changed++}});
    c.decorateCardSubheadings({querySelectorAll:()=>rows});
    assert.equal(changed,0);
});


function presentationBox({notes=[],items=[],paragraphs=[]}={}) {
    return {querySelectorAll:selector=>({
        '.result-card .source-note':notes, '.card-body li':items, ':scope > p':paragraphs
    }[selector] || [])};
}
function removable(text) {
    return {textContent:text,removed:false,remove(){this.removed=true}};
}

test('자료 수정 날짜만 화면에서 제거하고 번역 경고와 본문 날짜는 유지한다',()=>{
    const c=setup();
    const notes=['자료 수정','Document updated','Cập nhật tài liệu','资料更新']
      .map(label=>removable(label+': 2026-03-05 · 안내'));
    const warning=removable('번역이 준비되지 않은 부분은 한국어 원문으로 표시해요.');
    const date=removable('신청 기간: 2026-03-05부터');
    const box=presentationBox({notes:[...notes,warning,date]});
    c.tidyResultPresentation(box);
    assert.ok(notes.every(note=>note.removed));
    assert.equal(warning.removed,false);assert.equal(date.removed,false);
});

test('목록 앞 쉼표만 정리하고 금액·소수·문장 안 쉼표·HTML 요소는 보존한다',()=>{
    const c=setup();
    const cases=[
        [', 정확한 진단을 위한 대면 검사 실시','정확한 진단을 위한 대면 검사 실시'],
        [' ， Additional assessment','Additional assessment'],
        [', Kiểm tra trực tiếp','Kiểm tra trực tiếp'],
        ['， 进行检查','进行检查'],
        ['100,000원','100,000원'],['0,5','0,5'],[',5',',5'],[', 100원',', 100원'],
        ['일반, 장애/발달지연','일반, 장애/발달지연']
    ];
    const items=cases.map(([text])=>({firstChild:{nodeType:3,nodeValue:text}}));
    const nested={firstChild:{nodeType:1,nodeValue:null}};
    c.tidyResultPresentation(presentationBox({items:[...items,nested]}));
    cases.forEach(([,expected],i)=>assert.equal(items[i].firstChild.nodeValue,expected));
    assert.equal(nested.firstChild.nodeValue,null);
});

test('더 보기 반복 안내와 해당 구분선만 없애고 원문 안내·마지막 결과 안내는 보존한다',()=>{
    const c=setup();
    for(const text of [
        '아래 ‘더 보기’에서 다음 결과를 확인할 수 있어요.',
        'Use ‘Show more’ below to see the next results.',
        'Chọn ‘Xem thêm’ bên dưới để xem các kết quả tiếp theo.',
        '点击下方“更多”查看后续结果。'
    ]){
        const note=removable(text),hr=removable('');hr.tagName='HR';note.previousElementSibling=hr;
        const source=removable('지원 대상·신청 방법은 자료 원문과 담당 기관에서 확인해 주세요.');
        const end=removable('모든 결과를 확인했습니다.');
        c.tidyResultPresentation(presentationBox({paragraphs:[note,source,end]}));
        assert.equal(note.removed,true);assert.equal(hr.removed,true);
        assert.equal(source.removed,false);assert.equal(end.removed,false);
    }
});

test('캐시 답변도 표시 정리를 거치고 더 보기는 중앙에 배치한다',async()=>{
    const c=setup(),box=element();let called=0;
    c.tidyResultPresentation=()=>called++;
    await c.renderChatResponse({status:'complete',answer:'cached',last_result_ids:['1','2','3'],total_found:3},box,'질문',0);
    assert.equal(called,1);
    assert.equal(box.children[0].className,'show-more-btn');
    const css=fs.readFileSync('static/style.css','utf8');
    const rule=css.match(/\.show-more-btn\s*\{([^}]+)\}/)[1];
    assert.match(rule,/margin: 12px auto 0/);assert.match(rule,/display: flex/);
});


for (const lang of ['ko','en','vi','zh']) {
    test(lang+' 이메일 문의는 주소·제목만 전달하고 대화를 포함하지 않는다',()=>{
        const c=setup(),box=element();
        c.window.currentLang=lang;
        vm.runInContext("chatHistory=[{role:'user',content:'PRIVATE_HISTORY'}]; currentQuestion='PRIVATE_QUESTION';",c);
        c.addContactActions(box);
        const details=box.children[0],summary=details.children[0],content=details.children[1];
        const mail=new URL(content.children[0].href);
        assert.equal(details.className,'contact-actions');
        assert.equal(summary.textContent,c.window.CHAT_UI_TEXT[lang].contact.label);
        assert.equal(mail.protocol,'mailto:');
        assert.equal(mail.pathname,'chanyoung@devleop136.com');
        assert.deepEqual([...mail.searchParams.keys()],['subject']);
        assert.equal(mail.searchParams.get('subject'),c.window.CHAT_UI_TEXT[lang].contact.subject);
        assert.doesNotMatch(mail.href,/PRIVATE/);
        assert.equal(content.children[1].type,'button');
        assert.equal(content.children[0].textContent,'chanyoung@devleop136.com');
        assert.equal(content.children[2].className,'contact-status');
        assert.equal(content.children.length,3);
    });
    test(lang+' 주소 복사는 실제 성공 확인 후 표시하고 네트워크 요청을 안 한다',async()=>{
        const c=setup(),box=element();let copied='',requests=0;
        c.fetch=async()=>{requests++;throw new Error('No request expected');};
        c.navigator.clipboard={writeText:async value=>{copied=value;}};
        c.addContactActions(box,lang);
        const content=box.children[0].children[1],button=content.children[1];
        await button.onclick();
        assert.equal(copied,'chanyoung@devleop136.com');
        assert.equal(requests,0);
        assert.equal(content.children[2].textContent,c.window.CHAT_UI_TEXT[lang].contact.copied);
        assert.equal(button.disabled,false);
    });
    test(lang+' 복사 권한이 없으면 수동 복사 안내와 주소를 유지한다',async()=>{
        for (const clipboard of [undefined,{writeText:async()=>{throw new Error('denied');}}]) {
            const c=setup(),box=element();c.navigator.clipboard=clipboard;
            c.addContactActions(box,lang);
            const content=box.children[0].children[1];
            await content.children[1].onclick();
            assert.equal(content.children[2].textContent,c.window.CHAT_UI_TEXT[lang].contact.copy_failed);
            assert.equal(content.children[0].textContent,'chanyoung@devleop136.com');
            assert.equal(content.children[1].disabled,false);
        }
    });
}
test('같은 메시지에 이메일 메뉴를 중복 추가하지 않는다',()=>{
    const c=setup(),box=element();
    box.querySelector=()=>box.children.find(child=>child.className==='contact-actions');
    c.addContactActions(box);c.addContactActions(box);
    assert.equal(box.children.length,1);
});
test('캐시 답변처럼 job_id가 없어도 이메일 문의가 표시된다',async()=>{
    const c=setup(),box=element();c.box=box;
    await vm.runInContext("renderChatResponse({status:'complete',answer:'cached'},box,'q',0)",c);
    assert.equal(box.children[0].className,'contact-actions');
});
test('재시도 불가 오류에도 이메일 문의가 남는다',()=>{
    const c=setup(),box=element();
    c.showRequestError(box,{retryable:false,message:'error'},null,'q',0);
    assert.equal(box.children[0].className,'contact-actions');
});
test('첫 안내에는 문의 메뉴 없이 다국어 안내와 통계 고지를 유지한다',()=>{
    const html=fs.readFileSync('static/index.html','utf8');
    assert.doesNotMatch(html,/welcome-contact|addContactActions|time-notice/);
    const c=setup();loadHome(c);
    for (const lang of ['en','vi','zh','ko']) {
        c.changeLanguage(lang);
        assert.equal(c.document.getElementById('welcome-msg').textContent,c.window.CHAT_UI_TEXT[lang].welcome);
        assert.equal(c.document.getElementById('analytics-notice').textContent,c.window.CHAT_UI_TEXT[lang].analytics_notice);
        assert.equal(c.document.getElementById('welcome-title').textContent,c.window.CHAT_UI_TEXT[lang].welcome_title);
        assert.equal(c.document.getElementById('privacy-notice').textContent,c.window.CHAT_UI_TEXT[lang].privacy_notice);
        assert.equal(c.document.getElementById('analytics-label').textContent,c.window.CHAT_UI_TEXT[lang].analytics_label);
    }
});
test('결과 더 보기는 회색 버튼이며 문의는 답변 바깥 보조 메뉴이다',()=>{
    const css=fs.readFileSync('static/style.css','utf8');
    const more=css.match(/\.show-more-btn\s*\{([^}]+)\}/)[1];
    assert.ok(more.includes('color: #344054; background: #EAECF0'));
    assert.match(css,/\.contact-actions\s*\{[^}]*grid-column: 2/);
    assert.match(css,/#welcome-title\s*\{[^}]*font-size: 24px/);
});
test('새 프런트엔드는 질문·답변을 피드백 API로 전송하는 코드를 포함하지 않는다',()=>{
    const source=fs.readFileSync('static/script.js','utf8');
    assert.doesNotMatch(source,/submitFeedback|addFeedbackButtons|API_URL_FEEDBACK|fetch\(['"]\/feedback/);
});

test('통계용 ID는 새 질문마다 생성하고 동일 요청 재전송에서는 보존한다',()=>{
    const c=setup();let next=0;c.window.crypto={randomUUID:()=> 'opaque-'+(++next)};
    const body={question:'PRIVATE_QUESTION'};
    c.attachAnalyticsMetadata(body);c.attachAnalyticsMetadata(body);
    assert.equal(body.analytics_id,'opaque-1');
    const other={question:'PRIVATE_QUESTION'};c.attachAnalyticsMetadata(other);
    assert.equal(other.analytics_id,'opaque-2');
});
test('유입 경로는 허용 목록만 전송하고 전체 URL은 전송하지 않는다',()=>{
    const c=setup();c.URL=URL;
    for (const [url,expected] of [['https://test.invalid/?utm_source=qr','qr'],
        ['https://test.invalid/?utm_source=PRIVATE_URL','unknown'],['https://test.invalid/','direct']]) {
        c.window.location.href=url;const body={};c.attachAnalyticsMetadata(body);
        assert.equal(body.entry_source,expected);
        assert.doesNotMatch(JSON.stringify(body),/PRIVATE_URL|https:/);
    }
});
test('원문 클릭은 서명 토큰만 보내고 반복 클릭을 중복 전송하지 않는다',async()=>{
    const c=setup();c.box=element();const calls=[];
    vm.runInContext("analyticsMessages.set(box,{token:'signed-token',busy:false,sent:false})",c);
    c.fetch=async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true};};
    await c.trackSourceClick(c.box);await c.trackSourceClick(c.box);
    assert.equal(calls.length,1);assert.deepEqual(calls[0],{url:'/analytics/source-click',body:{token:'signed-token'}});
});
test('원문 클릭 통계 오류는 화면 동작을 실패시키지 않는다',async()=>{
    const c=setup();c.box=element();let count=0;
    vm.runInContext("analyticsMessages.set(box,{token:'signed-token',busy:false,sent:false})",c);
    c.fetch=async()=>{count++;throw new Error('offline');};
    await c.trackSourceClick(c.box);await c.trackSourceClick(c.box);
    assert.equal(count,2);
});


test('4개 언어의 결과 더 보기 버튼은 새 검색 대신 more 요청으로 이전 결과를 이어간다',async()=>{
    for(const lang of ['ko','en','vi','zh']){
        const c=setup();c.window.currentLang=lang;c.box=element();
        vm.runInContext("addMessageToBox=()=>({}); fetchChatResponse=async body=>{window.sent=body};",c);
        await vm.runInContext("renderChatResponse({status:'complete',answer:'ok',last_result_ids:['a','b','c'],shown_count:2},box,'q',0)",c);
        c.box.children[0].onclick();
        assert.equal(c.window.sent.action,'more');
        assert.deepEqual(Array.from(c.window.sent.last_result_ids),['a','b','c']);
        assert.equal(c.window.sent.shown_count,2);
        assert.equal(c.window.sent.question,c.buildServerQuestion(c.window.CHAT_UI_TEXT[lang].more));
    }
});


test('동작 줄이기 설정에 따라 팁 순환을 중단·재개하고 리스너를 정리한다',()=>{
    const c=setup(),tip=element(),box=element();box.querySelector=()=>tip;
    let change,removed=false,started=0,stopped=0;
    const preference={matches:true,addEventListener:(name,fn)=>{change=fn;},
        removeEventListener:(name,fn)=>{removed=fn===change;}};
    c.window.matchMedia=()=>preference;
    c.setInterval=()=>{started++;return 7;};c.clearInterval=id=>{assert.equal(id,7);stopped++;};
    const stop=c.startLoadingTips(box,'ko');
    assert.ok(tip.textContent);assert.equal(started,0);
    preference.matches=false;change();assert.equal(started,1);
    preference.matches=true;change();assert.equal(stopped,1);
    stop();assert.equal(removed,true);
});
test('답변 포커스 보정은 가려진 키보드 제어에만 작동한다',()=>{
    const c=setup();let calls=0;
    const target={matches:()=>true,getBoundingClientRect:()=>({top:720,bottom:760}),
        scrollIntoView:opts=>{assert.equal(opts.behavior,'instant');calls++;}};
    c.document.getElementById('chat-box').getBoundingClientRect=()=>({top:0,bottom:844});
    c.window.getComputedStyle=()=>({scrollPaddingBottom:'160px'});
    c.revealFocusedAnswerControl({target});assert.equal(calls,1);
    target.getBoundingClientRect=()=>({top:200,bottom:230});
    c.revealFocusedAnswerControl({target});assert.equal(calls,1);
    target.matches=()=>false;target.getBoundingClientRect=()=>({top:720,bottom:760});
    c.revealFocusedAnswerControl({target});assert.equal(calls,1);
});
test('시각 디자인은 유지하고 폰트 지연·장식 이미지·카드 동작 줄이기를 보완한다',()=>{
    const css=fs.readFileSync('static/style.css','utf8'),html=fs.readFileSync('static/index.html','utf8');
    const faces=css.match(/@font-face\s*\{[^}]+\}/g);
    assert.equal(faces.length,1);assert.ok(faces.every(rule=>rule.includes('font-display: swap')));
    assert.match(css,/\.result-card \{ animation: none; opacity: 1; \}/);
    assert.doesNotMatch(html,/alt="(?:bot|icon)"/);
    assert.match(css,/scroll-padding-top: calc\(var\(--chat-top-height/);
    assert.match(css,/scroll-padding-bottom: var\(--chat-bottom-padding/);
});


test('요청 시작 시 추천 질문을 접고 완료 후에도 유지하며 수동으로 다시 열 수 있다',()=>{
    const suggestions=element(),toggle=element(),footer=element();
    for(const el of [suggestions,toggle]){
        const names=new Set();
        el.classList={add:n=>names.add(n),remove:n=>names.delete(n),contains:n=>names.has(n),
            toggle(n){if(names.has(n))names.delete(n);else names.add(n);}};
        el.getBoundingClientRect=()=>({height:40,width:100});
    }
    footer.getBoundingClientRect=()=>({height:76});
    const c=setup({toggle,selectors:{'.suggestion-container':suggestions,'.chat-input-box':footer}});
    c.setLoadingState(true);
    assert.equal(suggestions.classList.contains('hidden'),true);
    assert.equal(suggestions.inert,true);
    assert.equal(toggle.attributes['aria-expanded'],'false');
    c.setLoadingState(false);
    assert.equal(suggestions.classList.contains('hidden'),true);
    toggle.events.click[0]();
    assert.equal(suggestions.classList.contains('hidden'),false);
    assert.equal(suggestions.inert,false);
    assert.equal(toggle.attributes['aria-expanded'],'true');
});
test('빈 질문과 길이 제한 초과는 추천 질문을 자동으로 접지 않는다',async()=>{
    const c=setup();let collapsed=0;c.collapseSuggestions=()=>{collapsed++;};
    c.document.getElementById('user-input').value='';
    await c.handleFormSubmit();
    c.document.getElementById('user-input').value='x'.repeat(50000);
    await c.handleFormSubmit();
    assert.equal(collapsed,0);
});


test('완료/오류 문의는 답변 라이브 영역 밖 같은 행에 한 번만 붙인다',async()=>{
    for(const response of [{status:'complete',answer:'답변'},{status:'error',message:'오류'}]) {
        const c=setup(),box=element(),row=element();c.box=box;c.response=response;
        box.closest=selector=>selector==='.message-row.assistant'?row:null;
        row.querySelector=()=>row.children.find(el=>el.className==='contact-actions');
        await vm.runInContext("renderChatResponse(response,box,'질문',0)",c);
        c.addContactActions(box);
        assert.equal(box.children.length,0);
        assert.equal(row.children.length,1);
        assert.equal(row.children[0].className,'contact-actions');
    }
});
test('시작 안내에는 말풍선이 없고 입력창의 개인정보 안내를 접근성 설명으로 연결한다',()=>{
    const html=fs.readFileSync('static/index.html','utf8');
    const section=html.match(/<section id="welcome-panel"[\s\S]*?<\/section>/)[0];
    assert.doesNotMatch(section,/message-row|class="message /);
    assert.match(section,/class="analytics-disclosure"/);
    assert.doesNotMatch(section,/class="analytics-disclosure" open/);
    assert.match(html,/aria-describedby="privacy-notice"/);
});

test('한국어 시작 설명만 쉼표 뒤에서 줄바꿈하고 HTML로 삽입하지 않는다',()=>{
    const c=setup();loadHome(c);c.changeLanguage('ko');
    assert.equal(c.document.getElementById('welcome-msg').textContent,'아동수당부터 발달검사 등,\n도봉구 영유아 지원 정보를 안내합니다.');
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/#welcome-msg\s*\{[^}]*white-space: pre-line/);
});

test('첫 안내 캐릭터 중복 제거와 입력창 고지 크기를 보존한다',()=>{
    const html=fs.readFileSync('static/index.html','utf8');
    const welcome=html.match(/<section id="welcome-panel"[\s\S]*?<\/section>/)[0];
    assert.doesNotMatch(welcome,/<img|<svg/);
    assert.match(html,/header-icon\.png/);
    assert.match(fs.readFileSync('static/script.js','utf8'),/bot-icon\.png/);
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/\.input-notice\s*\{[^}]*font-size: 10px/);
});

test('한국어 첫 제목은 의미 단위 두 줄이며 설명의 줄 간격은 조밀하다',()=>{
    const c=setup();loadHome(c);c.changeLanguage('ko');
    assert.equal(c.document.getElementById('welcome-title').textContent,'우리 아이에게\n필요한 지원을 찾아보세요');
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/#welcome-title\s*\{[^}]*white-space: pre-line/);
    assert.match(css,/#welcome-msg\s*\{[^}]*line-height: 1.35;/);
});

test('상단 브랜드는 작은 크기로 유지하고 고정 높이로 자르지 않는다',()=>{
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/\.chat-topbar \.chat-header h2\s*\{[^}]*font-size: 15px/);
    assert.match(css,/\.chat-topbar \.header-icon\s*\{[^}]*width: 24px; height: 24px/);
    const header=css.match(/\.chat-topbar \.chat-header\s*\{([^}]+)\}/)[1];
    assert.match(header,/min-height: 50px/);
    assert.doesNotMatch(header,/(?:^|;)\s*height:|overflow: hidden/);
});

test('정보 수집 안내 명칭과 Pretendard 제목 굵기를 보존한다',()=>{
    const c=setup();loadHome(c);
    const expected={ko:'정보 수집 안내',en:'Data collection notice',vi:'Thông báo thu thập thông tin',zh:'信息收集说明'};
    for(const [lang,label] of Object.entries(expected)){
        c.changeLanguage(lang);
        assert.equal(c.document.getElementById('analytics-label').textContent,label);
    }
    const css=fs.readFileSync('static/style.css','utf8');
    const title=css.match(/#welcome-title\s*\{([^}]+)\}/)[1];
    assert.match(title,/font-weight: 800/);
    assert.match(title,/font-family: 'Pretendard', 'SF Pro', sans-serif/);
    assert.doesNotMatch(title,/-webkit-text-stroke/);
});

test('장식 서체 로딩을 제거하고 추천 질문은 텍스트만 유지한다',()=>{
    const css=fs.readFileSync('static/style.css','utf8'),html=fs.readFileSync('static/index.html','utf8');
    assert.doesNotMatch(css+html,/ONE Mobile POP/);
    assert.match(css,/\.splash-title\s*\{[^}]*font-family: 'Pretendard'/);
    assert.match(css,/body\s*\{[^}]*font-family: 'Pretendard', 'SF Pro', sans-serif/);
    const c=setup();
    for(const lang of ['ko','en','vi','zh']){
        const chips=c.window.CHAT_UI_TEXT[lang].chips;
        assert.equal(chips.length,7);
        for(const chip of chips){
            assert.doesNotMatch(chip.label,/\p{Extended_Pictographic}/u);
            assert.ok(chip.label.trim()&&chip.text.trim());
        }
    }
});


test('입력창 주변 표면은 투명하고 주의 문구는 2px 간격이다',()=>{
    const css=fs.readFileSync('static/style.css','utf8');
    const foot=[...css.matchAll(/\.chat-input-box\s*\{([^}]+)\}/g)].at(-1)[1];
    assert.match(foot,/gap: 2px/);
    assert.match(foot,/background: transparent; border-top: 0/);
    assert.match(foot,/backdrop-filter: none/);
    assert.match(css,/#welcome-title\s*\{[^}]*line-height: 1.15/);
});


test('접기 버튼의 강조를 줄이고 펼침 상태에 따라 세로 중앙을 맞춘다',()=>{
    const c=overlaySetup();
    c.syncInputOverlay();
    assert.equal(c.document.documentElement.style['--suggestion-toggle-offset'],'20px');
    // This test isolates layout measurement; the shared stub has a no-op classList.
    c.document.querySelector('.suggestion-container').classList.contains=name=>name==='hidden';
    c.syncInputOverlay();
    assert.equal(c.document.documentElement.style['--suggestion-toggle-offset'],'6px');
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/\.toggle-text\s*\{[^}]*font-weight: 500/);
    assert.match(css,/\.toggle-icon\s*\{[^}]*width: 12px; height: 12px/);
    assert.match(css,/#suggestion-toggle-btn\s*\{[^}]*box-shadow: 0 2px 4px rgba\(0, 0, 0, .03\)/);
});


test('키보드로 일부만 보이는 추천 질문에 초점을 옮기면 가로 영역 안으로 드러낸다',()=>{
    const c=overlaySetup(),tray=c.document.querySelector('.suggestion-container');
    tray.scrollLeft=0;tray.getBoundingClientRect=()=>({left:0,right:200});
    const target={classList:{contains:n=>n==='suggestion-chip'},matches:()=>true,
        getBoundingClientRect:()=>({left:190,right:290})};
    c.revealFocusedSuggestion({target});
    assert.equal(tray.scrollLeft,94);
    target.matches=()=>false;
    c.revealFocusedSuggestion({target});
    assert.equal(tray.scrollLeft,94);
    target.matches=()=>true;target.getBoundingClientRect=()=>({left:-10,right:40});
    c.revealFocusedSuggestion({target});
    assert.equal(tray.scrollLeft,80);
});
