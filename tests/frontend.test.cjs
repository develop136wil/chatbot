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
    assert.match(c.box.textContent,/오류/);
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
test('언어 선택은 국기 대신 언어명이며 상단 높이를 측정한다', () => {
    const html=fs.readFileSync('static/index.html','utf8');
    assert.match(html,/class="chat-topbar"/);
    assert.match(html,/Tiếng Việt/);
    assert.doesNotMatch(html,/🇰🇷|🇺🇸|🇻🇳|🇨🇳/);
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
    assert.match(html,/style\.css\?v=2026\.09\.20-mobile/);
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
