-- Chatbot exact-response cache for Vercel server functions.
-- Run this once in Supabase Dashboard > SQL Editor.

create table if not exists public.chatbot_response_cache (
  cache_key text primary key check (cache_key <> ''),
  response jsonb not null,
  cache_version text not null default 'v1',
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists chatbot_response_cache_expires_at_idx
  on public.chatbot_response_cache (expires_at);

-- This table is only accessed by the server with SUPABASE_CACHE_KEY.
-- Do not add anon/authenticated policies: cached responses should not be exposed
-- directly to a browser through the Supabase REST endpoint.
alter table public.chatbot_response_cache enable row level security;

grant usage on schema public to service_role;
revoke all on table public.chatbot_response_cache from anon, authenticated;
grant select, insert, update, delete on table public.chatbot_response_cache to service_role;
