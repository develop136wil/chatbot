-- 오직 비어 있는 임시 테스트 DB에서 실행. 운영 DB 실행 금지.
\set ON_ERROR_STOP on
create role anon;
create role authenticated;
create role service_role bypassrls;
create table public.site_pages(page_id text primary key, metadata jsonb not null);
\i supabase/20260730_response_cache.sql
\i supabase/20260730_response_cache_scopes.sql
\i supabase/20260919_runtime_safety.sql

do $test$
declare before_version bigint;
begin
  if public.chatbot_runtime_ready() is not true then raise exception 'trigger missing'; end if;
  if has_table_privilege('anon','public.chatbot_ai_daily_usage','SELECT') then
    raise exception 'anon can read usage';
  end if;
  if has_function_privilege('anon','public.chatbot_reserve_ai_request(text,integer,integer)','EXECUTE') then
    raise exception 'anon can reserve budget';
  end if;
  if not has_function_privilege('service_role','public.chatbot_reserve_ai_request(text,integer,integer)','EXECUTE') then
    raise exception 'server cannot reserve budget';
  end if;

  insert into public.site_pages values ('test','{"category":"의료/재활"}');
  if (select version from public.chatbot_cache_scope_versions where scope='__all__') is distinct from 1 then
    raise exception 'insert invalidation missing';
  end if;
  update public.site_pages set metadata='{"category":"돌봄/양육"}' where page_id='test';
  if (select version from public.chatbot_cache_scope_versions where scope='의료/재활') is distinct from 2
     or (select version from public.chatbot_cache_scope_versions where scope='돌봄/양육') is distinct from 1 then
    raise exception 'old/new category invalidation missing';
  end if;

  select version into before_version from public.chatbot_cache_scope_versions where scope='__all__';
  begin
    update public.site_pages set metadata='{"category":"생활 지원"}' where page_id='test';
    raise sqlstate 'P9999' using message='rollback test';
  exception when sqlstate 'P9999' then null;
  end;
  if (select version from public.chatbot_cache_scope_versions where scope='__all__') is distinct from before_version then
    raise exception 'invalidation not atomic with write rollback';
  end if;
  delete from public.site_pages where page_id='test';
  if (select version from public.chatbot_cache_scope_versions where scope='__all__') is distinct from before_version+1 then
    raise exception 'delete invalidation missing';
  end if;

  if public.chatbot_reserve_ai_request('client-a',2,1) is not true then raise exception 'first denied'; end if;
  if public.chatbot_reserve_ai_request('client-a',2,1) is not false then raise exception 'actor limit bypass'; end if;
  if public.chatbot_reserve_ai_request('client-b',2,1) is not true then raise exception 'second denied'; end if;
  if public.chatbot_reserve_ai_request('client-c',2,1) is not false then raise exception 'global limit bypass'; end if;
  begin
    perform public.chatbot_reserve_ai_request('null-limit',null,1);
    raise check_violation using message='null limit accepted';
  exception when raise_exception then null;
  end;
end;
$test$;

-- 테스트 DB 상태를 보존한 채 신규 SQL 재적용 가능 여부 확인
insert into public.site_pages values ('preserved', '{"category":"교육/보육"}');
insert into public.chatbot_response_cache(cache_key,response,expires_at)
values ('preserved', '{"status":"complete","answer":"keep"}', now()+interval '1 day');
\i supabase/20260919_runtime_safety.sql

do $checks$
declare denied boolean; marker text;
begin
  if (select metadata->>'category' from public.site_pages where page_id='preserved')
     is distinct from '교육/보육' then raise exception 'migration lost document'; end if;
  if (select response->>'answer' from public.chatbot_response_cache where cache_key='preserved')
     is distinct from 'keep' then raise exception 'migration lost cache'; end if;
  if (select count(*) from pg_catalog.pg_trigger
      where tgname='chatbot_page_cache_invalidation' and tgrelid='public.site_pages'::regclass)
     is distinct from 1::bigint then raise exception 'duplicate/missing trigger'; end if;

  alter table public.site_pages disable trigger chatbot_page_cache_invalidation;
  if public.chatbot_runtime_ready() is not false then raise exception 'disabled trigger reported ready'; end if;
  alter table public.site_pages enable replica trigger chatbot_page_cache_invalidation;
  if public.chatbot_runtime_ready() is not false then raise exception 'replica-only trigger reported ready'; end if;
  alter table public.site_pages enable trigger chatbot_page_cache_invalidation;

  if exists (select 1 from pg_catalog.pg_class where oid in (
    'public.chatbot_response_cache'::regclass,
    'public.chatbot_cache_scope_versions'::regclass,
    'public.chatbot_ai_daily_usage'::regclass) and not relrowsecurity)
    then raise exception 'RLS missing'; end if;

  foreach marker in array array['anon','authenticated'] loop
    execute format('set local role %I',marker);
    denied := false;
    begin
      perform public.chatbot_reserve_ai_request('forbidden',100,30);
    exception when insufficient_privilege then denied := true;
    end;
    if not denied then raise exception 'unprivileged RPC execution'; end if;
    denied := false;
    begin
      perform used from public.chatbot_ai_daily_usage;
    exception when insufficient_privilege then denied := true;
    end;
    if not denied then raise exception 'unprivileged usage read'; end if;
    reset role;
  end loop;

  set local role service_role;
  if public.chatbot_runtime_ready() is not true then raise exception 'service readiness denied'; end if;
  if public.chatbot_reserve_ai_request('server-client',3,1) is not true then
    raise exception 'service budget reservation denied';
  end if;
  reset role;

  if (select used from public.chatbot_ai_daily_usage where actor='__all__'
      and usage_day=(now() at time zone 'Asia/Seoul')::date)
      is distinct from 3 then raise exception 'budget count incorrect'; end if;
end;
$checks$;
select 'Database regression passed: migrations, triggers, rollback, limits, roles, RLS, reapply, readiness' as result;
