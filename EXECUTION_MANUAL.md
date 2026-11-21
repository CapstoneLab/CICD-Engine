# 로컬 CI 엔진 실행 매뉴얼

## 1. 목적

이 문서는 다른 사람이 그대로 따라 실행해도 실패 확률이 낮도록, 준비부터 검증까지 표준 절차를 정의한다.

기본 파이프라인 순서(워크플로 파일이 없을 때):

- clone
- install
- lightweight_security_scan
- test
- deep_security_scan
- build

레포지토리에 워크플로 파일이 있으면, clone 이후 단계는 YAML 정의를 기준으로 동작한다.

레포지토리에 워크플로 파일이 없으면, clone 직후 공통 템플릿(workflow.template.yml) 기반으로 .localci/workflow.yml을 자동 생성한 뒤 그 YAML 기준으로 진행한다.

자동 탐지 경로:

- .localci/workflow.yml
- .localci/workflow.yaml
- .ci/workflow.yml
- .ci/workflow.yaml

## 2. 현재 정책(중요)

아래 정책은 기본 워크플로 기준이다. 저장소별 YAML에서 조정 가능하다.

- lightweight_security_scan
  - gitleaks 탐지 결과를 수집하고 최종 security_gate에서 정책 판정
  - Hardcoded Secret(CWE-798)으로 분류된 결과는 Critical로 병합·배포 차단
  - gitleaks 실행 자체 실패는 step 실패

- deep_security_scan
  - semgrep 결과를 보안 카탈로그의 CWE 및 등급으로 정규화
  - Critical은 차단하고 High는 승인 전까지 차단
  - production/staging의 카탈로그 외 결과는 MANUAL_REVIEW로 처리

- build
  - build 우선
  - 없으면 build:frontend, build:server 순서로 fallback 실행
  - 성공 시 산출물을 runs/<run_id>/artifacts/ 아래로 저장
  - 명령은 성공했지만 산출물이 없으면 build step failed 처리

Gitleaks 단계 자체는 결과 수집을 위해 성공으로 종료될 수 있지만,
최종 security_gate에서 Critical Secret으로 분류되면 파이프라인은 실패한다.

- test
  - 테스트 파일이 없으면 test step skipped
  - 테스트 파일은 있으나 package.json test 스크립트가 없거나 placeholder면 skipped

워크플로 커스터마이징 포인트:

- uses: install | lightweight_security_scan | test | deep_security_scan | build
- run: 커스텀 명령(문자열 또는 배열)
- continue_on_failure: step 실패 시 계속 진행 여부
- cwd/env: 실행 디렉터리 및 환경 변수
- args.report_file: 보안 리포트 파일명 변경

## 3. 권장 실행 환경

권장 버전:

- Python 3.11.9
- Node.js 22.x
- npm 11.x
- gitleaks 8.30.1 이상
- semgrep 1.157.0

로컬에서 검증된 파이썬 버전:

- Python 3.13.5

## 4. 환경별 설치 가이드

아래는 운영체제/셸별 최소 설치 절차이다.

### 4.1 Windows PowerShell

1) 프로젝트 루트로 이동

cd <프로젝트_루트>

2) 가상환경 생성/활성화

python -m venv .venv
.\.venv\Scripts\Activate.ps1

3) pip 업데이트 및 의존성 설치

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

4) gitleaks 설치(미설치 시)

winget install --id Gitleaks.Gitleaks -e --accept-source-agreements --accept-package-agreements

5) semgrep 설치(미설치 시)

python -m pip install semgrep==1.157.0

### 4.2 Git Bash / WSL / Linux / macOS

1) 프로젝트 루트로 이동

cd <프로젝트_루트>

2) 가상환경 생성/활성화

python3 -m venv .venv
source .venv/bin/activate

3) pip 업데이트 및 의존성 설치

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

4) gitleaks 설치

- Ubuntu 예시
  - sudo apt update
  - sudo apt install -y git nodejs npm python3 python3-venv python3-pip
  - gitleaks는 배포 방식에 따라 바이너리 설치 또는 패키지 매니저 설치

5) semgrep 설치(미설치 시)

python -m pip install semgrep==1.157.0

## 5. 실행 전 체크리스트

반드시 아래가 모두 통과해야 한다.

공통:

- git --version
- node -v
- npm -v
- semgrep --version

Windows PowerShell:

- gitleaks version

Linux/macOS/Git Bash:

- gitleaks --version

실패 방지 팁:

- 새로 설치한 도구가 인식되지 않으면 터미널을 새로 연다.
- 프로젝트 루트 폴더에서 실행한다.
- 설치/테스트/빌드가 길 수 있으므로 실행 중 Ctrl+C를 누르지 않는다.
- Node 프로젝트마다 의존성 설치 시간이 길 수 있다(수 분 이상).

## 6. 표준 실행 절차

SSH 트리거 + HTTP 콜백 운영 시 입력 파라미터:

- --job-id: Windows가 생성한 작업 식별자
- --repo: 실행 대상 GitHub 레포 URL
- --branch: 대상 브랜치(기본 main)
- --callback-url: Windows 콜백 API URL
- --callback-token: x-callback-token 값

### 6.1 PowerShell

cd <프로젝트_루트>
.\.venv\Scripts\python.exe main.py --repo https://github.com/juice-shop/juice-shop

브랜치 명시:

.\.venv\Scripts\python.exe main.py --repo https://github.com/juice-shop/juice-shop --branch master

워크플로 파일 명시:

.\.venv\Scripts\python.exe main.py --repo https://github.com/juice-shop/juice-shop --workflow .localci/workflow.yml

콜백 포함 실행:

.\.venv\Scripts\python.exe main.py --job-id <uuid> --repo https://github.com/juice-shop/juice-shop --branch main --callback-url http://192.168.0.4:8000/get-results --callback-token <shared-token>

참고:

- --workflow가 상대 경로 YAML이고 해당 파일이 없으면 clone 이후 템플릿으로 자동 생성한다.

### 6.2 Git Bash / WSL / Linux / macOS

cd <프로젝트_루트>
./.venv/bin/python main.py --repo https://github.com/juice-shop/juice-shop

브랜치 명시:

./.venv/bin/python main.py --repo https://github.com/juice-shop/juice-shop --branch master

워크플로 파일 명시:

./.venv/bin/python main.py --repo https://github.com/juice-shop/juice-shop --workflow .localci/workflow.yml

콜백 포함 실행:

./.venv/bin/python main.py --job-id <uuid> --repo https://github.com/juice-shop/juice-shop --branch main --callback-url https://windows-host/get-results --callback-token <shared-token>

## 7. 성공 판정 방법

실행 후 출력에서 아래를 확인한다.

- status: success
- 모든 step이 success

결과 파일 확인:

- runs/run-YYYYMMDD-XXX/pipeline_result.json
- runs/run-YYYYMMDD-XXX/security_summary.json
- runs/run-YYYYMMDD-XXX/security_findings.json
- runs/run-YYYYMMDD-XXX/callback_result.json (callback_url 설정 시)
- runs/run-YYYYMMDD-XXX/callback_delivery.json
- runs/run-YYYYMMDD-XXX/logs/*.log

## 8. 실패 시 1차 진단

1) clone 실패

- 원인: repo URL 오타, 네트워크 이슈
- 확인: logs/clone.log

2) install 실패

- 원인: npm/node 미설치, 네트워크 불안정, postinstall 실패
- 확인: logs/install.log

3) lightweight_security_scan 실패

- 원인: gitleaks 실행 실패(미설치/경로 문제)
- 확인: logs/lightweight_security_scan.log

4) test 실패

- 원인: 테스트 자체 실패, 브라우저 헤드리스 환경 문제
- 확인: logs/test.log

5) deep_security_scan 실패

- 원인: semgrep 실행 실패 또는 정책 차단
- 확인: logs/deep_security_scan.log

6) build 실패

- 원인: build 관련 스크립트 실패
- 확인: logs/build.log

## 9. 자주 묻는 해석

- npm warn deprecated 메시지
  - 경고이며 즉시 실패 원인이 아닐 수 있다.
- npm audit 취약점 카운트
  - 정보 메시지일 수 있으며 즉시 step 실패와 다를 수 있다.
- gitleaks leaks found
  - 현재 정책에서는 non-blocking이므로 step success 가능

## 10. Ubuntu 최소 이관 실행 절차

Ubuntu에서 최소 실행만 하려면 아래만 하면 된다.

1) 필수 패키지 설치

sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nodejs npm

2) 프로젝트 배치

git clone <engine-repo>
cd <engine-repo>

3) venv 및 의존성 설치

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

4) gitleaks 설치

공식 릴리스 바이너리 설치 또는 패키지 매니저 사용

5) semgrep 확인

semgrep --version

6) 실행

./.venv/bin/python main.py --repo https://github.com/juice-shop/juice-shop

7) 결과 확인

runs/run-*/pipeline_result.json

## 11. 운영 안정화 최소 수칙

- runs, workspace 디스크 용량 주기 점검
- 동일 기준 repo로 주 1회 스모크 실행
- 도구 버전 변경 시 반드시 재검증 1회 수행

### Docker Compose 배포 환경 점검

엔진 이미지에는 Docker CLI와 Compose 플러그인이 모두 필요하다.
`docker compose version`이 실패하면 배포 설정 변경 전에 명확한 오류로 중단한다.
엔진이 컨테이너에서 실행되는 경우 앱 기동 점검은 같은 Docker 네트워크의
앱 컨테이너 DNS 이름과 내부 포트를 사용한다. 엔진의 localhost는 호스트가 아니다.
호스트에서 직접 실행할 때만 localhost와 게시된 호스트 포트를 사용한다.
공용 프록시의 상태 디렉터리가 바뀔 때는 기존 컨테이너의 모든 route 파일을
먼저 복사해 백엔드(`/api`, `/auth`, `/webhooks`, `/open/pipeline`)와 다른 앱의 경로를 보존한다.
복사 실패 시 공유 프록시 설정 교체를 중단한다.
