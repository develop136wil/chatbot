# 이용 통계와 시각화 대시보드 적용 안내

## 이번 구현과 한계

- 관리자 화면: https://chatbot-tau-bay.vercel.app/admin/analytics
- 질문 추이 선 그래프, 분야 막대, 언어 도넛, 결과·응답시간·유입·입력 방식 차트.
- 기간 선택, 일별 CSV 내보내기, 브라우저 인쇄/PDF 저장.
- 자료 원문을 누른 답변 수 / 자료를 찾은 질문 수로 원문 연결률 계산.
- 질문 원문·답변·IP·이메일은 새 통계 테이블에 저장하지 않음. 기존 Notion 로그 설정은 변경하지 않음.
- 수집 기본 비활성. ENABLE_CHAT_ANALYTICS=true이고 VERCEL_ENV=production이며 SESSION_SECRET_KEY가 있을 때만 기록.
- 운영 Supabase SQL은 사용자가 직접 적용한다. 코드 배포만으로 테이블이 생성되지 않는다.

## 1. 프로젝트부터 확인

Vercel > chatbot > Settings > Environment Variables에서 Production의 SUPABASE_URL을 확인한다.
해당 URL의 첫 부분과 Supabase 대시보드 주소의 /project/ 뒤 reference ID가 같아야 한다.
기존 운영 로그의 프로젝트는 vlxxxpqyvrvcwffrpvid였다. 현재 Production URL과 다시 대조한다.
이전에 다른 프로젝트에 SQL을 적용한 일이 있었으므로, 프로젝트 이름만 보고 판단하지 않는다.
비밀키 값은 이 대화에 붙여넣지 않는다.

## 2. 통계 테이블·함수 생성

1. 올바른 Supabase 프로젝트에서 SQL Editor > New query.
2. supabase/20260921_analytics.sql 파일 전체를 복사해 붙여넣기.
3. Run 실행. 오류가 없어야 한다. 함수 생성 SQL은 결과 행이 없을 수 있다.
4. 오류가 있으면 다음 단계로 넘어가지 않고 오류 문구만 전달한다.

이 파일은 트랜잭션으로 실행하며 동일 버전 재실행이 가능하다.
site_pages, hybrid_search_v3, 기존 응답 캐시 테이블을 변경·삭제하지 않는다.
통계 테이블은 RLS 활성화와 권한 제한을 적용해 anon/authenticated가 직접 읽거나 쓰지 못한다.
실제 요청은 서버의 Secret key 또는 기존 service_role 키로만 처리한다.

## 3. 자동 집계와 보관 기간 정리

Supabase에서 pg_cron 확장을 활성화한다. Dashboard의 Database > Extensions에서 pg_cron을 검색해 활성화하거나, Cron 설치 화면 안내를 따른다.
그다음 새 SQL 창에서 supabase/20260921_analytics_schedule.sql 전체를 실행한다.

성공 결과: jobname=chatbot-analytics-hourly, schedule=17 * * * *, active=true.
매시간 17분에 통계 집계와 보관 기간 정리를 수행한다.
같은 이름으로 재실행하면 동일 작업의 설정을 갱신한다.
이 스케줄은 GitHub Actions가 아니며 Notion 인덱싱을 실행하지 않는다.

보관 정책:
- 상세 요청 기록: 한국 날짜 기준 최근 90일.
- 일별 집계: 최근 730일.
- 상세 기록은 집계가 생성된 후에만 자동 삭제한다. 삭제된 상세 내역은 집계로 복원할 수 없다.
- 검색 문서·응답 캐시는 이 작업의 삭제 대상이 아니다.
- cron 실행 기록 자체의 용량도 Supabase에서 정기적으로 확인한다.
- 대시보드 조회 시에도 변경된 날짜를 집계하지만, 대시보드를 열지 않아도 정리되도록 예약 설정이 필요하다.

공식 참고: https://supabase.com/docs/guides/cron/quickstart

## 4. 적용 결과 확인

SQL Editor에서 supabase/20260921_analytics_verify.sql 전체 실행:
- requests_table / daily_table에 테이블 이름 표시.
- anon_read_must_be_false=false.
- anon_report_must_be_false=false.
- server_report_must_be_true=true.
- recorded_requests=0은 아직 수집 전이면 정상.
- 예약 작업 active=true.

## 5. Vercel에서 수집 활성화

chatbot > Settings > Environment Variables에 다음을 등록한다.

ENABLE_CHAT_ANALYTICS=true

Environment는 Production만 선택한다. Preview는 자동으로 수집 제외된다.
기존 SUPABASE_URL, SUPABASE_KEY, SESSION_SECRET_KEY, ADMIN_SECRET_KEY를 사용한다.
통계 전용 서버 키가 필요한 경우에만 SUPABASE_ANALYTICS_KEY를 별도로 설정한다.
anon/publishable 키는 사용할 수 없다. 기존 키를 불필요하게 다시 교체하지 않는다.

저장 후 최신 코드의 Production 배포를 Redeploy한다.
환경변수 추가만으로 기존 배포에 적용되지는 않는다.

## 6. 관리자 차트 확인

1. /admin/analytics 접속.
2. ADMIN_SECRET_KEY 입력. Supabase Secret key가 아니라 기존 앱 관리자 키다.
3. 수집 활성 표시와 DB 호스트 확인.
4. 처음에는 차트가 비어 있는 것이 정상. 예시 데이터는 운영 화면에 넣지 않는다.
5. 챗봇에서 새 질문 1건, 같은 질문 재입력 1건, 원문 보기 1회, 더 보기 1회를 수행.
6. 관리자 화면에서 해당 한국 날짜를 포함해 조회.
   새 질문 2건, 더 보기 1건으로 구분되는지 확인한다. 같은 요청의 통신 재전송은 새 질문으로 세지 않는다.
   원문 클릭은 카드별 합계가 아니라 답변별 최초 클릭으로 집계된다.
7. 요청 결과와 원시 기록·일별 합계가 일치하는지 확인한 후 업무 실적에 활용한다.

실제 방문자와 구분할 수 없는 운영 테스트는 통계에 포함된다.
초기 검증일을 보고 기간에서 제외하거나 검증 건수를 별도로 밝힌다. 임의로 실적을 부풀리거나 누락 기록을 추정 복원하지 않는다.

## 7. 유입 경로를 구분하는 링크

기관 홈페이지:
https://chatbot-tau-bay.vercel.app/?utm_source=website

QR 안내:
https://chatbot-tau-bay.vercel.app/?utm_source=qr

협력 기관:
https://chatbot-tau-bay.vercel.app/?utm_source=partner

일반 링크는 직접/출처 없음, 허용 목록 외 값은 미상으로 집계한다.
전체 접속 URL이나 다른 쿼리 매개변수는 통계에 저장하지 않는다.
이 값은 브라우저가 제공하므로 정확한 방문자 출처를 보증하지 않는다.

## 8. 지표 해석과 신뢰성

- 신규 요청 ID는 한 번 입력한 질문마다 발급. 같은 문장 재입력은 새 이용 요청.
- 동일 요청 ID의 재시도는 1건으로 묶고 재시도 횟수를 별도로 보관. 최종 성공 시 앞선 오류 상태를 대체.
- 동시에 완료된 오래된 재시도가 최신 결과를 덮지 않도록 attempt ID 확인.
- 더 보기·인사·초기화·범위 밖 응답은 질문 수에서 제외.
- 검색 실패는 HTTP 200이어도 통계에서는 오류로 기록.
- 요청 접수와 완료를 각각 DB에서 확인한다. fire-and-forget으로 성공을 가정하지 않는다.
- 시작 기록 실패는 서버 경고, 시작 후 완료 기록 실패는 pending으로 확인 가능.
- API 요청당 통계 저장 최대 대기 1.5초씩 최대 두 번. 실제 지연을 점검한 뒤 조정할 수 있다.
- 통계 장애는 답변을 막지 않는다. 이 선택 때문에 전체 요청의 100% 수집을 보장하지 않는다.
- 현재 인스턴스 저장 실패 카운터는 재시작 시 초기화되므로 전체 누락률이 아니다.
- 요청 형식 오류·HTTP 속도 제한·서버 미도달·브라우저 클릭 전달 실패는 완전 측정하지 못한다.
- 수집 시작 전의 과거 기록은 자동으로 채워지지 않는다. 기록 없는 날은 0건으로 단정하지 않고 차트 단절·표의 대시·CSV 빈칸으로 표시한다.
- 분야는 기존 의도 분석과 안내 카드 분류를 사용한다. 복합·미분류 포함, 추가 AI 호출 없음.
- 언어는 선택 언어이지 국적이 아니다. 세션은 임시 구분이지 고유 사람 수가 아니다.
- 일별 세션을 합산한 값은 기간 전체의 고유 세션 수가 아니다.
- 응답시간 차트는 성공한 답변의 서버 처리시간 구간이다. 브라우저 렌더·통계 완료 저장 시간은 포함하지 않는다.
- 캐시/신규 검색을 구분하며, 일별 백분위 평균을 전체 백분위라고 표시하지 않는다.
- 원문 연결은 신청·지원 수혜·문제 해결·만족도와 다르다.

## 9. 장애 대응과 용량

- 통계만 끄기: ENABLE_CHAT_ANALYTICS=false로 바꾸고 Redeploy. 검색 기능은 유지된다.
- 401: 관리자 키가 맞는지 확인. URL 쿼리에 키를 넣지 않는다.
- 503: 올바른 프로젝트의 SQL·SUPABASE_URL/서버 키 조합 확인. 오류 응답에 비밀키는 표시하지 않는다.
- 미완료 누적: Vercel의 [Analytics] storage_failed 로그와 작업 처리 오류를 함께 확인.
- 상세 통계 테이블+인덱스 50MB를 넘으면 신규 수집을 중단해 공유 DB를 보호한다.
  이 제한은 프로젝트 전체 용량 보장이 아니다. Supabase의 전체 DB 크기·여유 공간도 확인한다.
- 관리자 키는 페이지 메모리에서만 사용하며 새로고침/잠금 시 다시 입력한다.
- 전체 보고서는 관리자 화면에서만 확인하고, 외부 공유에는 기간과 집계만 내보낸다.

자동 정리를 잠시 멈춰야 한다면 Cron 화면에서 chatbot-analytics-hourly만 비활성화한다.
다른 작업이나 기존 검색 테이블을 삭제하지 않는다.

## 검증 내역

- 오프라인 Python 130개, 프런트엔드 106개와 대시보드 집계 테스트 3개 통과.
- 실제 임시 PostgreSQL에서 SQL 재적용·권한·중복·재시도·클릭·보관 기간 등 8개 통과.
- 실제 Redis 통합 테스트 6개 통과.
- 로컬 Chromium에서 관리자 로그인, 데스크톱/375px 모바일 차트, 가로 넘침, CSV, 잠금 검증.
- 브라우저 검증은 명시적으로 표시한 합성 데이터이며 운영 실적이 아니다.
- 운영 SQL 적용과 실제 데이터 수집 검증은 사용자의 적용 이후에 확인해야 한다.
