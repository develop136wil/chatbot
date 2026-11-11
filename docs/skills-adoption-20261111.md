# 챗봇 검증 스킬 도입 기록

## 범위

사용자의 권장 순서 진행 요청에 따라 개발자용 로컬 스킬만 설치했다.
챗봇 런타임, requirements, SQL, 환경변수, 운영 데이터, 예약 실행은 변경하지 않았다.
GitHub 커밋·푸시·Production 배포, 실제 AI 호출, 인덱싱 재실행, 메일 발송도 하지 않았다.
이 기록은 운영 환경의 현재 정상 여부나 전체 보안 감사 결과가 아니다.

## 설치 출처

설치 위치: `C:/Users/mycom/.codex/skills/`.
공식 skill-installer의 download 방식으로 아래 고정 커밋을 설치했다.
스킬 본문·포함 파일을 확인했으며 전체 저장소의 보안 감사를 수행한 것은 아니다.
외부 스킬의 원본을 수정하거나 자동 업데이트 설정을 추가하지 않았다.

| 스킬 | 원본 저장소/경로 | 고정 커밋 |
|---|---|---|
| supabase-postgres-best-practices | supabase/agent-skills / skills/supabase-postgres-best-practices | c9be0e931b7930f7d02126d04774d904c381e7d7 |
| security-best-practices | openai/skills / skills/.curated/security-best-practices | 49f948faa9258a0c61caceaf225e179651397431 |

설치한 SKILL.md의 SHA-256:

- Supabase: `AD65E776F45E761BAFC609D3F506C77C1032225AA65E0C4C02F241B8071E5855`
- Security: `7B3DAE1FFC5434D890F3C65C8F552AF52D0307FAB3B35DEC13013C9CA3844C4F`

## 프로젝트 전용 스킬

원본: `skills/chatbot-ops-verification/`.
동일 폴더를 사용자 스킬 경로에 설치하고 소스 6개 파일의 해시 일치를 확인했다.
스킬 본문, UI 메타데이터, 인덱싱/배포/품질 참조 문서, 로컬 summary 판정 도구를 포함한다.
수정 시 이 원본을 먼저 검증하고 설치본과 동기화해야 한다. 자동 동기화는 없다.

- 다른 저장소에 적용하지 않는 좁은 설명과 자동 선택 기본값을 사용한다.
- 모델/무료 한도/임베딩 변경, 운영 SQL·데이터 수정, 배포를 임의로 승인하지 않는다.
- summary 판정 도구는 표준 라이브러리만 사용한다. 앱 import, 환경파일 로드, 네트워크,
  외부 명령, 파일 쓰기가 없다. 입력 파일과 출력 JSON만 사용한다.
- 완전한 summary와 실행 SHA·이벤트·attempt·Actions 결론의 확인을 분리한다.
- 모든 문서를 건너뛴 성공은 새 번역 품질 검증으로 확대하지 않는다.
- 문서 수 변화 자체를 실패로 처리하지 않는다. 0건은 직전 상태와 비교할 대상으로 남긴다.
- DB·보안 스킬 설치는 실제 프로젝트의 보안 검토 완료를 뜻하지 않는다.

## 검증 결과

- 새 판정 도구 행동 테스트 14개 통과 (`tests/test_ops_skill.py`).
- 전체 Python 오프라인 회귀 223개 통과. 실제 AI/운영 DB 요청 없음.
- 세 스킬 모두 공식 `quick_validate.py` 통과.
- 형식 검증에 필요한 PyYAML 6.0.3은 별도 `.venv-skill-tools`에만 설치했다.
  운영/기존 테스트 의존성 파일은 변경하지 않았다.
- 브라우저·실제 Redis/PostgreSQL·원격 CI·Production 검증은 이번 작업에서 실행하지 않았다.
- 스킬 형식/보조 도구 테스트는 에이전트의 모든 미래 판단을 보증하지 않는다.

## 보류한 항목

- Vercel/Supabase MCP: 기존 연결·CLI로 가능한 검증을 먼저 사용한다.
  새 MCP 인증이나 설정은 추가하지 않았다. 필요해지면 프로젝트 한정·읽기 전용·최소 권한을
  확인한 후 연결한다. 현재 연결 승인이나 인증 대기를 요구하는 필수 작업은 없다.
- Web Design Guidelines/Context7/Playwright/Gemini 스킬: 이번 우선순위에 포함하지 않았다.
  기존 디자인 계약과 무료 모델 원칙을 유지하고 중복 도구 설치를 피했다.

## 사용

설치 파일의 존재와 앱의 자동 선택은 별개다. 아래 후속 확인에서 실제 로더의 인식·활성을
확인했다. 명시적 사용 예:
`$chatbot-ops-verification 다음 예약 인덱싱의 실제 완료 여부를 읽기 전용으로 확인해줘.`
실제 조회에 필요한 실행/기준 커밋을 별도로 확인하며, 이 예문 자체로 예약 조회를 시작하지 않는다.

## 후속 보완 및 인식 확인 (2026-11-11)

사용자가 부작용 점검 후 권장 보완 순서를 승인했다. 위 최초 테스트 수는 당시 결과이며,
아래가 후속 작업의 최종 결과다.

### 판정 보완

- 시도보다 많은 번역 완료, 업데이트보다 많은 완료, complete 상태에서 시도/업데이트만
  있고 번역 완료가 없는 모순을 `unverified`로 처리한다.
- 시도 수는 청크 단위일 수 있으므로 시도와 페이지별 완료의 단순 동등 비교를 강제하지 않는다.
- 새로운 summary 필드가 추가되면 성공으로 단정하지 않는다. 미지 필드명·값은 출력하지 않는다.
- 이미 확인된 오류는 추가 불일치가 있어도 `failed`로 유지한다.
- `IndexingReport`의 필드/타입과 검증기 스키마를 AST로 비교하는 회귀를 추가했다.
  이를 위해 앱을 import하거나 `.env`를 로드하지 않는다.
- 새 반례 테스트는 수정 전 5개 하위 사례에서 실패했고 수정 후 통과했다.

### 지침과 설치본 관리

- `AGENTS.md`의 인덱서 경로, async worker, 5개 언어, 이메일 문의, 관리자 인증,
  무료 모드 키 순환 금지, 서버/Vercel/GitHub 스케줄 구분을 실제 코드에 맞게 정정했다.
  기존 한국어 응답 규칙과 UI 디자인 계약은 보존했다.
- `scripts/check_skill_install.py`를 추가했다. 소스/설치본의 누락·추가·변경을 읽기 전용으로
  확인하고 바이트코드는 제외한다. 실제 파일 차이와 설치 폴더 누락도 테스트한다.
- 설치본 변경 전 백업:
  `C:/Users/mycom/.codex/skill-backups/chatbot-ops-verification-20261111-133503/`.
  변경한 참조 문서 2개와 판정 스크립트 1개를 보존했다.
- 수정한 3개 파일만 동기화한 뒤 소스 6개 파일 모두 설치본과 일치함을 확인했다.

### 실제 인식 및 검증 범위

앱에 포함된 `codex.exe`의 공식 app-server stdio 연결에서
`initialize` → `initialized` → `skills/list`(`cwds=[D:\\coding\\chatbot]`, `forceReload=true`)만
호출했다. 새 thread/turn을 생성하거나 모델을 호출하지 않았고 진단 프로세스는 종료했다.

- 스킬 3개 모두 실제 설치 경로 `C:/Users/mycom/.codex/skills/`에서 인식.
- 각각 `enabled=true`, `scope=user`; 로드 오류 0건.
- 현재 로더가 이 경로를 지원하므로 `.agents/skills`로 이동/중복 설치하거나 설정을 변경하지 않았다.
- 이는 같은 실행파일의 새 진단 프로세스에서 로더 인식을 확인한 결과다. 현재 UI 선택기 표시나
  미래 대화에서의 암묵적 선택까지 검증한 것은 아니다.
- 최종 Python 회귀 **231개 통과**(스킬 관련 22개 포함).
- 원본/설치본 스킬 형식 검사 통과. 설치본에서도 번역 수치 모순이 거부되는 것을 실행 확인했다.
- 이번에는 UI·운영 코드·SQL·키·모델·예약 실행·배포를 변경하지 않았다. 커밋/푸시도 미실행.

공식 참고: [스킬 탐색과 선택](https://learn.chatgpt.com/docs/build-skills),
[App Server skills/list](https://learn.chatgpt.com/docs/app-server#skills).
