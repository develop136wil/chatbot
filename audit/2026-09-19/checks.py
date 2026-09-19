"""오프라인 감사: 실제 함수 AST + 가짜 서비스. .env/네트워크/실제 DB 접근 없음."""
import ast, asyncio, gc, hashlib, html, json, logging, re, time, unicodedata, warnings
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, Mock
ROOT = Path(__file__).resolve().parents[2]
logging.disable(logging.CRITICAL)
def load(file, names, **overrides):
    nodes=[]
    for node in ast.parse((ROOT/file).read_text(encoding='utf-8-sig')).body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list=[]
            nodes.append(node)
        elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in node.targets):
            nodes.append(node)
    env=dict(globals(),logger=logging.getLogger('audit'),**overrides)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),file,'exec'),env)
    return env
async def checks():
    for f in ['main.py','utils.py','worker.py','run_indexer.py','api/index.py']:
        compile((ROOT/f).read_text(encoding='utf-8-sig'),f,'exec')
    print('PASS: Python syntax, 5 files')
    u=load('utils.py',['LOCALIZED_UI','SUPPORTED_LANGUAGE_CODES','resolve_language','_normalize_cache_question','build_response_cache_key','build_response_cache_scopes','clean_summary_text','format_search_results'],RESPONSE_CACHE_SCHEMA_VERSION='v2',GLOBAL_CACHE_SCOPE='__all__')
    key=u['build_response_cache_key']
    assert key(' A  B ','ko')==key('a b','ko') and key('a b','ko')!=key('a b','en')
    print('PASS: cache normalization and language separation')
    c=load('main.py',['is_response_cache_read_eligible'],ChatRequest=Any,build_response_cache_key=key)
    req=NS(last_result_ids=[],shown_count=0,chat_history=[{'role':'user','content':'a b'},{'role':'assistant','content':'answer'}])
    assert c['is_response_cache_read_eligible'](req,'a b','ko')
    print('PASS: immediate repeated question is cache eligible')
    s=load('utils.py',['search_supabase_async'],get_gemini_embedding_async=AsyncMock(return_value=[0.1]),supabase_async=NS(rpc=Mock(side_effect=RuntimeError('simulated outage'))))
    saver=AsyncMock()
    w=load('worker.py',['process_job_async'],resolve_language=u['resolve_language'],LOCALIZED_UI=u['LOCALIZED_UI'],expand_search_query_async=AsyncMock(return_value=['test']),search_supabase_async=s['search_supabase_async'],save_response_cache_async=saver)
    out=await w['process_job_async']({'question':'test','language':'ko','cacheable':True})
    assert out[0]==u['LOCALIZED_UI']['ko']['not_found'] and saver.await_args.args[2]['status']=='complete'
    print('REPRODUCED: DB outage saved as successful no-result cache')
    docs=[{'id':i,'metadata':{'page_id':str(i),'start_age':0,'end_age':12}} for i in range(3)]
    s['supabase_async']=NS(rpc=Mock(return_value=NS(execute=lambda:NS(data=list(docs)))))
    assert len(await s['search_supabase_async']('36 months',{'category':'care','age':36},['test']))==3
    print('REPRODUCED: category search ignores age filter')
    assert '__all__' not in u['build_response_cache_scopes']([{'metadata':{'category':'family'}}],'welfare')
    print('REPRODUCED: global fallback cache missing global invalidation scope')
    async def translate(*args): return 'translated'
    loc=load('utils.py',['localize_result_pages_async'],resolve_language=u['resolve_language'],LOCALIZED_UI=u['LOCALIZED_UI'],LIVE_TRANSLATION_ENABLED=False,translate_content_simple_async=translate)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        await loc['localize_result_pages_async']([{'title':'original','pre_summary':'original'}],'en')
        gc.collect()
    assert any('was never awaited' in str(x.message) for x in caught)
    print('REPRODUCED: unawaited translation coroutine when translation disabled')
    calls=[]
    def gen(**kw): calls.append(kw); return NS(text='{}')
    g=load('utils.py',['generate_content_safe'],FREE_TIER_ONLY=True,FREE_TIER_MAX_OUTPUT_TOKENS=400,types=NS(GenerateContentConfig=lambda **kw:kw),LLM_CLIENT=NS(models=NS(generate_content=gen)),time=NS(sleep=lambda _:None))
    g['generate_content_safe'](None,'translate',timeout=40,max_output_tokens=4096)
    assert calls[0]['config']['max_output_tokens']==400 and 'timeout' not in calls[0]
    print('REPRODUCED: translation capped at 400; sync timeout ignored')
    quota=type('FreeTierQuotaExceeded',(RuntimeError,),{})
    i=load('utils.py',['extract_info_from_question_async','_fallback_question_info'],LLM_MODEL=True,get_llm_client=lambda:True,GROQ_FALLBACK_ENABLED=True,GROQ_CLIENT=True,redis_async_client=None,types=NS(SafetySetting=lambda **kw:kw),FreeTierQuotaExceeded=quota,call_groq_async_simple=AsyncMock(return_value='{"category":"null","age":"24","intent":null}'))
    out=await i['extract_info_from_question_async']('test')
    assert out['category']=='null' and out['age']=='24'
    print('REPRODUCED: invalid schema accepted')
    i['call_groq_async_simple']=AsyncMock(return_value=None)
    i['generate_content_safe_async']=AsyncMock(side_effect=quota())
    assert 'error' in await i['extract_info_from_question_async']('test')
    print('REPRODUCED: quota error stops intent instead of deterministic fallback')
    try: await i['extract_info_from_question_async']('test',[{}])
    except KeyError: print('REPRODUCED: malformed history raises uncaught KeyError')
    else: raise AssertionError('expected KeyError')
    safe=u['format_search_results']([{'title':'<script>x</script>','pre_summary':'<img src=x onerror=alert(1)>','page_url':'javascript:alert(1)'}],'en')
    assert '<script>' not in safe and 'href="javascript:' not in safe
    print('PASS: card HTML escaped and dangerous URL rejected')
    def indexer(storage,embedding):
        trans={l:{'title':'title','content':'body'} for l in ('en','vi','zh')}
        return load('run_indexer.py',['run_indexing'],init_clients=lambda:None,get_llm_client=lambda:True,load_state_from_db=lambda:{},DATABASE_IDS={'medical':'a','care':'b'},NOTION_KEY='fake',NOTION_REQUEST_TIMEOUT_SECONDS=1,NOTION_PROPERTY_NAMES={k:k for k in ('title','support_detail','extra_req','contact','start_age','end_age','sub_category','cost_info','notes')},requests=NS(post=lambda url,**kw:NS(raise_for_status=lambda:None,json=lambda:{'results':[{'id':url.split('/')[-2],'last_edited_time':'today','properties':{}}],'has_more':False})),time=NS(sleep=lambda _:None),_get_title=lambda *a:'title',_get_rich_text=lambda *a:'body',_get_number=lambda *a:None,_get_multi_select=lambda *a:[],translate_content_simple=lambda text,**kw:text,translate_content_multilingual_sync=lambda *a:trans,get_gemini_embedding=embedding,supabase=storage,purge_expired_response_cache=Mock(),bump_response_cache_scope_versions=Mock(),send_email_alert=Mock(),traceback=__import__('traceback'))
    n=indexer(Mock(),lambda *a,**kw:None)
    assert n['run_indexing']() is None
    print('REPRODUCED: both embeddings fail but indexer returns without failure')
    writes=[]
    def save():
        writes.append(1)
        if len(writes)==2: raise RuntimeError('second upsert failed')
    n=indexer(NS(table=lambda _:NS(upsert=lambda *a,**kw:NS(execute=save))),lambda *a,**kw:[0.1])
    n['run_indexing']()
    assert len(writes)==2 and n['bump_response_cache_scope_versions'].call_count==0
    print('REPRODUCED: partial indexing success fails to invalidate cache')
if __name__=='__main__': asyncio.run(checks())
