'use strict';
let adminKey = '', currentReport = null, reportSequence = 0;
const $ = id => document.getElementById(id);
const COLORS = ['#187d78','#d29a3d','#5784a0','#a37baf','#83a36a','#8e9699','#bb7b6b'];
const COUNTS = ['questions','answered','empty','errors','limited','pending','clarify','source_clicks','more','other','retry_attempts','cache_hits','cache_eligible','sessions'];
const LABELS = {ko:'한국어',en:'영어',vi:'베트남어',zh:'중국어',ja:'일본어',direct:'직접/출처 없음',website:'홈페이지',qr:'QR 안내',partner:'협력 기관',unknown:'미상',typed:'직접 입력',suggestion:'추천 질문',clarification:'추가 조건 선택'};
const BUCKETS = ['<1초','1–3초','3–5초','5–10초','10–20초','20–30초','30초 이상'];
function node(tag, text, cls) {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function svgNode(tag, attrs={}) {const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;}
function sumReport(days) {
    const totals=Object.fromEntries(COUNTS.map(k=>[k,0]));
    for(const k of ['categories','languages','sources','inputs','latency_cached','latency_fresh'])totals[k]={};
    for(const {stats:s} of days) {
        for(const k of COUNTS)totals[k]+=Number(s[k]||0);
        for(const k of ['categories','languages','sources','inputs','latency_cached','latency_fresh'])
            for(const [name,value] of Object.entries(s[k]||{}))totals[k][name]=(totals[k][name]||0)+Number(value||0);
    }
    return totals;
}
function percent(n,d) {return d ? (100*n/d).toFixed(1)+'%' : '—';}
function number(n) {return Number(n).toLocaleString('ko-KR');}
function empty(host) {host.replaceChildren(node('p','아직 수집된 데이터가 없습니다.','empty'));}
function bars(id, values, labels=LABELS) {
    const host=$(id);host.replaceChildren();
    const entries=Object.entries(values).filter(([,n])=>n>0).sort((a,b)=>b[1]-a[1]);
    if(!entries.length)return empty(host);
    const max=Math.max(...entries.map(([,n])=>n));
    for(const [name,count] of entries) {
        const row=node('div',undefined,'bar-row');const track=node('div',undefined,'bar-track');
        const fill=node('div',undefined,'bar-fill');fill.style.width=(count/max*100)+'%';track.append(fill);
        row.append(node('span',labels[name]||name),track,node('span',number(count),'bar-value'));
        host.append(row);
    }
}
function line(days) {
    const host=$('trend');host.replaceChildren();
    if(!days.some(d=>d.stats.questions))return empty(host);
    const width=Math.max(320,Math.min(960,host.clientWidth||960)),height=220,left=40,bottom=185,plot=width-80,max=Math.max(1,...days.map(d=>d.stats.questions||0));
    const svg=svgNode('svg',{viewBox:'0 0 '+width+' '+height,role:'img','aria-label':'일별 질문 수 추이. 정확한 값은 아래 일별 집계표에서 확인할 수 있습니다.'});
    for(let i=0;i<=4;i++){
        const y=bottom-i*150/4;svg.append(svgNode('line',{x1:left,x2:width-40,y1:y,y2:y,stroke:'#e4edeb'}));
        const text=svgNode('text',{x:left-8,y:y+4,'text-anchor':'end'});text.textContent=number(Math.round(max*i/4));svg.append(text);
    }
    const points=days.map((d,i)=>[left+(days.length===1?plot/2:i*plot/(days.length-1)),bottom-(d.stats.questions||0)/max*150]);
    // A day without any stored record is unknown, not a confirmed zero.
    let segment=[];
    const draw=()=>{
        if(!segment.length)return;
        svg.append(svgNode('polygon',{points:[[segment[0][0],bottom],...segment,[segment.at(-1)[0],bottom]].map(p=>p.join(',')).join(' '),fill:'#e2f0eb'}));
        svg.append(svgNode('polyline',{points:segment.map(p=>p.join(',')).join(' '),fill:'none',stroke:COLORS[0],'stroke-width':3,'stroke-linejoin':'round'}));
        segment=[];
    };
    points.forEach((point,i)=>{if(days[i].missing)draw();else segment.push(point);});draw();
    points.forEach(([x,y],i)=>{
        if(days[i].missing || (days.length>62 && i%7))return;
        const c=svgNode('circle',{cx:x,cy:y,r:3,fill:COLORS[0]});const title=svgNode('title');title.textContent=days[i].day+': '+number(days[i].stats.questions||0)+'건';c.append(title);svg.append(c);
    });
    for(const i of [...new Set([0,Math.floor((days.length-1)/2),days.length-1])]) {
        const text=svgNode('text',{x:points[i][0],y:212,'text-anchor':'middle'});text.textContent=days[i].day.slice(5);svg.append(text);
    }
    host.append(svg);
}
function donut(values) {
    const host=$('languages');host.replaceChildren();
    const entries=Object.entries(values).filter(([,n])=>n>0),total=entries.reduce((n,[,v])=>n+v,0);
    if(!total)return empty(host);
    const row=node('div',undefined,'donut-layout'),svg=svgNode('svg',{viewBox:'0 0 180 180',role:'img','aria-label':'언어별 질문 비중'});
    const legend=node('div',undefined,'donut-legend');let offset=0;
    entries.forEach(([name,n],i)=>{
        const circle=svgNode('circle',{cx:90,cy:90,r:65,fill:'none',stroke:COLORS[i%COLORS.length],'stroke-width':24,pathLength:100,
            'stroke-dasharray':(n/total*100)+' '+(100-n/total*100),'stroke-dashoffset':-offset,transform:'rotate(-90 90 90)'});
        offset+=n/total*100;svg.append(circle);
        const item=node('div'),swatch=node('span',undefined,'swatch');swatch.style.background=COLORS[i%COLORS.length];
        item.append(swatch,node('span',(LABELS[name]||name)+' '+number(n)+'건 · '+percent(n,total)));legend.append(item);
    });
    const label=svgNode('text',{x:90,y:96,'text-anchor':'middle'});label.textContent=number(total)+'건';svg.append(label);
    row.append(svg,legend);host.append(row);
}
function latency(t) {
    const host=$('latency');host.replaceChildren();
    const max=Math.max(0,...BUCKETS.map(k=>(t.latency_cached[k]||0)+(t.latency_fresh[k]||0)));
    if(!max)return empty(host);
    for(const k of BUCKETS) {
        const a=t.latency_cached[k]||0,b=t.latency_fresh[k]||0;
        const row=node('div',undefined,'bar-row latency-row'),track=node('div',undefined,'bar-track');
        const one=node('div',undefined,'bar-fill'),two=node('div',undefined,'bar-fill fresh');
        one.style.width=(100*a/max)+'%';two.style.width=(100*b/max)+'%';track.append(one,two);
        row.title='캐시 '+a+'건, 새 검색 '+b+'건';
        row.append(node('span',k),track,node('span',number(a+b),'bar-value'));host.append(row);
    }
}
function dailyTable(days) {
    const table=node('table'),head=node('thead'),body=node('tbody'),tr=node('tr');
    ['날짜','질문','자료 발견','결과 없음','오류','한도 제한','미완료','원문 클릭','더 보기','일별 세션'].forEach(x=>tr.append(node('th',x)));
    head.append(tr);table.append(head,body);
    for(const d of days) {
        const row=node('tr');row.append(node('td',d.day));
        for(const k of ['questions','answered','empty','errors','limited','pending','source_clicks','more','sessions'])row.append(node('td',d.missing?'—':number(d.stats[k]||0)));
        body.append(row);
    }
    $('daily-table').replaceChildren(table);
}
function fillDays(data,start,end) {
    const map=new Map(data.map(d=>[d.day,d])),rows=[];
    for(let d=new Date(start+'T00:00:00Z');d<=new Date(end+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+1)) {
        const day=d.toISOString().slice(0,10);rows.push(map.get(day)||{day,stats:{},missing:true});
    }
    return rows;
}
function render(data,start,end) {
    const days=fillDays(data.days,start,end),t=sumReport(days);currentReport={days,totals:t,start,end};
    $('period-title').textContent=start+' — '+end;
    $('updated').textContent='조회 시각 '+new Date(data.updated_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'});
    $('health').textContent=(data.enabled?'수집 활성':'수집 비활성: SQL 적용 후 ENABLE_CHAT_ANALYTICS=true로 설정하세요.')+
        ' · 최초 기록 '+(data.first_recorded_day||'없음')+' · 조회 기간 중 기록 없는 날 '+days.filter(d=>d.missing).length+'일 (이용 없음/미수집 구분 불가)'+' · 보관 중 전체 10분 이상 미완료 '+number(data.pending_over_10m||0)+'건'+
        ' · 현재 인스턴스 저장 실패 '+number(data.process_storage_failures||0)+'회 (전체 누락률 아님)'+
        ' · DB '+(data.project_host||'미설정')+' · 상세 저장 '+((data.raw_bytes||0)/1048576).toFixed(1)+'MB / 수집 제한 50MB';
    const cards=[
        ['기록된 질문 수',number(t.questions),'더 보기·인사·초기화 제외'],
        ['자료 발견',number(t.answered),'검색 결과가 있는 질문'],
        ['원문 연결률',percent(t.source_clicks,t.answered),number(t.source_clicks)+'개 답변에서 원문 클릭'],
        ['기술 오류율',percent(t.errors,t.questions),'한도 제한·결과 없음은 별도']];
    $('kpis').replaceChildren(...cards.map(([label,value,hint])=>{
        const card=node('article',undefined,'kpi');card.append(node('p',label),node('strong',value),node('p',hint));return card;
    }));
    line(days);bars('categories',t.categories);donut(t.languages);
    bars('outcomes',{'자료 발견':t.answered,'결과 없음':t.empty,'기술 오류':t.errors,'한도 제한':t.limited,'추가 질문 필요':t.clarify,'접수 후 미완료':t.pending},{});
    latency(t);bars('sources',t.sources);bars('inputs',t.inputs);dailyTable(days);
}
async function loadReport(){
    const start=$('start').value,end=$('end').value;
    if(!start||!end||start>end||(new Date(end)-new Date(start))/86400000>729){$('status').textContent='조회 기간은 시작일부터 최대 730일로 선택하세요.';return;}
    const sequence=++reportSequence;
    $('status').textContent='집계 내용을 확인하고 있습니다…';$('refresh').disabled=true;
    try {
        const response=await fetch('/admin/analytics/data?start='+encodeURIComponent(start)+'&end='+encodeURIComponent(end),
            {headers:{'X-Admin-Secret':adminKey},cache:'no-store',signal:AbortSignal.timeout(15000)});
        if(response.status===401||response.status===404)throw new Error('관리자 키를 확인해 주세요. Supabase 키가 아니라 ADMIN_SECRET_KEY입니다.');
        if(!response.ok)throw new Error(response.status===429?'조회 요청이 많습니다. 잠시 후 다시 시도하세요.':'통계 저장소 연결 실패: 올바른 프로젝트에 SQL을 적용했는지 확인해 주세요.');
        const data=await response.json();
        if(sequence!==reportSequence || !adminKey)return;
        render(data,start,end);$('report').hidden=false;$('login-panel').hidden=true;$('status').textContent='';
    } catch(error){if(sequence!==reportSequence)return;$('status').textContent=error.name==='TimeoutError'?'조회 시간이 초과됐습니다. 다시 시도해 주세요.':error.message;}
    finally{if(sequence===reportSequence)$('refresh').disabled=false;}
}
function csvCell(value){return '"'+String(value).replaceAll('"','""')+'"';}
function csvText(report){
    const keys=['questions','answered','empty','errors','limited','pending','clarify','source_clicks','more','retry_attempts','sessions','cache_hits','cache_eligible'];
    const rows=[['date_kst',...keys],...report.days.map(d=>[d.day,...keys.map(k=>d.missing?'':d.stats[k]||0)])];
    return '\ufeff'+rows.map(r=>r.map(csvCell).join(',')).join('\r\n');
}
$('login-form').addEventListener('submit',async e=>{e.preventDefault();adminKey=$('secret').value;$('secret').value='';await loadReport();});
$('refresh').addEventListener('click',loadReport);
$('logout').addEventListener('click',()=>{
    ++reportSequence;adminKey='';currentReport=null;$('refresh').disabled=false;
    $('report').hidden=true;$('login-panel').hidden=false;$('status').textContent='잠금 상태입니다.';
    for(const id of ['kpis','trend','categories','languages','outcomes','latency','sources','inputs','daily-table'])$(id).replaceChildren();
    $('health').textContent='';
});
window.addEventListener('resize',()=>{if(currentReport)line(currentReport.days);});
$('print').addEventListener('click',()=>window.print());
$('csv').addEventListener('click',()=>{
    if(!currentReport)return;
    const url=URL.createObjectURL(new Blob([csvText(currentReport)],{type:'text/csv;charset=utf-8'})),a=node('a');
    a.href=url;a.download='chatbot-'+currentReport.start+'-'+currentReport.end+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
const today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Seoul'});
$('end').value=today;
const start=new Date(today+'T00:00:00Z');start.setUTCDate(start.getUTCDate()-29);$('start').value=start.toISOString().slice(0,10);
