# KCI 논문 실험 지시서 (후배 배포용)

> 목표: KCI(보안/DevSecOps 계열) 논문 게재.
> 본 문서의 각 과제는 논문의 표/그림과 1:1로 대응한다. 후배는 이 문서만 보고 독립 수행하고,
> 최종적으로 `results.xlsx` 한 권 + 산출물 아카이브를 제출한다.
>
> 범위: **KCI 통과선 과제만** 포함 (필수 6 + 강력권장 3). 그 외 보강 실험은 제외.

---

## 0. 공통 사항 (전원 숙지)

### 엔진 실행 기본형
```bash
python main.py --repo <URL> --branch <BR> \
  --environment development \
  [--selected-items CWE-89,CWE-319] [--approved-cwes CWE-319] [--commit <SHA>]
```

### 실행 후 산출물 (runs/run-YYYYMMDD-NNN/)
| 파일 | 내용 | 주 용도 |
|------|------|---------|
| `pipeline_result.json` | 단계별 상태/시각 | 타이밍, 런타임 |
| `security_verdict.json` | 게이트 판정/점수/counts/out_of_scope | 판정·점수 |
| `security_findings.json` | **정책 재등급된** finding | in-scope, 재등급 |
| `security_summary.json` | 스캐너별 집계 | 보조 |
| `semgrep_report.json` / `gitleaks_report.json` | **원시 스캐너 출력** | ★Baseline·등급일관성 |
| `logs/*.log` | 단계 로그 | 증거 캡처 |

### ⚠️ 절대 규칙
- `runs/` 산출물은 **절대 덮어쓰지 말 것**. repo별 폴더로 보관.
- Baseline(원시 등급) 계산은 반드시 **`semgrep_report.json`(원시)** 사용. `security_findings.json`은 이미 재등급된 값이라 baseline에 쓰면 안 됨.
- 실행 stdout의 `result file:` 경로로 run 디렉터리를 매핑해 기록.

---

## 과제 목록

| # | 과제 | 우선순위 | 담당(권장) | 기간 | 논문 매핑 |
|---|------|----------|-----------|------|-----------|
| T0 | 환경 세팅 | 필수 | 1명 | 0.5일 | 실험 환경 절 |
| T1 | 데이터셋 구축 | 필수 | 1명 | 1일 | 표: 데이터셋 |
| T2 | 메인 배치 실행 | 필수 | 1~2명 | 1~2일 | (원천 데이터) |
| T3 | 경보 축소율 | 필수 | 0.5일 | 표/그림: 경보 축소 |
| T4 | Baseline 대비 | 필수 | 1명 | 1일 | ★표: Baseline vs 제안 |
| T5 | 디지털트윈 심층사례 | 필수 | 1명 | 1일 | ★그림: 차단/Before-After |
| T6 | 정밀도/재현율 | 강력권장 | 1명(보안지식) | 2~3일 | 표: P/R/F1 |
| T7 | 등급 일관성 | 강력권장 | 0.5일 | 표: 등급 재정의 |
| T8 | 성능 오버헤드 | 강력권장 | 0.5일 | 표/그림: 단계별 시간 |

---

## T0. 환경 세팅 [필수]
**목적:** 모든 실험의 전제.
- 설치: `git`, `node+npm`, `python3+venv`, `JDK 17`, `gitleaks`, `semgrep`. (배포 실험은 KCI 범위 제외)
- `.env`에 `ANTHROPIC_API_KEY` 설정(AI 권고용; T5에서 필요).
- 검증: 임의 repo 1개 실행 → `runs/`에 산출물 6종 정상 생성 확인.
- **제출:** 각 도구 `--version` 캡처 → `env_versions.txt`.

---

## T1. 데이터셋 구축 [필수]
**목적:** 정량평가 표본. → 논문 *표: 데이터셋 구성*

세 그룹, 총 30~40개:
- **그룹 A (취약앱, ground truth용 ~8개):** OWASP Juice Shop, NodeGoat, DVNA, OWASP WebGoat(Java), Vulnerable-Flask-App, Django.nV, railsgoat 등.
- **그룹 B (일반 OSS ~24개):** Node/Python/Java 각 8개. 도메인·규모 다양하게.
- **그룹 C (산업 사례 1개):** 수소추진 디지털트윈(보유).

**제출 (sheet1 = `dataset`):**

| id | repo_url | group(A/B/C) | language | stars | LoC | 비고 |
|----|----------|--------------|----------|-------|-----|------|

---

## T2. 메인 배치 실행 [필수]
**목적:** 전 repo 실행 → 후속 과제의 원천 데이터.

**절차:**
1. T1의 각 repo를 `--environment development`로 1회 실행.
2. run 디렉터리 매핑 기록.
3. 산출물 6종을 `repo_id`별 폴더로 보관.

**제출 (sheet2 = `runs_master`):** repo 1행씩.

| id | run_id | runtime_type | pipeline_status | gate_verdict | score | crit | high | med | low | out_of_scope | raw_findings_총건수 |
|----|--------|--------------|-----------------|--------------|-------|------|------|-----|-----|--------------|---------------------|

- runtime_type, pipeline_status ← `pipeline_result.json`
- verdict/score/counts/out_of_scope ← `security_verdict.json`
- raw_findings_총건수 ← `security_findings.json` 배열 길이

**추가 제출:** 모든 `runs/` zip → `runs_archive.zip`.

---

## T3. 경보 축소율 [필수]
**목적:** 정책 카탈로그의 노이즈 감소 실증(디지털트윈 7→2가 대표). → *표/그림: 경보 축소율*

repo별:
- N_raw = `security_findings.json` 전체 건수
- M_inscope = `in_scope:true` 건수
- 축소율(%) = (N_raw − M_inscope) / N_raw × 100

**제출 (sheet3 = `alert_reduction`):**

| id | N_raw | M_inscope | 축소율(%) |
|----|-------|-----------|-----------|

마지막 행에 **전체 평균 축소율**.

---

## T4. Baseline 대비 [필수, ★핵심]
**목적:** "스캐너 등급 그대로 게이팅" vs "제안 정책 게이팅" 대비. → *표: Baseline vs 제안*

**Baseline 정의:** `semgrep_report.json`의 각 result `extra.severity`(ERROR/WARNING/INFO) + `gitleaks_report.json` 건수를 원시 그대로 사용.
단순 규칙 예: "원시 ERROR(=high/critical급) 1건 이상이면 block".

**제안:** `security_verdict.json`의 실제 판정.

**제출 (sheet5 = `baseline_compare`):**

| id | baseline_판정대상_건수 | baseline_verdict | proposed_in-scope_건수 | proposed_verdict | 판정 달라짐? |
|----|------------------------|------------------|------------------------|------------------|--------------|

핵심 수치: 평균 판정대상 건수(baseline vs 제안)와 판정이 달라진 케이스 수.

---

## T5. 디지털트윈 심층 사례 [필수, ★flagship]
**목적:** 산업 적용 + 수정 효과. → *그림: 차단 사례 / Before-After*

1. **Before:** run-20260604-008 결과 정리(보유): CWE-319(평문 WebSocket) 차단, 원시 7→in-scope 2, 점수 94, build/deploy skip.
2. **AI 권고 전문 캡처:** `security_findings.json`의 CWE-319 항목 `ai_recommendation` 전체 텍스트 → 인용 박스용.
3. **After:** 디지털트윈 fork에서 `ws://`→`wss://` 수정 후 재실행 → 게이트 통과 + build/deploy 진행 확인. *(회사 협의 필요)*

**제출 (`digitaltwin_case/`):** before/after `security_verdict.json` 2개 + AI 권고 전문 + 단계 진행 로그/스크린샷.

---

## T6. 정밀도/재현율 [강력권장] — 손이 많이 감
**목적:** 게이트 탐지 정확도. → *표: Precision/Recall/F1*

**절차:**
1. 그룹 A 각 앱의 **ground truth 라벨링:** 공식 문서/CWE 목록에서 16종 카탈로그에 해당하는 알려진 취약점을 파일/CWE 단위로 정리.
2. `security_findings.json`의 `in_scope:true` 건과 ground truth 대조:
   - TP = 카탈로그가 잡았고 GT에도 있음
   - FP = 잡았으나 GT에 없음
   - FN = GT에 있으나 못 잡음
3. Precision=TP/(TP+FP), Recall=TP/(TP+FN), F1.

**⚠️ 경계:** 16종 카탈로그 **범위 내 항목만** 평가. 범위 밖 CWE는 FN으로 세지 말 것(정책 대상 아님). 이 경계를 논문에 명시.

**제출 (sheet4 = `accuracy`):** 앱별 TP/FP/FN/P/R/F1 + 전체 마이크로평균.
별도: `groundtruth_labels.md`(라벨 근거·출처).

---

## T7. 등급 일관성 [강력권장]
**목적:** "스캐너마다 다른 등급 → 카탈로그로 통일" 실증. → *표: 등급 재정의 사례*

전체 in-scope finding에서 **원시 severity ≠ 카탈로그 등급** 건수 카운트:
- 원시: `semgrep_report.json`의 `extra.severity`/`metadata.severity`
- 카탈로그: `security_findings.json`의 `severity`(재등급됨)
- 같은 CWE를 매핑해 불일치 건 카운트. 대표 사례 2~3개 표로 예시(예: "semgrep=WARNING → 정책=High").

**제출 (sheet6 = `grade_consistency`):** 전체 finding 수 / 불일치 수 / 불일치율 + 대표 사례.

---

## T8. 성능 오버헤드 [강력권장]
**목적:** 보안 단계가 추가하는 시간. → *표/그림: 단계별 소요시간*

각 run `pipeline_result.json`의 단계별 `started_at`/`finished_at` 차(초)로 산출.
강조점: **deep-security(semgrep) 단계 비중**, **security_gate 자체 오버헤드(≈0초)**.

**제출 (sheet8 = `timing`):** repo별 clone/install/test/scan/gate/build 시간 + 그룹별 평균.

---

## 최종 제출 패키지 (후배 → 작성자)
1. `results.xlsx` — sheet1, sheet2, sheet3, sheet4(권장), sheet5(=baseline_compare), sheet6(권장), sheet8(권장). *(시트 번호는 과제 표기 따름)*
2. `runs_archive.zip` — 모든 run 산출물 원본.
3. `groundtruth_labels.md` — T6 라벨 근거.
4. `env_versions.txt` — T0 도구 버전.
5. `digitaltwin_case/` — T5 before/after + AI 권고 전문.

---

## 진행 순서
```
T0 → T1 → T2 ─┬→ T3
              ├→ T4
              ├→ T6 (권장)
              ├→ T7 (권장)
              └→ T8 (권장)
T5 는 병렬 진행 가능 (디지털트윈 별도)
```
**최소선(시간 부족 시):** T0 → T1 → T2 → T3 → T4 → T5.
