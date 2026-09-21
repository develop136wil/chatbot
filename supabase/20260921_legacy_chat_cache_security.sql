-- Run as postgres in the Production project's Supabase SQL Editor.
-- Scope: public.chat_cache and every public.match_chat_cache function overload.
-- No rows, tables, policies or functions are deleted. No other cache is changed.
begin;
set local lock_timeout = '5s';

alter table public.chat_cache enable row level security;
revoke all privileges on table public.chat_cache from public, anon, authenticated;
grant select, insert, update, delete on table public.chat_cache to service_role;

do $security$
declare
    fn record;
    client_role text;
begin
    -- Discover exact signatures instead of assuming vector argument types.
    for fn in
        select p.oid, p.oid::regprocedure as signature
        from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname = 'match_chat_cache'
          and p.prokind = 'f'
    loop
        execute format('revoke execute on function %s from public, anon, authenticated', fn.signature);
        execute format('grant execute on function %s to service_role', fn.signature);
        if has_function_privilege('anon', fn.oid, 'EXECUTE')
           or has_function_privilege('authenticated', fn.oid, 'EXECUTE') then
            raise exception 'Public RPC access remains: %. Check inherited roles.', fn.signature;
        end if;
    end loop;

    -- Abort rather than report success if inherited/column grants remain.
    foreach client_role in array array['anon','authenticated']
    loop
        if has_table_privilege(client_role, 'public.chat_cache',
                'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
           or has_any_column_privilege(client_role, 'public.chat_cache',
                'SELECT,INSERT,UPDATE,REFERENCES') then
            raise exception 'Table access remains for %. Check inherited roles.', client_role;
        end if;
    end loop;
end
$security$;

commit;

-- Verification: every returned value must be true.
select
    (select relrowsecurity from pg_class
     where oid = 'public.chat_cache'::regclass) as rls_enabled,
    not (
        has_table_privilege('anon','public.chat_cache',
            'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        or has_any_column_privilege('anon','public.chat_cache',
            'SELECT,INSERT,UPDATE,REFERENCES')
    ) as anon_blocked,
    not (
        has_table_privilege('authenticated','public.chat_cache',
            'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        or has_any_column_privilege('authenticated','public.chat_cache',
            'SELECT,INSERT,UPDATE,REFERENCES')
    ) as authenticated_blocked,
    (select bool_and(has_table_privilege('service_role','public.chat_cache',privilege))
     from unnest(array['SELECT','INSERT','UPDATE','DELETE']) as x(privilege)
    ) as server_table_allowed,
    not exists (
        select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname = 'match_chat_cache' and p.prokind = 'f'
          and (has_function_privilege('anon',p.oid,'EXECUTE')
               or has_function_privilege('authenticated',p.oid,'EXECUTE'))
    ) as public_rpc_blocked,
    not exists (
        select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname = 'match_chat_cache' and p.prokind = 'f'
          and not has_function_privilege('service_role',p.oid,'EXECUTE')
    ) as server_rpc_allowed;
