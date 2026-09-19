const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function element() {
    return { style:{}, value:'', children:[], className:'', textContent:'', innerHTML:'',
        classList:{add(){}, remove(){}, contains(){return false}, toggle(){}},
        addEventListener(){}, setAttribute(){}, querySelector(){return null},
        querySelectorAll(){return []}, appendChild(child){this.children.push(child)},
        append(){}, remove(){}, blur(){}, focus(){}, click(){} };
}
function setup() {
    const elements = new Map();
    const document = {
        getElementById(id) { if (!elements.has(id)) elements.set(id,element()); return elements.get(id) },
        createElement:element, querySelector(){return null}, querySelectorAll(){return []},
        addEventListener(){}, body:element()
    };
    const window={currentLang:'ko',addEventListener(){},location:{href:'https://test.invalid'}};
    window.self=window.top=window;
    const context=vm.createContext({
        window, document, navigator:{}, console:{log(){}}, AbortController, DOMException,
        setTimeout,clearTimeout,setInterval,clearInterval,requestAnimationFrame:fn=>fn(),
        fetch:async()=>{throw new Error('Unexpected network')},
    });
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
