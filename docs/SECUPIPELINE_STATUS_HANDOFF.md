# Secupipeline 운영 장애 분석 및 인수인계

## 1. 현재 결론

현재 핵심 문제는 백엔드가 파이프라인을 인식하지 못하는 것이 아니다.

운영 검증 결과:

- 엔진 워커 컨테이너는 실행 중이다.
- 백엔드 polling 요청은 정상적으로 `200 OK`를 반환한다.
- Job은 `queued`에서 벗어나 엔진에 의해 정상 claim된다.
- clone, 의존성 설치, 테스트, 보안 검사 단계가 실행된다.
- 최종적으로 `security_gate`에서 보안 탐지 때문에 실패한다.
- 백엔드 API의 실제 Job 상태는 `failed`이다.

따라서 프론트에서 `running`으로 보이는 현상은 실제 실행 중인 Job의 상태가 아니라, 오래된 상태 또는 다른 Job ID를 표시하는 문제일 가능성이 높다.

## 2. 문제 발생 경위

### 2.1 GitHub Webhook 권한 문제

GitHub OAuth 토큰에 Webhook 관리 권한이 없어 Webhook API가 실패했다.

조치:

- OAuth scope에 `read:org`, `admin:repo_hook` 추가
- 기존 OAuth 권한은 자동 갱신되지 않으므로 재로그인 필요
- GitHub Webhook 등록 및 ping 수신 확인
- Webhook callback:
  - `POST /webhooks/github`
- Webhook으로 생성된 Job은 `trigger_source="webhook"`으로 저장됨

### 2.2 저장소 목록 누락 문제

`/user/repos`와 조직 저장소 조회만으로는 목표 저장소가 누락될 수 있었다.

조치:

- `GITHUB_REPOSITORY_HINTS` 설정 추가
- 목록에 없는 저장소를 직접 조회하는 fallback 추가
- `CapstoneLab/Capstone-FE` 저장소가 백엔드 `/api/repos` 응답에 포함되는 것 확인

### 2.3 Job이 queued에서 멈춘 문제

엔진의 환경변수는 다음 주소를 사용했다.

```text
BACKEND_BASE_URL=http://backend:8000
```

하지만 Docker 네트워크에서 백엔드 컨테이너에 `backend` 네트워크 alias가 없어 DNS 조회가 실패했다.

엔진 로그의 대표 오류:

```text
Temporary failure in name resolution
```

조치:

- 백엔드 컨테이너에 `backend` 네트워크 alias 복구
- 엔진에서 `http://backend:8000/health`가 `200` 응답하는 것 확인
- 이후 워커가 Job을 claim하고 실행하는 것 확인

### 2.4 Gradle 설치 실패 문제

샘플 Java 저장소는 Spring Boot 3.4.2와 Gradle 8.7을 요구했다.

기존 엔진에는 시스템 Gradle 4.4.1이 사용되고 있었고, Gradle wrapper JAR도 누락되어 있었다.

조치:

- 엔진 Dockerfile에 Gradle 8.7 설치
- 엔진 이미지 재빌드 및 재배포
- 운영 엔진에서 Gradle 8.7 확인
- Gradle install 단계 정상 진행 확인

### 2.5 현재 보안 게이트 실패

샘플 저장소 `jongha021229/sample_java5`에는 학습용 취약점과 Secret 탐지용 코드가 의도적으로 포함되어 있다.

기존 탐지 항목:

- `scanner-fixtures/03-hardcoded-secrets.txt`
- `src/main/java/com/example/samplejava5/controller/VulnController.java`
- Gitleaks `generic-api-key`
- Gitleaks `stripe-access-token`
- Semgrep Critical/High/Medium 항목

이 탐지는 보안정책상 정상적인 차단이다. 워커 또는 백엔드 통신 실패가 아니다.

## 3. 운영에서 확인된 Job 상태

### Job 1

```text
Job ID: c0e5c94c-60e6-472d-99c2-9dd1189664a5
status: failed
latest_step: security_gate
progress: 8/8
trigger_source: manual
```

### Job 2

```text
Job ID: 500bd6c1-020f-4efd-92cb-fe26a007da5c
status: failed
latest_step: security_gate
progress: 8/8
trigger_source: webhook
```

두 Job 모두 엔진이 실행했고 `security_gate`에서 종료됐다.

## 4. 프론트에서 running으로 보이는 현상

백엔드 상세 API 응답 구조는 다음과 같다.

```json
{
  "job": {
    "job_id": "...",
    "status": "failed",
    "latest_step_name": "security_gate",
    "completed_steps": 8,
    "total_steps": 8
  },
  "steps": [],
  "current_step": null
}
```

프론트 API 매퍼는 `raw.job` 내부의 상태를 읽도록 구현되어 있다.

따라서 실제 운영 화면에서 계속 `running`으로 보인다면 다음을 확인해야 한다.

1. 프론트가 표시하는 Job ID가 최신 Job ID인지 확인
2. `GET /api/jobs/{job_id}` 응답의 `job.status` 확인
3. 브라우저/Electron 앱의 상태 캐시 제거
4. `PipelineProcessPage`의 polling 요청이 동일 Job ID로 반복되는지 확인
5. 프론트가 `GET /api/jobs/{job_id}/steps` 응답의 `job.status`도 반영하는지 확인

## 5. 수정된 백엔드 파일

### Capstone-Back

- `app/config.py`
  - OAuth scope 추가
  - 저장소 hint 설정
- `app/api/repos_router.py`
  - 저장소 누락 fallback
- `app/api/webhooks_router.py`
  - GitHub status/message/path 로깅
  - Webhook 수신 및 멱등성 처리
  - `trigger_source="webhook"`
- `app/main.py`
  - Job claim, callback, stuck-job 처리
- `scripts/deploy.sh`
  - 운영 OAuth scope 반영
- `.github/workflows/cd.yml`
  - 운영 배포 설정 확인
- `docs/github-oauth-login.md`
  - OAuth 및 Webhook 권한 문서

### CICD-Engine

- `Dockerfile`
  - Gradle 8.7 설치
- `app/poller.py`
  - Job polling 및 claim
- `app/orchestrator.py`
  - 단계 실행 및 callback
- `app/callback.py`
  - 단계별 상태 callback
- `app/steps/lightweight_security.py`
  - Gitleaks 실행

## 6. 로컬에서 수행한 저장소 수정

대상 저장소:

```text
https://github.com/jongha021229/sample_java5
```

로컬 경로:

```text
/home/capstone/sample_java5
```

로컬 커밋:

```text
5fb05da fix: move training credentials to environment
```

수정 내용:

- DB URL, DB 사용자, DB 비밀번호를 환경변수로 전환
- AES 키를 환경변수로 전환
- 하드코딩된 API key/JWT secret 제거
- Secret fixture의 실제 형식 값을 제거
- README에 환경변수 사용법 추가

검증:

- 현재 파일 기준 Gitleaks: `0 leaks`
- Gradle test: `BUILD SUCCESSFUL`

주의:

- 현재 인증 계정은 `jongha021229/sample_java5`에 push 권한이 없어 원격 반영에 실패했다.
- 기존 Git 이력에도 이전 값이 남아 있어 `gitleaks detect`가 이력까지 검사하면 탐지될 수 있다.
- 원격 반영을 위해서는 저장소 Write 권한 또는 저장소 소유자의 직접 push가 필요하다.
- 실제 운영 Secret이었다면 먼저 revoke/rotate해야 한다.

## 7. 운영 반영 후 검증 순서

1. 저장소 Write 권한 확보
2. 커밋 `5fb05da`를 원격 main에 push
3. GitHub Webhook delivery 확인
4. 백엔드에서 새 Job 생성 확인
5. 새 Job의 `trigger_source` 확인
6. 엔진 로그에서 Job claim 확인
7. 백엔드 API에서 단계별 상태 확인
8. 프론트가 동일 Job ID를 polling하는지 확인
9. Gitleaks 및 Semgrep 결과 확인
10. 최종적으로 `success` 또는 보안정책에 따른 `failed` 상태가 프론트에 일치하는지 확인

## 8. 운영 명령어

### 컨테이너 상태

```bash
docker ps
```

### 엔진 로그

```bash
docker logs --tail 200 capstone-cicd-engine
```

### 백엔드 로그

```bash
docker logs --tail 200 capstone-back
```

### Job 상세 조회

```bash
curl -sS http://127.0.0.1:8000/api/jobs/<JOB_ID> | jq
```

### 핵심 상태만 확인

```bash
curl -sS http://127.0.0.1:8000/api/jobs/<JOB_ID> \
  | jq '{id: .job.job_id, status: .job.status, latest_step: .job.latest_step_name, completed: .job.completed_steps, total: .job.total_steps, current_step}'
```

## 9. 최종 판단

현재 시스템은 다음까지 정상이다.

- GitHub OAuth
- 저장소 조회
- Webhook 등록
- Webhook 수신
- Webhook Job 생성
- `trigger_source` 저장
- 엔진 polling
- Job claim
- Docker 네트워크 연결
- Gradle 설치
- 단계별 callback
- 보안 게이트 실행

남은 이슈는 두 가지다.

1. 프론트가 실제 백엔드의 terminal 상태를 계속 `running`으로 표시하는지 확인
2. 샘플 저장소의 기존 Git 이력 및 의도적 취약점에 대한 보안정책 처리

