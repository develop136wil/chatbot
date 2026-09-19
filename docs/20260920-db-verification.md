# 2026-09-20 격리 DB 검증

운영 Supabase 연결·데이터 변경·AI 호출·키 교체 없이 수행했습니다.
2026-09-20 후속 검증: 챗봇 테스트 브랜치에 커밋·푸시했고 CI가 모두 통과했습니다.
main 병합/운영 SQL/운영 배포는 수행하지 않았습니다. Vercel은 Preview 환경에 자동 배포되었습니다.

## 실행 환경

- Node 24.13.0
- 임시 폴더에만 설치한 @electric-sql/pglite 0.5.8
- 실제 SQL 실행 엔진: PostgreSQL 18.3 (WebAssembly)
- 신규 메모리 DB를 생성하고 테스트 종료 시 닫음. 운영 데이터 복사 없음.
- 프로젝트 package.json/node_modules/lock에는 테스트 의존성을 추가하지 않음.

## 통과한 SQL 검사

- 기존 두 캐시 마이그레이션 + 새 runtime_safety 마이그레이션 실행.
- 문서 삽입/카테고리 이동/삭제 시 전체 및 old/new 범위 버전 갱신.
- 문서 변경 트랜잭션 롤백 시 캐시 버전 증가도 롤백.
- 전역/개별 사용량 한도 초과 예약 거절 및 원장 수 일치.
- 잘못된 NULL 한도 거절.
- anon/authenticated 역할로 예산 함수 실행·원장 읽기 차단.
- service_role 역할로 준비 상태 조회·예산 예약 성공.
- 응답 캐시·범위 버전·사용량 테이블의 RLS 활성화.
- 새 SQL 재실행 후 기존 문서/캐시 보존 및 트리거 중복 없음.
- 트리거 비활성화/복제 전용 상태에서 준비 완료를 반환하지 않음.

## 검증 중 보완

준비 상태 함수는 종전에 트리거가 비활성화(D)만 아니면 준비 완료로 판단했습니다.
복제 전용(R)은 일반 요청의 쓰기에서 실행되지 않으므로 정상(O)·항상 실행(A)만 허용하도록 수정했습니다.
테스트의 NULL 비교도 엄격하게 변경했고, 롤백 검사가 예기치 않은 오류까지 삼키지 않게 했습니다.

## 회귀 검증

- 기존 Python 테스트 48개 통과.
- 기존 JavaScript UI 테스트 10개 통과.
- 새 DB 검증 실행기의 Python/JavaScript 문법 확인.
- SQL 테스트는 위 기능별 검사 묶음이며 58개 테스트 수에 섞어 세지 않았습니다.

## 재실행

테스트용 별도 npm prefix에 PGlite 0.5.8을 설치한 후:

    node tests/database-pglite.cjs <temporary-npm-prefix>

실행기는 항상 메모리 DB를 만들고 외부 DB 연결 문자열이나 .env를 사용하지 않습니다.
tests/database_regression.sql 자체는 초기 역할/테이블을 만드는 테스트 전용 파일이므로 운영 SQL Editor에 넣으면 안 됩니다.
운영 적용 대상은 supabase/20260919_runtime_safety.sql입니다.

## 남은 단계

1. 테스트용 브랜치 커밋·푸시 및 Regression Tests: 완료.
   - 저장소: develop136wil/chatbot만 사용.
   - 코드 커밋: 7dfd32e176f489001089a665e3c426aa9acdc289.
   - [전체 CI 결과](https://github.com/develop136wil/chatbot/actions/runs/35459291616): success.
   - Python 3.11의 48개 테스트, Node 24의 10개 테스트, SQL 단계 모두 성공.
2. native PostgreSQL 17 동시 요청 검증: 아래 예상값과 실제 로그가 모두 일치.
   - 서로 다른 24개 요청, 전체 한도 7 → 승인 정확히 7.
   - 동일 사용자 24개 요청, 개인 한도 3 → 승인 정확히 3.
   - 5개 사용자 30개 요청, 전체 9·개인 2 → 승인 정확히 9, 사용자별 최대 2.
3. 아직 남음: 실제 프로젝트 확인 → 운영 SQL 적용 → 운영 배포 및 실사용 확인.

격리 DB의 다중 세션 검사와 Python 3.11 CI까지 완료했지만,
Supabase 운영 설정 및 새 답변 품질·지연 검증을 대체하지 않습니다.
[PGlite 공식 문서](https://pglite.dev/docs/)도 단일 전용 연결 구조를 명시합니다.
