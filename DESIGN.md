---
version: alpha
name: Dobong Child Welfare Chatbot
description: 기존 캐릭터와 밝은 글라스 UI를 보존하는 모바일 복지정보 안내 서비스
colors:
  primary: "#101828"
  secondary: "#667085"
  surface: "#FFFFFF"
  assistant: "#F2F4F7"
  user: "#FFF4C9"
  accent: "#FDB022"
  card-border: "#E4E7EC"
  action-text: "#344054"
  more-background: "#EAECF0"
  more-hover: "#DDE2E8"
  more-border: "#CBD2DC"
  divider: "#DDE2E8"
  focus: "#175CD3"
typography:
  title:
    fontFamily: "ONE Mobile POP, sans-serif"
    fontSize: 20px
    fontWeight: 400
  body:
    fontFamily: "SF Pro, Pretendard, sans-serif"
    fontSize: 15px
    lineHeight: 1.65
  mobile-body:
    fontFamily: "SF Pro, Pretendard, sans-serif"
    fontSize: 14px
    lineHeight: 1.65
  action:
    fontFamily: "SF Pro, Pretendard, sans-serif"
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.4
  caption:
    fontFamily: "SF Pro, Pretendard, sans-serif"
    fontSize: 13px
    lineHeight: 1.6
  tip:
    fontFamily: "SF Pro, Pretendard, sans-serif"
    fontSize: 12px
    lineHeight: 1.6
rounded:
  bubble: 18px
  card: 16px
  mobile-card: 12px
  compact-button: 16px
spacing:
  welcome-paragraph: 6px
  small: 8px
  action-gap: 12px
  page: 16px
components:
  chat:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    width: 600px
  assistant:
    backgroundColor: "{colors.assistant}"
    textColor: "{colors.primary}"
    typography: "{typography.body}"
    rounded: "{rounded.bubble}"
  user:
    backgroundColor: "{colors.user}"
    textColor: "{colors.primary}"
  result-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    rounded: "{rounded.card}"
    padding: 14px
  result-more:
    backgroundColor: "{colors.more-background}"
    textColor: "{colors.action-text}"
    typography: "{typography.action}"
    rounded: "{rounded.compact-button}"
  result-more-hover:
    backgroundColor: "{colors.more-hover}"
    textColor: "{colors.action-text}"
  loading-tip:
    backgroundColor: "{colors.assistant}"
    textColor: "{colors.secondary}"
    typography: "{typography.tip}"
---

# 도봉구 영유아 복지정보자료집 디자인 기준

## Overview

아이를 돌보는 보호자가 휴대전화에서 지원 내용을 읽고 원문으로 이동하는 작은 상담 창이다.
캐릭터의 친근함, 크림색 사용자 말풍선, 흰 결과 카드와 서리 낀 제목 영역이 기존 정체성이다.
새 랜딩페이지나 대시보드 스타일을 이 채팅 화면에 덮어씌우지 않는다.

이 문서는 기존 코드와 사용자가 선택한 방향을 정리한 기준이지 자동 생성된 새 테마가 아니다.
사용자의 새 명시적 요청이 우선한다. 의도한 변경은 이 문서와 회귀 테스트도 함께 갱신한다.
사용자가 마음에 들어 한 요소를 일반적인 외부 스킬 권고만으로 제거하지 않는다.

적용 범위: static/index.html, static/ui-text.js, static/script.js, static/style.css.
통계 대시보드는 별도 화면이며 기존 차트·지표·인증·수집 로직을 이 기준으로 개편하지 않는다.

## Colors

- 밝은 모드만 제공한다. 운영체제의 다크 모드로 자동 전환하지 않는다.
- 본문은 primary, 보조 안내와 로딩 팁은 secondary를 사용한다.
- 사용자 말풍선은 user, 답변 말풍선은 assistant, 결과 카드는 surface를 사용한다.
- '결과 더 보기'는 회색 보조 버튼이다. 노란 강조색으로 되돌리거나 전체 너비로 확장하지 않는다.
- 원문 이동이 핵심 행동이고 결과 이어보기와 문의는 보조 행동이다.
- 일반 텍스트는 실제 합성 배경에서 대비 4.5:1 이상을 목표로 검증한다.
- 옅은 선은 장식적 구분용이며, 선의 색만으로 상태나 조작 가능 여부를 전달하지 않는다.
- 글라스 영역은 rgba(240, 242, 245, 0.70)이며 blur(10px)를 유지한다.
  투명 배경 위 대비는 단일 색상 토큰 검사만으로 보증하지 않는다.

## Typography

- 제목: ONE Mobile POP. 본문: SF Pro, Pretendard, 시스템 sans-serif 폴백.
- 제목은 일반 20px, 390px 이하에서 18px. 말풍선은 일반 15px, 576px 이하에서 14px.
- 카드·배지의 기존 크기 체계를 유지한다. 외부 가이드의 '본문 16px'을 일괄 강제하지 않는다.
  작은 본문의 실제 사용자 가독성 검증은 별도로 남겨 둔다.
- 입력창은 모바일 16px을 유지한다. 로딩 진행 문구 14px, 팁 12px을 임의 확대하지 않는다.
- 로컬 폰트는 font-display: swap으로 첫 글자가 폰트 다운로드를 기다리지 않게 한다.
- 한국어·영어·베트남어·중국어 모두 자연스럽게 줄바꿈한다.
  긴 단어·URL은 필요할 때만 끊으며 일반 문장에 word-break: break-all을 적용하지 않는다.
- 제목, 스플래시, 브라우저 제목의 서비스 이름을 일치시킨다.

## Layout

- 채팅 컨테이너는 화면 너비 100%, 최대 600px. 문서 전체 가로 스크롤을 만들지 않는다.
- 오른쪽 국기 영역 60px을 확보하여 카드 내용을 가리지 않게 한다.
- 제목 높이와 입력창·추천 질문 영역 높이를 측정한 CSS 변수로 스크롤 여백을 확보한다.
- 키보드 포커스는 제목·하단 고정 영역 밖에 보이게 보정하되 포인터로 읽는 사람의 스크롤은 유지한다.
- 추천 질문은 기존 가로 스크롤 방식을 유지한다. 문서 전체 가로 스크롤과 구분한다.
  마지막 질문도 키보드/터치로 접근 가능해야 하며 접힌 질문에는 포커스가 들어가지 않아야 한다.
- 작은 화면 320/390px, 태블릿 768px, 데스크톱 1280px, 가로 화면 812×375px에서 확인한다.
- 주요 본문·안내·액션의 200% 텍스트 확대와 실제 모바일 키보드는 별도로 점검한다.
- 최초 안내는 기능·질문 방법·작은 개인정보 주의의 3개 문장 그룹으로 구성한다. 통계 고지는 말풍선 밖 11px 보조 글씨로 둔다.
  안내문 사이 과도한 빈 줄과 최초 화면의 문의 메뉴를 다시 추가하지 않는다.

## Elevation & Depth

- 제목과 국기 등 기존 고정 UI의 글라스 효과를 보존한다.
- 결과 카드 내부는 불투명한 흰 배경으로 읽기 쉽게 유지한다.
- 새 강한 그림자, 네온, 그라데이션, 대형 유리 패널을 도입하지 않는다.
- 반투명 영역 위에서 글자가 읽히는지는 실제 스크린샷으로 확인한다.

## Shapes

- 말풍선 18px, 카드 일반 16px/모바일 12px, 보조 버튼 16px 둥근 모서리를 유지한다.
- 결과 더 보기의 시각적 크기는 13px 글씨, 최소 높이 32px, 내용 너비를 기준으로 한다.
- 웹 클릭 영역은 최소 24×24 CSS px을 확인한다. 44px 확대는 개선 목표이지
  네이티브 앱 단위를 웹에 그대로 적용하는 자동 변경 규칙이 아니다.
- 인접 클릭 영역과 겹치는 투명 터치 영역을 만들어 크기만 충족시키지 않는다.

## Components

### 첫 안내

'도봉구 영유아 복지정보를 찾아드려요.'와 질문 방법, 개인정보 입력 주의를 제공한다. 예시는 입력창과 추천 질문으로 제공한다.
문의·불편 신고는 첫 안내에 없다. 네 언어의 의미와 문장 그룹 수를 일치시킨다.
통계 고지는 말풍선 아래 별도 표시하고, 최종 지원 여부 확인은 첫 안내에서 빼고 실제 결과의 원문 확인 안내로 제공한다.
유효한 요청 시작 시 추천 질문을 자동으로 접되 수동으로 다시 펼칠 수 있다.
문의는 짧은 이메일 링크·테두리 없는 복사 버튼·선택 가능한 주소만 표시한다. 대화 내용을 메일에 자동 첨부하지 않는다.

### 결과와 보조 행동

순서: 결과 카드 → 원문 확인 안내 → 결과 더 보기(남은 결과가 있을 때만) → 옅은 선 → 문의.
문의는 완료 답변/오류 안내에 접힌 details 형태로 표시한다.
버튼 명칭은 '결과 더 보기 / More results / Xem thêm kết quả / 查看更多结果'.
명칭 변경 후에도 action=more와 기존 결과 ID·커서를 보존해야 한다.
자료 수정 날짜를 다시 노출하지 않는다. 원문의 금액·대상·조건을 디자인 목적으로 바꾸지 않는다.

### 캐릭터·언어 선택

기존 header-icon.png, bot-icon.png와 네 국기 SVG를 보존한다.
제목 옆·답변 옆 캐릭터는 장식으로 접근성 트리에서 제외한다.
국기 버튼은 언어 이름과 선택 상태를 제공한다. 국적에 따른 사람 수로 통계를 해석하지 않는다.
추천 질문의 기존 이모지 역시 전면 교체하지 않는다.

### 로딩과 오류

3줄 스켈레톤과 육아 팁을 유지하고 AI를 추가 호출해 팁을 만들지 않는다.
일반 모드에서는 7초 간격으로 바로 같은 팁을 반복하지 않는다.
동작 줄이기에서는 처음 선택한 팁을 고정하고 카드 등장 애니메이션을 생략한다.
완료·실패·취소 시 타이머와 설정 변경 리스너를 정리한다.
오류와 '검색 결과 없음'을 같은 상태로 표시하지 않는다. 수동 재시도와 문의를 유지한다.

## Do's and Don'ts

- 변경 전에 이 문서와 해당 화면의 기존 테스트를 읽는다.
- 새 UI 스킬은 참고자료이며 사용자 선택과 이 저장소 규칙을 덮어쓰지 않는다.
- 외부 예시의 React/Tailwind·GSAP를 도입하지 않는다. 현재는 HTML/CSS/JavaScript이다.
- 검색·랭킹·캐시·Supabase·Notion·무료 AI 제한·통계 집계를 UI 정리와 함께 바꾸지 않는다.
- 테스트는 로컬 합성 데이터로 실행한다. 운영 질문이나 문의 메일을 자동 발송하지 않는다.
- 명시적 지시 없이 외부 스킬을 전역 설치하거나 운영 배포하지 않는다.
- '접근성 완벽 호환'이라고 선언하지 않는다. 자동 검증/실제 기기/사용자 평가 범위를 구분한다.

참고 규격: [Google DESIGN.md](https://github.com/google-labs-code/design.md/blob/9bf8eae67128b6cc55ad9bf86665767deb4c11cd/docs/spec.md).
검토 기준: [UI/UX Pro Max quick reference](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/0d2b646cb6f48d8478f41417b2e8a5a30fd59175/.claude/skills/ui-ux-pro-max/references/quick-reference.md).
외부 패키지/스킬을 설치하거나 디자인 시스템 생성기를 실행한 것이 아니라, 위 문서와 현재 코드를 대조했다.
