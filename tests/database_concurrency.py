"""CI의 전용 localhost chatbot_test DB만 사용하는 다중 세션 경합 검사."""
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

def sql(statement):
    result = subprocess.run(
        ["psql", "-X", "-qAt", "-h", "127.0.0.1", "-p", "5432",
         "-U", "postgres", "-d", "chatbot_test", "-v", "ON_ERROR_STOP=1", "-c", statement],
        capture_output=True, text=True, timeout=30, check=True,
        env={**os.environ, "PGPASSWORD":"test-only-password", "PGOPTIONS":""},
    )
    return result.stdout.strip()

def check(label, actors, global_limit, actor_limit, expected):
    sql("truncate public.chatbot_ai_daily_usage")
    barrier=threading.Barrier(len(actors))
    def reserve(actor):
        barrier.wait(timeout=20)
        # actor는 아래에 고정된 테스트 문자열이며 사용자 입력/운영키를 받지 않습니다.
        return sql(
            "set role service_role; "
            f"select public.chatbot_reserve_ai_request('{actor}',{global_limit},{actor_limit});"
        )
    with ThreadPoolExecutor(max_workers=len(actors)) as pool:
        results=list(pool.map(reserve,actors))
    assert all(r in ("t","f") for r in results), results
    accepted=results.count("t")
    used=int(sql("select used from public.chatbot_ai_daily_usage where actor='__all__'"))
    actor_sum=int(sql("select coalesce(sum(used),0) from public.chatbot_ai_daily_usage where actor<>'__all__'"))
    actor_max=int(sql("select coalesce(max(used),0) from public.chatbot_ai_daily_usage where actor<>'__all__'"))
    assert accepted==used==actor_sum==expected,(label,accepted,used,actor_sum,expected)
    assert actor_max<=actor_limit,(label,actor_max,actor_limit)
    print(f"PASS {label}: requests={len(actors)}, accepted={accepted}, ledger={used}, actor_max={actor_max}")

if __name__=="__main__":
    if os.getenv("CHATBOT_ISOLATED_DB_TEST")!="1":
        raise SystemExit("Refusing: only run in isolated CI PostgreSQL with CHATBOT_ISOLATED_DB_TEST=1")
    if sql("select current_database()")!="chatbot_test":
        raise SystemExit("Unexpected test database")
    if sql("select public.chatbot_runtime_ready()")!="t":
        raise SystemExit("Test migration not ready")
    check("global cap", [f"client-{i}" for i in range(24)],7,2,7)
    check("same client cap", ["same-client"]*24,50,3,3)
    check("mixed caps", [f"group-{i%5}" for i in range(30)],9,2,9)
