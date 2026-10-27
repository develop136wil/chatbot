# 보안·운영 개선 — 2026-10-27

## 변경 범위

- DOMPurify 3.2.6 → 3.4.17. marked는 15.0.12를 유지.
- 두 브라우저 라이브러리를 npm 정확한 버전 및 package-lock.json으로 관리.
  scripts/browser-vendor.cjs가 배포용 번들과 원본 라이선스를 static/vendor에 복사한다.
  --check는 파일을 쓰지 않고 설치된 잠금 버전과 바이트 단위로 대조한다.
- 외부 CDN 스크립트 대신 같은 사이트의 정적 파일을 로드한다.
  화면 디자인·캐릭터·국기·폰트·검색 프롬프트는 변경하지 않는다.
- CI에서 npm audit와 실제 Chromium HTML 정화 검사, 기존 UI 회귀 검사를 실행한다.
- Chatbot Actions는 Ubuntu 24.04 및 Python 3.11을 사용한다.
  Vercel은 지원되는 기본 버전인 Python 3.12를 .python-version에 명시한다.
  오프라인 CI는 Python 3.11/3.12 둘 다 검사한다.
- requirements.txt에 직접·전이 의존성을 모두 고정한다. requirements.lock.txt의 기준 목록과 동일해야 한다.
  초기 기준은 성공한 인덱서 실행 40416356738의 설치 목록이다.
  pip check, 전체 회귀 및 Redis·SQL 통합 CI를 통과해야 배포한다.
- 인덱싱 워크플로 제한 45분, SMTP 연결 제한 10초.
- 카테고리별 중복 메일 대신 CLI 최종 실패에 한 번 알린다.
  번역·캐시·초기화·문서 실패 및 예기치 않은 종료를 포함한다.
  메일은 상태·집계·오류 종류만 포함하고 원문/키/공급자 응답을 넣지 않는다.
- 관리자 캐시 삭제는 X-Admin-Secret 헤더만 허용한다. URL secret 파라미터는 무시한다.

## Supabase 읽기 전용 비교

진단 결과:
- 대상 프로젝트는 두 저장소 모두 vlxxxpqyvrvcwffrpvid.supabase.co.
- Chatbot Actions: JWT의 선언 역할 service_role, 조회 가능한 문서 155건.
- keeper Actions: publishable 키, 조회 가능한 문서 0건.
- JWT 역할 표시는 서명 검증 결과가 아닌 진단 힌트다. 실제 권한은 서버 응답이 결정한다.
- 이 결과는 같은 프로젝트의 접근 권한 차이를 보여준다.
  keeper에 서버 키를 복사하거나 RLS를 완화하지 않는다.
- keeper는 연결 확인 전용이다. 빈 결과를 데이터 소실이나 전체 인덱싱 완료로 해석하지 않는다.
- Chatbot 수동 진단은 인덱스가 보여야 성공한다.
  keeper 수동 진단은 연결 확인 모드로 제한된 가시성을 명시한다.
- 진단은 GET만 사용하며 키·문서 내용은 출력하지 않는다. 15초 제한, 리다이렉트 금지.
- 일회성 작업 브랜치 자동 진단 트리거는 결과 확인 후 제거한다.
- 이는 GitHub Actions 환경 비교이며 Vercel의 환경변수 값을 읽거나 바꾼 것이 아니다.

## 검증 및 남은 경계

- 로컬: Python 177개, 프런트엔드 132개, UI 319항목 및 실제 HTML 정화 브라우저 검사 통과.
- 로컬 캡처는 합성 데이터이며 운영 검색/AI 호출·통계 쓰기·메일 발송은 하지 않았다.
- 운영 인덱싱은 수동 실행하지 않는다. main 반영 후 기존 예약에서 적용된다.
- SMTP Secrets 등록은 확인했다. 실제 이메일 수신은 검증하지 않았다.
- 설치 단계 실패, 강제 취소, 작업 전체 시간 초과는 Python이 메일을 보낼 수 없을 수 있다.
  GitHub Actions 실패 알림 설정 및 실행 결과를 함께 확인해야 한다.
- 라이브러리 업데이트가 모든 XSS나 모든 의존성 취약점의 부재를 보증하는 것은 아니다.
- SQL/RLS/자격증명, 실제 검색 품질·번역 의미 정확성은 이번 변경 대상이 아니다.

## Vercel 빌드 호환 수정

- 최초 배포는 requirements.txt의 -c requirements.lock.txt 포함 단계에서 파싱 실패했다.
- 동일한 버전 목록을 requirements.txt에 평탄화해 포함 파일 처리를 제거한다.
- tests/test_requirements_contract.py가 포함 지시문 금지·정확한 버전 고정·기준 목록 일치를 검사한다.
- 패키지 버전, SQL, 키, 운영 데이터는 변경하지 않는다.

## 후속 보완

- 실패 메일 STARTTLS에 ssl.create_default_context()를 전달하여 인증서·호스트명을 검증한다.
- 인증서 검증 실패 시 로그인 및 발송을 하지 않는 회귀 테스트를 추가한다.
- python-security CI 작업에서 pip-audit 2.10.1로 고정한 requirements.txt를 검사한다.
  검사 도구는 앱과 별도 작업에 설치한다. 자동 수정·취약점 무시·실패 무시는 하지 않는다.
- node_modules 59개 파일의 Git 추적만 해제한다. 로컬 파일과 package-lock.json, 배포용 static/vendor는 보존한다.
- 실제 이메일 발송·수신과 새 코드의 예약 인덱싱 성공은 별도 확인 항목이다.
- 후속 로컬 검증: Python 181개, 프런트엔드 132개, 실제 정화 브라우저 검사 및 UI 회귀 통과.
- pip-audit 2.10.1 및 npm audit에서 알려진 취약점이 발견되지 않았다(검사 시점 기준).
- npm ci --ignore-scripts 재설치 후 배포용 라이브러리 무결성 검사도 통과했다.

## 승인된 메일 점검 경로

- Manual Alert Email Test는 workflow_dispatch와 confirm=true일 때만 실행한다. push/예약으로 실행하지 않는다.
- scripts/test_alert_email.py는 SMTP_USER 자신에게 테스트 안내만 한 번 보내며 자동 재시도하지 않는다.
- 인덱싱을 호출하지 않고 DB/AI 자격증명을 전달하지 않는다. 주소·키를 로그로 출력하지 않는다.
- 성공은 SMTP 서버의 접수 확인이며, 받은편지함 또는 스팸함 수신은 사용자가 별도 확인해야 한다.
