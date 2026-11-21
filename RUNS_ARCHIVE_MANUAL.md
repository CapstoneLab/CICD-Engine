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
