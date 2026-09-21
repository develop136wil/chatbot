-- Read-only. Run after indexing to verify preparation; no AI calls.
select count(*) as total_documents,
       count(*) filter (where nullif(btrim(metadata->>'title_ja'),'') is not null
                         and nullif(btrim(metadata->>'pre_summary_ja'),'') is not null) as japanese_ready,
       count(*) filter (where nullif(btrim(metadata->>'title_ja'),'') is null
                          or nullif(btrim(metadata->>'pre_summary_ja'),'') is null) as japanese_pending
from public.site_pages;

select language, count(*) as recorded_requests
from public.chatbot_analytics_requests
group by language order by language;
