> 2026-11-15 정책 1.3.1: 사용자·저장소별 최초 전체 검사 완료 후 선택 검사를 허용합니다. 이후에는 선택한 항목만 검사·점수·차단에 반영하며 Secret 강제 검사는 없습니다. [현재 선택 검사 정책](docs/selected-scan-policy.md)을 우선 참고하세요.

# 보안 정책 매뉴얼 — 취약점 게이트 & 점수 (16개 항목)

> 이 문서는 CI/CD 파이프라인 보안 게이트의 **단일 사양서**입니다.
> 엔진 구현(`app/security_catalog.py`, `app/security_policy.py`)과 이 문서는 일치해야 합니다.
> 백엔드 연동 작업 지시서는 [BACKEND_SECURITY_POLICY_PROMPT.md](BACKEND_SECURITY_POLICY_PROMPT.md) 참고.

---

## 1. 목적과 설계 원칙

이 정책은 CI/CD 파이프라인에서 사용자가 선택한 취약점 항목을 검사하고 배포 가능 여부를 판정하기 위한 기준이다. 핵심 원칙은 세 가지다.

첫째, **게이트(차단 여부)와 점수(건강도)를 분리한다.** "배포해도 되는가"와 "코드가 얼마나 건강한가"는 다른 질문이므로 점수 하나로 섞지 않는다. 이렇게 해야 "Critical 1개 vs Low 30개" 같은 비교 문제가 게이트 단에서 사라진다.

둘째, **위계는 절대 깨지지 않는다.** 하위 등급이 아무리 누적돼도 상위 등급 1건의 위험을 넘지 못한다. 이를 위해 점수 계산에 등급별 상한(cap)을 적용한다.

셋째, **점수는 항상 "선택한 항목 기준"이다.** 사용자가 16개 중 일부만 선택할 수 있으므로, 검사하지 않은 항목은 "안전"이 아니라 "미검사"임을 화면에 명시한다.

근거 표준: 심각도 분류는 **CVSS**(취약점 정량화), 등급별 악용 난이도 정의는 **OWASP Risk Rating**(위험도 = 발생가능성 × 영향도)을 따른다.

---

## 2. 검사 항목 및 등급 정의 (16개)

| 등급 | 검사 항목 | item key | CWE | 한줄 설명 | 감점 |
| --- | --- | --- | --- | --- | --- |
| 🔴 Critical | SQL Injection | `sql-injection` | CWE-89 | 입력값이 SQL 쿼리에 직접 삽입, 인증 우회·DB 조작 | -20 |
| 🔴 Critical | Command Injection | `command-injection` | CWE-78 | 입력값이 시스템 명령어로 실행됨 | -20 |
| 🔴 Critical | Hardcoded Secret | `hardcoded-secret` | CWE-798 | 코드에 비밀번호·API 키 하드코딩 | -20 |
| 🔴 Critical | Code Injection | `code-injection` | CWE-94 | 입력값이 코드로 직접 실행됨 (eval 등) | -20 |
| 🟠 High | Insecure Deserialization | `insecure-deserialization` | CWE-502 | 역직렬화 시 악의적 객체 주입 | -5 |
| 🟠 High | IDOR | `idor` | CWE-639 | 권한 검증 없이 타인 리소스 접근 | -5 |
| 🟠 High | Improper JWT Verification | `improper-jwt` | CWE-347 | JWT 서명 검증 누락으로 토큰 위변조 | -5 |
| 🟠 High | Cleartext Transmission | `cleartext-transmission` | CWE-319 | HTTP로 민감 정보 평문 전송 | -5 |
| 🟡 Medium | Path Traversal | `path-traversal` | CWE-22 | `../` 삽입으로 서버 내부 파일 접근 | -1 |
| 🟡 Medium | Cross-Site Scripting (XSS) | `xss` | CWE-79 | 입력값이 HTML에 출력돼 악성 스크립트 실행 | -1 |
| 🟡 Medium | Weak Cryptography | `weak-crypto` | CWE-327 | MD5·SHA1 등 취약한 암호화 사용 | -1 |
| 🟡 Medium | SSRF | `ssrf` | CWE-918 | 서버가 내부 네트워크로 요청을 보내도록 유도 | -1 |
| 🟢 Low | Error Message Info Exposure | `error-info-exposure` | CWE-209 | 에러 메시지에 DB 버전·내부 IP 노출 | -0.2 |
| 🟢 Low | Missing HttpOnly Flag | `missing-httponly` | CWE-1004 | 쿠키 HttpOnly 미설정으로 JS 접근 가능 | -0.2 |
| 🟢 Low | Missing Secure Flag | `missing-secure-flag` | CWE-614 | 쿠키 Secure 플래그 미설정 | -0.2 |
| 🟢 Low | Weak Password Requirements | `weak-password-policy` | CWE-521 | 비밀번호 복잡도 정책 미흡 | -0.2 |

구성: Critical 4 / High 4 / Medium 4 / Low 4.

> **등급의 권위는 CWE다.** semgrep/gitleaks가 매긴 자체 severity를 믿지 않고, finding의 CWE를 위 표로 매핑해 등급을 재분류한다. (예: CWE-89는 도구가 뭐라 하든 항상 Critical) 엔진의 단일 소스는 `app/security_catalog.py`.

**등급 정의 요약**

| 등급 | 악용 조건 | 감점 |
| --- | --- | --- |
| 🔴 Critical | 공격자에게 아무것도 필요 없음 | -20 |
| 🟠 High | 로그인 계정 1개만 있으면 악용 가능 | -5 |
| 🟡 Medium | 피해자 행동 또는 추가 조건 필요 | -1 |
| 🟢 Low | 직접 공격 불가, 정보 수집·조합 시 위험 | -0.2 |

---

## 3. 1단계 — 배포 게이트 (Gate), 정책 1.4.0

점수와 무관하게 선택 범위 내 검출 건수를 등급별로 집계한다. 아래 순서대로 적용하며 가장 강한 조치를 우선한다. 건수는 검출 결과 기준이고, 별도 `unique_finding_count`는 중복 제거 통계다.

| 조건 | verdict | 처리 |
| --- | --- | --- |
| Critical ≥ 1 | `block` | 즉시 차단, 승인 불가 |
| High ≥ 2 | `block` | 즉시 차단, 승인 불가 |
| High = 1 | `block_pending_approval` | 승인 필요 |
| Medium ≥ 2 | `block_pending_approval` | 승인 필요 |
| Medium = 1 | `warn` | 경고(통과) |
| Low ≥ 1 | `warn` | 경고(통과) |
| 없음 | `pass` | 통과 |

### 3-1. High/Medium 승인 절차

승인 필요 결과는 파이프라인을 정지한다. 소유자가 승인을 요청하고, 저장소 쓰기 권한을 가진 지정 보안 검토자가 사유와 대상 CWE를 확인하여 승인한다. 자기 승인은 허용하지 않는다. 승인 내역은 기록되며 동일 저장소·브랜치·검사 커밋의 후속 실행에만 최대 24시간 유효하다.

승인된 High/Medium CWE는 후속 실행의 승인 대상 집계에서 제외하지만 점수에는 남는다. Critical 또는 원래 High 검출 건수 2건 이상은 승인 여부와 무관하게 차단한다. 선택하지 않은 CWE는 판정에서 제외한다. 선택된 Gitleaks Secret은 Critical로 즉시 차단한다.

### 3-2. 환경

`development`, `feature`, `staging`, `production` 모두 같은 개수 기준을 적용한다. 운영·스테이징의 Medium 추가 차단 규칙은 적용하지 않는다.

---

## 4. 2단계 — 보안 점수 (Score)

점수는 **게이트를 통과했거나 통과 가능한 상태(Critical 없음, High는 승인됨)에서 코드의 상대적 건강도**를 보여주는 보조 지표다. **점수는 게이트를 결정하지 않는다.**

### 4-1. 동적 만점 표기

만점은 항상 100점에서 시작하되, **점수 라벨에 "선택 항목 N개 기준"을 반드시 병기한다.** 검사하지 않은 항목은 안전한 것이 아니라 미검사 상태이기 때문이다.

```
예) "82/100 (검사 항목 9개 기준)"
    화면에 선택된 항목 목록을 함께 노출
    정책 범위 밖 추가 탐지가 있으면 out_of_scope 건수도 병기
```

### 4-2. 계산 공식

```
등급별 감점(cap 적용):
  High 감점 합   = min(High 건수 × 5,   19)   # Critical 1건(20) 미만
  Medium 감점 합 = min(Medium 건수 × 1,  4)    # High 1건(5) 미만
  Low 감점 합    = min(Low 건수 × 0.2, 0.9)   # Medium 1건(1) 미만

[Critical이 0개]
  점수 = 100 - (High 감점 + Medium 감점 + Low 감점)
  → cap 때문에 최저값은 100 - 19 - 4 - 0.9 = 76.1점

[Critical이 1개 이상]   # 위험 구간(0~40) 강제
  raw   = 100 - (Critical 건수 × 20) - High 감점 - Medium 감점 - Low 감점
  점수  = max(0, min(40, raw))
  → 게이트는 이미 BLOCK. 점수는 빨강으로 0~40 안에 표시.
```

> **[수정됨] 이전 버전의 "0~40으로 강제 표시"는 공식이 모호했다.** 위와 같이 `max(0, min(40, raw))`로 확정한다.

### 4-3. cap의 의미

하위 등급의 감점 총합이 상위 등급 1건의 감점을 절대 초과할 수 없다.

```
Low 전체 합 (최대 0.9) < Medium 1건 (1)
Medium 전체 합 (최대 4) < High 1건 (5)
High 전체 합 (최대 19) < Critical 1건 (20)
```

따라서 Low가 30개든 100개든 최대 -0.9점이므로, 절대로 High 1개(-5점)보다 위험해 보이지 않는다. 점수상에서도 위계가 유지된다.

### 4-4. 게이지 색상 기준 (게이트 판정 기반)

> **[수정됨] 색상은 점수 구간이 아니라 게이트 판정(verdict)을 따른다.**
> cap 때문에 Critical=0이면 점수가 76.1점 밑으로 내려가지 않아, "점수 41~74 = 주황" 같은 구간은 도달 불가능했다.
> 점수 band로 색을 정하면 verdict와 어긋나므로(예: High 1건 95점이 색상표상 초록으로 보이는 모순), 색은 verdict로 정한다.

| 게이트 판정(verdict) | 색상 | 점수(참고 범위) |
| --- | --- | --- |
| `block` (Critical) | 🔴 빨강 | 0~40 (강제) |
| `block_pending_approval` (High / 엄격환경 Medium) | 🟠 주황 | 76.1~95 (cap상 81 이상) |
| `warn` (Medium) | 🟡 노랑 | 96~99 |
| `pass` (Low / 없음) | 🟢 초록 | 99.1~100 |

엔진은 이 색을 `gauge_color` 필드로 직접 방출한다. **백엔드/프론트는 점수로 색을 재계산하지 말고 `gauge_color`를 그대로 사용한다.**

---

## 5. 적용 예시

### 예시 A — SQL Injection 검출 (Critical 1건)
- **게이트:** Critical ≥ 1 → **`block`** (우선순위 1에서 종료)
- **점수:** `max(0, min(40, 80))` = **40점** (빨강)
- **실패 사유:** "SQL Injection (CWE-89, Critical) 검출 — 즉시 차단 정책"

### 예시 B — IDOR만 검출 (High 1건)
- **게이트:** High = 1 → **`block_pending_approval`** (승인 예외 절차 필요)
- **점수(참고):** 100 - min(1×5, 19) = **95점**
- **색상:** 🟠 **주황** — High BLOCK이기 때문(점수 95가 초록이라서가 아님)
- 승인 없이는 점수와 무관하게 배포 불가.

### 예시 C — XSS 2건 + SSRF 1건 (Medium 3건)
- **게이트:** Medium 3건 → **`block_pending_approval`** (승인 필요)
- **점수:** 100 - min(3×1, 4) = **97점** (주황)
- 모든 환경에서 승인 후 배포 허용.

### 예시 D — Low 항목 4종 모두 검출
- **게이트:** Low만 존재 → **`warn`** (경고 통과)
- **점수:** 100 - min(4×0.2, 0.9) = 100 - 0.8 = **99.2점** (노랑)
- "거의 건강하나 정리할 항목 있음"으로 표시.

### 예시 E — High 2건 + Medium 5건 + Low 4건
- **게이트:** High 2건 → **`block`** (즉시 차단, 승인 불가)
- **점수(참고):** 100 - min(2×5,19) - min(5×1,4) - min(4×0.2,0.9) = 100 - 10 - 4 - 0.8 = **85.2점** (빨강)

---

## 6. 결과 화면 표기 규칙

1. **실패 사유는 게이트 규칙으로 표기한다.** "취약점 발견" 같은 모호한 문구 대신 "Command Injection (CWE-78, Critical) 검출 — 즉시 차단 정책"처럼 어떤 항목이 어떤 규칙에 걸렸는지 명시한다. (엔진이 `block_reasons`/`warn_reasons`로 이 문구를 제공)
2. **점수 옆에 검사 범위를 병기한다.** "82/100 (검사 항목 9개 기준)"(`score_label`)처럼 미검사 항목과 구분하고, 선택 항목 목록(`selected_items`)을 함께 노출한다.
3. **게이트 통과 조건을 별도 카드로 보여준다.** 점수 쓰레숄드를 메인처럼 두지 않는다. Critical이 있으면 점수와 무관하게 막히므로 쓰레숄드만 강조하면 정책이 모순돼 보인다.
4. **게이지 색상은 `gauge_color`를 그대로 쓴다.** 점수 구간으로 색을 재계산하지 않는다(§4-4).
5. **분류 체계를 CWE로 통일한다.** 결과 표기에 CVE 대신 CWE를 쓰고, 항목명·설명·CWE 매핑이 어긋나지 않게 한다.

---

## 변경 이력

아래는 과거 정책 기록이다. 현재 판정에는 §3의 1.4.0 기준을 적용한다.

- **2026-11-15 (1.4.0)**: High 2건 즉시 차단, Medium 2건 승인 필요, Low 경고 통과로 변경. 환경별 추가 차단 제거, Medium 승인 지원.
- **2026-05-30**: 6개 → 16개 항목 확장. 게이트/점수 분리, 등급 cap 도입, `block_pending_approval` 상태 신설, 선택 항목 스코핑 추가. §4-2 Critical 점수 공식 확정, §4-4 색상 기준을 점수 band → 게이트 판정 기반으로 수정(모순 해소).


## v1.2.1 보안 보완 (2026-11-14)

기존 16개 항목의 등급·감점·점수 상한과 개발 환경 Medium 경고 기준은 유지한다.
운영·스테이징에서는 고유 Medium 1~9건 승인 필요, 10~29건 수동 검토,
30건 이상 승인 예외 없는 차단 기준을 유지한다. 고유 건수는 CWE·rule_id·파일·줄로 집계한다.

- Critical/Secret 차단과 Medium 30건 이상 차단은 범위 밖 탐지나 수동 검토 조건이 완화할 수 없다.
- Secret은 필수 항목이며 결과의 selected_items에도 포함한다. Gitleaks는 CWE-798로 정규화한다.
- 워크플로는 Secret 검사 → 심층 검사/게이트 → 배포 순서를 준수한다. 각 스캐너는 정확히 한 번 실행한다.
- 필수 검사 누락·중복·순서 오류는 워크플로 실행 전에 실패 처리한다. mirae도 Secret 검사를 생략하지 않는다.
- 스캐너의 오류, 보고서 누락·손상·구조 오류·Semgrep errors는 검사 실패다. continue_on_failure로 우회할 수 없다.
- 이미 생성된 보고서는 검사 전에 제거한다. Secret 발견 종료 코드인데 보고서가 비어 있어도 실패 처리한다.
- 알 수 없는 환경값은 거부한다. 웹훅 기본 환경 development는 유지한다. 운영 환경의 연결은 별도 설정 사항이다.
- High 승인 예외는 지정된 책임자(SECURITY_APPROVER_LOGINS)와 해당 저장소 Write 이상 권한을 모두 요구한다.
  실행 소유자만 승인 요청 가능하며 자기 승인은 금지한다. 승인자 목록이 비어 있으면 예외 승인은 차단된다.
- 승인은 요청된 High CWE의 부분집합, 검증된 동일 커밋·저장소·브랜치·후속 Job에 한정된다.
  기본 및 최대 유효기간은 24시간이며 실행 전달 시 다시 검증한다. 만료/불일치 시 승인 예외를 제거하고 정상 검사한다.
- manual_review는 자동 승인/배포 경로가 아니다. 현재 승인 API는 High 예외만 지원한다.
  Medium 승인·수동 검토의 별도 해제 절차는 이번 보완에서 추가하지 않는다.

신뢰 경계: 이 검증은 엔진의 워크플로와 배포 기능을 통제한다. 임의의 저장소 명령은
신뢰된 코드라는 기존 실행 모델을 유지한다. 악의적인 명령의 외부 배포·호스트 접근을
막으려면 Docker 소켓·네트워크·자격증명 격리 등 별도의 실행기 격리가 필요하다.
