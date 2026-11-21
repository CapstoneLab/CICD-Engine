# 논문 작업 노트 (Paper Worklog)

> 본 문서는 CI/CD 파이프라인 엔진 + 수소추진 선박 디지털트윈 논문에 관한
> 전체 논의·결정·초안을 한 곳에 모은 **논문 전용 작업 허브**다.
> 실험 지시는 별도 문서 → [`KCI_EXPERIMENT_WORKORDER.md`](KCI_EXPERIMENT_WORKORDER.md)

---

## 0. 핵심 결정 사항 (Decisions)

| 항목 | 결정 |
|------|------|
| 목표 등급 | **KCI 우선** (이후 SCI 확장 여지) |
| 1차 정체성 | **보안 / DevSecOps 중심** (디지털트윈은 적용·실증 사례) |
| 주인공 | **우리가 개발한 CI/CD 파이프라인** (디지털트윈은 검증 vehicle) |
| 정량 평가 | 가능 (후배들이 직접 실행) |
| 타깃 저널(예시) | 정보보호학회논문지(JKIISC), 정보과학회 계열 |

**한 줄 주장(thesis):** 디지털트윈은 사이버-물리 시스템(CPS)이므로 1순위 위협은 *실시간 데이터 채널*이며,
제안 파이프라인의 보안 게이트가 그 위협(평문 WebSocket, CWE-319)을 빌드·배포 이전에 자동 차단함을 실증한다.

---

## 1. 대상 시스템 ① — 우리 파이프라인 (CICD-Engine)

### 1.1 개요
백엔드 잡 큐에서 폴링한 작업을 받아 클론 → (언어 자동감지) 설치/테스트/빌드 → **CWE 16종 보안 게이트** →
AWS EC2 자동배포까지 수행하는 단일 머신 CI/CD 엔진. Node/Python/Java 3개 런타임 자동 대응.
실제 엔진 코드 약 7,900줄(.venv·workspace·runs 제외), Python 단일 언어.

### 1.2 실행 흐름
```
backend job queue
   │  poller.py: HTTP 폴링 → claim → subprocess spawn
   ▼
main.py ──► LocalOrchestrator.run()  [orchestrator.py]
   ├─ clone           (항상 첫 스텝, 엔진이 직접 실행)
   ├─ env_check       (.env.example 키 충족 여부)
   ├─ resolve_workflow(repo의 .localci/workflow.yml or 템플릿 생성)
   └─ for step in workflow:
        install → lightweight_security_scan(gitleaks)
        → test → deep_security_scan(semgrep)
        →  ★ security_gate ★  (deep_security_scan 직후 삽입)
        → build → deploy
   ▼
콜백 전송 (스텝별 step_complete + 최종 pipeline_complete)
```

두 진입점:
- **poller.py** — 운영 모드(systemd 상주). `/api/jobs/pending` 폴링 → `claim` → `main.py` 자식 프로세스 기동 + reaper.
- **main.py** — CLI 직접 실행. 인자: `--source`, `--environment`, `--selected-items`, `--approved-cwes`, `--commit`, `--repo-token`.

### 1.3 핵심 차별점 — 보안 정책 게이트 (논문 메인 기여)
파일: `app/security_catalog.py`, `app/security_policy.py`

**(a) 16종 CWE 카탈로그 = 단일 진실 공급원(SSOT)**
- Critical 4 / High 4 / Medium 4 / Low 4 = 16개를 CWE-ID에 고정 매핑.
- **스캐너가 매긴 severity를 신뢰하지 않음** — CWE만 추출 후 카탈로그에서 등급 재결정.
  (`semgrep_parser.py:131`, `gitleaks_parser.py:38`)
- → 도구 간 등급 불일치를 정책으로 정규화 (도구 교체에 불변).

**(b) 계층형 게이트 + 점수는 자문용** (`security_policy.py:208`)
- 판정은 점수가 아닌 등급 계층: Critical≥1→block(예외불가), High≥1→block_pending_approval(승인예외만),
  Medium≥1→warn(통과), else pass.
- 점수(100점)는 보조 지표.

**(c) 무모순 점수 모델** (`security_catalog.py:32`)
- 등급별 감점 상한: 하위 등급 총합 < 상위 등급 1건 (High≤19<20, Med≤4<5, Low≤0.9<1).
- 게이지 색상도 점수 구간이 아닌 판정에서 파생 → 색상-판정 모순 불가.

**(d) 환경별 단조강화(완화 불가)** (`security_policy.py:228`)
- production/staging에선 Medium-only warn도 승인필요로 격상. 절대 완화 없음.

**(e) 승인 예외 + 선택 범위**
- `approved_cwes`로 들어온 High는 통과(acknowledged), **Critical은 절대 예외 불가** (`security_policy.py:158`).
- 선택 항목만 in-scope, 미선택은 "안전"이 아닌 "미검사(out-of-scope)"로 분리 보고.

### 1.4 부가 설계 포인트
- **멀티런타임 자동대응**: 마커로 런타임 감지, 선언↔실제 불일치 시 자동 보정, 모노레포 하위탐색.
  - Python: AST 기반 ASGI 진입점 자동 탐지(factory면 kwargs 주입 wrapper 생성).
  - Java: 래퍼 감지/시스템 바이너리 폴백, 테스트 인프라 실패 vs 로직 실패 구분.
- **로그 마스킹**: 환경변수 KEY/SECRET/TOKEN 등 + 인라인 할당 마스킹(`secrets.py`, `shell.py:35`). 클론 토큰도 마스킹.
- **AI 권고**: semgrep 발견마다 Claude(`claude-sonnet-4-6`)로 한국어 4문장 수정 가이드 생성(`ai_recommender.py`).
- **콜백 신뢰성**: 스텝별 즉시 콜백 + 최종 콜백(재시도 5/15/30초), 실패 시 로컬 저장.
- **배포**: S3 업로드 → SSM Run Command로 EC2 배포. 런타임별 포트 슬라이스, 포트 강제 wrapper,
  해시 기반 중복 배포 방지 + 헬스체크, nginx 동적 리버스 프록시.
- **인프라**: CDK로 t3.micro 단일 EC2 + S3 + SSM (프리티어 지향).

---

## 2. 대상 시스템 ② — 수소추진 선박 디지털트윈

`hydrogen-ship-LBTS` = **수소선박 육상시험설비(LBTS)용 3D 디지털트윈** (회사: TimSolution, 제품코드 `uipa-hydrogenship`).

기술 구성:
- **3D 렌더링**: `react-unity-webgl` → Unity WebGL로 선박 3D 모델 시각화 ("3D 디지털트윈"의 실체)
- **실시간 대시보드**: `recharts`, `react-gauge-chart` (연료/배출 게이지 = 텔레메트리 시각화)
- **데이터 연동**: `axios`로 외부 서버에서 선박 데이터 fetch
- **프론트**: React+TS+Vite / **서버**: Node.js / **배포**: Kubernetes + Docker
- **기존 CI**: Azure Pipelines → 빌드 → Docker 푸시 (**보안 검사 단계 없음**)
  - 참고: 기존 azure-pipelines.yml에 fontawesome 토큰 평문 하드코딩 존재(논문 motivation 보강 소재).

논문에서의 위치: 물리 자산 상태를 실시간 데이터로 가상 모델에 반영하는 전형적 CPS →
위협면 중심이 *실시간 데이터 채널* → 제안 게이트가 정확히 그 부분을 차단(§3).

---

## 3. 실험 결과 — run-20260604-008 (디지털트윈 1차 실행)

저장소: `https://github.com/suhodang77/hydrogen-ship-LBTS`, commit `7a34c89`, 런타임 자동감지=node, 총 ~115초.

| 단계 | 결과 | 내용 |
|------|------|------|
| clone | ✅ | 2초 |
| install | ✅ | npm ci, 90 packages, 468ms |
| lightweight-security (gitleaks) | ✅ 0건 | 비밀키 미검출 |
| test | ⏭️ skip | 테스트 부재 |
| deep-security (semgrep) | ✅ | 원시 7건 (1분 41초) |
| **security_gate** | ❌ **BLOCK** | **CWE-319로 차단** |
| build / deploy | ⏭️ skip | 게이트 차단으로 중단 |

**최종 판정: `BLOCK_PENDING_APPROVAL`, 94/100(orange), 승인 필요.**

### 3.1 원시 7건 → 정책 2건 (경보 축소 대표값)
| 원시 검출(semgrep 7건) | CWE | 등급 | 정책 판정 |
|---|---|---|---|
| Insecure WebSocket (ws://) | CWE-319 | High | **in-scope → BLOCK** |
| dangerouslySetInnerHTML (XSS) | CWE-79 | Medium | in-scope → warn |
| Missing SRI integrity | CWE-353 | – | out-of-scope |
| ReDoS (non-literal RegExp) | CWE-1333 | – | out-of-scope |
| K8s run-as-root | CWE-250 | – | out-of-scope |
| K8s privilege escalation | CWE-732 | – | out-of-scope |
| Express CSRF 미들웨어 누락 | CWE-352 | – | out-of-scope |

### 3.2 핵심 관찰 (논문 4.3의 근거)
- 차단된 유일한 High = **3D 엔진(Unity WebGL 빌드)이 실시간 데이터를 평문 `ws://`로 전송**
  (`frontend/public/unities/uipa/Build/BuildWeb.framework.js:10`).
  → 디지털트윈(CPS)에서 가장 치명적인 "데이터 채널" 위협을 빌드·배포 이전에 자동 차단.
- 점수 94점(높음)인데도 게이트는 BLOCK → **점수 임계치 모델이었다면 통과**, 계층형 모델이라 저지됨(설계 유효성 실증).
- 원시 7→정책 2 = 경보 피로 완화 실증.

---

## 4. 논문 프레이밍 (보안/DevSecOps, KCI)

### 4.1 기여 3가지
1. 클론–설치–테스트–정적보안–빌드–배포를 단일 엔진으로 수행하고 단계별 콜백하는 자기완결적 CI/CD 엔진.
2. 정적분석 도구 등급에 의존하지 않고 CWE를 정책 카탈로그에 사상해 등급을 재결정하는 보안 게이트 모델.
3. 제안 파이프라인을 실제 산업 디지털트윈에 적용해 CPS 고유 위협(실시간 채널 평문)의 자동 차단 실증.

### 4.2 KCI 보안저널용 본문 구조
1. 서론 — DevSecOps에서 보안검증의 후행/선택 문제, 디지털트윈에서 특히 위험, 기여 3가지.
2. 관련연구 — (a) CI/CD 보안 게이트(OPA, GitLab/GitHub), (b) SAST 등급 불일치, (c) 디지털트윈 보안.
   → "정책을 1급 게이트로 내장 + 스캐너 불가지론적 재등급"의 빈칸 명시.
3. **위협모델 및 요구사항** — 공격자 가정, 보호대상(배포 산출물·실시간 채널), 요구사항 R1~R4.
4. 시스템 설계 — 우리 파이프라인 (§1.2~1.4).
5. **게이트 정책 형식화** — R1~R4를 정의·정리로 (§4.4).
6. 평가 — 공개 repo 정량평가 + baseline 대비 + 디지털트윈 산업사례.
7. 논의 및 한계.
8. 결론.

### 4.3 요구사항 R1~R4 (위협모델 절)
- **R1** 도구 독립적 등급 일관성 (스캐너 교체에 불변)
- **R2** 점수-판정 무모순 (색상·점수·판정 충돌 불가)
- **R3** 환경 단조강화 (완화 불가, 강화만)
- **R4** 예외의 안전성 (Critical 무예외)

### 4.4 형식화 정리 (신규성 보강 — 코드에 이미 구현된 불변식)
- **정리 1 (계층 보존)**: 하위 등급 감점 총합 < 상위 등급 단일 감점. (증명: cap 19<20, 4<5, 0.9<1)
- **정리 2 (점수-판정 무모순)**: 게이지 색상이 판정에서 파생 → 색상-판정 모순 불가.
- **정리 3 (단조강화)**: 환경 변경은 판정을 완화하지 않음.
- **정리 4 (예외 안전성)**: 승인 예외 집합에 Critical 포함 불가.

---

## 5. 본문 초안 (작성 완료분)

> 아래는 1차 작성한 본문 초안. KCI 보안저널 문체로 §3 위협모델·§5 형식화는 추가 작성 예정.

### 제목 후보
- "CWE 정책 기반 보안 게이트를 내장한 멀티런타임 CI/CD 파이프라인과 수소추진 선박 디지털트윈 적용"
- "사이버-물리 시스템 보안을 위한 CWE 정책 기반 CI/CD 보안 게이트: 수소선박 3D 디지털트윈 적용 사례"

### 초록 (Abstract) — 초안
본 연구는 소스 저장소의 클론부터 의존성 설치·테스트·정적 보안 분석·빌드·클라우드 배포에 이르는 전 과정을
단일 엔진으로 자동화하는 CI/CD 파이프라인을 설계·구현한다. 핵심 기여는 (1) Node.js·Python·Java 프로젝트를
마커 기반으로 자동 식별·대응하는 멀티런타임 추상화, (2) 스캐너가 부여한 등급을 신뢰하지 않고 CWE 식별자를
16종 보안 정책 카탈로그에 사상하여 등급을 재결정하는 스캐너-불가지론적 보안 게이트, (3) 점수·게이지·판정이
상호 모순될 수 없도록 상한을 둔 계층형 차단 모델, (4) 탐지 항목별 한국어 수정 가이드를 자동 생성하는 LLM 연동이다.
실효성 검증을 위해 실시간 텔레메트리를 3D로 가시화하는 수소추진 선박 육상시험설비(LBTS) 디지털트윈을 투입한 결과,
디지털트윈의 가장 치명적 위협면인 실시간 데이터 전송 채널의 평문 WebSocket(CWE-319)을 빌드·배포 이전 단계에서
자동 차단하였으며, 정적분석 원시 경보 7건을 정책 관련 2건으로 축소하여 경보 피로를 완화함을 확인하였다.

**주제어**: CI/CD, DevSecOps, 정적 보안 분석, CWE, 보안 게이트, 디지털트윈, 사이버-물리 시스템

> ※ 1~6장 상세 초안은 대화 기록 기준으로 §1~4 자료가 모두 확보됨. (서론/설계/적용 본문은 본 worklog의
> §1~§4 내용을 그대로 확장하여 작성)

---

## 6. KCI 적합성 평가

| 항목 | 상태 |
|------|------|
| 실험 분량/다양성 | ✅ 충분 (KCI 기준 이상) |
| T6 정밀도/재현율 | ⚠️ **필수로 승격 필요** (보안저널은 탐지 정확도 반드시 요구) |
| 신규성 프레이밍 | ❗ 본문에서 결정 — "스캐너 불가지론적 재등급 + 무모순 계층 게이트"로 못박기 |
| 16종 카탈로그 근거 | ❗ 본문에 선정기준 명시 필요 (4×4, 공격 난이도 기반) |
| 관련연구 위치선점 | ❗ 세 갈래(CI/CD 게이트, SAST 불일치, 디지털트윈 보안) 정리 |

**결론:** 실험은 충분(단 T6 필수화). 합격 여부는 §신규성·§위협모델/정책근거·§관련연구에 달림.

### 리뷰어가 desk reject 거는 전형 3가지 (대비)
1. 신규성 한 줄이 약함 → §5 형식화(정리 1~4)로 받침.
2. "왜 이 16개냐" → 선정 기준·근거 명시.
3. 관련연구 위치선점 부족 → 빈칸에 우리를 놓기.

---

## 7. 실험 계획 요약

상세 → [`KCI_EXPERIMENT_WORKORDER.md`](KCI_EXPERIMENT_WORKORDER.md)

| # | 과제 | 우선순위 | 논문 매핑 |
|---|------|----------|-----------|
| T0 | 환경 세팅 | 필수 | 실험환경 절 |
| T1 | 데이터셋 구축(30~40개) | 필수 | 데이터셋 표 |
| T2 | 메인 배치 실행 | 필수 | 원천 데이터 |
| T3 | 경보 축소율 | 필수 | 노이즈 감소 표/그림 |
| T4 | Baseline 대비 | 필수★ | Baseline vs 제안 표 |
| T5 | 디지털트윈 심층사례(Before/After) | 필수★ | flagship 그림 |
| T6 | 정밀도/재현율 | **필수로 승격** | P/R/F1 표 |
| T7 | 등급 일관성 | 권장 | 등급 재정의 표 |
| T8 | 성능 오버헤드 | 권장 | 단계별 시간 |

⚠️ Baseline·등급일관성은 반드시 **원시 `semgrep_report.json`** 사용(재등급된 findings 쓰면 안 됨).

---

## 8. 다음 작업 (TODO)
- [ ] 실험 지시서 T6를 "강력권장 → 필수"로 수정
- [ ] §신규성 한 문단 작성 (차별점 못박기)
- [ ] §위협모델 + R1~R4 작성
- [ ] §16종 카탈로그 선정 근거 작성
- [ ] §관련연구 3갈래 작성
- [ ] §5 형식화(정리 1~4) 작성
- [ ] T5 After 실험(디지털트윈 ws→wss) 회사 협의
- [ ] 후배 results.xlsx 수신 후 §평가 표/그림 채우기
```
