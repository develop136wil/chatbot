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
test('4개 언어의 피드백 필드가 완비되어 있다',()=>{
    const c=setup();
    assert.equal(vm.runInContext("Object.values(UI_TEXT).every(v => v.feedback.reasons.length && v.feedback.send && v.feedback.sending && v.feedback.thanks_good && v.feedback.thanks_bad)",c),true);
});
test('피드백 HTTP 실패를 성공 메시지로 표시하지 않는다',async()=>{
    const c=setup(); c.box=element();
    c.fetch=async()=>({ok:false,status:503});
    await vm.runInContext("submitFeedback('id','질문','답변','👍',box,'')",c);
    assert.match(c.box.children.find(child=>child.className==='feedback-status').textContent,/오류/);
    assert.doesNotMatch(c.box.innerHTML,/feedback-success/);
});
test('피드백 저장 확인 후에만 성공 표시한다',async()=>{
    const c=setup(); c.box=element();
    c.fetch=async()=>({ok:true,json:async()=>({status:'success'})});
    await vm.runInContext("submitFeedback('id','질문','답변','👍',box,'')",c);
    assert.match(c.box.innerHTML,/feedback-success/);
});
test('초기화 응답은 실제 내역·문서 ID·커서를 모두 지운다',async()=>{
    const c=setup(); c.box=element();
    vm.runInContext("chatHistory=[{role:'user',content:'old'}]; currentResultIds=['old']; currentShownCount=2; pendingContext='old';",c);
    await vm.runInContext("renderChatResponse({status:'complete',action:'reset',answer:'초기화'},box,'초기화',0)",c);
    assert.equal(vm.runInContext("chatHistory.length+currentResultIds.length+currentShownCount",c),0);
    assert.equal(vm.runInContext("pendingContext",c),null);
});
test('응답 공통 경로가 버튼 번역·더 보기·피드백을 처리한다',async()=>{
    const c=setup(); c.box=element(); c.localized=0;
    vm.runInContext("translateCardButtons=()=>{localized++};",c);
    await vm.runInContext("renderChatResponse({status:'complete',answer:'answer',last_result_ids:['a','b','c'],shown_count:2,job_id:'fresh-id'},box,'질문',0)",c);
    assert.equal(c.localized,1);
    assert.equal(c.box.children[0].className,'show-more-btn');
    assert.equal(c.box.children[1].className,'feedback-container');
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
    for (const [lang,label] of Object.entries({ko:'더 보기',en:'Show more',vi:'Xem thêm',zh:'更多'})) {
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
    assert.equal(c.box.children.length,0);
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
    assert.equal(c.document.getElementById('scroll-bottom-btn').textContent,c.window.CHAT_UI_TEXT.vi.scroll_bottom);
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
    assert.match(html,/style\.css\?v=2026\.09\.21-loading/);
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

test('추천 질문 끝 여백은 번역된 접기 버튼 너비를 반영한다', () => {
    for(const width of [72,154]) {
        const c=overlaySetup({width});
        c.syncInputOverlay();
        assert.equal(c.document.documentElement.style['--suggestion-toggle-width'],width+'px');
    }
    const css=fs.readFileSync('static/style.css','utf8');
    assert.match(css,/#suggestion-container\s*\{[^}]*padding:\s*10px calc\(var\(--suggestion-toggle-width, 100px\) \+ 32px\)/);
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
    assert.equal(c.boxes[0].children.length,0);
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
        assert.equal(c.boxes[0].children.length,0);
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

function feedbackContext(lang='ko') {
    const c=setup();c.window.currentLang=lang;
    const box=element(), input=element(), button=element(), locked=element();
    input.value='보존할 의견'; locked.disabled=true;
    box.appendChild(input);box.appendChild(button);box.appendChild(locked);
    box.querySelectorAll=()=>[input,button,locked];
    const submit=()=>c.submitFeedback('job','question','answer','👎',box,input.value,'reason','history');
    const status=()=>box.children.find(child=>child.className==='feedback-status');
    return {c,box,input,button,locked,submit,status};
}

test('피드백 오류 후 입력 노드·작성 내용·기존 잠금 상태를 보존한다',async()=>{
    const {c,box,input,button,locked,submit,status}=feedbackContext();
    c.fetch=async()=>({ok:false,status:503});
    await submit();
    assert.equal(box.children[0],input);
    assert.equal(input.value,'보존할 의견');
    assert.equal(input.disabled,false);
    assert.equal(button.disabled,false);
    assert.equal(locked.disabled,true);
    assert.equal(status().textContent,c.window.CHAT_UI_TEXT.ko.feedback.send_failed);
    assert.equal(box.innerHTML,'');
});

test('전송 중 피드백 중복 클릭은 요청을 추가하지 않는다',async()=>{
    const {c,input,button,submit}=feedbackContext();
    let finish,count=0;
    c.fetch=()=>{count++;return new Promise(resolve=>{finish=resolve;});};
    const pending=submit();
    assert.equal(input.disabled,true);assert.equal(button.disabled,true);
    await submit();
    assert.equal(count,1);
    finish(response({status:'success'}));await pending;
});

test('저장 성공 후 오래된 피드백 버튼을 호출해도 다시 전송하지 않는다',async()=>{
    const {c,submit,box}=feedbackContext();let count=0;
    c.fetch=async()=>{count++;return response({status:'success'});};
    await submit();await submit();
    assert.equal(count,1);assert.match(box.innerHTML,/feedback-success/);
});

test('피드백 실패 후 수동 재전송은 작성 내용·사유·문맥을 유지한다',async()=>{
    const {c,submit,box}=feedbackContext();const payloads=[];
    c.fetch=async(url,options)=>{
        payloads.push(JSON.parse(options.body));
        return payloads.length===1 ? {ok:false,status:503} : response({status:'success'});
    };
    await submit();await submit();
    assert.equal(payloads.length,2);
    assert.deepEqual(payloads[0],payloads[1]);
    assert.equal(payloads[1].comment,'보존할 의견');
    assert.equal(payloads[1].reason,'reason');
    assert.match(box.innerHTML,/feedback-success/);
});

test('오프라인 피드백은 전송하지 않고 초안을 유지한다',async()=>{
    const {c,submit,input,status}=feedbackContext();let count=0;
    c.navigator.onLine=false;c.fetch=async()=>{count++;};
    await submit();
    assert.equal(count,0);assert.equal(input.value,'보존할 의견');
    assert.equal(status().textContent,c.window.CHAT_UI_TEXT.ko.offline);
});

test('피드백 시간 초과는 잠금을 해제하고 초안을 유지한다',async()=>{
    const {c,submit,input,button,status}=feedbackContext();
    let timeout,cleared=false;
    c.setTimeout=(fn,ms)=>{assert.equal(ms,15000);timeout=fn;return 77;};
    c.clearTimeout=id=>{if(id===77)cleared=true;};
    c.fetch=(url,options)=>new Promise((resolve,reject)=>{
        options.signal.addEventListener('abort',()=>reject(new DOMException('timeout','AbortError')));
    });
    const pending=submit();timeout();await pending;
    assert.equal(cleared,true);assert.equal(button.disabled,false);
    assert.equal(input.value,'보존할 의견');
    assert.equal(status().textContent,c.window.CHAT_UI_TEXT.ko.feedback.send_failed);
});

test('피드백 429의 Retry-After 동안 재전송을 차단한다',async()=>{
    const {c,submit}=feedbackContext();let count=0,now=1000;
    c.Date={now:()=>now,parse:Date.parse};
    c.fetch=async()=>{count++;return {ok:false,status:429,headers:{get:()=> '3'}};};
    await submit();await submit();assert.equal(count,1);
    now=4001;await submit();assert.equal(count,2);
});

test('피드백 잘못된 JSON·실패 응답을 성공으로 표시하지 않는다',async()=>{
    for(const result of [response({status:'error'}),{ok:true,json:async()=>{throw new SyntaxError('bad');}}]){
        const {c,submit,box,button}=feedbackContext();
        c.fetch=async()=>result;
        await submit();
        assert.doesNotMatch(box.innerHTML,/feedback-success/);
        assert.equal(button.disabled,false);
    }
});

test('피드백 실패 문구는 요청 시작 시 선택한 언어로 표시된다',async()=>{
    for(const lang of ['ko','en','vi','zh']){
        const {c,submit,status}=feedbackContext(lang);
        c.fetch=async()=>{c.window.currentLang='ko';return {ok:false,status:503};};
        await submit();
        assert.equal(status().textContent,c.window.CHAT_UI_TEXT[lang].feedback.send_failed);
    }
});

test('피드백 사유 변경은 작성 중인 의견을 새 입력창으로 옮긴다',()=>{
    const {c,box}=feedbackContext();
    const old=element(), input=element();input.value='이미 작성한 의견';
    old.querySelector=()=>input;
    let removed=false;old.remove=()=>{removed=true;};
    box.querySelector=()=>old;
    const drafts=[];
    c.showCommentInput=(...args)=>drafts.push(args.at(-1));
    c.showFeedbackInput(box,'job','q','a','👎');
    const reasons=box.children.find(child=>child.className==='reason-container');
    reasons.children[1].onclick();
    assert.equal(removed,true);assert.deepEqual(drafts,['이미 작성한 의견']);
});

test('피드백 입력 화면을 다시 열어도 상태 안내와 429 대기는 유지한다',async()=>{
    const {c,box,submit,status}=feedbackContext();let count=0;
    c.fetch=async()=>{count++;return {ok:false,status:429,headers:{get:()=> '60'}};};
    await submit();
    const originalStatus=status();
    box.children=[]; // Simulate the DOM nodes removed by reopening the reason form.
    await submit();
    assert.equal(count,1);
    assert.equal(status(),originalStatus);
    assert.match(status().textContent,/다시 시도/);
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
    assert.match(top,/background: var\(--glass-bg\)/);
    assert.match(top,/backdrop-filter: var\(--glass-blur\)/);
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
    for(const value of Object.values(c.window.CHAT_UI_TEXT)) assert.ok(value.welcome.includes('<br><br>'));
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
    for(const rule of ['font-size: 12px','font-weight: 400','color: #888','margin: 0','line-height: 1.6']) assert.ok(tip.includes(rule));
    assert.doesNotMatch(css,/\.tip-text\s*\{[^}]*margin-top:\s*12px/);
});
