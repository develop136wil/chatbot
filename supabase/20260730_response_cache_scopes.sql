-- Selective cache invalidation by Notion category.
-- Run this after 20260730_response_cache.sql in Supabase Dashboard > SQL Editor.

alter table public.chatbot_response_cache
  add column if not exists scope_versions jsonb not null default '{}'::jsonb;

create table if not exists public.chatbot_cache_scope_versions (
  scope text primary key check (scope <> ''),
  version bigint not null default 0,
  updated_at timestamptz not null default now()
);

alter table public.chatbot_cache_scope_versions enable row level security;
grant usage on schema public to service_role;
revoke all on table public.chatbot_cache_scope_versions from anon, authenticated;
grant select, insert, update, delete on table public.chatbot_cache_scope_versions to service_role;

create or replace function public.bump_chatbot_cache_scope_versions(p_scopes text[])
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.chatbot_cache_scope_versions (scope, version, updated_at)
  select distinct scope, 1, now()
  from unnest(p_scopes) as scope
  where scope is not null and scope <> ''
  on conflict (scope) do update
  set version = public.chatbot_cache_scope_versions.version + 1,
      updated_at = now();
end;
$$;

revoke all on function public.bump_chatbot_cache_scope_versions(text[]) from public;
grant execute on function public.bump_chatbot_cache_scope_versions(text[]) to service_role;
