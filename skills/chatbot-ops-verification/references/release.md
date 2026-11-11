# 변경 및 배포 검증

## 로컬

기존 변경을 보존하고 실제 diff 범위에 맞는 검사를 선택한다. 기본 오프라인 회귀 명령:

```powershell
python -X utf8 -m unittest discover -s tests -p 'test_*.py'
node --test tests/frontend.test.cjs tests/analytics_dashboard.test.cjs
git diff --check
```

이 명령은 저장소 루트와 의존성이 준비된 테스트 Python에서 실행한다. 현재 환경에 있으면
`.venv-ops-20261027/Scripts/python.exe`를 사용할 수 있으나 경로·버전을 먼저 확인한다.
`tests/test_no_sql_contract.py`의 환경변수·dotenv·외부 소켓 격리를 확인하고, 필요한 변경이
없다면 테스트 준비를 위해 운영 키를 로드하지 않는다. 루트의 오래된 `test_*.py`나
`run_indexer.py`를 일반 테스트로 실행하지 않는다.

UI 변경 시 `node tests/ui_design.browser.cjs`와 `node tests/security.browser.cjs`도 실행한다.
브라우저를 실행하지 못했다면 정적/단위 테스트 결과로 대체했다고 하지 않는다.
DB/Redis 통합 검사는 현재 `.github/workflows/no-sql-tests.yml`의 격리 서비스만 사용한다.
외부 취약점 조회가 필요한 audit는 네트워크 검사이며 오프라인 검사와 구분한다.

스킬 변경 시에는 형식 검증 외에 `tests/test_ops_skill.py`를 실행하고 저장소 루트에서
`python scripts/check_skill_install.py skills/chatbot-ops-verification <installed-skill-folder>`로
설치본의 누락·변경·추가 파일을 확인한다. 이 명령은 읽기 전용이며 자동 복사하지 않는다.
종료 코드 0은 파일 일치, 1은 차이, 2는 비교 불가다. `__pycache__`/바이트코드는 비교에서 제외한다.
파일 일치와 실제 앱 인식은 별개다. 인식 확인에는 공식 `skills/list`의 `forceReload` 조회를
사용할 수 있으며, 조회만을 위해 새 대화/모델 턴을 생성하거나 설정을 변경하지 않는다.

## GitHub 및 Production

- 커밋·푸시·main 반영·Production 배포의 승인 범위를 확인한다. 스킬 설치 요청은 배포 승인이 아니다.
- 승인된 배포에서는 대상 SHA의 모든 필수 CI job을 확인한다. 이전 SHA의 성공은 대체 증거가 아니다.
- Vercel의 대상 프로젝트, 환경, 소스 SHA, Ready 상태와 실제 Production 별칭 연결을 대조한다.
  Preview Ready를 Production 완료라고 하지 않는다. SHA를 확인할 수 없으면 미확인으로 남긴다.
- 공개 GET `/`, `/health`는 가용성 확인이다. 신규 검색/번역 성공의 증거는 아니다.
  관리자 보호 확인에는 유효한 요청 형식을 사용한다. 필수 파라미터 누락의 422를 인증 성공/실패로
  오해하지 않는다. 관리자 키를 URL 쿼리에 넣지 않는다.
- `/chat` 검사는 AI 호출·캐시·통계 쓰기를 유발할 수 있다. 단순 GET 점검과 구분하고,
  운영 데이터 오염 없는 검사 경로와 명시적 요청 범위가 확인된 경우에만 실행한다.

## MCP가 필요할 때만

기존 GitHub/CLI로 확인되면 새 MCP를 필수로 만들지 않는다. 접근이 막힌 항목을 명시하고
사용자 인증이 필요하면 안내한다. Supabase 연결은 실제 Production 호스트와 대상 프로젝트를
대조한 뒤 프로젝트 범위·읽기 전용·최소 도구 설정을 확인한다. Vercel도 Chatbot 프로젝트를
대상으로 한다. 읽기 전용은 개인정보 노출까지 차단하는 보장이 아니다.
