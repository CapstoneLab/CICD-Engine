# runs 폴더 압축·저장 메뉴얼 (레포별)

> 파이프라인을 1개 돌릴 때마다 해당 run 폴더를 **레포 이름**으로 압축해 보관한다.
> 파일명 규칙: `runs_YYYYMMDD_레포이름.zip`  (예: `runs_20260608_juiceshop.zip`)

---

## 0. 기본 정보
- 결과 위치: `/home/capstone/CICD-Engine/runs/`
- run을 돌리면 `runs/run-YYYYMMDD-NNN/` 폴더가 새로 생성됨.
- 분석에 필요한 JSON·로그는 전부 이 폴더 안에 있음. (`workspace/`는 압축 불필요)

---

## 1. 방금 돌린 run 폴더 확인
가장 최근 생성된 run 폴더가 방금 돌린 결과다.
```bash
cd /home/capstone/CICD-Engine
ls -dt runs/run-* | head -1
```
> 어떤 레포의 결과인지 헷갈리면 확인:
> ```bash
> grep '"repo_url"' "$(ls -dt runs/run-* | head -1)/pipeline_result.json"
> ```

---

## 2. 레포 이름으로 압축
방금 돌린 최신 run을 자동으로 잡아 레포 이름만 바꿔 압축:
```bash
cd /home/capstone/CICD-Engine
LATEST=$(ls -dt runs/run-* | head -1)
zip -r "runs_$(date +%Y%m%d)_juiceshop.zip" "$LATEST"
```
- `juiceshop` 부분만 **실제 레포 이름**으로 바꿔서 실행한다.
- 특정 run을 직접 지정하려면:
  ```bash
  zip -r runs_20260608_juiceshop.zip runs/run-20260608-005
  ```

---

## 3. 압축 확인
```bash
ls -lh runs_*.zip                                  # 파일·용량 확인
unzip -l runs_$(date +%Y%m%d)_juiceshop.zip | tail # 내용 확인
```

---

## 4. 전달
생성된 `runs_YYYYMMDD_레포이름.zip` 들을 한 폴더에 모아 저자/분석 담당에게 전달.

---

## 주의
- **레포 이름은 일관되게**(소문자, 공백 없이). dataset 시트의 repo id와 맞추면 매핑이 쉬움.
- 같은 레포를 같은 날 두 번 돌렸으면 뒤에 버전 표기: `runs_20260608_juiceshop_v2.zip`.
- 너무 크면(수백 MB↑) zip 대신:
  ```bash
  tar -czf runs_$(date +%Y%m%d)_juiceshop.tar.gz "$LATEST"
  ```
- run 결과 폴더는 **삭제·덮어쓰기 금지**. 압축본만 따로 만든다.


## GitHub 공개 자료 (2026-11-21)

코드·논문·보고서와 소형 실험 압축파일은 이 저장소에 보관합니다.
일반 Git 업로드 한도를 넘는 아래 두 파일은 [졸업작품 자료 Release](https://github.com/CapstoneLab/CICD-Engine/releases/tag/capstone-materials-2026-11-21)에서 다운로드할 수 있습니다.

- `runs_20260718_nus-digital-twin.zip`
- `runs_20260719_nus-digital-twin_v2.zip`

공개용 압축파일에서 토큰·키 및 키 조각을 마스킹했습니다. 원본은 로컬에 보존되어 있으며, 마스킹으로 인해 원본 실험 산출물의 해시와 공개용 파일의 해시는 다를 수 있습니다. 공개용 파일의 SHA-256과 보관 위치는 `analysis/reproducibility/published-archives.json`을 참고하세요. 테스트 코드와 탐지 규칙은 유지하되, GitHub에서 차단하는 Slack 웹훅 예시 문자열은 공개용 규칙 파일에서도 마스킹했습니다.

테스트용 Java 프로젝트의 로컬 추가 커밋은 [CapstoneLab/sample_java5](https://github.com/CapstoneLab/sample_java5)에 보관합니다.
