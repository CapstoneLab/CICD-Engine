# 프론트엔드 명세서 — 보안 정책(16개 항목) 결과/선택/승인 화면

> 대상: 프론트엔드 개발자
> 백엔드 베이스 URL: `http://54.221.222.244/capstonelab/capstone-back`
> 관련 문서: [SECURITY_POLICY_MANUAL.md](SECURITY_POLICY_MANUAL.md)(정책 전문), [BACKEND_SECURITY_POLICY_PROMPT.md](BACKEND_SECURITY_POLICY_PROMPT.md)(백엔드 계약)
> 최종: 2026-05-30

---

## PART 1. 지금까지 한 것 (배경 — 프론트가 알아야 할 맥락)

### 1-1. 무엇을 푸는 정책인가
CI/CD 파이프라인이 레포를 스캔해 **배포 가능 여부(게이트)** 와 **코드 건강도(점수)** 를 분리해 판정한다. 16개 취약점 항목을 4등급(Critical/High/Medium/Low)으로 나누고, 사용자가 그중 검사할 항목을 고른다.

핵심 원칙 3가지 (프론트 UI가 지켜야 함):
1. **게이트와 점수는 별개다.** 점수가 높아도 게이트에서 막힐 수 있다(예: Critical 1건 → score는 보조, verdict는 block).
2. **위계는 안 깨진다.** Low 100개 < High 1개. UI도 이 위계를 흐리면 안 된다.
3. **선택 안 한 항목은 "안전"이 아니라 "미검사"다.** 이게 `out_of_scope_count`이고, **반드시 화면에 표시**해야 한다.

### 1-2. 엔진이 한 일 (구현 완료, 라이브)
- **16항목 카탈로그**: CWE → 항목 → 등급 → 감점을 단일 소스(`app/security_catalog.py`)로 관리.
- **CWE 기반 등급 재분류**: 스캐너(semgrep/gitleaks)의 자체 severity를 믿지 않고, finding의 CWE로 등급을 다시 매긴다. (예: CWE-89 = 항상 Critical, gitleaks 시크릿 = CWE-798 Critical)
- **cap 점수**: High≤19, Medium≤4, Low≤0.9로 상한. Critical 있으면 0~40 강제.
- **위계 게이트**: Critical≥1 `block` / High≥1 `block_pending_approval` / Medium≥1 `warn` / 그 외 `pass`.
- **선택 항목 스코핑**: 선택한 항목만 게이트·점수에 반영, 나머지는 `out_of_scope_count`로 집계.
- **commit 정확 스캔**: payload `commit_sha`를 checkout(실패 시 HEAD fallback), 실제 스캔한 SHA를 `scanned_commit_sha`로 회신.
- **승인 waive**: `approved_cwes`의 High를 게이트 통과 처리(Critical은 불가), `acknowledged_cwes`로 회신.
- **gauge 색상**: verdict 기준 색(`gauge_color`)을 직접 방출 → 프론트는 점수로 색을 재계산하지 않는다.

### 1-3. 백엔드가 한 일 (구현 완료)
- 잡 payload에 `selected_items` / `environment` / `commit_sha` / `approved_cwes` 포함해 엔진(폴러)에 전달.
- 엔진 콜백의 verdict 신규 스키마(13+2필드) 전부 DB 저장.
- 신규 엔드포인트: catalog 조회, result 상세, 승인 request/approve/reject, 감사 로그.
- `block_pending_approval` 승인 시 **후속 잡 자동 enqueue**(`approved_cwes` 포함) → 엔진이 재스캔 후 deploy.

### 1-4. 검증된 라이브 동작 (실제 run 기준)
- 16개 전체 검사 → Critical 11건 → `block`, score 0, block_reason "Hardcoded Secret (CWE-798, Critical) 검출 — 즉시 차단 정책".
- IDOR/JWT/Cleartext 3개만 선택 → 해당 없음 → `pass`, score 100, **그러나 `out_of_scope_count: 18`** (선택 안 한 hardcoded secret 등 18건은 미검사). ← 이 케이스가 프론트 표시의 핵심.

---

## PART 2. 프론트가 해야 할 일 (화면별 상세 명세)

전체 화면 4개: **(A) 검사 항목 선택 → (B) 결과 → (C) 승인 → (D) 감사 로그**

### 데이터 소스 — 프론트가 호출할 API (JWT 인증)

| 화면 | Method · Path | 용도 |
| --- | --- | --- |
| A | `GET /api/security/catalog` | 16항목 목록(인증 불필요) |
| A | `POST /api/pipelines` | 파이프라인 시작 (selected_items/environment/commit_sha) |
| B | `GET /api/jobs/{id}` | 잡 상태 + 스텝 진행 (폴링) |
| B | `GET /api/jobs/{id}/result` | verdict 전체 + findings |
| B | `GET /api/jobs/{id}/findings` | findings만 |
| C | `GET /api/jobs/{id}/approval` | 해당 잡 승인 레코드 |
| C | `POST /api/jobs/{id}/approval/request` | 승인 요청 생성 |
| C | `POST /api/jobs/{id}/approval/approve` | 승인 (body: `{reason, approved_cwes?}`) |
| C | `POST /api/jobs/{id}/approval/reject` | 거부 (body: `{reason}`) |
| D | `GET /api/approvals?status=pending` | 감사 로그 목록 |

---

## 화면 A — 검사 항목 선택 (파이프라인 시작)

### A-1. 16항목 선택 UI
`GET /api/security/catalog`로 받은 16개를 **등급별 4그룹**으로 묶어 표시. 각 항목은 체크박스.

```
🔴 Critical (4)   □ SQL Injection (CWE-89)   □ Command Injection (CWE-78)
                  □ Hardcoded Secret (CWE-798)  □ Code Injection (CWE-94)
🟠 High (4)       □ Insecure Deserialization (CWE-502)  □ IDOR (CWE-639)
                  □ Improper JWT Verification (CWE-347)  □ Cleartext Transmission (CWE-319)
🟡 Medium (4)     □ Path Traversal (CWE-22)  □ XSS (CWE-79)
                  □ Weak Cryptography (CWE-327)  □ SSRF (CWE-918)
🟢 Low (4)        □ Error Message Info Exposure (CWE-209)  □ Missing HttpOnly (CWE-1004)
                  □ Missing Secure Flag (CWE-614)  □ Weak Password Requirements (CWE-521)
```

요구사항:
- **등급별 전체선택/해제** 토글 제공 (예: "Critical 4개 모두").
- **"전체 선택"** 기본값 권장(=16개 전체). 사용자가 부분 선택 가능.
- 항목별 한줄 설명(catalog의 description)을 툴팁/보조텍스트로.
- 등급 색상 배지(🔴🟠🟡🟢)로 위험도 직관화.
- **최소 1개 이상** 선택 강제(0개 제출 막거나, 0개=전체로 처리할지 백엔드와 합의 — 권장: 0개 선택은 제출 비활성).

### A-2. environment 선택
드롭다운: `development` / `feature` / `staging` / `production`.
- 보조 문구: "production/staging은 더 엄격 — **Medium도 승인 필요**로 승격됩니다."

### A-3. 제출 — `POST /api/pipelines`
```json
{
  "repo_url": "https://github.com/owner/repo",
  "branch": "main",
  "environment": "production",
  "selected_items": ["CWE-89", "idor", "xss"],   // CWE id 또는 key, 혼용 가능
  "commit_sha": "a1b2c3d4"                         // 선택. 없으면 branch HEAD
}
```
- `selected_items`는 CWE id(`CWE-89`) 또는 key(`sql-injection`) 어느 쪽이든 OK. 일관되게 CWE id 권장.
- 응답으로 `job_id` 수신 → 결과 화면(B)으로 이동, 폴링 시작.

---

## 화면 B — 결과 (가장 중요한 화면)

`GET /api/jobs/{id}/result`의 `security.verdict` + `security.findings[]`를 렌더.

### B-0. verdict 필드 → UI 바인딩 표 (그대로 사용, 재계산 금지)

| verdict 필드 | UI 요소 | 규칙 |
| --- | --- | --- |
| `gauge_color` | 게이지/배너 색 | **그대로 사용.** 점수로 색 재계산 ❌ |
| `score_label` | 점수 텍스트 | "82.0/100 (검사 항목 9개 기준)" 그대로 출력 |
| `score` | 게이지 수치 | 0~100 |
| `verdict` | 상단 상태 배지 | 4종별 배지(B-1) |
| `counts` | 등급별 카운트 칩 | critical/high/medium/low (in-scope 기준) |
| `selected_items` | 검사 항목 목록 | 표시 + **미선택 = "미검사"** 구분 |
| `selected_count` | "N개 기준" 라벨 | score_label에 이미 포함 |
| `out_of_scope_count` | **범위 밖 경고 배너** | **>0이면 반드시 표시** (B-3) |
| `requires_approval` | 승인 CTA 노출 | true → 승인 화면(C) 진입 버튼 |
| `block_reasons` | 차단 사유 리스트 | 문자열 그대로(이미 사람이 읽는 문구) |
| `warn_reasons` | 경고 사유 리스트 | 문자열 그대로 |
| `score_breakdown` | 감점 내역(접기) | {critical,high,medium,low} 감점 |
| `scanned_commit_sha` | 스캔 커밋 표시 | 요청 commit과 다르면 경고(B-4) |
| `acknowledged_cwes` | "수용된 취약점" 배지 | 비어있지 않으면 표시(B-5) |

### B-1. verdict 4종별 화면 상태

| verdict | 배지/배너 | 색 | 메인 메시지 | 액션 |
| --- | --- | --- | --- | --- |
| `pass` | ✅ 통과 | 🟢 green | "배포 가능" | 배포 진행 표시 |
| `warn` | ⚠️ 경고 | 🟡 yellow | "경고 — 배포는 가능" | warn_reasons 노출, 배포 진행 |
| `block_pending_approval` | 🟠 승인 필요 | 🟠 orange | "차단 — 승인 시 배포 가능" | **승인 요청 CTA(화면 C)** |
| `block` | ⛔ 차단 | 🔴 red | "배포 차단 — 코드 수정 필요" | 승인 버튼 **숨김**, 수정 안내 |

> `block`과 `block_pending_approval`을 절대 같게 표시하지 말 것. 전자는 승인 불가(하드 차단), 후자는 승인 경로 존재. 구분 신호 = `verdict` 값 + `requires_approval`.

### B-2. 게이트 카드 (점수보다 우선 노출)
점수 게이지를 메인처럼 두지 말고, **게이트 위계 카드**를 상단에 배치:
```
[ 배포 게이트 ]   현재 판정: 🟠 승인 필요
  🔴 Critical ≥ 1 → 즉시 차단
  🟠 High ≥ 1     → 승인 필요   ← 현재 여기
  🟡 Medium ≥ 1   → 경고(통과)
  🟢 Low/없음     → 통과
```
- 현재 걸린 위치를 하이라이트.
- 그 아래에 점수 게이지(보조 지표) 배치.

### B-3. ⭐ out_of_scope 배너 (필수 — 누락 금지)
`out_of_scope_count > 0`이면 **눈에 띄는 정보 배너**를 결과 상단/점수 근처에 표시:

```
ⓘ 선택 범위 밖에서 18건이 추가로 탐지되었습니다 (미검사 항목).
   이번 판정은 선택한 3개 항목 기준입니다. 미선택 항목은 "안전"이 아니라 "검사 안 함"입니다.
   [ 미검사 항목 보기 ]  [ 전체 16개로 다시 검사 ]
```

이유: 위 라이브 케이스처럼 **score 100 / pass인데 실제로는 18건의 미검사 위험**이 있을 수 있다. 이 배너가 없으면 "안전하다"고 치명적으로 오해한다. (정책 §6 결과 화면 규칙 2)

- `[미검사 항목 보기]`: findings 중 `in_scope == false`인 항목을 별도 섹션으로.
- `[전체 16개로 다시 검사]`: 화면 A로 보내 16개 선택 후 재실행.

### B-4. 커밋 표시 + 불일치 경고
- `scanned_commit_sha`를 짧게(앞 12자) 표시: "스캔 커밋: `12bb3942e8df`".
- 요청한 `commit_sha`와 다르면(백엔드가 비교) **경고**: "요청 커밋을 가져오지 못해 브랜치 HEAD를 스캔했습니다(force-push/rebase 추정)."

### B-5. acknowledged_cwes 배지
`acknowledged_cwes`가 비어있지 않으면(=승인 수용된 High가 포함된 결과):
```
🟠 수용된 취약점 포함: IDOR(CWE-639)
   이 항목은 책임자 승인 하에 게이트를 통과했습니다. 점수에는 위험이 그대로 반영되어 있습니다.
```
> 중요: 승인돼도 **score는 -5 유지**(예: pass인데 95점). "수용했지만 아직 안 고친 위험"임을 이 배지로 설명. score가 100이 아니라고 버그로 보지 말 것.

### B-6. findings 목록
`security.findings[]`를 표/리스트로. **in_scope 우선, severity 내림차순** 정렬 권장.

각 finding 카드 필드:
| 필드 | 표시 |
| --- | --- |
| `severity` | 등급 배지(🔴🟠🟡🟢) |
| `policy_item` / `cwe` | 항목명 + CWE 태그. `policy_item==null`이면 "16항목 외" |
| `in_scope` | false면 흐리게/"미검사" 태그 |
| `file_path` : `line_number` (`column_number`) | 위치(클릭 시 코드 점프) |
| `code_snippet` (+ `code_snippet_start_line`) | 코드 스니펫 하이라이트 |
| `message` / `title` | 설명 |
| `ai_recommendation` | "AI 수정 제안" 펼치기 |
| `scanner_name` | gitleaks/semgrep 출처 태그 |
| `cvss_score` | 있으면 보조 표시 |

- **in_scope == false** 항목은 별도 섹션("정책 범위 밖 N건")으로 모아, 게이트에 영향 없음을 명시.
- 분류는 **CWE로 통일**(CVE 쓰지 말 것).

### B-7. 진행 상태 (스캔 중)
`GET /api/jobs/{id}`를 폴링해 스텝 진행 표시:
- `steps[]`의 `step_name` / `step_type` / `status` / `duration_secs`로 단계별 타임라인.
- `pipeline_status`(running/success/failed)로 전체 진행률.
- 완료(`pipeline_complete`) 후 결과(B) 렌더.

---

## 화면 C — 승인 (block_pending_approval 전용)

`verdict == "block_pending_approval"` && `requires_approval == true`일 때만 진입.

### C-1. 승인 요청 생성
- 담당자가 `POST /api/jobs/{id}/approval/request` 호출 → 승인 대기 상태.
- 차단을 유발한 High 항목 목록을 `block_reasons` 또는 findings(`severity==high && in_scope`)에서 추출해 표시.

### C-2. 사유 작성 + 승인/거부
- **사유 입력 필수**(textarea). 무기한 예외 금지 안내 문구.
- 승인자(보안책임자/팀리드)만 승인 버튼 활성 — **권한 체크**(개발자 본인 승인 불가, 백엔드가 403 시 안내).

**전체 승인**:
```
POST /api/jobs/{id}/approval/approve
{ "reason": "검토 후 수용 — 차기 스프린트 패치 예정" }
```
→ block된 High CWE 전부 수용.

**부분 승인** (일부만):
```
POST /api/jobs/{id}/approval/approve
{ "reason": "IDOR만 수용, JWT는 패치 예정", "approved_cwes": ["CWE-639"] }
```
→ `approved_cwes`에 든 것만 수용. 나머지 High는 여전히 차단 → 후속 잡이 다시 `block_pending_approval`로 돌아올 수 있음(정상).

**거부**:
```
POST /api/jobs/{id}/approval/reject
{ "reason": "수용 불가 — 즉시 수정 필요" }
```

### C-3. 부분 승인 UI
- 차단 High 항목들을 체크박스로 나열 → 선택한 것만 `approved_cwes`로 전송.
- **Critical은 목록에 아예 노출 금지**(승인 불가). 만약 verdict가 `block`(Critical)이면 이 화면 자체에 진입하지 않음.

### C-4. 승인 후 흐름 표시
- 승인 시 백엔드가 **후속 잡을 자동 enqueue** → 응답의 `followup_job_id`(있으면)로 추적.
- 후속 잡 결과에서 `acknowledged_cwes`가 echo되면 "수용 처리됨"으로 확정 표시(B-5와 연결).
- **커밋 한정**: 새 커밋에 같은 High가 있으면 다시 승인 필요 — "이 승인은 커밋 `12bb3942`에만 유효" 안내.

### C-5. Critical 차단(block) 화면
- 승인 버튼 **없음**. "Critical은 예외 없이 차단됩니다. 코드 수정 후 새 커밋으로 재실행하세요."
- `approval/approve` 호출 시 백엔드 403 → 버튼 자체를 숨겨 호출 자체를 막을 것.

---

## 화면 D — 감사 로그

`GET /api/approvals?status=pending`(및 status 필터)로 승인 이력 표시:
- 컬럼: job/commit, 대상 CWE, 사유, 승인자, 일시, 상태(pending/approved/rejected), 만료.
- append-only(수정 불가) 특성 안내.
- commit 불일치(요청 vs scanned) 추적 뷰에 `scanned_commit_sha` 활용.

---

## PART 3. 공통 규칙 & 체크리스트

### 색상/배지 규칙 (절대 원칙)
- 게이지/상태 색은 **항상 `gauge_color`를 그대로 사용**. score 구간으로 색을 만들지 말 것 → verdict와 모순됨(High 95점이 초록으로 보이는 버그).
- 등급 배지 고정: Critical 🔴 / High 🟠 / Medium 🟡 / Low 🟢.

### 카피(문구) 가이드
- 차단 사유: `block_reasons` **그대로** 출력. "취약점 발견" 같은 자체 문구로 덮지 말 것.
- 점수 옆 범위: `score_label` 그대로. 자체로 "/100"만 보여주지 말 것.
- 미검사: "안전"이라는 단어 금지. "미검사 / 검사 안 함 / 정책 범위 밖"으로.

### 엣지 케이스
| 상황 | 처리 |
| --- | --- |
| `out_of_scope_count > 0` | 정보 배너 필수(B-3) |
| `score==100` & `out_of_scope>0` | "100점이지만 미검사 N건" 동시 표기 |
| `acknowledged_cwes` 존재 & score<100 | "수용된 위험 반영" 배지(B-5), 버그 아님 |
| `scanned_commit_sha` ≠ 요청 commit | 커밋 불일치 경고(B-4) |
| `verdict==block` | 승인 UI 전면 숨김 |
| `policy_item==null` finding | "16항목 외" 태그, 게이트 영향 없음 |

### 구현 체크리스트
- [ ] 화면 A: 16항목 등급별 그룹 선택 + environment + commit_sha → `POST /api/pipelines`
- [ ] 화면 B: `gauge_color`/`score_label` 그대로 사용(재계산 금지)
- [ ] 화면 B: 게이트 위계 카드 우선 노출
- [ ] 화면 B: **out_of_scope 배너(>0 필수)**
- [ ] 화면 B: block_reasons/warn_reasons 원문 출력
- [ ] 화면 B: findings — in_scope 구분, CWE 분류, code_snippet, ai_recommendation
- [ ] 화면 B: scanned_commit_sha 표시 + 불일치 경고
- [ ] 화면 B: acknowledged_cwes 배지 + score 미차감 안내
- [ ] 화면 C: block_pending_approval 승인 요청/사유/승인/거부
- [ ] 화면 C: 부분 승인(approved_cwes 체크박스), Critical 노출 금지
- [ ] 화면 C: block(Critical) 승인 버튼 숨김
- [ ] 화면 C: 후속 잡 추적 + 커밋 한정 안내
- [ ] 화면 D: 감사 로그
- [ ] 공통: verdict 4종 상태별 색/배지/액션 분기
