# 보안 정책 게이트를 내장한 멀티런타임 CI/CD 파이프라인 *SecuPipeline*
## — 캡스톤디자인 결과보고서 —

---

## 목차

1. 서론
2. 관련 연구 및 기술 배경
3. 시스템 전체 구조
4. 프론트엔드 설계 및 구현
5. 백엔드 설계 및 구현
6. CI/CD 엔진 설계 및 구현
7. 핵심 기여 — CWE 정책 기반 보안 게이트
8. 구현 결과 및 검증
9. 결론 및 향후 과제
10. 참고문헌

---

## 요약 (Abstract)

본 연구는 소스 저장소의 클론부터 의존성 설치·테스트·정적 보안 분석·빌드·클라우드 배포에 이르는 전 과정을 단일 엔진으로 자동화하고, 그 중심에 **보안 게이트를 1급 단계로 내장**한 CI/CD 플랫폼 *SecuPipeline*을 설계·구현한 결과를 기술한다. 기존 CI/CD가 빌드·배포 자동화에 치중하여 보안 검증을 후행·선택적으로 처리하는 문제, 정적 분석 도구마다 동일 취약점에 상이한 심각도를 부여하여 차단 기준이 도구에 종속되는 문제, 그리고 방대한 경보로 인해 핵심 위협이 묻히는 경보 피로(alert fatigue) 문제를 동시에 해결하는 것을 목표로 한다.

핵심 기여는 (1) Node.js·Python·Java 프로젝트를 마커 기반으로 자동 식별·대응하는 멀티런타임 추상화, (2) 스캐너가 부여한 등급을 신뢰하지 않고 발견 항목의 CWE 식별자를 16종 보안 정책 카탈로그에 사상하여 등급을 재결정하는 스캐너-불가지론적 보안 게이트, (3) 점수·게이지 색상·배포 판정이 상호 모순될 수 없도록 감점 상한을 둔 계층형 차단 모델, (4) 탐지 항목별 한국어 수정 가이드를 자동 생성하는 LLM 연동, (5) 보안 비전문가도 배포 가능 여부와 위험 항목을 직관적으로 파악할 수 있는 Electron 데스크톱 GUI이다. 시스템은 Electron 기반 데스크톱 프론트엔드, FastAPI 기반 작업 큐 백엔드, Python 기반 CI/CD 엔진의 세 구성요소가 GitHub OAuth·JWT·작업 큐 폴링·HTTP 콜백으로 연동되는 분산 구조로 구현되었다. 실저장소를 대상으로 한 검증에서, 정적 분석 원시 경보 7건이 정책 관련 2건으로 축소되었으며, 점수가 높음에도(94/100) 위계 기반 게이트가 평문 전송 취약점을 배포 이전에 자동 차단함으로써 설계의 유효성을 확인하였다.

**주제어**: CI/CD, DevSecOps, 정적 보안 분석, CWE, 보안 게이트, 멀티런타임, 경보 피로

---

## 1. 서론

소프트웨어 개발에서 CI/CD(Continuous Integration / Continuous Deployment)는 코드 변경의 통합과 배포를 자동화하여 릴리스 주기를 단축하고 휴먼 에러를 줄이는 핵심 방법론으로 자리잡았다. 그러나 현장의 CI/CD 파이프라인은 대부분 빌드와 배포의 자동화에 집중하는 반면, 보안 검증은 파이프라인의 부가 단계로 취급되거나 별도의 보안 담당자가 배포 이후에 수동으로 점검하는 데 그치고 있다. 보안 검증이 배포 이후로 밀리면 취약점이 포함된 산출물이 이미 운영 환경에 도달한 뒤에야 문제가 드러나며, 이때의 사고 대응 비용은 개발 단계에서 동일한 결함을 수정하는 비용보다 훨씬 크다. 이는 보안을 개발 과정의 앞단으로 끌어오는 "Shift-Left Security"가 강조되는 배경이다.

보안 검사를 파이프라인에 자동으로 포함하더라도 또 다른 장벽이 존재한다. gitleaks·semgrep과 같은 정적 분석 도구의 출력은 전문적이고 양이 방대하여, 보안 전문 지식이 없는 일반 개발자가 "이 결과를 보고 지금 배포해도 되는가"를 판단하기 어렵다. 더 근본적으로, 도구마다 동일한 취약점에 서로 다른 심각도(severity)를 부여하기 때문에 어떤 기준으로 배포를 막을지에 대한 일관성을 확보하기 어렵고, 도구를 교체하거나 버전을 올리면 같은 코드에 대한 판정이 흔들린다. 또한 정적 분석은 배포 맥락과 무관한 경보까지 다량으로 생성하여, 정작 배포를 막아야 할 치명적 위협이 그 속에 묻히는 경보 피로(alert fatigue)를 유발한다. 경보 피로는 개발자가 경보 전체를 무시하게 만들어 보안 자동화의 본래 목적을 무력화한다.

이상의 세 가지 문제 — 보안의 후행 처리, 등급의 비일관성, 경보 피로 — 를 종합하면, 빌드·배포 과정 안에 보안 검사를 1급 단계로 내장하고, 그 결과를 도구에 독립적인 기준으로 통과/경고/차단으로 자동 판정하며, 그 판정을 비전문가도 이해할 수 있도록 시각화하는 통합 CI/CD 시스템이 필요하다. 본 캡스톤디자인은 이 필요성에 따라 보안 게이트를 핵심으로 하는 자체 CI/CD 플랫폼 *SecuPipeline*을 설계·구현하였으며, 구체적 목표는 다음과 같다. 첫째, 클론부터 클라우드 배포까지 전 과정을 단일 엔진으로 자동화한다. 둘째, Node.js·Python·Java 등 서로 다른 런타임을 자동 인식하여 별도 설정 없이 처리한다. 셋째, 발견 항목의 CWE를 정책 카탈로그에 사상해 등급을 재결정하고 위계에 따라 배포 가능 여부를 판정한다. 넷째, 점수·색상·판정이 모순되지 않는 정직한 평가 모델을 제공한다. 다섯째, 결과를 데스크톱 GUI와 AI 수정 권고로 시각화하여 비전문가의 의사결정을 돕는다.

기존의 범용 CI 서비스(GitHub Actions, GitLab CI 등)도 보안 스캔을 단계로 추가할 수는 있으나, 차단 정책을 도구의 종료 코드(exit code)나 도구가 매긴 severity에 의존하여 위에서 지적한 등급 비일관성·경보 피로 문제를 그대로 떠안는다. 본 프로젝트는 "정책을 1급 게이트로 내장하고 스캐너에 독립적으로 재등급하는" 접근으로 이와 구분된다. 본 보고서는 2장에서 기술 배경을, 3장에서 시스템 전체 구조를, 4~6장에서 프론트엔드·백엔드·엔진의 설계와 구현을, 7장에서 핵심 기여인 보안 게이트를, 8장에서 검증 결과를, 9장에서 결론을 기술한다.

---

## 2. 관련 연구 및 기술 배경

CI(Continuous Integration)는 여러 개발자의 코드 변경을 빈번하게 통합하고 매 통합마다 자동 빌드·테스트를 수행하여 통합 결함을 조기에 발견하는 실천법이고, CD(Continuous Deployment/Delivery)는 통합을 통과한 산출물을 자동으로 배포 가능 상태로 만들거나 운영에 반영하는 실천법이다. DevSecOps는 이 흐름에 보안을 통합한 개념으로, 보안을 릴리스 직전의 게이트나 별도 팀의 사후 점검이 아니라 개발 파이프라인 전 과정에 내재된 책임으로 본다. 그 핵심 원칙인 "Shift-Left Security"는 보안 검증을 가능한 한 개발 초기로 이동시켜 결함을 값싸게 고칠 수 있는 시점에 발견하는 것을 지향한다. 본 프로젝트는 이 철학을 구체적 메커니즘으로 구현하여, 빌드와 배포 사이에 통과 없이는 다음 단계로 진행할 수 없는 보안 게이트를 강제로 배치한다.

본 시스템이 사용하는 정적 보안 분석(SAST)은 프로그램을 실행하지 않고 소스 코드·구성 파일을 분석하여 취약점을 찾는 기법으로, 두 단계로 구성된다. **gitleaks**는 소스와 커밋 이력에 하드코딩된 비밀정보(API 키, 토큰, 비밀번호, 개인키 등)를 정규식·엔트로피 기반으로 탐지하는 경량 스캔이고, **semgrep**은 언어별 구문 패턴 규칙으로 SQL Injection·XSS·평문 전송 등 코드 내부 취약점을 탐지하는 심층 스캔이다. 두 도구 모두 발견 항목에 CWE 식별자를 제공하거나 규칙 메타데이터로부터 CWE를 유추할 수 있다.

CWE(Common Weakness Enumeration)는 MITRE가 관리하는 소프트웨어 취약점 "유형"의 표준 분류 체계로, 개별 취약 사례를 가리키는 CVE와 달리 취약점의 종류를 식별한다(예: CWE-89=SQL Injection, CWE-798=하드코딩된 자격증명, CWE-319=평문 전송). 도구가 매기는 severity는 같은 취약점에도 도구별·규칙별로 달라질 수 있는 반면, CWE는 취약점의 본질적 유형을 가리키는 안정적 식별자이다. 본 시스템은 이 점에 착안하여 도구의 임의적 severity 대신 CWE를 단일 기준으로 등급을 재결정함으로써, "도구를 바꿔도 같은 코드에 같은 판정"이라는 일관성을 확보한다. 요컨대 본 시스템은 (1) 발견 항목의 CWE를 정책 카탈로그로 재사상하는 스캐너 불가지론적 재등급, (2) 등급별 감점 상한과 판정 파생 색상으로 보장되는 무모순 계층형 게이트, (3) 운영·스테이징에서 판정을 강화만 하는 단조강화 정책, (4) 선택 항목만 게이트에 반영하고 나머지는 "미검사"로 분리하는 스코핑을 정책 엔진에 내장했다는 점에서 기존 접근과 차별화된다(7장).

---

## 3. 시스템 전체 구조

*SecuPipeline*은 역할이 분리된 세 개의 독립 구성요소가 표준 프로토콜로 연동되는 분산 시스템이다. 사용자는 데스크톱 앱으로 검사를 요청하고, 백엔드는 인증·작업 큐·결과 저장을 담당하며, CI/CD 엔진은 실제 파이프라인을 실행하고 보안 게이트를 적용한다.

```
┌─────────────────────────┐        ┌──────────────────────────────┐
│  SecuPipeline Desktop    │  HTTPS  │     FastAPI Backend           │
│  (Electron + React 19)   │◄──────►│  (트리거 서버 + 작업 큐 + DB)  │
│  - GitHub OAuth 로그인    │  JWT   │  - GitHub OAuth / JWT 발급     │
│  - 16종 항목·환경 선택     │        │  - 작업 enqueue / claim        │
│  - 파이프라인 시작/조회    │        │  - 결과 저장 (PostgreSQL)      │
│  - 보안 결과 시각화        │        │  - 승인 워크플로 / 감사 로그   │
└─────────────────────────┘        └──────────────┬───────────────┘
                                       폴링(pending)│ │ 콜백(get-results)
                                          claim     │ ▼
                                    ┌──────────────────────────────┐
                                    │     CICD-Engine (Ubuntu)      │
                                    │  poller.py → main.py          │
                                    │  clone→install→test→scan      │
                                    │  →★ 보안 게이트 ★→build→deploy │
                                    │  - 멀티런타임 자동인식         │
                                    │  - CWE 16종 정책 판정          │
                                    │  - AI 수정 권고 생성           │
                                    └──────────────┬───────────────┘
                                                  │ S3 업로드 → SSM 배포
                                                  ▼
                                          AWS EC2 / S3 / SSM
```

| 구성요소 | 저장소 | 역할 | 주요 기술 |
|----------|--------|------|-----------|
| 프론트엔드 | Capstone-FE | 로그인·검사 요청·결과 시각화·승인 처리 | Electron, React 19, TypeScript, Tailwind v4 |
| 백엔드 | Capstone-Back | 인증·작업 큐·결과 저장·승인·감사 로그 | FastAPI, SQLAlchemy(async), PostgreSQL |
| CI/CD 엔진 | CICD-Engine | 파이프라인 실행·보안 게이트·AI 권고·배포 | Python(약 7,400줄), gitleaks, semgrep, AWS |

이 분리 구조는 세 가지 이점을 가진다. 첫째, 엔진이 상태를 보유하지 않고(stateless) 작업 큐를 폴링·선점하는 모델이므로 엔진을 늘리거나 교체해도 백엔드 계약만 지키면 된다. 둘째, 사용자 인터페이스와 실행 인프라가 분리되어 각각 독립적으로 발전·배포할 수 있다. 셋째, 결과가 모두 백엔드 DB에 영속화되어 이력 추적·감사·재조회가 가능하다. 통신 경계는 두 가지로, 프론트↔백엔드는 JWT 인증으로, 백엔드↔엔진은 엔진 토큰(`x-engine-token`)과 콜백 토큰(`x-callback-token`)으로 보호된다.

전체 시스템의 한 사이클은 다음 순서로 진행된다. ① 사용자가 데스크톱 앱에서 GitHub로 로그인하면 외부 브라우저로 OAuth 동의가 열리고, 백엔드가 access_token을 암호화 저장한 뒤 JWT를 발급한다. ② 사용자가 저장소·브랜치·검사할 16종 항목·환경·(선택)커밋을 지정해 파이프라인 시작을 요청한다(`POST /api/pipelines`). ③ 백엔드가 작업을 큐에 적재하고 즉시 `job_id`를 응답하며, 프론트는 진행 상황을 폴링하기 시작한다. ④ 엔진(poller)이 `GET /api/jobs/pending`으로 대기 작업을 폴링하고 `claim`으로 선점한 뒤 `main.py`를 자식 프로세스로 기동한다. ⑤ 엔진이 clone→환경검사→install→경량 보안검사→test→심층 보안검사→**보안 게이트**→build→deploy를 순차 수행하며, 게이트에서 차단되면 build/deploy는 수행되지 않는다. ⑥ 엔진이 스텝별 `step_complete`와 최종 `pipeline_complete` 콜백을 백엔드(`POST /get-results`)로 전송해 DB에 저장한다. ⑦ 프론트가 조회 API로 판정·점수·취약점·AI 권고를 받아 시각화한다. ⑧ 판정이 `block_pending_approval`이면 사용자가 승인/거부하고, 승인 시 백엔드가 후속 작업을 재적재해 재스캔 후 배포한다. 이처럼 검사 요청과 실행이 비동기로 분리되어, 장시간 걸리는 스캔·빌드가 사용자 요청을 블로킹하지 않는다.

---

## 4. 프론트엔드 설계 및 구현

프론트엔드는 **Electron 기반 데스크톱 애플리케이션** *SecuPipeline Desktop*으로 구현되었다. 웹 앱이 아닌 데스크톱 앱을 선택한 이유는 개발자의 GitHub 자격증명과 보안 결과를 OS 수준에서 격리된 환경에서 다루고, 외부 브라우저 기반 OAuth와 로컬 파일(엑셀) 내보내기를 자연스럽게 지원하며, 보안 도구라는 제품 정체성에 설치형 클라이언트가 부합하기 때문이다. UI는 React 19 + TypeScript로 작성하고 Tailwind CSS v4로 스타일링하며, Radix UI 기반 shadcn 스타일 컴포넌트와 chart.js로 시각화한다. 화면 전환은 react-router-dom 7, 결과 내보내기는 `xlsx`로 구현하였고, 인증·테마·확대 상태를 React Context로 전역 관리한다. 데스크톱 앱 자체의 공격면을 줄이기 위해 `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`, `allowRunningInsecureContent: false`로 설정하고, 외부 내비게이션은 https 링크만 외부 브라우저로 열도록 제한하였다. 로그인은 GitHub OAuth로 수행되며, 백엔드가 발급한 JWT를 `secupipeline:token`으로 보관하고 모든 API 호출에 `Authorization: Bearer` 헤더로 첨부한다.

주요 화면은 `src/App.tsx`의 라우팅을 기준으로, 홈(HomePage)·GitHub 로그인(AuthPage)·대시보드(DashboardPage)·저장소 상세(RepositoryDetailPage)·새 파이프라인(NewPipelinePage)·진행 상황(PipelineProcessPage)·결과(PipelineProgressPage)·승인(ApprovalPage)·감사 로그(AuditLogPage)·문서(DocsPage)로 구성된다. 새 파이프라인 화면은 16종 항목을 4등급으로 묶어 체크박스로 제시하고(카탈로그는 `GET /api/security/catalog`로 로드), 등급별 일괄 선택과 최소 1개 선택 강제, 환경 드롭다운(development/feature/staging/production)을 제공한다. 검사 시작 후에는 `GET /api/jobs/{id}`를 폴링하여 스텝별 타임라인과 진행률을 표시한다.

결과 화면은 본 시스템의 사용성을 결정하는 핵심 화면으로, 다음 원칙을 따른다. **게이트 위계 카드 우선 노출** — 점수 게이지보다 "Critical≥1→차단 / High≥1→승인필요 / Medium≥1→경고 / 그 외 통과"의 위계 카드를 상단에 두고 현재 판정 위치를 강조한다. **판정 4종 구분** — pass(🟢)·warn(🟡)·block_pending_approval(🟠 승인 경로 존재)·block(🔴 승인 불가)을 색·배지·액션으로 구분하며, block과 block_pending_approval을 절대 동일하게 표시하지 않는다. **색상 일관성** — 게이지 색은 엔진이 판정에서 파생해 보내는 `gauge_color`를 그대로 사용해 "고위험인데 초록색" 모순을 차단한다. **미검사 경고 배너** — 선택하지 않은 항목에서 추가 탐지된 건수(`out_of_scope_count`)가 0보다 크면 "미선택 항목은 안전이 아니라 검사 안 함"임을 알리는 배너를 강제 표시해, 점수 100점·통과인데 실제로는 미검사 위험이 다수인 상황을 안전으로 오해하지 않게 한다. **취약점 카드** — 각 취약점을 심각도 배지·CWE 태그·in-scope 여부·파일 위치·코드 스니펫(취약점 줄 강조)·AI 수정 권고·스캐너 출처와 함께 표시하고, 정책 범위 밖 항목은 별도 섹션으로 모은다. 끝으로 chart.js로 점수 도넛·심각도 분포를 시각화하고 `xlsx`로 결과를 엑셀로 내보낼 수 있다.

---

## 5. 백엔드 설계 및 구현

백엔드는 **FastAPI 기반의 트리거·작업 큐·결과 저장 서버**로서 프론트엔드(사용자)와 CI/CD 엔진(실행기) 사이를 매개한다. FastAPI의 비동기 처리와 SQLAlchemy 2.0 async ORM, asyncpg 드라이버로 PostgreSQL과 논블로킹 통신하며, 인증은 PyJWT로, GitHub 토큰 암호화는 `cryptography`로, 외부 호출은 httpx로 수행한다. 초기 아키텍처는 Windows 백엔드가 SSH로 Ubuntu 엔진을 직접 트리거하는 방식이었으나, 재시도·큐잉·관측성·엔진 다중화에 유리한 **HTTP 폴링 기반 작업 큐**로 발전하였다. 현재 모델에서 엔진은 백엔드를 폴링해 작업을 가져가고, 백엔드는 작업 적재와 결과 수집·저장에 집중한다.

DB는 파이프라인의 모든 작업·로그·보안 결과·배포 이력·승인 이력을 영속화하여 실시간 추적·분석·감사를 가능하게 한다. `app/db_models.py`의 주요 테이블은 사용자(`users`, 암호화된 access_token 포함), 작업(`pipeline_jobs`), 스텝(`pipeline_steps`), 스텝 로그(`step_logs`), 취약점(`security_findings`, CWE·위치·코드 스니펫·AI 권고·in_scope 포함), 요약 캐시(`security_summary`), 빌드 산출물(`build_artifacts`), 배포 이력(`deployments`), 승인 이력(`approval_records`)으로 구성된다. 스키마는 마이그레이션으로 점진 확장되었으며(v2 보안 정책, v3 승인 CWE, v4 요약 제약, v5 작업-사용자 매핑), 이는 정책이 6종에서 16종으로 확장되고 승인 워크플로가 도입된 과정을 반영한다. 주요 API는 ① 인증·저장소(`/auth/github/login·callback`, `/auth/me`, `/api/repos`, `/api/repos/{o}/{r}/branches`), ② 파이프라인 실행·조회(`POST /api/pipelines`, `/cancel`, `DELETE`, `GET /api/jobs/{id}`, `/result`, `/findings`), ③ 엔진 연동(`GET /api/jobs/pending`, `POST /claim`, `POST /get-results`), ④ 보안 정책·승인(`GET /api/security/catalog`, `/approval/request·approve·reject`, `GET /api/approvals`)으로 분류된다.

사용자의 private 저장소까지 검사할 수 있도록 백엔드는 OAuth 동의 scope에 `repo`를 포함하고, 발급받은 access_token을 사용자 계정에 매핑하여 **암호화(at rest)** 저장한다(평문 컬럼 금지 — DB 유출이 곧 GitHub 전체 노출이므로). 검사 작업을 엔진에 내려줄 때 payload의 `repo_token` 필드로 유효한 토큰을 실어 보내며, 엔진은 이 토큰으로 클론하고 모든 로그에서 `****`로 마스킹한다(공개 저장소는 토큰 생략 가능). 토큰을 다루는 엔드포인트는 HTTPS를 강제한다. 한편 백엔드는 단순 트리거를 넘어 작업 큐로 동작하여, 엔진이 stateless로 폴링·선점하는 구조 덕에 다중화·재시도·관측성 확장이 용이하다. 승인 워크플로는 판정이 `block_pending_approval`(차단을 유발한 High 존재)일 때 작동하며, 보안 책임자가 사유를 작성해 승인하면 백엔드가 `approved_cwes`를 포함한 후속 작업을 자동 재적재해 엔진이 재스캔 후 배포한다. 부분 승인(일부 CWE만 수용)도 지원하되 **Critical은 어떤 경우에도 승인 예외가 불가능**하며, 승인된 High도 점수에는 위험이 그대로 반영된다. 모든 승인 행위는 `approval_records`에 append-only로 기록되어 감사 추적이 가능하다.

---

## 6. CI/CD 엔진 설계 및 구현

CI/CD 엔진은 본 시스템의 실행 주체로 Python 약 7,400줄 규모로 구현되었으며, 두 진입점을 가진다. **`poller.py`**(운영 모드)는 systemd로 상주하며 백엔드 작업 큐를 폴링→선점→`main.py`를 자식 프로세스로 기동하고 종료된 자식을 회수(reaper)한다. **`main.py`**(CLI)는 `--repo`, `--branch`, `--environment`, `--selected-items`, `--approved-cwes`, `--commit`, `--repo-token`, `--callback-url` 등을 받아 단일 파이프라인을 실행하며, 운영 모드와 동일한 오케스트레이터를 사용해 디버깅·재현에 그대로 활용된다. 오케스트레이터(`orchestrator.py`)의 실행 순서는 다음과 같다.

```
clone (항상 첫 스텝) → env_check → resolve_workflow
  → install → lightweight_security_scan(gitleaks)
  → test → deep_security_scan(semgrep)
  → ★ security_gate ★ (심층 보안검사 직후 삽입)
  → build → deploy
  → 콜백 (스텝별 step_complete + 최종 pipeline_complete)
```

워크플로 파일은 저장소의 `.localci/workflow.yml` 등에서 자동 탐색하며 없으면 공통 템플릿으로 생성하고, 각 스텝은 `continue_on_failure`로 중단 여부를 개별 제어한다. 모든 산출물(결과 JSON, 보안 요약/발견 JSON, 로그, 빌드 아티팩트)은 `runs/run-YYYYMMDD-XXX/`에 영속화된다. 게이트가 차단(`block`/`block_pending_approval`) 판정을 내면 build·deploy는 수행되지 않으며, 이것이 "보안 게이트를 1급 단계로 내장한다"는 핵심 동작이다.

엔진은 저장소를 분석해 런타임을 자동 감지·보정한다(마커 기반 감지 → 선언·실제 불일치 자동 보정 → 모노레포 하위 탐색). **Node.js**는 `package.json` 기반으로 install/test/build를 수행하되 테스트가 없거나 플레이스홀더이면 test를 skip하고, **Python**은 AST 분석으로 ASGI 진입점을 탐지해 팩토리 패턴이면 kwargs 주입 wrapper를 자동 생성하며, **Java**는 Gradle/Maven 래퍼를 감지하되 손상 시 시스템 바이너리로 폴백하고 테스트 인프라 실패와 로직 실패를 구분한다. 빌드 단계는 명령 성공 여부만 보지 않고, 알려진 출력 경로에 배포 가능한 산출물이 없으면 failed로 처리해 거짓 성공을 방지한다. 배포는 빌드 산출물을 S3에 업로드한 뒤 AWS SSM Run Command로 EC2에서 실행하며, 런타임별 포트 슬라이스 할당, 포트 강제 wrapper, 해시 기반 중복 배포 방지와 헬스체크, nginx 동적 리버스 프록시를 지원한다. 인프라는 AWS CDK로 t3.micro 단일 EC2 + S3 + SSM(프리티어 지향)으로 코드화하였다.

신뢰성과 보안을 위한 부가 설계도 갖춘다. 콜백은 스텝 완료 즉시 전송하고 최종 콜백은 실패 시 5/15/30초 간격으로 재시도하며 최종 실패 시 로컬에 저장해 유실을 막는다. 환경변수의 KEY/SECRET/TOKEN 등 민감 값과 클론 토큰은 로그에서 자동으로 `****` 마스킹하고, `GIT_TERMINAL_PROMPT=0`으로 잘못된 토큰에도 대화형 프롬프트 없이 즉시 실패하게 한다. 또한 semgrep 발견 항목마다 Claude API(`claude-sonnet-4-6`)로 근본 원인과 수정 방법을 설명하는 한국어 4문장 가이드를 생성해 콜백에 포함함으로써, 프론트의 취약점 카드에서 보안 비전문가의 대응을 돕는다.

---

## 7. 핵심 기여 — CWE 정책 기반 보안 게이트

본 프로젝트의 핵심 기여는 정적 분석 도구의 출력을 그대로 신뢰하지 않고 **CWE를 단일 기준으로 등급을 재결정하여 배포 가능 여부를 판정하는 보안 게이트**이다(`security_catalog.py`, `security_policy.py`). 그 토대는 16개 대표 취약점 항목을 4등급(Critical/High/Medium/Low)×4개로 나누어 CWE-ID에 고정 매핑한 카탈로그로, 등급·감점·게이트 동작이 모두 이 단일 진실 공급원(SSOT)에서 파생되므로 정책 변경은 카탈로그 한 곳만 수정하면 된다. semgrep·gitleaks가 매긴 자체 severity는 신뢰하지 않고 각 발견 항목의 CWE를 추출해 카탈로그로 등급을 다시 결정하며(예: CWE-89는 항상 Critical, gitleaks 비밀정보는 CWE-798 Critical), 이로써 도구 간 불일치를 정책 수준에서 정규화해 "스캐너를 바꿔도 같은 코드에 같은 판정"이라는 등급 일관성을 확보한다.

| 등급 | 항목(CWE) |
|------|-----------|
| 🔴 Critical | SQL Injection(89), Command Injection(78), Hardcoded Secret(798), Code Injection(94) |
| 🟠 High | Insecure Deserialization(502), IDOR(639), Improper JWT Verification(347), Cleartext Transmission(319) |
| 🟡 Medium | Path Traversal(22), XSS(79), Weak Cryptography(327), SSRF(918) |
| 🟢 Low | Error Message Info Exposure(209), Missing HttpOnly(1004), Missing Secure Flag(614), Weak Password Requirements(521) |

배포 판정은 점수가 아니라 등급 위계로 결정한다 — Critical≥1 → `block`(예외 없이 차단), High≥1 → `block_pending_approval`(승인 시에만 통과), Medium≥1 → `warn`(통과), 그 외 → `pass`. 이 위계는 "하위 등급이 아무리 많아도 상위 등급 1건의 판정을 뒤집을 수 없다"는 원칙을 따른다. 점수는 보조 지표로서 100점 만점에서 등급별 감점에 상한을 두어 **하위 등급 감점 총합 < 상위 등급 1건 감점**을 항상 보장하므로(High≤19<20, Medium≤4<5, Low≤0.9<1), "경미한 다수가 치명적 1건보다 점수를 더 깎는" 역전이 수학적으로 불가능하다. 게이지 색상도 점수 구간이 아니라 판정에서 직접 파생되어, 점수·색상·판정이 서로 모순될 수 없다.

정책은 환경과 승인에 대해서도 안전성을 보장한다. 배포 환경은 판정을 강화만 할 뿐 절대 완화하지 않으며(production·staging에서는 Medium-only warn도 승인 필요로 격상), 어떤 환경에서도 위계가 완화되지 않는다. 승인(`approved_cwes`)으로 게이트를 통과시킬 수 있는 대상은 High에 한정되고 **Critical은 어떤 경우에도 예외가 불가능**하며, 승인된 High도 점수에는 위험을 그대로 반영(−5)하여 "승인은 배포를 허용할 뿐 위험이 사라진 것은 아니다"라는 정직성을 점수로 표현한다. 끝으로 사용자가 선택한 항목만 게이트·점수에 반영하고, 선택하지 않은 항목에서 탐지된 건수는 `out_of_scope_count`로 분리 집계한다. 핵심은 미선택 항목을 "안전"이 아니라 "미검사"로 구분한다는 점으로, 이는 경보 피로를 줄이는 동시에 부분 검사 결과를 전체 안전으로 오해하는 위험을 방지한다. 선택 항목은 payload의 `selected_items`로 전달되며 미지정 시 16종 전체가 검사된다.

---

## 8. 구현 결과 및 검증

실제 오픈소스 및 산업 저장소를 대상으로 전체 파이프라인(클론→설치→테스트→보안검사→게이트→빌드→배포)을 실행하여 동작을 검증하였다. **사례 1(비밀정보 즉시 차단)**에서는 16종 전체를 검사한 결과 하드코딩된 비밀정보(CWE-798) 등 Critical이 다수(11건) 탐지되어 판정이 `block`(점수 0)으로 즉시 차단되었고, 사유로 "Hardcoded Secret (CWE-798, Critical) 검출 — 즉시 차단 정책"이 명시되어 Critical 무예외 차단이 실제로 동작함을 확인하였다. **사례 2(평문 전송 차단)**에서는 실시간 데이터 전송 채널의 평문 WebSocket(CWE-319, High)이 빌드·배포 이전에 자동 차단되었다. 이 사례에서 파이프라인은 clone·install을 통과하고 gitleaks에서 비밀정보 0건, 심층 보안검사에서 원시 7건을 탐지한 뒤, 게이트가 평문 전송을 in-scope High로 판정해 차단하였으며 최종 판정은 `block_pending_approval`, 점수 94/100이었다.

사례 2에서 semgrep이 출력한 원시 경보 7건은 정책 카탈로그 기준 2건으로 축소되었고, 나머지 5건은 정책 범위 밖으로 분리 보고되어 개발자가 유의미한 위협에 집중하도록 경보 피로를 완화하였다(약 71% 감소).

| 원시 검출(semgrep 7건) | CWE | 정책 판정 |
|---|---|---|
| 평문 WebSocket(ws://) | CWE-319 | in-scope → **차단** |
| dangerouslySetInnerHTML(XSS) | CWE-79 | in-scope → 경고 |
| SRI integrity 누락 | CWE-353 | 정책 범위 밖 |
| ReDoS(non-literal RegExp) | CWE-1333 | 정책 범위 밖 |
| K8s run-as-root | CWE-250 | 정책 범위 밖 |
| K8s 권한 상승 | CWE-732 | 정책 범위 밖 |
| CSRF 미들웨어 누락 | CWE-352 | 정책 범위 밖 |

특히 사례 2에서 점수가 94점으로 높음에도 게이트가 차단했다는 사실은 중요하다. 단순 점수 임계치 모델(예: 60점 미만 차단)이었다면 이 코드는 통과되었겠지만, 본 시스템의 계층형 게이트는 점수와 무관하게 High 1건의 위계로 차단하였다. 이는 점수와 게이트의 분리, CWE 위계 기반 판정이라는 핵심 설계의 유효성을 직접 실증한다. 종합하면 본 검증은 (1) Critical 무예외 차단, (2) High 위계 기반 차단, (3) 점수 임계치로는 놓칠 위협의 포착, (4) 경보 축소, (5) 점수·색상·판정의 무모순성을 모두 실제 실행으로 확인하였다.

---

## 9. 결론 및 향후 과제

본 캡스톤디자인에서는 보안 검사를 1급 단계로 내장한 멀티런타임 CI/CD 플랫폼 *SecuPipeline*을 설계·구현하였다. Electron 데스크톱 프론트엔드, FastAPI 작업 큐 백엔드, Python CI/CD 엔진의 세 구성요소가 GitHub OAuth·JWT·작업 큐 폴링·HTTP 콜백으로 유기적으로 연동되며, 소스 저장소의 클론부터 클라우드 배포까지 전 과정을 자동화한다. 특히 정적 분석 도구의 등급에 의존하지 않고 CWE를 단일 기준으로 등급을 재결정하는 보안 게이트를 통해 도구 독립적이고 무모순적인 배포 차단 판정을 달성하였고, 감점 상한과 판정 파생 색상으로 점수·색상·판정의 무모순성을, 환경별 단조강화와 Critical 무예외로 정책 안전성을, 선택 항목 스코핑으로 경보 피로 완화를 보장하였다. 실저장소 검증에서 원시 경보를 약 71% 축소하고, 점수가 높음에도 위계 기반 게이트가 평문 전송 취약점을 배포 이전에 차단함으로써 설계의 유효성을 확인하였다.

본 프로젝트의 기여는 (1) 클론–설치–테스트–정적보안–빌드–배포를 단일 엔진으로 수행하고 단계별 콜백하는 자기완결적 CI/CD 엔진, (2) CWE를 16종 정책 카탈로그에 사상해 등급을 재결정하는 스캐너 불가지론적 보안 게이트, (3) 점수·게이지·판정이 모순될 수 없는 계층형 차단 모델과 환경별 단조강화·Critical 무예외 정책, (4) 선택 항목 스코핑을 통한 경보 피로 완화, (5) 비전문가 친화적 데스크톱 GUI와 LLM 기반 한국어 수정 권고로 정리된다. 향후 과제로는 공개 저장소 다수를 대상으로 한 정밀도·재현율 정량 평가와 베이스라인 대비 경보 축소율 비교, 16종 카탈로그의 사용자 정의 확장형 정책화, 엔진 다중화·대규모 동시 작업에 대한 성능·확장성 검증, 의존성·컨테이너·IaC 스캔 등 분석 도구 확장, 만료·역할 기반 승인 등 승인 정책 고도화가 있다.

---

## 10. 참고문헌

[1] M. Fowler, "Continuous Integration," martinfowler.com, 2006.
[2] MITRE, "Common Weakness Enumeration (CWE)," https://cwe.mitre.org.
[3] OWASP Foundation, "OWASP Top 10 — 2021," https://owasp.org/Top10.
[4] Semgrep, "Semgrep: Lightweight static analysis for many languages," https://semgrep.dev.
[5] Gitleaks, "Gitleaks: Protect and discover secrets," https://github.com/gitleaks/gitleaks.
[6] FastAPI, "FastAPI framework, high performance, easy to learn," https://fastapi.tiangolo.com.
[7] OpenJS Foundation, "Electron Documentation," https://www.electronjs.org/docs.
[8] GitHub, "Authorizing OAuth apps," https://docs.github.com/en/apps/oauth-apps.
[9] Amazon Web Services, "AWS Systems Manager / AWS CDK Developer Guide," https://docs.aws.amazon.com.
[10] G. Kim, J. Humble, P. Debois, and J. Willis, *The DevOps Handbook*, IT Revolution Press, 2016.
[11] SQLAlchemy, "SQLAlchemy 2.0 Documentation," https://docs.sqlalchemy.org.
[12] React, "React Documentation," https://react.dev.

---

*작성: CapstoneLab · 구성요소 레포지토리 — 엔진: CICD-Engine, 백엔드: CapstoneLab/Capstone-Back, 프론트엔드: CapstoneLab/Capstone-FE*
