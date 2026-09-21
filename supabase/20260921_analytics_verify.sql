-- Read-only verification. Run in the SAME project as Production SUPABASE_URL.
select
 to_regclass('public.chatbot_analytics_requests') as requests_table,
 to_regclass('public.chatbot_analytics_daily') as daily_table,
 has_table_privilege('anon','public.chatbot_analytics_requests','select') as anon_read_must_be_false,
 has_function_privilege('anon','public.chatbot_analytics_report(date,date)','execute') as anon_report_must_be_false,
 has_function_privilege('service_role','public.chatbot_analytics_report(date,date)','execute') as server_report_must_be_true;

select count(*) as recorded_requests,
 count(*) filter (where outcome='pending') as pending,
 count(*) filter (where outcome='answered') as answered
from public.chatbot_analytics_requests;

-- Run this line after pg_cron and the schedule have been installed:
select jobname,schedule,active from cron.job where jobname='chatbot-analytics-hourly';
