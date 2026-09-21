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
    fontFamily: "Pretendard, SF Pro, sans-serif"
    fontSize: 15px
    fontWeight: 600
  body:
    fontFamily: "Pretendard, SF Pro, sans-serif"
    fontSize: 15px
    lineHeight: 1.65
  mobile-body:
    fontFamily: "Pretendard, SF Pro, sans-serif"
    fontSize: 14px
    lineHeight: 1.65
  action:
    fontFamily: "Pretendard, SF Pro, sans-serif"
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.4
  caption:
    fontFamily: "Pretendard, SF Pro, sans-serif"
    fontSize: 13px
    lineHeight: 1.6
  tip:
    fontFamily: "Pretendard, SF Pro, sans-serif"
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
- 국기 글라스는 rgba(240, 242, 245, 0.70)·blur(10px)이다. 상단 배경은 rgba(249,250,251,.98)·blur(10px)이며 위 65%는 제목 가독성을 위해 유지하고 아래 35%에서 완전히 투명해진다.
  투명 배경 위 대비는 단일 색상 토큰 검사만으로 보증하지 않는다.

## Typography

- 사용자 요청으로 ONE Mobile POP의 사용 선언과 프리로드를 제거했다. 제목·본문은 Pretendard 우선, SF Pro와 시스템 sans-serif 폴백이다. 기존 폰트 파일은 참조 없이 보관한다.
- 상단 서비스명은 15px·600, 왼쪽 정렬. 첫 안내 제목은 24px. 말풍선은 일반 15px, 576px 이하에서 14px.
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
- 상단은 기본 높이 50px, 텍스트 서비스명만으로 식별을 보조한다. 이름과 글라스를 유지하고 스크롤 자동 숨김은 사용하지 않는다. 긴 번역이나 글자 확대 시 높이 증가를 허용하여 자르지 않는다.
- 제목 높이와 입력창·추천 질문 영역 높이를 측정한 CSS 변수로 스크롤 여백을 확보한다.
- 키보드 포커스는 제목·하단 고정 영역 밖에 보이게 보정하되 포인터로 읽는 사람의 스크롤은 유지한다.
- 추천 질문은 기존 가로 스크롤 방식을 유지한다. 문서 전체 가로 스크롤과 구분한다.
  마지막 질문도 키보드/터치로 접근 가능해야 하며 접힌 질문에는 포커스가 들어가지 않아야 한다.
- 작은 화면 320/390px, 태블릿 768px, 데스크톱 1280px, 가로 화면 812×375px에서 확인한다.
- 주요 본문·안내·액션의 200% 텍스트 확대와 실제 모바일 키보드는 별도로 점검한다.
- 최초 안내는 회색 말풍선이 아닌 배경 없는 시작 영역으로 구성한다. 24px·800 굵기 제목·12px 설명·11px 통계 펼침 메뉴를 사용한다.
  안내문 사이 과도한 빈 줄과 최초 화면의 문의 메뉴를 다시 추가하지 않는다.

## Elevation & Depth

- 제목의 글라스는 별도 배경 레이어에만 적용하고 아래로 갈수록 완전히 투명해진다. 하단 경계선은 없으며 제목·국기는 흐려지지 않는다. 국기의 글라스 효과는 보존한다.
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

'우리 아이에게' 다음 줄에 '필요한 지원을 찾아보세요'를 표시한다. 첫 안내 제목은 Pretendard 우선 24px·800 굵기이며 인위적인 획 보강은 적용하지 않는다. 답변 본문의 글자 크기는 유지한다.
한국어 시작 설명은 '아동수당부터 발달검사 등,' 뒤에서 지정 줄바꿈한다. 제목 줄 높이는 1.15(27.6px), 설명 줄 높이는 1.35(16.2px), 제목과의 간격은 10px이다. 검색 결과·금액·주소의 쉼표에는 자동 줄바꿈을 적용하지 않는다.
첫 안내의 별도 위쪽 margin/padding은 0으로 두어 첫 국기 버튼과 시작 높이를 가깝게 맞춘다. 좌측 시작은 채팅창 기준 24px로 모든 화면에서 통일한다. 채팅 영역의 상단 안전 여백과 국기 오른쪽 공간은 유지한다.
첫 안내에는 캐릭터를 중복 표시하지 않는다. 상단 캐릭터는 사용자 요청으로 제거하고 답변 캐릭터는 유지한다. 개인정보 주의는 입력창 아래 10px로 두고 textarea의 aria-describedby로 연결한다.
통계 고지는 시작 영역의 '정보 수집 안내' details에 기본 접힘으로 표시한다. 내용은 통계에 한정하여 질문 원문 미저장을 설명한다.
문의는 시작 영역에 없다. 실제 결과의 원문 확인 안내는 유지한다.
유효한 요청 시작 시 추천 질문을 자동으로 접되 수동으로 다시 펼칠 수 있다.
입력 컨트롤은 하나의 밝고 둥근 테두리 안에 배치한다. 바깥 하단 영역은 투명하며 전체 블러/경계선은 없다. 개인정보 안내와 입력 필드 간격은 2px이다. 입력 시 마이크/전송 버튼까지 감싸는 1px 베이지 테두리(#A17B45)와 옅은 후광을 표시한다. textarea의 개별 파란 링은 제거하되 키보드 버튼 포커스와 강제 색상 모드 표시는 유지한다. 하단 영역의 실측 높이와 추천 질문/스크롤 여백의 연동을 유지한다.

### 결과와 보조 행동

답변 안: 결과 카드 → 원문 확인 안내 → 수평선 → 결과 더 보기(남은 결과가 있을 때만). 더 보기 영역은 위 여백 16px, 구분선 아래 16px, 버튼 아래 추가 12px로 답변 바닥과의 간격을 확보한다.
문의는 완료 답변/오류 안내 바깥 같은 행의 하단 오른쪽에 접힌 details로 표시한다.
문의는 답변의 aria-live 영역 밖에 두며, 열면 주소 링크와 복사 버튼만 한 줄에 제공한다. 좁은 화면/확대/긴 번역은 자연스럽게 줄바꿈한다.
메일에 질문/답변을 자동 첨부하지 않는다. 기본 파란 링크·큰 버튼·상시 노출된 긴 주소 설명을 다시 추가하지 않는다.
버튼 명칭은 '결과 더 보기 / More results / Xem thêm kết quả / 查看更多结果 / 結果をもっと見る'.
명칭 변경 후에도 action=more와 기존 결과 ID·커서를 보존해야 한다.
자료 수정 날짜를 다시 노출하지 않는다. 원문의 금액·대상·조건을 디자인 목적으로 바꾸지 않는다.

### 캐릭터·언어 선택

상단 제목의 PNG는 제거한다. 스플래시/파비콘의 header-icon.png, 답변 bot-icon.png와 다섯 국기 SVG는 보존한다.
답변 옆 캐릭터는 장식으로 접근성 트리에서 제외한다.
국기 버튼은 언어 이름과 선택 상태를 제공한다. 국적에 따른 사람 수로 통계를 해석하지 않는다.
추천 질문의 아이콘은 사용자 요청으로 다섯 언어 모두 제거하고 텍스트 라벨만 사용한다. 전송 질문 원문은 변경하지 않는다.
접기/추천 질문 토글은 13px·500, 12px 화살표, 약한 그림자와 은은한 베이지 글라스(245,240,231,.94)를 사용한다. 질문 버튼은 기본 흰색을 유지하고 hover에서 #FAF3E7 베이지로 바뀐다. 질문 스크롤 영역은 실측 토글 너비만큼 줄이고 버튼 앞 8px 공간을 확보한다. 펼친 상태에서는 세로 중앙을 맞춘다. 추천 질문 아래부터 입력 필드까지 간격은 16px이다.
추천 질문 영역은 투명하며 영역 전체 블러는 없다. 개별 버튼에만 흰색 90%·blur(10px)의 옅은 글라스를 적용한다. 블러 미지원 시 불투명 #F9FAFB로 표시한다. 국기·캐릭터·입력/공유 등 기능 아이콘은 유지한다.

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

### 일본어 (2026-09-21)

언어 순서는 한국어·영어·베트남어·중국어·일본어이며 일본어는 ja, 음성 인식은 ja-JP이다.
국기 버튼의 접근 가능한 이름은 日本語, 선택 상태는 aria-pressed로 전달한다.
일본어는 시스템 sans-serif 폴백을 사용하며 추가 웹폰트를 다운로드하지 않는다.
높이 480px 이하에서는 언어 목록만 세로 스크롤하여 다섯 번째 버튼이 입력 영역을 덮지 않는다.
추천 질문·팁·문의·오류·정보 수집 안내도 일본어를 제공한다.
일본어 카드의 금액과 자격 조건은 임의로 생략하지 않는다. 한국 복지제도를 일본 제도로 치환하지 않는다.
