# 백엔드 명세: Private 저장소 검사를 위한 GitHub OAuth 토큰 전달

> 대상: 백엔드팀
> 목적: 사용자가 GitHub OAuth로 로그인하면, 그 사용자가 접근 가능한 **private 저장소도** CI 엔진이 클론·검사할 수 있게 한다.
> 엔진 측 구현은 **이미 완료**되어 있다. 백엔드는 아래 3가지만 충족하면 된다.

---

## 0. 요약 (TL;DR)

1. OAuth 동의 scope에 **`repo`** 를 포함한다. (private 접근 권한)
2. 사용자별 **access_token 을 안전하게 저장**한다. (암호화 at rest)
3. 검사 job 을 엔진에 내려줄 때 payload 에 **`repo_token`** 필드로 그 사용자의 토큰을 실어 보낸다.

이게 전부다. 토큰을 받으면 엔진이 `git clone https://x-access-token:<token>@github.com/owner/repo` 형태로 클론하며, 토큰은 모든 로그에서 `****` 로 마스킹된다.

---

## 1. 동작 원리 (왜 이렇게 하나)

GitHub 토큰은 **그 토큰 주인의 권한을 그대로** 위임한다. 따라서:

| 대상 | 검사 가능 |
|------|-----------|
| 로그인 사용자가 **소유**한 private repo | ✅ |
| 로그인 사용자가 **collaborator/조직 멤버**로 접근 가능한 private repo | ✅ |
| 공개 repo | ✅ (토큰 없어도 됨) |
| 권한 없는 **타인의** private repo | ❌ (GitHub 가 차단 — 정상) |

즉 "해당 사용자가 GitHub 웹에서 볼 수 있는 repo"는 전부 검사 가능하고, 그 이상은 불가능하다 (보안상 당연).

---

## 2. 요구사항 ①: OAuth Scope

OAuth App 인가 요청 시 scope 에 반드시 **`repo`** 를 포함한다.

```
https://github.com/login/oauth/authorize
  ?client_id=<CLIENT_ID>
  &scope=repo read:user user:email
  &redirect_uri=<CALLBACK>
```

- `repo` 없이 `read:user` 만 있으면 → private repo 는 여전히 404/인증실패로 막힌다.
- `repo` 는 private 코드 read/write 권한 전체를 포함하는 광범위 scope다. 더 좁히고 싶으면 **GitHub App + fine-grained 권한**(Contents: Read-only)을 권장한다. (§7 참고)

---

## 3. 요구사항 ②: 토큰 저장

- access_token 을 **사용자 계정에 매핑하여 저장**한다. (예: `users.github_access_token`)
- **암호화 at rest** 필수. 평문 컬럼 금지. (DB 유출 = 사용자 GitHub 전체 노출이므로)
- OAuth 토큰 만료/갱신 처리:
  - **OAuth App 토큰**: 기본적으로 만료 없음(사용자가 revoke 하기 전까지). refresh 불필요.
  - **GitHub App user-to-server 토큰**: 8시간 만료 + refresh token 으로 갱신 필요.
  - 어느 쪽이든, 검사 job 을 만드는 시점에 **유효한 토큰**을 payload 에 넣어야 한다. (만료 토큰이면 클론이 인증 실패로 떨어진다 — §6)

---

## 4. 요구사항 ③: Job Payload 계약 (핵심)

### 4.1 현재 엔진↔백엔드 흐름 (변경 없음)

엔진(poller)이 백엔드를 폴링하는 구조다:

```
엔진 → GET  {BASE_URL}/api/jobs/pending?limit=N
        헤더: x-engine-token: <ENGINE_TOKEN>, x-engine-id: <ENGINE_ID>
        응답: { "jobs": [ <job>, <job>, ... ] }

엔진 → POST {BASE_URL}/api/jobs/{job_id}/claim   (claim 후 실행)
```

즉 백엔드는 **`/api/jobs/pending` 응답의 각 job 객체에 `repo_token` 한 필드만 추가**하면 된다.

### 4.2 Job 객체 스키마 (★ = 이번에 추가)

```jsonc
{
  "job_id":        "string  (필수)",
  "repo_url":      "string  (필수)  예: https://github.com/owner/repo",
  "branch":        "string  (기본 main)",
  "commit_sha":    "string  (선택, 특정 커밋 검사 시)",

  "repo_token":    "string  (★ 선택) 해당 사용자의 GitHub access_token",

  "source":        "capstone | mirae   (기본 capstone)",
  "environment":   "production | staging | development | feature (기본 development)",
  "workflow_path": "string  (선택)",
  "selected_items":"array | string (선택) 검사할 CWE/항목, 비우면 16개 전체",
  "approved_cwes": "array | string (선택) 승인된 High CWE"
}
```

- 필드명은 **`repo_token`** 을 사용한다. (엔진은 호환을 위해 `access_token` 키도 인식하지만, `repo_token` 을 권장)
- **public repo** 검사면 `repo_token` 을 **생략**해도 된다 (또는 빈 문자열). 기존 동작 그대로.
- **private repo** 검사면 `repo_token` 에 그 repo 소유/접근 권한이 있는 사용자의 토큰을 넣는다.

### 4.3 예시

**Private repo 검사 요청:**
```json
{
  "job_id": "job_20260603_001",
  "repo_url": "https://github.com/suhodang77/hydrogen-ship-LBTS",
  "branch": "main",
  "repo_token": "gho_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "source": "capstone",
  "environment": "development"
}
```

**Public repo 검사 요청 (토큰 불필요):**
```json
{
  "job_id": "job_20260603_002",
  "repo_url": "https://github.com/some-org/public-repo",
  "branch": "main",
  "source": "capstone"
}
```

---

## 5. 보안 요구사항 (백엔드가 지켜야 할 것)

1. **전송 구간 TLS 필수.** `/api/jobs/pending` 응답에 평문 토큰이 실리므로 엔드포인트는 반드시 HTTPS여야 한다. (HTTP면 토큰이 네트워크에 노출)
2. **응답 대상 제한.** `/api/jobs/pending` 은 `x-engine-token` 으로 인증된 엔진에만 토큰을 내려준다. 외부에 노출 금지.
3. **로깅 금지.** 백엔드 액세스 로그/APM 등에 `repo_token` 값이 찍히지 않도록 마스킹한다. (엔진 측은 이미 마스킹 처리됨)
4. **최소 권한.** 가능하면 GitHub App fine-grained 토큰(Contents: Read-only)으로 scope 를 좁힌다. (§7)
5. **DB 암호화 at rest** (§3 재강조).

> 참고 — 엔진 측 보안 처리(이미 구현됨):
> - 클론 URL의 토큰은 모든 로그(`clone.log`, `runs/job-*.log`)에서 `****` 로 마스킹됨.
> - `GIT_TERMINAL_PROMPT=0` 으로 토큰이 틀려도 대화형 프롬프트로 멈추지 않고 즉시 실패함.
> - 토큰 없으면 URL 변형 안 함 → public repo 기존 동작 100% 유지.

---

## 6. 실패/에러 처리

엔진은 클론 실패 시 step status `failed`, exit_code `128` 로 콜백을 보낸다. 백엔드/프론트는 다음 케이스를 구분해 안내하면 좋다:

| 로그 메시지 | 원인 | 사용자 안내 |
|-------------|------|-------------|
| `could not read Username ... No such device` | 토큰 미전달 + private repo | "GitHub 로그인/연동이 필요합니다" |
| `Invalid username or token` / `Authentication failed` | 토큰 만료·무효·scope 부족 | "GitHub 재인증이 필요합니다" |
| `Repository not found` | repo 없음 또는 권한 없음 | "저장소 접근 권한 또는 주소를 확인하세요" |

> 토큰이 만료됐는데 그대로 보내면 `Authentication failed` 로 떨어진다. 검사 job 생성 시점에 토큰 유효성을 확인하거나, 실패 콜백을 받아 재인증을 유도한다.

---

## 7. (선택·권장) GitHub App 방식

`repo` scope 는 사용자의 모든 repo 에 대한 read/write 권한이라 다소 넓다. 보안을 강화하려면 **GitHub App** 으로 전환:

- 권한을 **Contents: Read-only** 로 최소화.
- 사용자가 **특정 repo 만 선택해서 설치** 가능.
- payload 흐름은 동일 — App 이 발급한 **user-to-server access_token** 을 `repo_token` 에 넣으면 된다.
- 단, user-to-server 토큰은 **8시간 만료 + refresh** 처리가 필요하다.

엔진은 토큰 출처(OAuth App / GitHub App)를 구분하지 않으므로, 어느 방식이든 `repo_token` 에 유효한 토큰만 넣으면 그대로 동작한다.

---

## 8. 백엔드 구현 체크리스트

- [ ] OAuth 인가 요청 scope 에 `repo` 추가 (또는 GitHub App 도입)
- [ ] 콜백에서 access_token 수신 → 사용자에 매핑하여 **암호화 저장**
- [ ] (GitHub App 사용 시) refresh token 으로 토큰 갱신 로직
- [ ] `/api/jobs/pending` 응답의 각 job 에 `repo_token` 필드 추가
- [ ] private repo job 일 때 해당 사용자의 유효 토큰 주입
- [ ] 엔드포인트 HTTPS 확인, 로그에서 토큰 마스킹
- [ ] 클론 실패 콜백 처리 → 재인증 유도 UX
