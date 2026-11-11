# Gemini 생성 모델 전환 검증 (2026-11-11)

## 범위와 상태

로컬 코드 전환 및 아래에 명시한 실제 Gemini 7회 검사를 수행했다. Groq 호출,
운영 DB 쓰기, 인덱싱 실행, 키 변경은 하지 않았다. 이 문서 자체는 Production 배포 완료의
증거가 아니며, 배포 상태는 해당 커밋의 CI/배포 결과에서 별도로 확인한다.

- 생성 모델 기본값: `gemini-3.5-flash-lite` (`GEMINI_GENERATION_MODEL`).
- Gemini 3.5 Flash-Lite의 동기/비동기/번역 호출에 공통 설정을 사용한다.
- `temperature`, `top_p`, `top_k`, `candidate_count`를 전송하지 않는다.
- `thinking_budget=0` 대신 `thinking_level=minimal`을 사용하고 자동 함수 호출을 끈다.
- 일반 무료 출력 상한 400(설정 가능, 최대 1024)은 유지한다.
- 문서 번역 상한은 별도 `FREE_TIER_TRANSLATION_MAX_OUTPUT_TOKENS=4096`
  (설정 범위 1024~8192)이다. 이전에는 번역 요청도 일반 출력 상한(기본 400)에 제한됐다.
- 번역의 1회 네트워크 시도/40초 제한, 호출자 재시도 예산, MAX_TOKENS 거부,
  불완전 JSON 거부, 한도 오류 시 공급자 중단은 유지한다.
- 잘못된 순위 번호(음수/중복/문자열/불리언/범위 초과)는 기존 검색 순서로 되돌린다.
  클라이언트 부재 시에도 상위 5개 밖의 검색 결과를 버리지 않는다.
- Groq 모델, 임베딩 모델/768차원, DB/SQL, 캐시 버전, 통계, UI는 변경하지 않는다.

## 근거

- [공식 전환 일정](https://aistudio.google.com/docs/deprecations#gemini-2.5-flash-models):
  2026-12-01부터 기존 2.5 Flash 요청이 3.5 Flash-Lite로 자동 연결될 예정.
- [이전 안내](https://aistudio.google.com/docs/whats-new-gemini-3.6#migrate-to-gemini-3-5-flash-lite):
  모델 ID, 샘플링 옵션 제거, minimal 사고 수준.
- 사용자 제공 AI Studio PDF의 `chatbotproject5` 무료 한도:
  2.5 Flash 5 RPM/20 RPD, 3.5 Flash-Lite 15 RPM/500 RPD.
  Production 키 소속과 동일한지는 아직 확인하지 않았다. 계정별 한도는 변동 가능하다.

## 오프라인 검증

최종 결과: Python 209개(전환 검사 12개 및 실제 검사 도구 안전장치 5개 포함),
프런트엔드/통계 JavaScript 132개 모두 통과.
`git diff --check` 통과. 실제 브라우저/Redis/PostgreSQL 통합 검사는 이번에 재실행하지 않았다.

신규 회귀 테스트는 수정 전 모델 하드코딩/미분리 상한/잘못된 순위에서 실패했다.
수정 후 새 설정, 무료 한도 초과의 Groq 단일 대체/예외, 번역 상한 및 순위 보존을 검사한다.

`google-genai==2.33.0` 실제 SDK에 HTTPX MockTransport를 연결하여 동기/비동기/
번역 요청 3개의 직렬화와 응답 파싱도 검사한다. 네트워크나 실제 API 키를 사용하지 않는다.
SDK가 `thinking_level`을 그대로 직렬화하는 경우도 있다. ProtoJSON 규격상 원래 필드명과
lowerCamelCase 둘 다 허용되므로 테스트는 두 표기를 허용하되 MINIMAL 값과 예산 필드 부재를 확인한다.
[ProtoJSON 필드명 규칙](https://protobuf.dev/programming-guides/json/)

실행 명령:

```powershell
.\.venv-ops-20261027\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_*.py'
node --test tests/frontend.test.cjs tests/analytics_dashboard.test.cjs
git diff --check
```

로컬 Python은 3.14이며 CI의 Python 3.11/3.12 실행을 대체하지 않는다.
기존 의존성의 Python/Starlette deprecation 경고는 남아 있다. 이번 변경에서 의존성을 교체하지 않는다.

## 배포 전 남은 확인

1. 실제 Production Gemini 키가 무료 프로젝트 소속인지 확인한다. 키 값은 출력/공유하지 않는다.
2. 승인된 소량의 실제 호출로 새 모델의 의도 분석/검색 순위/5개 언어와 번역을 검증한다.
   HTTP 200 또는 JSON 파싱만으로 품질 합격 처리하지 않고 금액·월령·거주 조건·누락을 비교한다.
3. GitHub CI 및 배포 확인. SQL 적용/전체 재인덱싱은 필요하지 않다.
4. 새 환경변수는 기본값이 있으므로 필수 추가는 아니다. 기존에 같은 이름으로 지정된 값이
   있다면 배포 전 확인한다. 현재 설정은 3.5 Flash-Lite만 대상으로 검증했으므로 다른 모델
   이름만 넣어 되돌리는 방식은 사용하지 않는다.
5. 운영 캐시는 그대로 유지한다. 새 모델 검증에는 캐시가 없는 가상 질문을 사용하고
   운영 통계/캐시에 테스트 데이터를 저장하지 않는다.

`FREE_TIER_ONLY`와 토큰 상한은 공급자 결제 상태나 총 요청량을 보장하지 않는다.

## 실제 검사 결과 (2026-11-11, 7회)

사용자가 다음 작업을 승인하고 무료 계정만 사용한다고 확인했다. 다만 PDF 프로젝트와
Production/로컬 키의 동일성은 확인하지 못했다. 기존 로컬 설정의 첫 번째 Gemini 키만 사용했다.
`scripts/gemini_migration_probe.py --live`는 명시적 실행만 허용한다. 공급자/모델/경로를 고정하고
HTTP 전송 단계에서 총 7회 및 단계별 1회를 제한한다. SDK 재시도/키 순환/다른 공급자
호출/DB·Redis·캐시·통계 연결을 막으며 오류가 나면 중단한다. 이 제한은 운영 코드가 아닌 검사 전용이다.

| 검사 | 실제 호출 | 확인 결과 |
|---|---:|---|
| 한국어·영어·베트남어·중국어·일본어 의도 분석 | 5 | 모두 24개월과 아동수당 검색 의도를 파악 |
| 가상 6개 문서 순위 | 1 | 해당 24~35개월 양육지원 문서를 첫 번째로 선택, 6개 모두 보존 |
| 가상 한국어 문서 → en/vi/zh/ja | 1 | 4개 언어의 제목·본문 모두 반환, JSON 완결 |

모든 HTTP 응답은 200, `modelVersion=gemini-3.5-flash-lite`, `finishReason=STOP`이었다.
429/잘림/추가 전송은 없었다. 번역 본문을 직접 대조해 도봉구 거주 조건, 24~35개월,
월 123,456원, 신청비 0원, 36개월 이상 제외, 2026-11-01~2026-11-30 기간이 모두 보존됨을 확인했다.
중국어는 날짜를 년·월·일로, 베트남어는 일-월-년으로 표시했으나 의미는 동일했다.
이는 소량의 가상 자료 검사이지 실제 정책 정확성·모든 질문·원어민 수준 문체 보장은 아니다.

### 발견 후 보완한 문제

영어/베트남어/중국어 의도 결과가 각각 `childcare`, `trợ cấp trẻ em`, `아동수당`을
카테고리로 반환했다. 모두 DB의 정확한 카테고리명이 아니다. 기존 전체 검색 fallback이 있으나
불필요한 1차 검색을 만들 수 있어 다음을 보완했다.

- 프롬프트에 실제 5개 한국어 카테고리를 명시하고 특정 서비스명은 JSON null로 요청한다.
- 반환 카테고리는 실제 DB 카테고리 목록과 대조하여 알 수 없는 값은 null로 정규화한다.
- 관측 응답과 잘못된 타입/문자열 null을 오프라인으로 재현하고 정상 카테고리는 유지한다.
- 테스트는 수정 전 10개 하위 사례에서 실패했고 수정 후 전체 209개가 통과했다.

7회 예산을 지키기 위해 이 보완 뒤 실제 API를 추가 호출하지 않았다. 따라서 새 프롬프트의
추가 실측은 미실시이며, 관측된 응답을 안전하게 정규화하는 로직은 오프라인으로 검증했다.
다음 명시적 검사에서는 특정 아동수당 질문에 category=null인지도 합격 조건에 포함한다.
