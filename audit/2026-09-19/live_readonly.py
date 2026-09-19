"""읽기 전용 운영 점검. AI 생성/인덱싱/DB 변경/이메일 발송 없음.
로컬 .env는 인증에만 사용하며 값은 출력하지 않습니다.
"""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import requests
from urllib.parse import urlsplit
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[2]
ENV=dict(dotenv_values(ROOT/'.env'),**os.environ)
S=requests.Session()
def emit(label,data): print(label, json.dumps(data,ensure_ascii=False))
def get(url,**kw): return S.get(url,timeout=20,**kw)

for path in ('/health','/','/static/script.js','/static/style.css'):
    try:
        r=get('https://chatbot-tau-bay.vercel.app'+path)
        item={'status':r.status_code,'seconds':round(r.elapsed.total_seconds(),3),'bytes':len(r.content)}
        if path in ('/static/script.js','/static/style.css','/'):
            local=ROOT/('static/index.html' if path=='/' else path.lstrip('/'))
            item['same_text_as_local']=r.text.replace('\r\n','\n')==local.read_text(encoding='utf-8-sig').replace('\r\n','\n')
        emit('PUBLIC '+path,item)
    except Exception as e: emit('PUBLIC '+path,{'error_type':type(e).__name__})

base='https://api.github.com/repos/develop136wil/chatbot'
for endpoint in ('/commits/main','/actions/workflows','/actions/runs?per_page=5'):
    try:
        r=get(base+endpoint); d=r.json()
        item={'status':r.status_code}
        if r.ok and endpoint.startswith('/commits'): item['sha']=d.get('sha','')[:7]
        elif r.ok and 'workflows' in d: item['workflows']=[{'name':x['name'],'state':x['state']} for x in d['workflows']]
        elif r.ok and 'workflow_runs' in d: item['runs']=[{k:x.get(k) for k in ('name','status','conclusion','created_at','head_sha','html_url')} for x in d['workflow_runs']]
        emit('GITHUB '+endpoint,item)
    except Exception as e: emit('GITHUB',{'error_type':type(e).__name__})

url=(ENV.get('SUPABASE_URL') or '').strip().rstrip('/')
host=urlsplit(url).hostname
emit('LOCAL CONFIG',{'supabase_host':host,'cache_key_present':bool(ENV.get('SUPABASE_CACHE_KEY')),'server_key_present':bool(ENV.get('SUPABASE_KEY')),'groq_key_present':bool(ENV.get('GROQ_API_KEY'))})
source_state={}
if host=='vlxxxpqyvrvcwffrpvid.supabase.co':
    key=(ENV.get('SUPABASE_CACHE_KEY') or ENV.get('SUPABASE_KEY') or '').strip().strip('\"\'')
    headers={'apikey':key,'Prefer':'count=exact'}
    if not key.startswith('sb_secret_'): headers['Authorization']='Bearer '+key
    for table,select in [('site_pages','page_id,metadata,embedding'),('chatbot_response_cache','cache_version,expires_at,scope_versions'),('chatbot_cache_scope_versions','scope,version')]:
        try:
            r=get(url+'/rest/v1/'+table,headers=headers,params={'select':select,'limit':1000})
            item={'status':r.status_code,'content_range':r.headers.get('Content-Range')}
            if r.ok:
                rows=r.json(); item['rows']=len(rows)
                if table=='site_pages':
                    source_state={x['page_id']:(x.get('metadata') or {}) for x in rows}
                    item['categories']=dict(Counter((x.get('metadata') or {}).get('category','missing') for x in rows))
                    item['missing_translations']={l:sum(not all(isinstance((x.get('metadata') or {}).get(k),str) and (x.get('metadata') or {})[k].strip() for k in ('title_'+l,'pre_summary_'+l)) for x in rows) for l in ('en','vi','zh')}
                    item['missing_source_timestamp']=sum(not (x.get('metadata') or {}).get('last_edited_time') for x in rows)
                    dims=Counter()
                    for x in rows:
                        vector=x.get('embedding')
                        if isinstance(vector,str): vector=json.loads(vector)
                        dims[str(len(vector)) if isinstance(vector,list) else 'missing']+=1
                    item['embedding_dimensions']=dict(dims)
                elif table=='chatbot_response_cache':
                    item['expired']=sum(datetime.fromisoformat(x['expires_at'])<=datetime.now(timezone.utc) for x in rows)
                    item['versions']=dict(Counter(x['cache_version'] for x in rows))
            emit('DB '+table,item)
        except Exception as e: emit('DB '+table,{'error_type':type(e).__name__})
else: emit('DB','운영 프로젝트 reference 불일치 또는 설정 없음: 조회 생략')

notion=ENV.get('NOTION_API_KEY') or ENV.get('NOTION_KEY')
if source_state and notion:
    tree=ast.parse((ROOT/'run_indexer.py').read_text(encoding='utf-8-sig'))
    dbs=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DATABASE_IDS' for t in n.targets))
    current={}; failures=[]
    for category,db in dbs.items():
        cursor=None; pages=[]
        try:
            while True:
                r=S.post('https://api.notion.com/v1/databases/'+db+'/query',headers={'Authorization':'Bearer '+notion,'Notion-Version':'2022-06-28'},json={'start_cursor':cursor} if cursor else {},timeout=20)
                if not r.ok:
                    failures.append(category); emit('NOTION '+category,{'status':r.status_code}); break
                data=r.json(); pages.extend(data.get('results',[]))
                if not data.get('has_more'):
                    current.update({p['id']:p.get('last_edited_time') for p in pages})
                    emit('NOTION '+category,{'status':r.status_code,'pages':len(pages)})
                    break
                cursor=data.get('next_cursor')
        except Exception as e:
            failures.append(category); emit('NOTION '+category,{'error_type':type(e).__name__})
    if not failures:
        emit('NOTION DB COMPARISON',{'source_pages':len(current),'db_pages':len(source_state),'missing_in_db':len(set(current)-set(source_state)),'not_in_notion':len(set(source_state)-set(current)),'edited_time_mismatch':sum(source_state[p].get('last_edited_time')!=t for p,t in current.items() if p in source_state)})

groq=ENV.get('GROQ_API_KEY')
if groq:
    try:
        r=get('https://api.groq.com/openai/v1/models',headers={'Authorization':'Bearer '+groq})
        models={x['id'] for x in r.json().get('data',[])} if r.ok else set()
        emit('GROQ MODEL ACCESS',{'status':r.status_code,'models':{m:m in models for m in ('openai/gpt-oss-20b','openai/gpt-oss-120b','llama-3.1-8b-instant')}})
    except Exception as e: emit('GROQ MODEL ACCESS',{'error_type':type(e).__name__})
