# 프론트엔드 통합 가이드 — 보안 게이트 + AI 권고 표시

## 적용 위치
프론트엔드 경로: `C:\Users\suhodang1\Desktop\Mirae-Naeil-FE`

## 콜백 payload 구조 (백엔드 → 프론트 전달)

엔진이 백엔드(`/get-results`)로 POST하는 payload. 백엔드는 이걸 DB 저장 + 프론트에 노출.

```jsonc
{
  "job_id": "f1681a28-7a3e-4708-82eb-9601bee099b6",
  "type": "pipeline_complete",            // step_complete | pipeline_complete
  "status": "failed",                     // success | failed | running
  "repo_url": "https://github.com/owner/repo",
  "branch": "main",
  "started_at": "2026-05-02T10:00:00Z",
  "ended_at": "2026-05-02T10:02:30Z",

  "steps": [
    {
      "name": "clone",
      "status": "success",                // success | failed | skipped | running
      "exit_code": 0,
      "summary": "Repository cloned ...",
      "started_at": "...",
      "finished_at": "...",
      "log_file": "runs/run-.../logs/clone.log"
    },
    // ... install, lightweight-security, test, deep-security, security_gate, build, deploy
  ],

  "logs": [
    "[clone.log] $ git clone ...",
    "[deep-security.log] [semgrep] 7 finding(s): critical=0, high=0, medium=6, low=1",
    // 모든 스텝 로그 라인이 [<filename>] 프리픽스로 합쳐짐
  ],

  "security": {
    "summaries": [
      {"scanner_name": "gitleaks", "scan_type": "lightweight",
       "critical_count": 11, "high_count": 0, "medium_count": 0, "low_count": 0,
       "max_detected_severity": "critical"},
      {"scanner_name": "semgrep", "scan_type": "deep",
       "critical_count": 0, "high_count": 0, "medium_count": 6, "low_count": 1,
       "max_detected_severity": "medium", "max_cvss_score": null}
    ],

    "findings": [
      {
        "scanner_name": "semgrep",                     // gitleaks | semgrep
        "rule_id": "javascript.express.security...",
        "severity": "medium",                          // critical | high | medium | low
        "title": "...",
        "file_path": "src/routes/index.js",
        "line_number": 27,
        "message": "User data flows into the host portion of this manually-constructed HTML...",
        "cvss_score": null,                            // float | null
        "ai_recommendation": "이 취약점의 근본 원인은 ... (4문장)",  // string | null (semgrep만)
        "code_snippet": "const router = express.Router();\n\n// route handler\nrouter.get('/', (req, res) => {\n  ...\n  const html = `<a href='${req.query.host}'>link</a>`;\n  ...\n});",  // string | null - 취약점 줄 ±28줄 (총 57줄)
        "code_snippet_start_line": 3                    // int | null - 스니펫 첫 줄의 실제 파일 줄 번호
      }
    ],

    "verdict": {                                       // ★ 신규: 게이트 판단 결과
      "verdict": "block",                              // pass | warn | block
      "score": 0.0,
      "environment": "development",                    // production | staging | development | feature
      "counts": { "critical": 11, "high": 0, "medium": 6, "low": 1 },
      "thresholds": {
        "min_score": 60,
        "max_critical": 0,
        "max_high": 4,
        "max_total_findings": 50
      },
      "block_reasons": [
        "Critical findings 11 > 0",
        "Security score 0.0 < development threshold (60)"
      ],
      "warn_reasons": []
    }
  },

  "metadata": {
    "executor": "ubuntu-ci-engine",
    "run_id": "run-20260502-001",
    "workflow_name": "default-common-workflow",
    "workflow_source": "..."
  }
}
```

## UI 권장 구성

### 1. 결과 페이지 (Result Page)

**페이지 상단 — 게이트 배너**
| verdict | 색상 | 메시지 예시 |
|---|---|---|
| `pass` | 초록 | "보안 게이트 통과 (점수 93/100)" |
| `warn` | 주황 | "통과 — 검토 권장 (점수 78/100, High 3건)" |
| `block` | 빨강 | "차단 (점수 0/100, Critical 11건 발견)" |

**점수 시각화**: 100점 만점 도넛 차트 / 게이지 바. `verdict.score` 사용.

**환경 표기**: `verdict.environment` 뱃지 (production/staging/development/feature).

**임계값 표시**: `verdict.thresholds`로 "현재 환경 기준: 60점 이상" 같은 안내.

**차단/경고 사유 리스트**: `verdict.block_reasons` / `verdict.warn_reasons` 그대로 bullet으로.

**심각도별 카운트**: `verdict.counts`를 색상 카드 4개로 (Critical/High/Medium/Low).

**파이프라인 단계 타임라인**: `steps[]`를 상태 아이콘과 함께 세로로 나열.

**취약점 상세 리스트**: `security.findings[]`를 severity 순(critical → low) 정렬.
- 각 finding 카드 구성:
  - 심각도 뱃지 (색상)
  - `rule_id` (모노스페이스)
  - `file_path:line_number` (클릭 시 GitHub blob URL로 이동 가능)
  - `message` (원문 영문)
  - **`code_snippet`** — 펼쳐보기/접기 (취약점 줄 ±28줄, 총 57줄, 기본 접힘)
    - syntax highlight 적용 (prism-react-renderer / shiki / react-syntax-highlighter 등)
    - 줄 번호는 `code_snippet_start_line`부터 시작
    - 취약점 줄(`line_number`)은 배경색으로 강조
    - gitleaks finding은 시크릿이 `****`로 마스킹되어 있음 (백엔드 처리)
    - `code_snippet`이 null이면 이 섹션 숨김
  - **`ai_recommendation`** — 펼쳐보기/접기 (4문장이라 길어서 기본 접힘)
  - 스캐너 표시 (`scanner_name`)

**전체 로그**: `logs[]`를 모노스페이스 코드 블록. 검색 가능하게.

### 2. 저장소 페이지 (Repository Page)

**저장소 카드 클릭** → 해당 레포의 **최신 스캔 결과** 로드:

권장 API 호출:
```
GET /api/repositories/<owner>/<repo>/latest-scan
→ payload 형식: 위와 동일한 callback payload (또는 백엔드가 단순화한 형태)
```

또는 백엔드 DB 스키마에 따라:
```
GET /api/jobs?repo=<repo_url>&order=desc&limit=1
```

**저장소 카드에 표시할 핵심 필드** (목록 화면에서 미리 보이게):
- 최신 verdict 뱃지 (pass/warn/block)
- 점수
- 마지막 스캔 시각 (`ended_at`)
- 심각도별 카운트 미니 차트

## 데이터 위치 매핑

프론트가 표시할 모든 데이터의 출처:

| UI 요소 | payload 경로 |
|---|---|
| 결과 배너 (pass/warn/block) | `security.verdict.verdict` |
| 점수 게이지 | `security.verdict.score` |
| 환경 뱃지 | `security.verdict.environment` |
| 심각도 카운트 | `security.verdict.counts.{critical,high,medium,low}` |
| 차단 사유 | `security.verdict.block_reasons[]` |
| 경고 사유 | `security.verdict.warn_reasons[]` |
| 임계값 | `security.verdict.thresholds` |
| 파이프라인 단계 | `steps[]` |
| 단계별 상태 | `steps[].status` |
| 단계별 요약 | `steps[].summary` |
| 취약점 목록 | `security.findings[]` |
| 취약점 상세 (위치) | `security.findings[].file_path:line_number` |
| 취약점 메시지 | `security.findings[].message` |
| **AI 수정 권고** | `security.findings[].ai_recommendation` ★ |
| **코드 스니펫** | `security.findings[].code_snippet` ★ (실제 줄바꿈 포함된 문자열) |
| 스니펫 시작 줄번호 | `security.findings[].code_snippet_start_line` ★ |
| 스캐너 종류 | `security.findings[].scanner_name` (gitleaks/semgrep) |
| CVSS 점수 | `security.findings[].cvss_score` (있으면) |
| 전체 로그 | `logs[]` |
| 메타데이터 | `metadata.{run_id, workflow_name}` |

## 색상 가이드

심각도 색상 (Tailwind 권장):
| 심각도 | 색상 | hex |
|---|---|---|
| critical | red-600 | `#dc2626` |
| high | orange-500 | `#f97316` |
| medium | yellow-500 | `#eab308` |
| low | sky-500 | `#0ea5e9` |
| pass (verdict) | green-600 | `#16a34a` |
| warn (verdict) | amber-500 | `#f59e0b` |
| block (verdict) | red-600 | `#dc2626` |

## 코드 스니펫 렌더링 가이드

`security.findings[].code_snippet`은 취약점 줄 기준 **앞뒤 28줄, 총 57줄**의 실제 소스 코드입니다 (파일이 57줄보다 짧으면 가능한 만큼). JSON에는 진짜 줄바꿈(`\n` 문자)으로 저장되어 있어 별도 변환 없이 syntax highlight 라이브러리에 그대로 넣으면 됩니다.

### 추천 라이브러리

| 라이브러리 | 비고 |
|---|---|
| `prism-react-renderer` | 가볍고 React 친화적 |
| `shiki` | 가장 정확한 하이라이트, 무겁지만 결과 좋음 |
| `react-syntax-highlighter` | 다양한 테마, 가장 흔히 쓰임 |

### 언어 자동 감지

`file_path` 확장자로 매핑:

```ts
const detectLanguage = (filePath: string): string => {
  const ext = filePath.split('.').pop()?.toLowerCase();
  const map: Record<string, string> = {
    js: 'javascript', jsx: 'jsx', ts: 'typescript', tsx: 'tsx',
    py: 'python', java: 'java', kt: 'kotlin', go: 'go',
    rb: 'ruby', php: 'php', rs: 'rust', cs: 'csharp',
    html: 'html', css: 'css', json: 'json', yml: 'yaml', yaml: 'yaml',
  };
  return map[ext ?? ''] ?? 'text';
};
```

### 줄 번호와 취약점 줄 강조

스니펫 첫 줄은 파일의 `code_snippet_start_line`번 줄. 취약점은 `line_number`번 줄.

```tsx
const lines = finding.code_snippet?.split('\n') ?? [];
const startLine = finding.code_snippet_start_line ?? 1;

lines.map((line, idx) => {
  const actualLineNumber = startLine + idx;
  const isVulnLine = actualLineNumber === finding.line_number;
  return (
    <div className={isVulnLine ? 'bg-red-100 dark:bg-red-900/30' : ''}>
      <span className="text-gray-500 mr-3">{actualLineNumber}</span>
      <span>{line}</span>
    </div>
  );
});
```

### 마스킹 표시

gitleaks finding의 `code_snippet`은 시크릿 값이 `****`로 백엔드에서 미리 치환되어 있습니다. 프론트는 별도 처리 없이 그대로 렌더링하면 됩니다. 참고로 사용자 친화적 표시를 원하면 `****` 위에 작은 자물쇠 아이콘(🔒)을 오버레이하거나 "마스킹됨" 툴팁을 추가하는 것도 좋습니다.

## 백엔드 측 작업 체크리스트

프론트 작업 전 백엔드(`http://192.168.0.2:8010`)가 다음을 준비해야 함:

1. **DB 스키마**에 `security_findings`, `security_verdicts`, `pipeline_runs` 테이블 (또는 동등한 스토리지)
2. **콜백 핸들러**(`POST /get-results`)가 새 `security.verdict` 필드 저장
3. **조회 API**:
   - `GET /api/jobs/<job_id>` — 단일 파이프라인 전체 정보
   - `GET /api/repositories` — 저장소 목록
   - `GET /api/repositories/<repo_url>/latest-scan` — 최신 스캔 결과
4. **CORS** 설정 (프론트 dev 서버 도메인 허용)

## 정책 요약 (사용자에게 보여줄 때)

UI에 정책 설명을 보여주고 싶으면 이 표 활용:

| verdict | 조건 |
|---|---|
| 🔴 BLOCK | Critical ≥ 1 / High ≥ 5 / 점수 < 환경기준 / 총 취약점 > 50 |
| 🟡 WARN | High 1~4건 또는 Medium ≥ 20건 (BLOCK 아닌 경우) |
| 🟢 PASS | 위 조건 모두 미해당 |

| 환경 | 최소 점수 | 추가 조건 |
|---|---|---|
| production | 85점 | Critical 0 + High ≤ 2 |
| staging | 75점 | Critical 0 |
| development | 60점 | Critical 0 |
| feature | 50점 | Critical 0 |

점수: `100 - Critical×20 - High×5 - Medium×1 - Low×0.2` (Critical 5개 이상이면 0점)
