const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const elements=new Map();
 const document={getElementById(id){if(!elements.has(id))elements.set(id,{value:'',addEventListener(){}});return elements.get(id);}};
 const c=vm.createContext({document,window:{addEventListener(){}},console,Date,URL,Blob,setTimeout,AbortSignal});
 vm.runInContext(fs.readFileSync('static/analytics-dashboard.js','utf8'),c);return c;
}
test('집계는 일별 건수를 더하며 비율을 평균내지 않는다',()=>{
 const c=setup(),t=c.sumReport([{stats:{questions:10,answered:5,source_clicks:1,languages:{ko:10}}},
 {stats:{questions:90,answered:45,source_clicks:9,languages:{ko:80,en:10}}}]);
 assert.equal(t.questions,100);assert.equal(t.languages.ko,90);
 assert.equal(c.percent(t.source_clicks,t.answered),'20.0%');
 assert.equal(c.percent(0,0),'—');
});
test('기록 없는 날은 결측, 실제 기록이 있는 0건은 0건으로 유지한다',()=>{
 const c=setup(),days=c.fillDays([{day:'2026-09-02',stats:{questions:0}}],'2026-09-01','2026-09-03');
 assert.equal(days.length,3);assert.equal(days[0].missing,true);assert.equal(days[1].missing,undefined);
 const csv=c.csvText({days});
 assert.ok(csv.includes('"2026-09-01","",""'));assert.ok(csv.includes('"2026-09-02","0","0"'));
});
test('관리자 키를 브라우저 저장소 또는 URL에 넣는 코드가 없다',()=>{
 const source=fs.readFileSync('static/analytics-dashboard.js','utf8');
 assert.doesNotMatch(source,/localStorage|sessionStorage|secret=|password=/);
 assert.match(source,/'X-Admin-Secret':adminKey/);
});

test('일본어 이용 건수와 차트 이름을 유지한다',()=>{
 const c=setup(),t=c.sumReport([{stats:{questions:2,languages:{ja:2}}}]);
 assert.equal(t.languages.ja,2);
 assert.equal(vm.runInContext('LABELS.ja',c),'일본어');
});
