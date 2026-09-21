-- Apply to the SAME Supabase project used by Production SUPABASE_URL.
-- Run after 20260921_analytics.sql. No data deletion, no RLS/grant changes.
begin;
alter table public.chatbot_analytics_requests
  drop constraint if exists chatbot_analytics_requests_language_check;
alter table public.chatbot_analytics_requests
  add constraint chatbot_analytics_requests_language_check
  check (language in ('ko','en','vi','zh','ja'));
commit;

-- Read-only verification: should list ja.
select pg_get_constraintdef(oid) as language_rule
from pg_constraint
where conrelid = 'public.chatbot_analytics_requests'::regclass
  and conname = 'chatbot_analytics_requests_language_check';
