# 요청 제한·긴 질문·실제 Redis 검증 (2026-09-20)

## 변경 범위

- 질문: IP별 60초/10회, 피드백: IP별 300초/5회 유지.
- Redis 및 메모리 키를 기능별로 분리. 클라이언트가 scope를 선택하지 않으며,
  각 API에서 chat 또는 feedback을 명시한다.
- 배포 시 기존 공유 카운터는 읽지 않으므로 제한 카운터가 한 번 새로 시작한다.
  응답 캐시와 일일 세션 한도는 변경하지 않는다.
- 긴 질문은 전송·입력 삭제·대화 수정 전에 검사한다.
  초과 입력을 자동으로 자르지 않고 선택 언어로 최대 길이를 안내한다.
- KO/EN/VI/ZH 안내 완비. 기존 외국어 지시문을 유지하고 그 길이까지 합쳐
  서버의 2,000자 제한에 맞춘다. 따라서 실제 사용자가 입력할 수 있는 길이는
  선택 언어에 따라 다르며 초과 안내에 해당 한도를 표시한다.
- 길이는 Python과 일치하는 Unicode 코드 포인트 기준이다. 이모지 결합 시퀀스와
  조합 문자는 화면상 한 글자처럼 보여도 여러 코드 포인트일 수 있다.
- 명확화 버튼은 이전 문맥과 선택한 문구를 합친 길이를 검사한다.
  초과 시 기존 문맥과 버튼을 유지한다.
- 입력 제한 상수를 서버와 프런트엔드 양쪽에서 유지하되 일치 여부를 테스트한다.
- 검색/랭킹/캐시 정책/LLM 프롬프트/모델/SQL/운영 환경변수 변경 없음.

## 테스트 구조

- 일반 오프라인: Python 94개, JavaScript 59개.
- 실제 Redis: 별도 CI 작업의 6개 테스트. 합계 159개.
- Redis 통합 테스트는 일반 test_*.py 검색에서 제외한다. 운영 REDIS_URL을 사용하지 않는다.
- GitHub-hosted Ubuntu의 일회용 Redis 7 서비스, 임의 매핑 포트,
  고정 127.0.0.1, DB 15, 테스트마다 무작위 키를 사용한다.
- 정리는 테스트가 직접 만든 두 키만 삭제한다. FLUSHDB/FLUSHALL을 사용하지 않는다.
- .env/외부 소켓 차단. 운영 키, AI 호출, Notion, Supabase 없이 실행한다.
- 50개 동시 요청 중 10개 허용, 기능별 독립 제한/TTL, 실제 만료 후 재허용,
  후속 요청의 TTL 미연장, TTL 없는 키의 복구(허용/차단)를 검사한다.
- Redis 접속 실패나 예기치 않은 메모리 대체는 실패로 처리한다.
  명시적 CI 플래그/테스트 포트가 없으면 실행을 거부하며 성공으로 건너뛰지 않는다.
- 서비스 구성 참고:
  [GitHub 공식 Redis 서비스 문서](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-redis-service-containers).

## 실행 및 한계

    python -m unittest discover -s tests -p "test_*.py" -q
    node --test --test-reporter=tap tests/frontend.test.cjs

실제 Redis 테스트는 .github/workflows/no-sql-tests.yml의 redis-integration
작업에서 실행한다. CHATBOT_REDIS_INTEGRATION 및 CHATBOT_TEST_REDIS_PORT는
그 CI 단계에만 지정하며 Vercel에 추가하지 않는다.

Windows 로컬에는 Redis 서버가 없어 실제 Lua 실행은 CI 결과로 확인해야 한다.
UI 테스트는 모의 DOM이며 실제 모바일/브라우저 시각 검증을 대신하지 않는다.
메모리 제한은 서버 프로세스 단위이고 일일 무료 한도는 세션 단위다.
운영 Redis 네트워크/서비스 설정이나 계정 전체 과금 상한까지 보장하는 테스트는 아니다.
CI 서비스 추가로 GitHub Actions 실행 시간이 소폭 늘어난다.
