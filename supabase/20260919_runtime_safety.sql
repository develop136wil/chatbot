-- 기존 두 캐시 SQL 이후 실행. DB 데이터/임베딩은 삭제하지 않습니다.
begin;

-- 문서 변경과 범위 무효화를 같은 트랜잭션에서 실행합니다.
create or replace function public.chatbot_invalidate_changed_page()
returns trigger language plpgsql security definer set search_path = '' as $$
declare scopes text[] := array['__all__'];
begin
  if TG_OP <> 'INSERT' then
    scopes := array_append(scopes, OLD.metadata->>'category');
  end if;
  if TG_OP <> 'DELETE' then
    scopes := array_append(scopes, NEW.metadata->>'category');
  end if;
  perform public.bump_chatbot_cache_scope_versions(scopes);
  return null;
end;
$$;
revoke all on function public.chatbot_invalidate_changed_page() from public;
drop trigger if exists chatbot_page_cache_invalidation on public.site_pages;
create trigger chatbot_page_cache_invalidation
after insert or update or delete on public.site_pages
for each row execute function public.chatbot_invalidate_changed_page();

create table if not exists public.chatbot_ai_daily_usage (
  usage_day date not null,
  actor text not null,
  used integer not null default 0 check (used >= 0),
  primary key (usage_day, actor)
);
alter table public.chatbot_ai_daily_usage enable row level security;
revoke all on public.chatbot_ai_daily_usage from anon, authenticated;
grant select, insert, update, delete on public.chatbot_ai_daily_usage to service_role;

create or replace function public.chatbot_reserve_ai_request(
  p_actor text, p_global_limit integer, p_actor_limit integer
) returns boolean language plpgsql security definer set search_path = '' as $$
declare
  d date := (now() at time zone 'Asia/Seoul')::date;
  global_used integer;
  actor_used integer;
begin
  if p_actor is null or p_actor = '' or p_actor = '__all__'
     or length(p_actor) > 128 or p_global_limit is null or p_actor_limit is null
     or p_global_limit < 1 or p_actor_limit < 1 then
    raise exception 'Invalid budget parameters';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('chatbot-ai-budget:' || d::text));
  select used into global_used from public.chatbot_ai_daily_usage where usage_day=d and actor='__all__';
  select used into actor_used from public.chatbot_ai_daily_usage where usage_day=d and actor=p_actor;
  if coalesce(global_used,0) >= p_global_limit or coalesce(actor_used,0) >= p_actor_limit then
    return false;
  end if;
  insert into public.chatbot_ai_daily_usage(usage_day,actor,used)
  values (d,'__all__',1),(d,p_actor,1)
  on conflict(usage_day,actor) do update set used=public.chatbot_ai_daily_usage.used+1;
  delete from public.chatbot_ai_daily_usage where usage_day < d-7;
  return true;
end;
$$;
revoke all on function public.chatbot_reserve_ai_request(text,integer,integer) from public;
grant execute on function public.chatbot_reserve_ai_request(text,integer,integer) to service_role;

create or replace function public.chatbot_runtime_ready()
returns boolean language sql security definer set search_path = '' as $$
  select exists(select 1 from pg_catalog.pg_trigger
    where tgname='chatbot_page_cache_invalidation'
      and tgrelid='public.site_pages'::regclass and tgenabled in ('O', 'A'));
$$;
revoke all on function public.chatbot_runtime_ready() from public;
grant execute on function public.chatbot_runtime_ready() to service_role;
commit;
