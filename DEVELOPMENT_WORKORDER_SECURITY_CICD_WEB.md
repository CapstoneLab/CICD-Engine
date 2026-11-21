# 보안 CI/CD 웹페이지 개발지시서

## 1. 개요

본 문서는 현재 보유 중인 보안 CI/CD 엔진을 웹 기반 서비스로 확장하기 위한 개발 지시서이다. 개발 대상은 GitHub 저장소를 웹에서 등록·연계하고, 보안 CI/CD 파이프라인을 실행하며, 실행 단계별 상세 내용과 로그, 보안 진단 결과를 사용자가 웹 화면에서 확인할 수 있도록 하는 기능이다.

현재 엔진은 명령어 기반으로 GitHub 저장소 clone, 의존성 설치, 보안 스캔, 테스트, 빌드, 배포 단계 실행 및 결과 파일 생성을 수행한다. 본 개발을 통해 해당 기능을 사용자 친화적인 웹 화면과 API로 제공하고, 실행 이력과 보안 결과를 체계적으로 관리할 수 있는 구조를 구축한다.

## 2. 추진 배경

현재 보안 CI/CD 엔진은 로컬 또는 서버 환경에서 직접 명령어를 실행하는 방식으로 동작한다. 이 방식은 기능 검증에는 적합하나, 비개발자 또는 운영 담당자가 반복적으로 사용하기에는 접근성이 낮고, 실행 이력과 로그를 한눈에 확인하기 어렵다.

또한 GitHub 저장소별 보안 진단 결과, 단계별 실패 원인, 보안 취약점 상세, 빌드·배포 결과를 통합적으로 확인할 수 있는 웹 인터페이스가 필요하다. 이에 따라 기존 엔진의 기능을 유지하면서, 저장소 연계부터 실행·조회·검수까지 가능한 웹 기반 관리 화면을 개발한다.

## 3. 개발 목표

본 개발의 주요 목표는 다음과 같다.

- GitHub 저장소를 웹에서 등록하고 보안 CI/CD 실행 대상으로 관리한다.
- 사용자가 웹 화면에서 저장소별 파이프라인을 수동 실행할 수 있도록 한다.
- 파이프라인의 단계별 진행 상태, 상세 수행 내용, 실패 사유를 시각적으로 제공한다.
- 전체 로그와 단계별 로그를 웹에서 조회·검색·다운로드할 수 있도록 한다.
- 보안 스캔 결과를 심각도별로 요약하고, 취약점 상세 및 조치 권고를 제공한다.
- 실행 이력과 결과를 저장하여 추후 조회 및 운영 검수에 활용할 수 있도록 한다.

## 4. 개발 범위

### 4.1 GitHub 저장소 연계 기능

웹 화면에서 GitHub 저장소를 등록하고, 등록된 저장소를 대상으로 보안 CI/CD 파이프라인을 실행할 수 있어야 한다.

필수 개발 항목:

- GitHub 저장소 URL 등록
- 저장소 소유자, 저장소명, 브랜치 정보 저장
- 기본 브랜치 자동 인식 또는 사용자 입력 지원
- public repository 실행 지원
- private repository 실행을 위한 GitHub token 또는 인증 연동 지원
- 저장소 목록 조회
- 저장소별 최신 실행 결과 요약 표시
- 저장소별 실행 이력 조회
- 저장소 삭제 또는 비활성화

권장 개발 항목:

- GitHub OAuth App 또는 GitHub App 기반 인증 연동
- 사용자가 접근 권한을 가진 저장소 목록 불러오기
- 브랜치 목록 조회
- 향후 GitHub webhook 자동 실행을 고려한 확장 구조

보안 요구사항:

- GitHub token은 화면, 로그, API 응답에 평문으로 노출되지 않아야 한다.
- token 저장이 필요한 경우 암호화 또는 별도 보안 저장소를 사용해야 한다.
- clone 로그에 인증정보가 포함될 경우 반드시 마스킹해야 한다.
- 사용자별 저장소 및 실행 이력 접근 권한을 분리해야 한다.

### 4.2 웹 기반 단계별 상세 수행 기능

사용자는 파이프라인 실행 과정을 웹 화면에서 단계별로 확인할 수 있어야 한다.

기본 표시 단계:

- clone
- install
- lightweight_security_scan
- test
- deep_security_scan
- security_gate
- build
- deploy

단계별 표시 항목:

- 단계명
- 상태: queued, running, success, failed, skipped
- 시작 시각
- 종료 시각
- 수행 시간
- exit code
- 요약 메시지
- 실패 사유
- 관련 로그 보기
- 보안 스캔 단계의 취약점 요약

화면 요구사항:

- 파이프라인 타임라인 또는 단계형 진행 화면을 제공해야 한다.
- 현재 실행 중인 단계를 명확히 표시해야 한다.
- 실패 단계는 사용자가 즉시 인지할 수 있도록 상태 색상과 메시지를 제공해야 한다.
- 사용자가 단계를 선택하면 해당 단계의 수행 내용과 로그를 확인할 수 있어야 한다.
- 실행 완료 후 전체 결과 요약과 단계별 결과를 함께 확인할 수 있어야 한다.

### 4.3 웹 기반 로그 표시 기능

사용자는 웹 화면에서 전체 로그와 단계별 로그를 확인할 수 있어야 한다.

필수 개발 항목:

- 실행 단위 전체 로그 조회
- 단계별 로그 조회
- 로그 파일명 또는 단계명 표시
- 로그 시간순 표시
- 로그 검색
- 실행 중 로그 주기적 갱신 또는 실시간 스트리밍
- 자동 스크롤 on/off
- 로그 다운로드

권장 개발 항목:

- error, warning 등 주요 키워드 강조 표시
- 긴 로그에 대한 페이지네이션 또는 가상 스크롤 적용
- 특정 단계 로그만 필터링
- 로그 레벨별 색상 표시

보안 요구사항:

- token, password, secret, authorization header 등 민감정보는 반드시 마스킹해야 한다.
- 로그 원문 저장 전 또는 API 응답 전 마스킹 정책을 적용해야 한다.
- 권한 없는 사용자가 다른 사용자의 실행 로그에 접근하지 못하도록 API 권한 검증을 수행해야 한다.

## 5. 주요 화면 요구사항

### 5.1 저장소 목록 화면

등록된 GitHub 저장소와 최신 보안 CI/CD 실행 결과를 한눈에 확인하는 화면이다.

표시 항목:

- 저장소명
- GitHub URL
- 기본 브랜치
- 최신 실행 상태
- 최신 보안 게이트 결과: pass, warn, block
- 보안 점수
- Critical, High, Medium, Low 취약점 수
- 마지막 실행 시각
- 실행 버튼
- 상세 보기 버튼

주요 기능:

- 저장소 등록
- 저장소 검색
- 저장소별 수동 파이프라인 실행
- 저장소 상세 화면 이동

### 5.2 저장소 등록 화면

GitHub 저장소를 실행 대상으로 등록하는 화면이다.

입력 항목:

- GitHub repository URL
- branch
- GitHub token 또는 인증 방식
- workflow 파일 경로, 선택 입력
- 실행 환경: development, staging, production 등

검증 항목:

- URL 형식 검증
- GitHub 접근 가능 여부 확인
- branch 존재 여부 확인
- private repository인 경우 인증 성공 여부 확인

### 5.3 실행 상세 화면

특정 실행 건의 전체 수행 결과를 확인하는 핵심 화면이다.

상단 요약 항목:

- 저장소명
- branch
- commit hash
- run id
- 실행 상태
- 시작 시각 및 종료 시각
- 총 수행 시간
- 보안 게이트 판정
- 보안 점수

단계별 영역:

- 단계 타임라인
- 각 단계 상태 및 요약
- 단계별 상세 수행 내용
- 단계별 로그

보안 결과 영역:

- 보안 게이트 결과 배너
- 심각도별 취약점 수
- 스캐너별 요약
- 취약점 목록
- 취약점 상세
- 코드 위치
- 코드 스니펫
- AI 수정 권고

로그 영역:

- 전체 로그
- 단계별 로그
- 검색
- 다운로드

### 5.4 실행 이력 화면

저장소 또는 전체 시스템 기준으로 과거 실행 이력을 조회하는 화면이다.

표시 항목:

- run id
- 저장소
- branch
- commit hash
- 실행 상태
- 보안 게이트 결과
- 보안 점수
- 취약점 수
- 시작 시각 및 종료 시각
- 실행자

필터 항목:

- 저장소
- branch
- 실행 상태
- 보안 게이트 결과
- 기간

## 6. 보안 결과 표시 기준

보안 게이트 결과는 다음 기준으로 표시한다.

| 값 | 의미 | 화면 표시 방향 |
| --- | --- | --- |
| pass | 보안 기준 통과 | 정상 진행 가능 |
| warn | 진행 가능하나 검토 필요 | 주의 표시 및 사유 제공 |
| block | 보안 기준 미달 | 차단 표시 및 차단 사유 제공 |

취약점 심각도는 다음 네 단계로 표시한다.

- Critical
- High
- Medium
- Low

취약점 상세 화면에는 다음 항목을 표시해야 한다.

- 스캐너명
- rule id
- severity
- title
- file path
- line number
- message
- CWE
- CVSS score
- code snippet
- AI recommendation

코드 스니펫 표시 요구사항:

- 실제 파일의 line number를 표시해야 한다.
- 취약점 발생 라인을 강조해야 한다.
- 파일 확장자 기반 syntax highlighting을 적용해야 한다.
- 긴 코드는 접기·펼치기 기능을 제공해야 한다.

## 7. 시스템 연동 및 실행 방식

웹 백엔드는 사용자의 실행 요청을 받아 현재 CI/CD 엔진을 비동기로 실행해야 한다.

현재 엔진 실행 예시:

```bash
python main.py --repo https://github.com/example/repo.git --branch main
```

콜백 방식 실행 예시:

```bash
python main.py \
  --job-id <uuid> \
  --repo https://github.com/example/repo.git \
  --branch main \
  --callback-url <backend-callback-url> \
  --callback-token <shared-token>
```

실행 요구사항:

- 실행 요청 즉시 run id를 반환해야 한다.
- 실제 파이프라인은 비동기로 실행해야 한다.
- 실행 중 상태를 DB 또는 파일 기반으로 갱신해야 한다.
- 동시에 여러 run이 실행될 수 있는 구조를 고려해야 한다.
- 실행 실패 시 실패 사유를 저장해야 한다.
- 서버 재시작 후에도 완료된 run 이력과 결과를 조회할 수 있어야 한다.

권장 시스템 구성:

- Web frontend
- Web backend API
- Pipeline worker
- Database
- File storage 또는 object storage for logs/artifacts

## 8. API 요구사항

구체적인 URL은 업체 구현 환경에 따라 조정할 수 있으나, 아래 기능은 반드시 API로 제공해야 한다.

### 8.1 저장소 API

- `POST /api/repositories`: 저장소 등록
- `GET /api/repositories`: 저장소 목록 조회
- `GET /api/repositories/{repository_id}`: 저장소 상세 조회
- `DELETE /api/repositories/{repository_id}`: 저장소 삭제 또는 비활성화
- `GET /api/repositories/{repository_id}/runs`: 저장소별 실행 이력 조회
- `GET /api/repositories/{repository_id}/latest-run`: 저장소 최신 실행 결과 조회

### 8.2 파이프라인 실행 API

```http
POST /api/pipeline-runs
```

요청 예시:

```json
{
  "repository_id": "repo-001",
  "repo_url": "https://github.com/owner/repo",
  "branch": "main",
  "workflow": ".localci/workflow.yml",
  "environment": "development"
}
```

응답 예시:

```json
{
  "run_id": "run-20260624-021",
  "status": "queued"
}
```

### 8.3 실행 상세 조회 API

```http
GET /api/pipeline-runs/{run_id}
```

응답에는 다음 정보를 포함해야 한다.

- run 기본 정보
- steps 배열
- security summary
- security findings
- security verdict
- metadata

### 8.4 단계별 로그 조회 API

```http
GET /api/pipeline-runs/{run_id}/steps/{step_name}/logs
```

지원 파라미터:

- `offset`: 로그 읽기 시작 위치
- `limit`: 최대 라인 수 또는 바이트 수
- `keyword`: 검색어

응답 예시:

```json
{
  "run_id": "run-20260624-021",
  "step_name": "clone",
  "log_file": "clone.log",
  "lines": [
    "[2026-06-24 21:46:27] $ git clone --depth 1 ...",
    "[2026-06-24 21:46:29] [exit_code] 0"
  ],
  "next_offset": 2048,
  "completed": true
}
```

### 8.5 전체 로그 조회 API

```http
GET /api/pipeline-runs/{run_id}/logs
```

요구사항:

- 여러 단계 로그를 시간순 또는 단계순으로 병합 제공해야 한다.
- 각 라인에 로그 파일명 또는 단계명을 포함해야 한다.
- 민감정보 마스킹 후 반환해야 한다.

## 9. 데이터 관리 요구사항

최소 관리 대상:

- users
- repositories
- pipeline_runs
- pipeline_steps
- security_summaries
- security_findings
- pipeline_logs 또는 log file metadata

repositories 주요 필드:

- id
- owner
- name
- repo_url
- default_branch
- visibility
- credential_ref
- created_by
- created_at
- updated_at

pipeline_runs 주요 필드:

- id
- repository_id
- run_id
- branch
- commit_hash
- status
- verdict
- score
- started_at
- finished_at
- triggered_by
- metadata

pipeline_steps 주요 필드:

- id
- pipeline_run_id
- step_name
- status
- exit_code
- summary
- started_at
- finished_at
- log_file_path

security_findings 주요 필드:

- id
- pipeline_run_id
- scanner_name
- rule_id
- severity
- title
- file_path
- line_number
- message
- cwe
- cvss_score
- ai_recommendation
- code_snippet
- code_snippet_start_line

## 10. 비기능 요구사항

성능:

- 저장소 목록 화면은 2초 이내 로딩되어야 한다.
- 실행 상세 화면은 3초 이내 1차 렌더링되어야 한다.
- 대용량 로그는 페이지네이션, offset, streaming 중 하나 이상의 방식을 적용해야 한다.

안정성:

- 파이프라인 실행 중 웹 서버가 중단되어도 run 결과 파일이 손상되지 않아야 한다.
- worker 실패 시 run 상태가 failed로 정리되어야 한다.
- 동일 저장소 동시 실행 가능 여부에 대한 정책을 명확히 구현해야 한다.

보안:

- 사용자 인증 및 인가를 적용해야 한다.
- 저장소 및 run 조회 권한을 검증해야 한다.
- GitHub token, callback token, secret 값은 마스킹해야 한다.
- API 입력값 검증을 수행해야 한다.
- command injection을 방지해야 한다.
- 로그 및 파일 경로 접근 시 path traversal을 방지해야 한다.

운영:

- 환경변수 기반 설정을 지원해야 한다.
- 실행 로그 보관 기간을 설정할 수 있어야 한다.
- 오래된 run 및 artifact 정리 정책을 제공해야 한다.
- 장애 분석을 위한 backend/worker 로그를 제공해야 한다.

## 11. 인수 기준

개발 완료 후 다음 항목을 모두 충족해야 한다.

### 11.1 GitHub 저장소 연계

- 사용자가 GitHub 저장소 URL을 등록할 수 있다.
- 등록된 저장소 목록을 조회할 수 있다.
- public repository를 대상으로 파이프라인을 실행할 수 있다.
- private repository는 token 또는 인증 연동을 통해 실행할 수 있다.
- token은 화면, API 응답, 로그에 평문 노출되지 않는다.

### 11.2 파이프라인 실행

- 웹에서 실행 버튼 클릭 시 run id가 생성된다.
- run은 비동기로 실행된다.
- 실행 중 상태가 웹 화면에 반영된다.
- clone, install, security scan, test, build 등 단계별 상태가 표시된다.
- 실패 단계와 실패 사유가 명확히 표시된다.

### 11.3 상세 결과 표시

- 실행 상세 화면에서 전체 상태, 실행 시간, 저장소, branch, commit 정보를 확인할 수 있다.
- 보안 게이트 결과 pass/warn/block이 표시된다.
- Critical, High, Medium, Low 취약점 수가 표시된다.
- 취약점 상세, 코드 위치, AI 권고, 코드 스니펫을 확인할 수 있다.

### 11.4 로그 표시

- 전체 로그를 조회할 수 있다.
- 단계별 로그를 조회할 수 있다.
- 로그 검색이 가능하다.
- 실행 중 로그가 갱신된다.
- 로그 다운로드가 가능하다.
- 민감정보는 마스킹되어 표시된다.

### 11.5 운영 검수

- WebGoat, Juice Shop 등 테스트 저장소 2개 이상으로 end-to-end 실행 검증을 완료한다.
- 성공, 실패, 보안 차단 케이스가 각각 화면에서 정상 표시된다.
- 브라우저 새로고침 후에도 실행 상세 조회가 가능하다.
- 서버 재시작 후에도 완료된 실행 이력 조회가 가능하다.

## 12. 기대 효과

본 개발 완료 시 다음 효과를 기대할 수 있다.

- 보안 CI/CD 실행 절차를 웹 기반으로 표준화하여 사용 편의성을 높인다.
- 저장소별 보안 상태와 실행 이력을 체계적으로 관리할 수 있다.
- 단계별 실패 원인과 로그를 빠르게 확인하여 장애 대응 시간을 단축한다.
- 보안 취약점의 심각도, 위치, 조치 권고를 한 화면에서 확인할 수 있다.
- 향후 GitHub webhook, 자동 배포 승인, 보안 정책 고도화 등 확장 기능의 기반을 마련한다.

## 13. 제출 산출물

업체는 개발 완료 시 다음 산출물을 제출해야 한다.

- 웹 프론트엔드 소스코드
- 백엔드 API 소스코드
- worker 또는 파이프라인 실행 연동 코드
- DB schema 또는 migration 파일
- API 명세서
- 화면 설계서 또는 주요 화면 캡처
- 배포 매뉴얼
- 운영 환경변수 목록
- 테스트 결과서
- 보안 점검 체크리스트

## 14. 참고 자료

현재 프로젝트 내 참고 문서:

- `README.md`: 로컬 CI 엔진 개요 및 실행 방식
- `EXECUTION_MANUAL.md`: 실행 절차 및 검증 방법
- `FRONTEND_INTEGRATION_GUIDE.md`: 프론트엔드 표시용 payload 구조 및 UI 가이드
- `SECURITY_POLICY_MANUAL.md`: 보안 정책
- `RUNS_ARCHIVE_MANUAL.md`: 실행 결과 보관 구조

현재 주요 결과 경로:

- `runs/<run_id>/pipeline_result.json`
- `runs/<run_id>/security_summary.json`
- `runs/<run_id>/security_findings.json`
- `runs/<run_id>/logs/*.log`
- `workspace/<run_id>/repo`
