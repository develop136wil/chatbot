-- Required for unattended retention. Supabase: enable pg_cron in Database > Extensions first.
-- Schedules ONLY analytics aggregation/retention; does NOT run the Notion indexer.
select cron.schedule(
 'chatbot-analytics-hourly',
 '17 * * * *',
 'select public.chatbot_analytics_maintain();'
);
-- Re-running the same named schedule updates it, rather than creating another name.
select jobname, schedule, active from cron.job where jobname='chatbot-analytics-hourly';
