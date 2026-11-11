# 예약 인덱싱 확인

1. 사용자가 지정한 기준 커밋, workflow, 이벤트, 시점을 기록한다.
   기본 workflow는 `.github/workflows/daily_indexing.yml`의 Daily Content Indexing이다.
   예약 확인 요청에는 `schedule` 실행만 사용한다. 수동 실행을 예약 검증으로 대체하지 않는다.
2. 실행의 `head_sha`가 기준과 같거나 이를 포함하는지 Git 이력/API로 확인한다.
   최신 실행이라는 이유만으로 새 코드 검증으로 취급하지 않는다.
3. 실행 상태·결론과 해당 실행 attempt의 실제 로그를 함께 확인한다. 아직 없거나 진행 중이면
   미완료이지 실패가 아니다. 이전 실행 성공을 재사용하지 않는다.
4. 실제 `[Indexer Summary]`에서 아래 모든 필드를 읽는다. 잘린 로그·필드 누락·서로 다른
   실행이 섞인 로그는 미확인으로 처리한다. 키나 원문이 섞인 전체 로그를 보고서에 복사하지 않는다.

필수 필드:

- `status`, `discovered`, `updated`, `skipped`, `deleted`
- `failed_pages`, `failed_categories`, `failed_deletions`
- `translations_attempted`, `translations_completed`, `translations_pending`,
  `translations_failed`, `translations_deferred`
- `cache_refresh_failed`, `cache_marker_failures`, `cleanup_failed`, `setup_failed`

현재 상태 정의는 `run_indexer.py`의 `IndexingReport`와 `finish_indexing`에서 확인한다.
오류가 없어도 처리량 제한에 의한 `in_progress`와 번역 보류는 전체 완료가 아니다.
실패·캐시 오류가 있으면 Actions 결론이 성공이어도 성공 보고하지 않는다.
오래된 `incomplete` 등 다른 스키마는 실행 커밋의 코드를 읽고 별도로 판정한다.

## 로컬 판정 보조 도구

이 스킬의 `scripts/check_indexer_summary.py`는 표준 라이브러리만 사용하며 네트워크,
앱 모듈 import, `.env` 로드, 파일 쓰기를 하지 않는다. 파일은 직접 제공된 로컬 파일만 읽는다.
정제된 JSON 객체 하나 또는 `[Indexer Summary]` 한 줄이 있는 단일 실행 로그를 입력한다.

```powershell
python -X utf8 <skill-folder>/scripts/check_indexer_summary.py <local-summary-file>
```

- 종료 코드 0: summary 수치가 complete 조건 충족, 1: failed/in_progress, 2: 검증 불가.
- 여러 summary가 있으면 임의로 마지막 것을 고르지 않는다. 실행/attempt를 확인해 분리한다.
- 도구는 실행 링크·커밋 계보·이벤트·Actions 결론을 검증하지 않는다. 이 항목은 별도 확인해야 한다.
- 원본 필드 중 허용한 수치와 상태만 출력한다. 추가 필드에 든 질문/키는 출력하지 않는다.
- 모르는 필드가 추가되면 성공을 확정하지 않는다. 실행 커밋의 스키마와 의미를 확인한다.
- 번역 완료가 시도/업데이트보다 많거나, complete인데 시도·업데이트만 있고 번역 완료가
  없으면 미확인으로 처리한다. 시도는 청크별, 완료·업데이트는 페이지별일 수 있어 단순히
  시도 수와 완료 수가 같아야 한다고 가정하지 않는다. 명백한 오류는 미확인보다 우선한다.
- `tests/test_ops_skill.py`는 앱을 import하지 않고 `IndexingReport`의 필드/타입을 비교한다.
  현재 코드의 summary 스키마가 바뀌면 이 검사와 보조 도구의 가정을 함께 재검토한다.

## 해석의 한계

- 직전 문서 수와 증감을 비교하되 155건 등 특정 수를 고정 합격 기준으로 쓰지 않는다.
  합법적인 추가·삭제는 설명하고, 카테고리 조회 실패 시 discovered를 전체 문서 수라고 하지 않는다.
- 번역 보류는 updated와 겹칠 수 있으므로 단순 합산하지 않는다.
- 모든 문서를 건너뛰었다면 예약 실행 및 기존 상태 확인만 검증한 것이다.
  새 번역 생성·금액/월령 보존·원어민 문체까지 검증했다고 하지 않는다.
- complete라도 문서 0건이면 직전 기준·조회 범위와 비교해 이유를 확인하기 전 운영 정상이라고 하지 않는다.
- 실패·취소·시간 초과·접근 불가 시 근거와 못 본 범위를 보고한다. 무단 재실행은 하지 않는다.
