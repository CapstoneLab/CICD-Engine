# 백엔드 개발 요청서 — 보안 정책(16개 항목) 연동 (상세판)

> 이 문서는 백엔드 개발자에게 그대로 전달하기 위한 **완성형 작업 지시서**입니다.
> CI/CD 엔진(스캐너/실행기)은 아래 정책에 맞게 이미 수정 완료되었습니다.
> 정책 전문은 [SECURITY_POLICY_MANUAL.md](SECURITY_POLICY_MANUAL.md) 참고.

---

## 0. 책임 분담 — 누가 무엇을 하나

```
[프론트] --선택/승인 UI--> [백엔드] --CLI 트리거--> [엔진(stateless)]
   ^                          |  ^                       |
   |   상태/결과/감사로그 조회  |  |  콜백(webhook) verdict |
   +--------------------------+  +------------------------+
```

- **엔진(완료, 무상태)**: 클론 → semgrep/gitleaks 스캔 → CWE로 16항목 등급 재분류 → 위계 게이트 + cap 점수 → 콜백 전송. 승인 상태/이력을 **저장하지 않음**.
- **백엔드(이 문서의 대상)**:
  1. 검사 항목 선택 입력 받기 + 엔진에 전달
  2. 엔진 콜백 수신·저장
  3. **High 승인 예외 워크플로** (상태머신, 승인 UI, 감사로그, 재트리거) — 가장 큰 작업
  4. 결과 화면용 API 제공

---

## 1. 16개 항목 카탈로그 (선택 UI 소스)

선택 UI는 아래 16개를 **등급별로 묶어** 보여주고 부분 선택을 허용한다. 선택 토큰은 **CWE id**(`CWE-89`) 또는 **item key**(`sql-injection`) 둘 다 허용(엔진이 양쪽 해석).

| key | name | cwe | grade | 감점 |
| --- | --- | --- | --- | --- |
| sql-injection | SQL Injection | CWE-89 | critical | -20 |
| command-injection | Command Injection | CWE-78 | critical | -20 |
| hardcoded-secret | Hardcoded Secret | CWE-798 | critical | -20 |
| code-injection | Code Injection | CWE-94 | critical | -20 |
| insecure-deserialization | Insecure Deserialization | CWE-502 | high | -5 |
| idor | IDOR | CWE-639 | high | -5 |
| improper-jwt | Improper JWT Verification | CWE-347 | high | -5 |
| cleartext-transmission | Cleartext Transmission | CWE-319 | high | -5 |
| path-traversal | Path Traversal | CWE-22 | medium | -1 |
| xss | Cross-Site Scripting (XSS) | CWE-79 | medium | -1 |
| weak-crypto | Weak Cryptography | CWE-327 | medium | -1 |
| ssrf | SSRF | CWE-918 | medium | -1 |
| error-info-exposure | Error Message Info Exposure | CWE-209 | low | -0.2 |
| missing-httponly | Missing HttpOnly Flag | CWE-1004 | low | -0.2 |
| missing-secure-flag | Missing Secure Flag | CWE-614 | low | -0.2 |
| weak-password-policy | Weak Password Requirements | CWE-521 | low | -0.2 |

> 이 표의 단일 소스는 엔진 `app/security_catalog.py`. 백엔드는 이 표를 복제하되, 가능하면 **엔진이 노출하는 카탈로그 API**(아래 4-F)를 호출해 동기화한다. 불일치 시 점수/색상이 어긋난다.

---

## 2. 엔진 호출 계약 (백엔드 → 엔진)

엔진은 **CLI 서브프로세스**로 실행한다. 백엔드는 잡 트리거 시 아래 인자를 구성한다.

```bash
python main.py \
  --job-id        <백엔드가 발급한 job id> \
  --repo          <git url> \
  --branch        <branch> \
  --workflow      <선택: 레포 내 워크플로 yml 경로> \
  --source        <capstone | mirae> \
  --environment   <production | staging | development | feature> \
  --selected-items "CWE-89,CWE-78,CWE-639,CWE-79" \
  --approved-cwes  "" \
  --callback-url   <백엔드 콜백 webhook URL> \
  --callback-token <공유 시크릿>
```

### 인자 상세
| 인자 | 필수 | 의미 |
| --- | --- | --- |
| `--job-id` | 권장 | 백엔드 job 식별자. 콜백에 그대로 echo됨. |
| `--repo` | ✅ | git URL |
| `--branch` | | 기본 `main` |
| `--selected-items` | | 콤마구분. CWE id/key 혼용 가능. **빈 값=16개 전체.** payload가 yml보다 우선. |
| `--environment` | | `production`/`staging`은 Medium도 승인필요로 승격(§정책 3-2). 기본 `development`. |
| `--approved-cwes` | | **승인 후 재트리거 전용.** 승인된 High CWE 목록. 해당 CWE를 "인지·수용됨"으로 처리해 게이트를 통과시킴(아래 5-D). 평상시 빈 값. |
| `--callback-url` | | 결과를 POST할 백엔드 webhook |
| `--callback-token` | | 콜백 `x-callback-token` 헤더로 전송됨. 백엔드는 이 값으로 콜백 진위 검증. |

> ⚠️ `--approved-cwes`는 **엔진에 아직 미구현**입니다(엔진 측 1건 추가 필요). 이 인자가 승인→재배포의 핵심입니다. 엔진 담당이 추가해야 백엔드 재트리거가 동작합니다. (구현 명세는 7장)

### 검사 항목 경로 우선순위
**payload(`--selected-items`) > workflow.yml(`selected_items:`) > 미지정 시 16개 전체.**

---

## 3. 콜백 수신 계약 (엔진 → 백엔드)

엔진은 두 종류의 webhook을 백엔드 `--callback-url`로 POST한다. 헤더 `x-callback-token`을 검증할 것.

### 3-A. 스텝 완료 콜백 (`type: "step_complete"`) — 스텝마다 N회
```json
{
  "job_id": "...",
  "type": "step_complete",
  "pipeline_status": "running",
  "repo_url": "...",
  "branch": "...",
  "step": {
    "name": "deep_security_scan",
    "status": "success",
    "exit_code": 0,
    "summary": "...",
    "started_at": "...", "finished_at": "...",
    "log_file": "logs/deep_security_scan.log",
    "logs": ["...", "..."],
    "security": {
      "summary": { "scanner_name": "...", "critical_count": 0, "high_count": 1, "...": "..." },
      "findings": [ /* 아래 3-C finding 스키마 */ ]
    }
  },
  "metadata": { "executor": "ubuntu-ci-engine", "run_id": "...", "workflow_name": "...", "workflow_source": "..." }
}
```

### 3-B. 파이프라인 완료 콜백 (`type: "pipeline_complete"`) — 마지막 1회 (최종 verdict 포함)
```json
{
  "job_id": "...",
  "type": "pipeline_complete",
  "status": "failed",                 // success | failed | running
  "repo_url": "...", "branch": "...",
  "started_at": "...", "ended_at": "...",
  "logs": ["[clone.log] ...", "..."],
  "steps": [ { "name": "clone", "status": "success", "exit_code": 0, "summary": "...", "log_file": "..." }, ... ],
  "security": {
    "summaries": [ { "scanner_name": "semgrep", "critical_count": 0, "...": "..." } ],
    "findings":  [ /* 3-C */ ],
    "verdict":   { /* 3-D — 게이트 최종 판정. 백엔드 분기의 핵심 */ }
  },
  "metadata": { "executor": "ubuntu-ci-engine", "run_id": "...", "workflow_name": "...", "service": { /* 배포 엔드포인트(있으면) */ } }
}
```

> **주의:** `block`과 `block_pending_approval` 모두 `status: "failed"`로 옵니다. 둘을 구분하는 신호는 `security.verdict.verdict`와 `requires_approval`입니다. status만 보고 판단하지 마세요.

### 3-C. finding 스키마 (신규 필드 ★)
```json
{
  "scanner_name": "semgrep",
  "rule_id": "...",
  "severity": "high",
  "title": "...", "message": "...",
  "file_path": "app/user.py", "line_number": 42,
  "cvss_score": 8.1,
  "ai_recommendation": "...",
  "code_snippet": "...", "code_snippet_start_line": 40,
  "cwe": "CWE-639",          // ★ 정규화된 CWE
  "policy_item": "idor",     // ★ 매칭된 16-item key (미매칭 시 null)
  "in_scope": true           // ★ 선택 항목에 포함되어 게이트/점수에 반영됐는지
}
```

### 3-D. verdict 스키마 (게이트 최종 판정 — 전체 필드)
```json
{
  "verdict": "block_pending_approval",        // block | block_pending_approval | warn | pass
  "score": 94.0,
  "score_label": "94.0/100 (검사 항목 3개 기준)",
  "gauge_color": "orange",                    // red | orange | yellow | green
  "environment": "development",
  "counts": { "critical": 0, "high": 1, "medium": 1, "low": 0 },  // in-scope 기준
  "selected_count": 3,
  "selected_items": [ { "key": "idor", "name": "IDOR", "cwe": "CWE-639", "grade": "high" }, ... ],
  "out_of_scope_count": 0,                     // 선택 밖 또는 16항목 밖 탐지 수
  "requires_approval": true,
  "score_breakdown": { "critical": 0.0, "high": 5.0, "medium": 1.0, "low": 0.0 },
  "block_reasons": ["IDOR (CWE-639, High) 검출 — 승인 필요 정책"],
  "warn_reasons": []
}
```

### verdict 값 → 백엔드 동작
| verdict | 의미 | pipeline status | 백엔드 동작 |
| --- | --- | --- | --- |
| `block` | Critical ≥ 1 | failed | **하드 차단.** 배포 불가, 승인 경로 제공 ❌. 결과 표시. |
| `block_pending_approval` | High ≥ 1 (또는 엄격env Medium) | failed | **승인 워크플로 진입** (5장). `requires_approval:true`. |
| `warn` | Medium ≥ 1 | success | 경고 배너 후 배포 진행. |
| `pass` | Low만/없음 | success | 정상 배포. |

---

## 4. 백엔드가 구현할 REST API

> 경로/네이밍은 예시. 프로젝트 컨벤션에 맞춰 조정.

| # | Method · Path | 용도 | 호출자 |
| --- | --- | --- | --- |
| A | `POST /api/jobs` | 잡 생성(레포/브랜치/환경/**selected_items**) → 엔진 트리거 | 프론트 |
| B | `GET /api/jobs/{id}` | 잡 상태 + 최신 verdict + 스텝 진행 조회 | 프론트 |
| C | `POST /api/internal/engine-callback` | 엔진 webhook 수신(`x-callback-token` 검증) | 엔진 |
| D | `GET /api/jobs/{id}/approval` | 대기 중 승인 정보(차단된 High 항목/사유 요건) 조회 | 프론트 |
| E1 | `POST /api/jobs/{id}/approval/justification` | 개발자가 **수용 사유** 제출 | 개발자 |
| E2 | `POST /api/jobs/{id}/approval/decision` | 보안책임자/팀리드 **승인/거부** → 승인 시 재트리거 | 승인자 |
| F | `GET /api/security/catalog` | 16항목 카탈로그(선택 UI용) — 엔진 카탈로그 미러 | 프론트 |
| G | `GET /api/jobs/{id}/audit` | 해당 잡 승인/감사 이력 조회 | 감사/프론트 |

### 4-A `POST /api/jobs` 요청 예시
```json
{
  "repo_url": "https://github.com/org/repo.git",
  "branch": "feature/x",
  "environment": "production",
  "selected_items": ["CWE-89", "idor", "xss"]   // 빈 배열/생략 = 16개 전체
}
```
처리: 검증 → job 레코드 생성(상태 `QUEUED`) → 엔진 CLI 트리거(`--selected-items`에 정규화해 전달) → `job_id` 반환.

### 4-C 콜백 수신 처리
1. `x-callback-token` 헤더가 발급한 시크릿과 일치하는지 검증(불일치 401).
2. `type`으로 분기: `step_complete`는 진행상황/스텝 로그 갱신, `pipeline_complete`는 최종 `verdict` 저장 + 상태머신 전이(5장).
3. 멱등 처리: 같은 `run_id`+`step.name`/완료 콜백 중복 수신 대비(재시도가 있음 — 엔진은 5/15/30초 백오프 재전송).

---

## 5. High 승인 예외 워크플로 (★ 핵심)

### 5-A 잡 상태머신
```
QUEUED → RUNNING → ┬─ PASSED                (verdict pass/warn, status success)
                   ├─ BLOCKED               (verdict block: Critical, 종료)
                   └─ PENDING_APPROVAL      (verdict block_pending_approval)
                          │
            justification 제출 (개발자)
                          ▼
                   AWAITING_DECISION
                     │            │
            approve(승인자)   reject(승인자)
                     ▼            ▼
            APPROVED→재트리거   REJECTED (종료)
                     │
          엔진 재실행(--approved-cwes)
                     ▼
            RUNNING → PASSED/BLOCKED/...
```

### 5-B 데이터 모델 (예시 스키마)
```
job(
  id, repo_url, branch, environment, commit_sha,
  selected_items JSON, status,           -- QUEUED/RUNNING/PASSED/BLOCKED/PENDING_APPROVAL/AWAITING_DECISION/APPROVED/REJECTED
  latest_run_id, latest_verdict JSON,
  created_at, updated_at
)

approval_request(
  id, job_id, commit_sha,
  target_cwes JSON,            -- 차단을 유발한 High CWE 목록 (verdict.block_reasons/ findings에서 추출)
  justification TEXT,          -- 개발자 수용 사유
  justified_by, justified_at,
  status,                      -- pending / approved / rejected
  decided_by, decided_at, decision_reason,
  expires_at                   -- 무기한 예외 금지: 만료 필수 권장
)

audit_log(                     -- append-only, 수정/삭제 불가
  id, job_id, commit_sha, event,   -- created/justified/approved/rejected/retriggered/expired
  actor_id, actor_role, target_cwes JSON, detail JSON, created_at
)
```

### 5-C 절차 (정책 §3-1 매핑)
1. `pipeline_complete` 콜백의 verdict가 `block_pending_approval` → job `PENDING_APPROVAL`로 전이, `approval_request` 생성(`target_cwes` = High로 차단된 CWE들; `verdict.counts`/`findings`에서 `severity=="high" && in_scope`인 CWE 수집), commit_sha 기록.
2. 개발자가 `E1`로 **수용 사유** 제출 → `AWAITING_DECISION`, `audit_log(event=justified)`.
3. 보안책임자/팀리드가 `E2`로 승인/거부.
   - **권한 검증 필수**: 승인자 role이 보안책임자/팀리드인지 확인(개발자 본인 승인 금지).
   - 승인 → `audit_log(event=approved, actor, target_cwes, commit_sha)` + `expires_at` 설정.
   - 거부 → `REJECTED` 종료.
4. 승인 시 **엔진 재트리거**: 동일 `commit_sha`, 동일 `selected_items`, 추가로 `--approved-cwes "<승인된 CWE들>"`. (7장)
5. **커밋 한정 스코프**: 승인은 그 `commit_sha`에만 유효. 새 커밋이 들어오면 `approval_request`를 재사용하지 말 것 — 새 잡은 처음부터 다시 게이트. 같은 High가 남아 있으면 다시 `PENDING_APPROVAL`.

### 5-D Critical 처리
- `verdict == "block"`(Critical)에는 **승인 경로를 만들지 말 것.** UI에서 승인 버튼 노출 금지. `BLOCKED` 종료.

### 5-E 감사/거버넌스 규칙
- 감사 로그는 **append-only** (수정·삭제 불가, 누가/언제/무엇을/왜).
- 무기한 예외 금지: `expires_at` 필수, 만료 시 자동 `expired` 처리.
- 승인은 "취약점 무시"가 아니라 "기한부 수용"임을 UI 문구로 명시.

---

## 6. 결과 화면 API/표기 규칙

`GET /api/jobs/{id}` 응답으로 프론트에 아래를 제공하고, 화면은 규칙대로 렌더한다.

1. **점수 + 검사범위 병기**: `score_label`("82/100 (검사 항목 9개 기준)") 그대로 표기. `selected_items` 목록을 함께 노출. **미선택 항목은 "안전"이 아니라 "미검사"로 구분.** `out_of_scope_count>0`이면 "정책 범위 밖 추가 탐지 N건" 보조 안내.
2. **게이지 색상은 `gauge_color` 그대로 사용.** 점수 구간으로 색을 **재계산하지 말 것** (재계산하면 verdict와 모순 — 예: High 95점이 초록으로 보임).
3. **게이트 카드 별도 노출**: "Critical=차단 / High=승인필요 / Medium=경고 / Low·없음=통과" 위계를 메인으로. 점수 쓰레숄드를 메인처럼 두지 말 것.
4. **실패 사유는 `block_reasons`/`warn_reasons` 그대로**: "SQL Injection (CWE-89, Critical) 검출 — 즉시 차단 정책" 형식으로 이미 옴. "취약점 발견" 같은 모호한 문구로 덮지 말 것.
5. **분류는 CWE로 통일**: finding의 `cwe`/`policy_item` 사용(CVE 아님). 항목명·CWE 매핑은 카탈로그(1장) 기준.
6. **승인 대기 표시**: `requires_approval:true`면 승인 상태/승인자/사유/만료를 카드로 표시.

---

## 7. 엔진 측 의존성 1건 — `--approved-cwes` (엔진 담당에게)

승인→재배포가 동작하려면 엔진에 아래가 필요하다(현재 미구현):

- 신규 CLI 인자 `--approved-cwes "CWE-639,CWE-347"`.
- 게이트 평가 시: `severity==high && in_scope && cwe ∈ approved-cwes`인 High finding은 **차단 사유에서 제외**(인지·수용됨으로 처리). 그 결과 High만 남았다면 verdict는 `pass`/`warn`이 되어 배포 단계로 진행.
- 단, **Critical(`block`)은 절대 승인 불가** — `--approved-cwes`로도 해제되지 않음.
- verdict에 `acknowledged_cwes` 필드를 추가해 어떤 High가 수용됐는지 콜백으로 회신(감사용).

> 이 1건만 엔진에 추가하면 백엔드의 5장 재트리거가 그대로 동작합니다.

---

## 8. 회귀 주의 (기존 연동이 있다면)

- verdict 스키마 변경: **`thresholds` 필드 제거**, 신규 필드(`score_label` `gauge_color` `selected_items` `selected_count` `out_of_scope_count` `requires_approval` `score_breakdown`) 추가, verdict 값에 **`block_pending_approval` 신설**.
- 기존에 `verdict == "block"`만 차단 처리하던 코드 → **`block_pending_approval`도 차단**으로 수정.
- finding에 `cwe` / `policy_item` / `in_scope` 추가(기존 필드 유지).
- 환경별 점수 threshold(production=85 등)는 **폐기됨**. environment는 이제 "추가 엄격성"만(§정책 3-2).

---

## 9. 인수 기준 (테스트 시나리오)

| # | 입력 | 기대 |
| --- | --- | --- |
| 1 | SQL Injection 탐지 | verdict `block`, 빨강, 승인 버튼 없음, `BLOCKED` 종료 |
| 2 | IDOR 1건 | verdict `block_pending_approval`, 주황, `PENDING_APPROVAL`, 승인 UI 노출 |
| 3 | #2에서 개발자 사유 제출 → 팀리드 승인 | 엔진 재트리거(`--approved-cwes=CWE-639`) → `PASSED`, 감사로그 4건(created/justified/approved/retriggered) |
| 4 | #2에서 개발자 본인이 승인 시도 | 권한 거부(403) |
| 5 | 승인된 커밋 위에 새 커밋(같은 IDOR) push | 다시 `PENDING_APPROVAL` (이전 승인 무효) |
| 6 | XSS 2건만, env=development | verdict `warn`, 노랑, 배포 진행 |
| 7 | XSS 2건만, env=production | verdict `block_pending_approval` (Medium 승격), 승인 필요 |
| 8 | selected_items=[CWE-89]인데 IDOR만 탐지 | verdict `pass`, `out_of_scope_count=1`, 화면에 "범위 밖 1건" 안내 |
| 9 | 콜백에 잘못된 `x-callback-token` | 401, 잡 상태 변동 없음 |
