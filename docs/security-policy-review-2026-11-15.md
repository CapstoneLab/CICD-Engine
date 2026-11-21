# 보안정책 수정 및 국제 기준 비교 — 2026-11-15

## 범위와 결론

대상은 CICD-Engine의 정책 판정, 저장소 코드 실행, 스캐너 설정 및 Capstone-Back의 실행 환경 결정이다. 확인한 우회 경로를 수정했고 최초 반영은 1.3.0이며, 사용자 요구사항을 반영한 현재 정책은 **1.3.1**이다. [현재 선택 검사 정책](selected-scan-policy.md)이 우선한다. 전체 서비스 침투테스트나 ISO 인증 심사가 아니다. ISO는 국제표준화기구이고 NIST는 미국 기관, OWASP·CIS는 비영리 조직이다. 아래는 국제적으로 활용되는 표준·지침과 현재 구현을 비교한 결과다.

## 수정한 동작

| 문제 | 수정 |
|---|---|
| 최초 전체 검사 이후 선택 검사 지원 | 최초 전체 검사가 정상 완료되면 선택한 CWE만 실제 검사·점수·판정에 포함한다. 선택 밖 결과의 판정 제외는 제품의 의도된 기능이며 우회 취약점으로 취급하지 않는다. |
| CWE 고정 등급이 스캐너/CVSS의 높은 위험도를 낮춤 | 스캐너 등급·카탈로그 최소 등급·수치 CVSS 중 가장 높은 등급을 사용한다. 알 수 없는 등급은 High로 취급한다. CVSS 벡터의 버전 숫자를 점수로 읽지 않는다. |
| 클라이언트 development 지정으로 운영 정책 완화 | API 수동 실행, 구형 시작 API, 웹훅, 엔진 실행에 서버 소유 환경 하한 적용. 기본 및 현재 운영 설정은 production. 기존 대기 작업도 엔진에서 재적용한다. |
| 저장소 스크립트가 엔진 UID·비밀키·Docker 소켓 사용 | 설치·테스트·빌드·사용자 명령을 digest 고정 이미지의 일회용 컨테이너에서 실행한다. UID 10001, capability 제거, no-new-privileges, 읽기 전용 루트, 저장소만 마운트, 별도 PID 공간, 환경변수 초기화, 메모리/CPU/PID/시간 제한. 격리를 못 만들면 호스트에서 대신 실행하지 않고 실패한다. |
| 저장소 .gitleaks.toml/ignore/주석으로 검사 제외 | 서버 설정에서 기본 규칙을 고정하고 저장소 ignore 및 gitleaks:allow를 무시한다. |
| Semgrep auto 규칙 변동·검사 0개 PASS | 공식 p/security-audit 규칙 스냅샷을 서버 이미지에 포함한다. 저장소 ignore와 nosemgrep를 무시하며 오류·파일 미검사 보고서는 실패 처리한다. node_modules, .venv, .git만 서버 옵션으로 제외한다. |
| 지정 커밋 조회 실패 시 다른 HEAD 실행 | 요청 커밋을 가져오지 못하면 실패. clone 후 origin에 저장된 인증정보 제거 실패도 차단한다. |
| 실제 승인 API가 처리할 수 없는 Medium 승인 표시 | production/staging의 Medium은 수정 후 재검사하도록 명시적 BLOCK. 기존 High 승인만 유지하며 Critical·Secret은 승인으로 해제되지 않는다. |

추가로 저장소 밖 심볼릭 링크·하드 링크·특수 파일을 거부한다. 명령 종료 직후 검사하여 호스트의 산출물 수집 전에 탈출 경로를 차단한다. 취소 시 작업 소유 라벨로 격리 컨테이너도 제거하며, 종료를 확인할 수 없으면 취소 완료로 응답하지 않는다.

**기능상 영향:** 선택한 항목에서 상향 보존된 위험도, production의 Medium, 검사 실패 때문에 차단될 수 있다. 선택하지 않은 항목은 이후 선택 검사에서 차단 이유가 되지 않는다. 저장소 자체 스캐너 예외는 더 이상 적용되지 않는다. 저장소 밖 링크 및 특수 파일을 요구하는 프로젝트는 실패하며, 프로젝트별 호환성 보완이 필요할 수 있다. private 패키지용 자격증명을 엔진 환경에서 암묵적으로 받던 작업은 지원하지 않는다.

## 기준 비교와 아직 부족한 부분

| 기준 및 공식 출처 | 이번에 보완한 부분 | 남는 격차 / 우선순위 |
|---|---|---|
| [OWASP CI/CD Top 10](https://owasp.org/projects/top-10-cicd-security-risks), 특히 PPE·접근통제·자격증명 | 저장소 코드의 실행 권한·비밀 분리, 서버 정책 강제, 저장소 검사 설정 우회 차단 | **높음:** sandbox의 외부 통신은 Docker bridge로 유지된다. 사설망·메타데이터·호스트에 대한 목적지별 egress 제한과 패키지 저장소 allowlist가 아직 없다. 전용 runner 호스트 또는 더 강한 격리가 필요하다. |
| [OWASP PPE](https://owasp.github.io/www-project-top-10-ci-cd-security-risks/CICD-SEC-04-Poisoned-Pipeline-Execution) | 악성 설치 hook·테스트가 엔진 프로세스로 실행되는 경로 차단 | **높음:** Docker daemon 및 배포 제어기는 여전히 높은 권한을 갖는다. 스캐너도 신뢰된 제어기에서 실행한다. 빌드/스캔/배포를 별도 서비스 및 최소권한 자격증명으로 분리하는 후속 작업이 필요하다. |
| [NIST SSDF 1.1, SP 800-218](https://csrc.nist.gov/pubs/sp/800/218/final) — 소프트웨어 보호·안전한 개발·취약점 대응 | 정확한 커밋 사용, 고정 검사 정책, 실패 시 차단 | **높음:** 스캔 이후 빌드 스크립트가 소스/산출물을 바꿀 수 있다. 검사 대상–빌드–배포 산출물 사이의 서명·해시·출처 증명과 배포 직전 검증이 없다. 커밋 SHA 고정만으로 산출물 무결성이 보장되지는 않는다. |
| [CIS Controls v8.1, Control 16](https://cas.docs.cisecurity.org/en/latest/source/Controls16/) — 안전한 개발 수명주기 | SAST/Secret 탐지와 위험 등급 기반 차단 | **높음:** 의존성 SBOM, SCA/CVE 검사, 컨테이너 이미지 취약점 검사 및 취약 버전 업데이트 절차가 필수 게이트로 연결되어 있지 않다. 현재 SAST 규칙이 모든 언어·CWE·취약점을 검사한다는 보장도 없다. |
| [OWASP CI/CD Top 10](https://owasp.org/projects/top-10-cicd-security-risks) — 로깅·가시성 | 기존 실시간 로그·재연결·이력 저장 유지 | **중간:** 독립 감사 저장소의 변조 방지, 보존 기간, 접근 감사 및 보안 알림 연계가 추가로 필요하다. 실시간 로그가 곧 보안 감사 체계는 아니다. |
| [ISO/IEC 27001:2022](https://www.iso.org/standard/27001) — ISMS·위험 관리·지속 개선 | 기술 통제 및 테스트 증거 확보 | **중간:** 조직의 책임자, 자산·위험대장, 위험 수용 기준, 예외 만료·재검토, 사고 대응·훈련, 내부 감사 증거는 이 코드 검토로 확인되지 않았다. 별도 운영 문서와 실제 운영 증거를 확인해야 한다. |

이 표는 공개된 공식 자료에 근거한 기술 격차 분석이다. ISO 유료 표준 전체 조항의 적합성 평가 또는 인증 보장은 아니다. Critical/High/Medium 임계값과 CWE 목록은 우리 서비스의 정책 선택이며, 위 기관들이 이 서비스에 해당 임계값을 직접 요구한다는 의미는 아니다.

## 검증 및 운영

- 엔진 전체 테스트: 114 passed. 선택 우회, CVSS 하향, 검사 0개, 외부 링크, 환경 하한, 커밋 실패 등 회귀 테스트 포함.
- 백엔드 승인 보안 및 실행 계약 테스트: 30 passed, DB 통합 테스트 1 skipped(별도 테스트 DB 미지정).
- 실제 후보 이미지: 비밀키·소켓·제어기 파일 비노출, non-root 쓰기, Python venv 생성 확인.
- 실제 Semgrep/Gitleaks: 저장소 allowlist/ignore/인라인 suppression이 있는 합성 취약점 탐지 확인.
- 실제 Node 프로젝트: 격리된 install/test/build 성공 확인.
- 규칙 출처 및 SHA-256: `app/policies/provenance.json`. 규칙 변경은 관리자 검토·회귀 테스트·이미지 재빌드로만 적용한다.
- `CICD_SANDBOX_IMAGE`는 관리자 생성 이미지 digest/ID만 허용한다. `SECURITY_POLICY_MIN_ENVIRONMENT=production`을 백엔드와 엔진에 동일하게 설정한다. 이미지에는 런타임 비밀을 넣지 않는다.
- 반영·롤백 기록과 합성 통합검사: `/home/capstone/deployment-artifacts/security-hardening/`. 비밀 설정 백업은 private 디렉터리로 분리되어 있다.

후속 순서는 **사설망/메타데이터 egress 차단 → 빌드·배포 권한 분리 → 산출물 서명 및 배포 전 검증 → SBOM/SCA·이미지 검사 → 감사·위험관리 운영 체계**를 권장한다.

### 실제 반영 결과

2026-11-15 KST 백엔드 `capstone-back:security-20261115`, 엔진 `capstone-engine:security-20261115`로 교체했다. 기존 컨테이너는 `*-rollback-20261115-094912` 이름으로 보존했다. 반영 후 내부/공개 HTTPS health 200, 인증된 history/deployment 조회, 공개 WSS stage/log/heartbeat 및 reconnect/replay·ping/pong을 확인했다. 검증용 실행은 삭제했고 진행 중 작업은 0건이었다. 저장소 배포 설정/summary/homepage 확인도 기존 검증 스크립트로 수행했다.
