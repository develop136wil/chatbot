-- Chatbot statistics v1. Apply ONLY to the project used by Production SUPABASE_URL.
-- No changes to site_pages, search functions or response caches.
begin;

create table if not exists public.chatbot_analytics_requests (
  id uuid primary key,
  attempt uuid not null,
  day date not null default ((now() at time zone 'Asia/Seoul')::date),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  session_hash text not null check (session_hash ~ '^[0-9a-f]{64}$'),
  kind text not null check (kind in ('question','more','other')),
  language text not null check (language in ('ko','en','vi','zh')),
  source text not null check (source in ('direct','website','qr','partner','unknown')),
  input_method text not null check (input_method in ('typed','suggestion','clarification','unknown')),
  category text not null default '미분류'
    check (category in ('의료/재활','교육/보육','가족 지원','돌봄/양육','생활 지원','복합','미분류')),
  outcome text not null default 'pending'
    check (outcome in ('pending','answered','empty','error','limited','clarify','other')),
  cache_hit boolean not null default false,
  cache_eligible boolean not null default false,
  duration_ms integer check (duration_ms between 0 and 600000),
  attempts integer not null default 1 check (attempts between 1 and 100),
  source_clicked boolean not null default false
);
create index if not exists chatbot_analytics_requests_day_idx on public.chatbot_analytics_requests(day);
create table if not exists public.chatbot_analytics_daily (
  day date primary key,
  stats jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.chatbot_analytics_requests enable row level security;
alter table public.chatbot_analytics_daily enable row level security;
revoke all on public.chatbot_analytics_requests, public.chatbot_analytics_daily from public, anon, authenticated;
grant select,insert,update,delete on public.chatbot_analytics_requests, public.chatbot_analytics_daily to service_role;

create or replace function public.chatbot_analytics_begin(
 p_id uuid, p_attempt uuid, p_session text, p_kind text, p_language text, p_source text, p_input text
) returns uuid language plpgsql security definer set search_path = public as $$
declare saved uuid;
begin
 perform pg_advisory_xact_lock(20260921, 1);
 -- Storage cap protects the shared search DB; collection failure is surfaced by the app.
 if pg_total_relation_size('public.chatbot_analytics_requests') > 52428800 then
   raise exception 'analytics_capacity';
 end if;
 insert into public.chatbot_analytics_requests(id,attempt,session_hash,kind,language,source,input_method,updated_at)
 values(p_id,p_attempt,p_session,p_kind,p_language,p_source,p_input,clock_timestamp())
 on conflict(id) do update set
   attempt=p_attempt, updated_at=clock_timestamp(), outcome='pending',
   duration_ms=null, attempts=chatbot_analytics_requests.attempts+1
 where chatbot_analytics_requests.session_hash=p_session
   and chatbot_analytics_requests.outcome in ('error','limited','pending')
   and chatbot_analytics_requests.attempts<100
 returning attempt into saved;
 return saved;
end $$;

create or replace function public.chatbot_analytics_finish(
 p_id uuid,p_attempt uuid,p_kind text,p_outcome text,p_category text,
 p_cache_hit boolean,p_cache_eligible boolean,p_duration integer
) returns boolean language plpgsql security definer set search_path = public as $$
begin
 perform pg_advisory_xact_lock(20260921, 1);
 update public.chatbot_analytics_requests set
 kind=p_kind, outcome=p_outcome, category=p_category, cache_hit=p_cache_hit,
 cache_eligible=p_cache_eligible, duration_ms=least(600000,greatest(0,p_duration)), updated_at=clock_timestamp()
 where id=p_id and attempt=p_attempt and outcome='pending';
 return found;
end $$;

create or replace function public.chatbot_analytics_click(p_id uuid)
returns boolean language plpgsql security definer set search_path = public as $$
begin
 perform pg_advisory_xact_lock(20260921, 1);
 update public.chatbot_analytics_requests set source_clicked=true,updated_at=clock_timestamp()
 where id=p_id and outcome='answered' and not source_clicked
   and created_at>now()-interval '1 day';
 return found;
end $$;

create or replace function public.chatbot_analytics_day(p_day date)
returns jsonb language sql stable security definer set search_path = public as $$
with r as (select * from public.chatbot_analytics_requests where day=p_day),
q as (select * from r where kind='question'),
b as (select case
 when duration_ms<1000 then '<1초' when duration_ms<3000 then '1–3초'
 when duration_ms<5000 then '3–5초' when duration_ms<10000 then '5–10초'
 when duration_ms<20000 then '10–20초' when duration_ms<30000 then '20–30초'
 else '30초 이상' end label,cache_hit from q where outcome='answered' and duration_ms is not null)
select jsonb_build_object(
 'requests',(select count(*) from r),
 'questions',(select count(*) from q),
 'sessions',(select count(distinct session_hash) from q),
 'answered',(select count(*) from q where outcome='answered'),
 'empty',(select count(*) from q where outcome='empty'),
 'errors',(select count(*) from q where outcome='error'),
 'limited',(select count(*) from q where outcome='limited'),
 'pending',(select count(*) from q where outcome='pending'),
 'clarify',(select count(*) from q where outcome='clarify'),
 'source_clicks',(select count(*) from q where outcome='answered' and source_clicked),
 'more',(select count(*) from r where kind='more'),
 'other',(select count(*) from r where kind='other'),
 'retry_attempts',(select coalesce(sum(attempts-1),0) from r),
 'cache_hits',(select count(*) from q where cache_hit),
 'cache_eligible',(select count(*) from q where cache_eligible),
 'categories',coalesce((select jsonb_object_agg(category,n) from (select category,count(*) n from q group by category) x),'{}'),
 'languages',coalesce((select jsonb_object_agg(language,n) from (select language,count(*) n from q group by language) x),'{}'),
 'sources',coalesce((select jsonb_object_agg(source,n) from (select source,count(*) n from q group by source) x),'{}'),
 'inputs',coalesce((select jsonb_object_agg(input_method,n) from (select input_method,count(*) n from q group by input_method) x),'{}'),
 'latency_cached',coalesce((select jsonb_object_agg(label,n) from (select label,count(*) n from b where cache_hit group by label) x),'{}'),
 'latency_fresh',coalesce((select jsonb_object_agg(label,n) from (select label,count(*) n from b where not cache_hit group by label) x),'{}')
);
$$;

create or replace function public.chatbot_analytics_maintain()
returns void language plpgsql security definer set search_path = public as $$
declare d date;
begin
 -- Serialize rollups, including concurrent dashboard refresh and scheduled maintenance.
 perform pg_advisory_xact_lock(20260921, 1);
 for d in
   select r.day from public.chatbot_analytics_requests r
   left join public.chatbot_analytics_daily s on s.day=r.day
   group by r.day,s.updated_at having s.updated_at is null or max(r.updated_at)>=s.updated_at
 loop
   insert into public.chatbot_analytics_daily(day,stats,updated_at)
   values(d,public.chatbot_analytics_day(d),clock_timestamp())
   on conflict(day) do update set stats=excluded.stats,updated_at=excluded.updated_at;
 end loop;
 -- Delete only after a rollup exists. Raw: 90 days; aggregate: 730 days.
 delete from public.chatbot_analytics_requests r
 where day < (now() at time zone 'Asia/Seoul')::date-89
 and exists(select 1 from public.chatbot_analytics_daily s where s.day=r.day);
 delete from public.chatbot_analytics_daily where day < (now() at time zone 'Asia/Seoul')::date-729;
end $$;

create or replace function public.chatbot_analytics_report(p_start date,p_end date)
returns jsonb language plpgsql security definer set search_path = public as $$
declare result jsonb;
begin
 if p_start>p_end or p_end-p_start>729 then raise exception 'invalid_period'; end if;
 perform public.chatbot_analytics_maintain();
 select jsonb_build_object(
   'days',coalesce(jsonb_agg(jsonb_build_object('day',day,'stats',stats) order by day),'[]'),
   'first_recorded_day',(select min(day) from public.chatbot_analytics_daily),
   'updated_at',now(),
   'raw_bytes',pg_total_relation_size('public.chatbot_analytics_requests'),
   'aggregate_bytes',pg_total_relation_size('public.chatbot_analytics_daily'),
   'pending_over_10m',(select count(*) from public.chatbot_analytics_requests
       where outcome='pending' and updated_at<now()-interval '10 minutes')
 ) into result from public.chatbot_analytics_daily where day between p_start and p_end;
 return result;
end $$;

revoke all on function public.chatbot_analytics_begin(uuid,uuid,text,text,text,text,text) from public,anon,authenticated;
revoke all on function public.chatbot_analytics_finish(uuid,uuid,text,text,text,boolean,boolean,integer) from public,anon,authenticated;
revoke all on function public.chatbot_analytics_click(uuid) from public,anon,authenticated;
revoke all on function public.chatbot_analytics_day(date) from public,anon,authenticated;
revoke all on function public.chatbot_analytics_maintain() from public,anon,authenticated;
revoke all on function public.chatbot_analytics_report(date,date) from public,anon,authenticated;
grant execute on function public.chatbot_analytics_begin(uuid,uuid,text,text,text,text,text),
 public.chatbot_analytics_finish(uuid,uuid,text,text,text,boolean,boolean,integer),
 public.chatbot_analytics_click(uuid),public.chatbot_analytics_day(date),
 public.chatbot_analytics_maintain(),public.chatbot_analytics_report(date,date) to service_role;
commit;

-- Optional scheduling is in 20260921_analytics_schedule.sql (run once after this file).
