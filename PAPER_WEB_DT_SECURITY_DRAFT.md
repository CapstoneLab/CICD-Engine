# 웹 기반 디지털트윈 소프트웨어를 위한 CWE 정책 기반 보안성 측정 기법 및 실증 분석

**A CWE Policy-Based Security Measurement Method and Empirical Analysis for Web-Based Digital Twin Software**

## 초록

웹 기반 디지털트윈 소프트웨어는 물리 자산과 센서 데이터를 웹 인터페이스, API, 3차원 시각화 및 클라우드 배포 환경을 통해 연계한다. 본 논문은 웹 기반 디지털트윈 SW에 대한 보안성 측정의 부재를 문제로 정의한다. 여기서 부재는 디지털트윈 보안 연구나 분석 도구가 존재하지 않는다는 의미가 아니라, 웹 클라이언트, 서버 API, 3차원 시각화 코드, 자산·센서 데이터 채널, 자격증명 및 배포 설정을 반영한 디지털트윈 특화 측정 기준·지표·체계가 충분히 정립되지 않은 상태를 의미한다. 이를 해결하기 위해 디지털트윈 공격 표면을 네 영역으로 구조화한 CWE 정책 기반 보안성 측정 기법을 제안한다. 제안 기법은 Gitleaks 기반 비밀정보 검사와 Semgrep 기반 소스 코드·설정 정적 분석을 수행하고, 탐지 레코드를 연구자 정의 16종 CWE 정책 카탈로그에 매핑한다. 이후 정책 범위와 등급별 건수, 보조 점수 및 계층형 게이트 판정을 측정 지표로 산출하고, CI/CD 파이프라인을 통해 측정 절차를 반복 수행하며 실행 근거를 JSON으로 보존한다. 평가 후보군은 취약 웹 애플리케이션 8개, 공개 디지털트윈 14개 및 수소추진선박용 Unity 3D·센서 웹 저장소 1개 등 총 23개로 구성하였다. 이 중 원천 산출물 완전성 기준을 충족한 16개 대표 실행을 정량 분석한 결과, 엔진 생성 파일을 제외한 저장소 파일의 원시 탐지 레코드 3,851건 중 1,885건이 정책 범위에 포함되었다. A7에 포함된 Benchmark v1.2 정답표와 정책이 공통으로 포함하는 6개 CWE에 대한 입력 탐지는 정밀도 0.533, 재현율 0.772 및 F1 0.630을 보였다. 디지털트윈 8개에서는 원시 탐지 레코드 170건 중 67건이 정책 범위에 포함되었으며, 5개는 `block`, 2개는 `block_pending_approval`, 1개는 `pass`로 판정되었다. 수소추진선박 디지털트윈 적용 사례에서는 High 등급 CWE-319(Cleartext Transmission)과 Medium 등급 CWE-79(XSS) 탐지 레코드에 따라 보조 점수 94점과 함께 빌드 이전 승인 대기 판정이 수행되었다. 실험 결과는 제안 기법이 이질적인 보안 도구 결과를 디지털트윈 특화 측정 기준과 지표로 변환하고, 저장소의 정적 보안 특성을 빌드·배포 통제와 연결할 수 있음을 보여준다.

**주제어:** 웹 기반 디지털트윈, 보안성 측정, CWE, 정적 분석, DevSecOps, 보안 게이트

## Abstract

Web-based digital-twin software connects physical assets and sensor data through web interfaces, APIs, three-dimensional visualization, and cloud deployment environments. This paper defines the absence of security measurement for web-based digital-twin software as its research problem. Here, absence refers to the insufficient establishment of digital-twin-specific criteria, metrics, and a measurement framework that reflect web clients, server APIs, three-dimensional visualization code, asset and sensor data channels, credentials, and deployment configurations. To address this problem, this paper proposes a CWE policy-based security measurement method that structures the digital-twin attack surface into four measurement domains. The method performs secret scanning with Gitleaks and source-code and configuration analysis with Semgrep, and then maps the detected findings to a researcher-defined catalog of 16 CWE policy items. It derives policy-scope counts, grade-specific counts, an advisory score, and a hierarchical gate verdict as measurement metrics, while repeatedly applying the procedure and preserving execution evidence as JSON artifacts through a CI/CD pipeline. The candidate set comprised 23 repositories: eight intentionally vulnerable web applications, fourteen public digital-twin projects, and one hydrogen-powered ship digital-twin application repository with Unity 3D and sensor interfaces. Quantitative analysis was conducted on 16 representative runs that satisfied the source-artifact completeness criterion. Among these runs, 1,885 of 3,851 raw findings from repository files excluding engine-generated artifacts were included in the policy scope. For the six CWEs shared by the policy and the Benchmark v1.2 ground-truth file included in A7, the input detection achieved a precision of 0.533, recall of 0.772, and F1-score of 0.630. In the eight digital-twin cases, 67 of 170 raw findings were mapped to the policy scope; five repositories received `block`, two received `block_pending_approval`, and one received `pass`. In the hydrogen-powered ship digital-twin application case, a High-grade CWE-319 (Cleartext Transmission) finding and a Medium-grade CWE-79 (XSS) finding produced a pre-build approval-pending verdict with an advisory score of 94. The results show that the proposed method transforms heterogeneous scanner outputs into digital-twin-specific measurement criteria and metrics and connects statically observable repository properties to build and deployment decisions.

**Keywords:** Web-Based Digital Twin, Security Measurement, CWE, Static Analysis, DevSecOps, Security Gate

---

## 1. 서론

### 연구 배경

디지털트윈은 현실의 자산과 시스템을 디지털 공간에 표현하고, 관측 데이터와 모델을 이용하여 분석·예측·제어를 지원하는 기술이다. 또한 정보 기술, 운영 기술, 모델링 및 시뮬레이션 요소가 결합된 시스템으로 정의된다[1]. 최근 디지털트윈은 웹 브라우저 기반의 3차원 뷰어, 대시보드, API 서버 및 클라우드 배포 환경으로 구현되고 있다. 이러한 웹 기반 구조는 사용 편의성과 접근성을 높이며, 동시에 클라이언트 코드, 서버 API, 자격증명, 통신 채널 및 배포 설정까지 보안 검증 범위를 확장한다.

기존 디지털트윈 보안 연구는 데이터 무결성, 접근 통제, 신뢰, 사이버 물리 시스템(Cyber-Physical System; CPS) 위협, 침입 탐지 및 물리 시스템 방어를 중심으로 발전해 왔다[2]-[6]. 이러한 연구는 디지털트윈의 위협과 보안 구조를 제시하는 기반을 마련하였다. 이를 실제 공개 소프트웨어 저장소의 보안성 측정으로 연결하기 위해서는 소스 코드, 하드코딩 비밀정보 및 배포 설정을 동일한 조건으로 반복 분석하고, 서로 다른 보안 도구의 결과를 공통 정책 단위로 변환하는 절차가 요구된다.

### 디지털트윈 소프트웨어의 보안 검증 필요성

웹 기반 디지털트윈은 SQL Injection, Command Injection, XSS, Path Traversal, 인증·인가 취약점 및 민감정보 노출과 같은 웹 취약점에 노출될 수 있다. 또한 물리 자산의 상태를 반영하는 데이터 흐름과 연결되므로, Cleartext Transmission과 자격증명 노출은 관측 데이터의 기밀성과 무결성에 영향을 줄 수 있다. 이에 따라 백엔드 API, 접근 자격증명 및 시스템 구조를 보호하기 위한 소프트웨어 수명주기 전반의 자동 소스 코드 검사가 요구된다[2]. 또한 보안 활동을 기존 SDLC에 통합하는 개발 절차가 권고된다[7].

정적 분석과 비밀정보 검사는 이러한 보안 약점을 자동으로 탐지할 수 있지만, 도구별 분석 대상과 결과 형식 및 심각도 기준은 서로 다르다. 본 논문에서는 보안 도구가 생성한 개별 finding을 탐지 레코드로 정의한다. 탐지 레코드의 단순 건수와 도구별 심각도만으로는 웹 클라이언트, API, 데이터 채널 및 배포 설정이 결합된 디지털트윈의 보안성을 일관된 기준으로 평가하기 어렵다. 따라서 디지털트윈 구성요소와 보안 약점을 연결하는 측정 기준, 저장소 상태를 표현하는 지표, 그리고 이를 반복 적용하고 빌드·배포 판단으로 연결하는 체계가 필요하다.

### 연구 목적 및 기여점

본 논문의 목적은 웹 기반 디지털트윈 SW에 대한 보안성 측정의 부재를 해결하기 위해 디지털트윈 특화 측정 기준·지표·체계를 제안하고 실증하는 것이다. 본 연구에서 측정 기준은 웹 인터페이스, API, 데이터 채널, 자격증명 및 배포 설정의 공격 표면을 반영한 16종 CWE 정책 카탈로그를 의미한다. 측정 지표는 원시·정책 범위·정책 범위 외 탐지 레코드 수, 등급별 건수, 보조 점수 및 게이트 판정으로 구성한다. 측정 체계는 Semgrep과 Gitleaks의 탐지 결과를 정규화하고 측정 지표를 산출하는 CI/CD 파이프라인과 실행별 JSON 근거 보존 절차로 구성한다. 제안 기법은 공개 저장소와 수소추진선박 디지털트윈 적용 사례를 통해 검증한다.

이를 해결하기 위한 본 연구의 기여는 다음과 같다.

1. 웹 기반 디지털트윈의 공격 표면을 입력 처리, 통신·암호화, 인증·인가·세션 보호, 비밀정보·오류정보 노출의 네 영역으로 구조화하고, 이를 16종 CWE 정책 항목과 위험 등급으로 연결한 보안성 측정 기준을 제안한다.
2. Semgrep과 Gitleaks의 이질적인 탐지 결과를 저장소 단위 측정 지표로 변환하고, 이를 반복 적용하는 CI/CD 측정 체계와 실행별 JSON 근거 보존 절차를 구현한다.
3. 취약 웹 애플리케이션과 웹 기반 디지털트윈으로 구성된 23개 후보군 중 원천 산출물 완전성 기준을 충족한 16개 대표 실행을 대상으로 입력 탐지 성능, CWE 분포, 정책 적용 결과 및 수소추진선박 디지털트윈 적용 과정을 실증적으로 분석한다.

논문의 나머지 구성은 다음과 같다. 2장에서는 웹 보안성 측정 도구와 디지털트윈 보안 연구를 검토하고 문제를 정의한다. 3장에서는 제안 측정 기법과 구현 절차를 설명한다. 4장에서는 실험 대상, 환경, 탐지 유형 및 정량 분석 결과를 제시한다. 5장에서는 결론과 향후 연구를 기술한다.

## 2. 관련 연구 및 문제 정의

### 2.1 웹 보안성 측정 도구 및 관련 연구

본 절에서는 웹 보안성 측정에 활용되는 정적 분석 도구와 결과 정규화·평가 기준을 살펴보고, DevSecOps 및 디지털트윈 보안 관련 연구를 분석한다.

정적 애플리케이션 보안 테스팅(Static Application Security Testing; SAST)은 프로그램을 실행하지 않고 소스 코드 또는 중간 표현을 분석하여 보안 취약점 패턴을 탐지하는 기법이다. Semgrep은 구문 패턴과 데이터 흐름 규칙을 이용하여 여러 언어의 소스 코드와 설정 파일을 분석하고, 탐지 결과를 JSON 형식으로 제공한다[13]. Gitleaks는 Git 저장소, 디렉터리 및 파일에 포함된 API 키, 접근 토큰, 비밀번호, 개인 키 등의 비밀정보 패턴을 탐지한다[14]. 본 논문에서 비밀정보는 API 키, 접근 토큰, 비밀번호 및 개인 키를 통칭하며, 자격증명은 이 중 인증에 사용되는 값을 의미한다. 두 도구는 분석 대상과 결과 형식이 다르므로 탐지 레코드를 하나의 측정 결과로 통합하기 위한 공통 식별 기준이 필요하다.

CWE는 소프트웨어와 하드웨어의 보안 약점을 체계적으로 분류하는 공통 기준이며, 서로 다른 보안 도구의 탐지 결과를 연결하는 식별자로 활용된다[11]. 본 연구는 CWE 식별자를 결과 정규화 키로 사용하고, 16종 정책 카탈로그에 따라 탐지 레코드를 Critical, High, Medium, Low 등급으로 재분류한다. 또한 정보보안 측정 지침에 따라 측정 대상, 산출값 및 해석 범위를 명시하여 저장소 단위 보안성 측정 결과의 사용 목적을 구분한다[12].

정적 분석 도구의 탐지 성능은 정답 집합과의 비교를 통해 평가할 수 있다. SAST 도구 비교 연구에서는 적용 규칙과 분석 방식에 따라 CWE별 탐지 결과가 달라지는 특성이 확인되었다[15]. OWASP Benchmark는 실행 가능한 취약·비취약 테스트 케이스와 CWE별 정답표를 제공하며, 이를 통해 TP, FP, FN 및 TN을 산출할 수 있다[10]. 본 연구는 OWASP Benchmark를 Semgrep 정적 분석 결과의 입력 탐지 성능 평가에 사용하고, 나머지 취약 웹 애플리케이션은 제안 기법의 적용 결과 분석에 활용한다.

DevSecOps는 보안 검사를 소프트웨어의 개발·통합·배포 과정에 포함하는 접근이다. 보안 개발 활동을 기존 SDLC에 통합하는 공통 실무와 CI/CD 파이프라인에 소프트웨어 공급망 보안 조치를 결합하는 전략이 제시되어 있다[7],[8]. 또한 DevSecOps 도입 과정에서 고려해야 할 자동화 도구, 조직 및 인프라 요소가 체계적으로 정리되었다[9]. 본 연구는 CI/CD 파이프라인을 공통 측정 절차의 반복 적용, 측정 결과 보존 및 빌드·배포 통제를 위한 실행 기반으로 활용한다.

디지털트윈 보안 연구는 보안 분석, 시스템 아키텍처 및 위험 분류를 중심으로 수행되었다. 디지털트윈을 CPS의 보안 분석과 모니터링에 활용하는 연구가 정리되었으며[4], 산업 자동화·제어시스템을 위한 디지털트윈 보안 아키텍처도 제안되었다[5]. 또한 디지털트윈의 보안 활용과 잠재적 위험이 분석되었고[3], 보안·프라이버시·인프라·표준화 문제가 체계적으로 분류되었다[6]. 이러한 연구를 웹 기반 디지털트윈 소프트웨어의 저장소 수준 평가로 연결하려면, 디지털트윈의 복합 공격 표면을 반영한 측정 기준과 지표를 정의하고 이를 서로 다른 구현체에 반복 적용할 수 있는 측정 체계가 요구된다.

### 2.2 문제 정의

본 논문의 문제 정의는 **웹 기반 디지털트윈 SW에 대한 보안성 측정의 부재**이다. 여기서 부재는 디지털트윈 보안 연구나 웹 보안 분석 도구가 존재하지 않는다는 의미가 아니다. 웹 클라이언트, 서버 API, 3차원 시각화 코드, 자산·센서 데이터 채널, 접근 자격증명 및 배포 설정으로 구성되는 디지털트윈의 특성을 반영하여 보안성을 평가할 측정 기준·지표·체계가 충분히 정립되지 않은 상태를 의미한다.

측정 기준은 디지털트윈의 구성요소와 보안 약점의 대응 관계 및 위험 등급을 정의하는 기준이다. 측정 지표는 서로 다른 저장소의 보안 특성을 동일한 형식으로 표현하는 정량값이며, 측정 체계는 보안 도구의 탐지 결과를 수집·정규화하고 지표 산출과 빌드·배포 판단을 반복 수행하는 절차이다. 기존 CWE는 공통 약점 분류체계이므로, 디지털트윈 특화 측정에는 디지털트윈 공격 표면을 기준으로 CWE를 선별·영역화하고 정책 등급과 측정 지표로 연결하는 과정이 필요하다.

본 논문은 이 문제를 해결하기 위해 디지털트윈 공격 표면을 네 영역으로 구분하고 이에 대응하는 16종 CWE 정책 항목과 위험 등급을 측정 기준으로 정의한다. 정책 범위, 등급별 건수, 보조 점수 및 게이트 판정을 측정 지표로 구성하며, Semgrep과 Gitleaks의 탐지 결과를 CWE 중심 정책으로 정규화하는 CI/CD 파이프라인을 측정 체계로 구현한다. 제안 기법은 정답 집합 기반 입력 탐지 성능, 공개 디지털트윈의 CWE 분포와 정책 적용 결과, 수소추진선박 디지털트윈의 적용 과정 및 실행 특성을 기준으로 평가한다.

## 3. 웹 기반 디지털트윈을 위한 보안성 측정 기법

### 3.1 개요

본 논문에서 제안하는 보안성 측정 기법은 측정 기준, 측정 지표 및 측정 체계의 세 요소로 구성한다. 측정 기준은 웹 기반 디지털트윈 저장소에서 관찰할 보안 약점과 정책 등급을 정의하고, 측정 지표는 탐지 레코드의 정책 범위, 등급별 건수, 보조 점수 및 게이트 판정을 저장소 단위로 표현한다. 측정 체계는 분석 커밋을 기록한 뒤 비밀정보와 소스 코드 보안 약점을 수집하고, 이를 CWE 정책 단위로 정규화하여 빌드·배포 진행 여부를 결정한다. 그림 1은 제안 기법의 전체 절차를 나타낸다.

```text
저장소·브랜치 입력 및 분석 커밋 기록
    ↓
실행 환경 식별 및 의존성 설치
    ↓
Gitleaks 비밀정보 검사
    ↓
테스트(존재하는 경우)
    ↓
Semgrep 소스 코드·설정 정적 분석
    ↓
CWE 정규화 및 16종 정책 매핑
    ↓
정책 범위/등급/점수/게이트 판정 산출
    ↓
게이트 판정에 따른 빌드·배포 통제 및 JSON 보존
```

**그림 1. 웹 기반 디지털트윈 보안성 측정 절차**

제안 기법은 저장소별 결과를 동일한 형식으로 산출하기 위해 측정 벡터를 사용한다. 엔진 생성 파일을 제외한 저장소 \(R\)의 파일 기준 측정 벡터 \(M(R)\)를 다음과 같이 정의한다.

\[
M(R)=\langle N_{raw}, N_{in}, N_{out}, n_C,n_H,n_M,n_L,S,V,T \rangle
\]

여기서 \(N_{raw}\)는 두 보안 도구가 생성한 저장소 파일의 탐지 레코드 수이다. \(N_{in}\)은 16종 정책에 매핑된 레코드 수이고, \(N_{out}=N_{raw}-N_{in}\)은 정책 범위 외 레코드 수이다. \(n_C,n_H,n_M,n_L\)은 정책 등급별 탐지 레코드 수이며, \(S\), \(V\), \(T\)는 각각 보조 점수, 게이트 판정 및 단계별 실행 시간을 나타낸다. Semgrep 실행 작업 공간에 포함된 엔진 생성 파일 `.localci/workflow.yml`의 탐지 결과는 저장소 파일 집계에서 분리하고 민감도 분석에 사용한다. 동일 파일·행에 여러 규칙이 반응한 경우에도 각 탐지 레코드를 독립 레코드로 계산한다. 정답 집합 기반 탐지 성능 평가에서는 `(테스트 ID, CWE)` 단위로 중복을 정규화한다.

제안 파이프라인은 Node.js, Python 및 Java 프로젝트를 마커 기반으로 식별한다. 이후 프로젝트별 워크플로에 따라 복제, 의존성 설치, Gitleaks 비밀정보 검사, 테스트, Semgrep 정적 분석과 게이트 판정, 빌드 및 배포 단계를 수행한다. 보안 게이트는 `kind: builtin`과 `uses: deep_security_scan`으로 정의된 단계 직후 실행된다. 본 실험은 해당 단계가 포함된 실행을 선정하고, development 환경, 16종 정책 범위, Semgrep `auto` 및 Gitleaks `detect`를 공통 실행 설정으로 적용한다.

### 3.2 상세 절차

#### 3.2.1 보안 취약점 탐지 단계

첫째, 저장소 URL과 브랜치를 입력받아 작업 공간에 복제한다. 지정 커밋이 입력된 경우 해당 커밋을 checkout한다. 파이프라인은 실제 분석된 커밋 SHA를 결과에 기록하며, 이를 동일 저장소의 반복 실행과 저장소 간 결과를 비교하는 기준으로 사용한다.

둘째, Gitleaks의 `detect` 명령으로 저장소에 포함된 비밀정보 패턴을 검사한다. Gitleaks는 API 키, 접근 토큰, 비밀번호 및 개인 키에 대한 탐지 레코드를 JSON으로 생성한다. 정책 파서는 각 탐지 레코드를 Hardcoded Secret(CWE-798)에 매핑하고 Critical 등급을 부여한다. 탐지 문자열의 유효성을 해석할 때에는 운영 자격증명, 테스트 키, 예제 토큰 및 폐기 자격증명을 구분한다.

셋째, Semgrep을 `--config auto`로 실행하여 소스 코드와 설정 파일을 분석한다. Semgrep 결과에서 규칙 ID, 파일 경로, 행 번호, 메시지, 원시 심각도 및 CWE 메타데이터를 수집한다. `results` 배열은 정책 정규화의 입력으로 사용한다. `errors` 배열의 timeout과 partial parsing은 원시 보고서에 보존하며, 본 분석에서 완전성 정보로 별도 집계한다.

넷째, Semgrep과 Gitleaks의 탐지 레코드를 하나의 목록으로 결합한다. 16종 정책 카탈로그에 등록된 CWE는 해당 정책 등급으로 정규화한다. 카탈로그 외 CWE와 CWE 식별자 미부여 레코드는 정책 범위 외 결과로 분류한다. 정책 범위 외 결과도 원시 보고서와 정규화 보고서에 보존하여 후속 검토에 사용한다.

#### 3.2.2 취약점 탐지 결과 단계

취약점 탐지 결과 단계에서는 통합된 탐지 레코드를 16종 CWE 정책 카탈로그와 비교한다. 표 1은 본 연구에서 사용한 정책 항목, 등급 및 기본 감점 계수를 나타낸다. CWE는 도구 결과를 연결하는 공통 식별자로 사용한다. 등급과 감점은 공격 전제조건, 예상 영향 및 웹 기반 디지털트윈의 공격 표면을 고려하여 정의한 운영 정책이다.

정책 카탈로그는 웹 인터페이스와 API의 입력 처리, 자산·센서 데이터의 통신 및 암호화, 인증·인가와 세션 보호, 비밀정보와 오류 정보 노출의 네 영역으로 구성하였다. 입력 처리 영역에는 Injection, Path Traversal, XSS, SSRF 및 Insecure Deserialization을 포함하고, 통신·암호화 영역에는 Cleartext Transmission과 Weak Cryptography를 포함하였다. 인증·인가와 세션 보호 영역에는 IDOR, JWT 검증, 쿠키 보안 속성 및 비밀번호 요구사항을 배치하였으며, 비밀정보와 오류 정보 노출 영역에는 Hardcoded Secret과 Error Information Exposure를 포함하였다. 이 구성은 웹 기반 디지털트윈의 클라이언트, API, 데이터 채널 및 배포 설정에서 정적으로 관찰할 수 있는 보안 약점을 저장소 단위로 측정하기 위한 연구자 정의 범위이다. 본 연구의 디지털트윈 특화 기준은 새로운 약점 식별자를 정의하는 방식이 아니라, 공통 CWE를 디지털트윈 공격 표면에 따라 선별·영역화하고 정책 등급과 측정 지표 및 게이트 판정으로 연결하는 방식으로 구성한다.

**표 1. 디지털트윈 측정 영역별 16종 CWE 정책 카탈로그**

| 측정 영역 | 등급 | CWE | 정책 항목 | 기본 감점 계수 |
|---|---|---|---|---:|
| 입력 처리 | Critical | CWE-89 | SQL Injection | 20.0 |
| 입력 처리 | Critical | CWE-78 | Command Injection | 20.0 |
| 비밀정보·오류정보 노출 | Critical | CWE-798 | Hardcoded Secret | 20.0 |
| 입력 처리 | Critical | CWE-94 | Code Injection | 20.0 |
| 입력 처리 | High | CWE-502 | Insecure Deserialization | 5.0 |
| 인증·인가·세션 보호 | High | CWE-639 | IDOR | 5.0 |
| 인증·인가·세션 보호 | High | CWE-347 | Improper JWT Verification | 5.0 |
| 통신·암호화 | High | CWE-319 | Cleartext Transmission | 5.0 |
| 입력 처리 | Medium | CWE-22 | Path Traversal | 1.0 |
| 입력 처리 | Medium | CWE-79 | Cross-Site Scripting | 1.0 |
| 통신·암호화 | Medium | CWE-327 | Weak Cryptography | 1.0 |
| 입력 처리 | Medium | CWE-918 | SSRF | 1.0 |
| 비밀정보·오류정보 노출 | Low | CWE-209 | Error Information Exposure | 0.2 |
| 인증·인가·세션 보호 | Low | CWE-1004 | Missing HttpOnly Flag | 0.2 |
| 인증·인가·세션 보호 | Low | CWE-614 | Missing Secure Flag | 0.2 |
| 인증·인가·세션 보호 | Low | CWE-521 | Weak Password Requirements | 0.2 |

정책 카탈로그에 매핑된 탐지 레코드는 Critical, High, Medium, Low로 재분류된다. 등급별 탐지 레코드 수를 \(n_C,n_H,n_M,n_L\)이라 할 때 High, Medium, Low의 감점은 다음과 같다.

\[
D_H=\min(5n_H,19),\quad D_M=\min(n_M,4),\quad D_L=\min(0.2n_L,0.9)
\]

\(n_C=0\)인 경우 점수 (S)는 다음과 같다.

\[
S=\max(0,100-D_H-D_M-D_L)
\]

\(n_C\geq1\)인 경우 다음 식을 적용하여 점수를 0~40 구간으로 제한한다.

\[
S=\max(0,\min(40,100-20n_C-D_H-D_M-D_L))
\]

표 1의 값은 점수식에 적용되는 기본 감점 계수이다. Critical 등급이 한 건 이상이면 점수 상한 40을 함께 적용하므로, Critical 등급의 영향은 단순 건당 20점 감점과 구분된다. High, Medium, Low의 감점 상한은 각 등급의 누적 감점이 상위 등급의 단일 탐지 레코드보다 낮은 우선순위를 유지하도록 설계하였다. 보조 점수 \(S\)는 정책 범위의 저장소 상태를 요약한다. 빌드·배포 여부를 나타내는 게이트 판정 \(V\)는 점수와 분리하여 다음 계층 규칙으로 산출한다.

```text
Critical 등급 ≥ 1                                  → block
미승인 High 등급 ≥ 1                               → block_pending_approval
Critical·미승인 High 등급 = 0, Medium 등급 ≥ 1    → warn
그 밖의 경우                                       → pass
```

Critical 등급 탐지 레코드는 `block`으로 판정한다. 미승인 High 등급 탐지 레코드는 `block_pending_approval`로 판정하며, 승인된 High 등급 레코드도 보조 점수에는 반영한다. Medium 등급 레코드는 development 환경에서 `warn`으로 처리한다. 승인된 High 등급 및 Low 등급 레코드만 존재하거나 정책 범위 탐지 레코드가 0건인 경우 `pass`로 판정한다. `block`과 `block_pending_approval`은 후속 빌드와 배포를 중단한다. production과 staging에서는 Medium 등급만 존재하는 `warn`을 `block_pending_approval`로 강화한다.

제안 파이프라인은 탐지 결과와 게이트 판정을 실행별 JSON 산출물로 저장한다. 원시 탐지 결과는 `semgrep_report.json`과 `gitleaks_report.json`에 기록한다. 도구별 요약은 `security_summary.json`, 정규화 탐지 레코드는 `security_findings.json`, 게이트 판정은 `security_verdict.json`에 기록한다. 전체 실행 상태와 단계별 시간은 `pipeline_result.json`과 로그에 기록한다. 실제 단계 순서는 `steps` 배열의 위치가 아닌 단계별 timestamp를 기준으로 확인한다. 정책 전후의 심각도는 규칙 ID, 파일 경로 및 행 번호를 이용하여 연결한다.

## 4. 웹 기반 디지털트윈의 보안성 측정 및 분석

### 4.1 실험 대상 및 선정 기준

본 장에서는 제안 기법의 입력 탐지 성능과 웹 기반 디지털트윈의 보안성 측정 결과를 평가한다. 실험 대상은 평가 목적에 따라 세 그룹으로 구성하였다. 그룹 A의 취약 웹 애플리케이션 8개는 탐지 절차의 작동을 확인하고, 이 중 A7은 정답 집합 기반 탐지 성능 평가에 사용한다. 그룹 B의 공개 웹 기반 디지털트윈 14개는 탐지 레코드의 CWE 분포와 게이트 판정을 측정한다. 그룹 C는 수소추진선박용 Unity 3D·센서 웹 저장소 1개로 구성하고, 이를 수소추진선박 디지털트윈 적용 사례로 사용한다.

웹 기반 디지털트윈 후보군은 공개 소스 저장소이면서 웹 인터페이스 또는 API를 제공하고, 자산·공간의 디지털 표현이나 상태·센서·분석 데이터 연계 기능을 포함하는 프로젝트를 기준으로 구성하였다. 완성형 애플리케이션뿐 아니라 디지털트윈 웹 기능을 제공하는 플랫폼과 라이브러리도 포함하였다. 전체 후보군은 검증용 웹 애플리케이션 8개와 디지털트윈 15개를 합한 23개이다.

정량 분석 대상은 `pipeline_result.json`, `security_verdict.json`, `security_summary.json`, `security_findings.json`, `semgrep_report.json` 및 `gitleaks_report.json`과 실제 분석 커밋을 함께 확인할 수 있는 대표 실행으로 한정하였다. 이 원천 산출물 완전성 기준을 충족한 대상은 A1~A8, DT8~DT14 및 C1의 16개이며, 본 장의 정량 결과는 이들 대표 실행을 기준으로 산출하였다. DT1~DT7은 동일한 원천 산출물 기준을 충족하지 않아 정량 집계에서 제외하였다.

**표 2. 실험 대상 및 대표 실행 상태**

| 구분 | ID | 분석 프로젝트 | 주요 특성 | 분석 상태·대표 실행 |
|---|---|---|---|---|
| 취약 웹앱 | A1 | juice-shop/juice-shop | Node.js/TypeScript | run-20260624-009 |
| 취약 웹앱 | A2 | OWASP/NodeGoat | Node.js | run-20260624-011 |
| 취약 웹앱 | A3 | appsecco/dvna | Node.js | run-20260624-013 |
| 취약 웹앱 | A4 | WebGoat/WebGoat | Java | run-20260624-015 |
| 취약 웹앱 | A5 | yahho2468/Vulnerable-Flask-App (we45 fork) | Python/Flask | run-20260624-001 |
| 취약 웹앱 | A6 | yahho2468/django.nV (nVisium fork) | Python/Django | run-20260624-002 |
| 취약 웹앱 | A7 | yahho2468/BenchmarkJava (OWASP fork) | Java, 정답 집합 | run-20260624-017 |
| 취약 웹앱 | A8 | yahho2468/dvpwa (anxolerd fork) | Python | run-20260624-005 |
| 공개 DT | DT1 | Azure-Samples/digital-twins-explorer | Azure DT Explorer | 정량 분석 제외 |
| 공개 DT | DT2 | Autodesk-Forge/forge-digital-twin | 제조 DT | 정량 분석 제외 |
| 공개 DT | DT3 | autodesk-platform-services/aps-digital-twin | Viewer 기반 DT | 정량 분석 제외 |
| 공개 DT | DT4 | INTO-CPS-Association/DTaaS | Digital Twin as a Service | 정량 분석 제외 |
| 공개 DT | DT5 | iTwin/itwinjs-core | TypeScript/WebGL 코어 | 정량 분석 제외 |
| 공개 DT | DT6 | iTwin/viewer-components-react | React Viewer | 정량 분석 제외 |
| 공개 DT | DT7 | Vertexvis/digital-twin-demo | 3D·시계열 센서 | 정량 분석 제외 |
| 공개 DT | DT8 | yahho2468/collaboration-demo (Vertexvis fork) | 3D 실시간 협업 | run-20260710-001 |
| 공개 DT | DT9 | yahho2468/visual-analytics-demo (Vertexvis fork) | 3D 분석 오버레이 | run-20260710-002 |
| 공개 DT | DT10 | yahho2468/openremote (openremote fork) | IoT·자산 관리 | run-20260710-003 |
| 공개 DT | DT11 | yahho2468/GeoTwin (Geo-Twin fork) | 홍수 시뮬레이션 | run-20260710-004 |
| 공개 DT | DT12 | City-Syntax/nus-digital-twin | 캠퍼스 DT | run-20260713-001 |
| 공개 DT | DT13 | yahho2468/digital-twin-water (j03rul4nd fork) | 센서 시뮬레이션 | run-20260710-006 |
| 공개 DT | DT14 | nikonikoCW/Meteor3DEditor | 3D·IoT 대시보드 | run-20260713-002 |
| 수소추진선박 DT | C1 | suhodang77/hydrogen-ship-LBTS | Unity 3D·센서 웹 | run-20260604-008 |

A5~A8과 DT8~DT11·DT13의 대표 실행은 표 2에 표시한 실험용 fork 커밋을 분석하였다. 따라서 해당 결과의 직접적인 분석 단위는 표에 기재한 fork의 고정 커밋이며, upstream 프로젝트명은 소스 계보를 식별하는 기준으로 사용한다.

### 4.2 실험 환경 및 평가 방법

실행 산출물에서 공통으로 확인된 Semgrep 버전은 1.157.0이며 OSS 엔진을 사용하였다. Semgrep은 `--config auto`, Gitleaks는 `detect` 방식으로 실행하였다. 모든 대표 실행의 `security_verdict.json`에는 `development` 환경, `selected_count` 16 및 빈 `acknowledged_cwes` 목록이 기록되어 있어 High 등급 승인 예외가 적용되지 않았다. 저장소 복제는 depth 1을 사용하므로 Gitleaks 결과는 대표 실행에서 복제된 커밋 범위를 대상으로 한다.

프로젝트별로 생성된 워크플로와 기본 워크플로가 함께 사용되었다. Semgrep 실행 옵션과 16종 CWE 정책은 공통으로 적용하였다. 실행 로그에 기록된 `auto` 규칙 묶음은 A·C 그룹 1,059개와 B 그룹 1,074개로 구성되어 그룹 간 Raw 절대값에는 실행 시점 규칙 묶음의 차이가 반영된다. 이에 따라 그룹 간 결과는 탐지 건수의 우열보다 정책 범위, CWE 분포 및 게이트 판정의 기술통계로 해석한다.

대표 실행은 지정 커밋 또는 분석 시점의 브랜치 HEAD를 대상으로 하였으며, 실제 분석 커밋 SHA를 결과에 기록하였다. 동일 프로젝트에 복수 실행이 존재하는 경우 `pipeline_result.json`, `security_verdict.json`, `security_summary.json`, `security_findings.json`, `semgrep_report.json` 및 `gitleaks_report.json`이 모두 생성된 실행 한 건을 대표값으로 선정하였다. 보안 게이트가 빌드·배포를 중단한 실행과 `pass` 게이트 판정 이후 후속 단계가 진행된 실행은 별도로 구분하였다.

탐지 성능 평가는 A7의 `expectedresults-1.2.csv`를 정답 집합으로 사용하였다. 정책 16종과 Benchmark v1.2가 공통으로 포함하는 CWE-22, CWE-78, CWE-79, CWE-89, CWE-327, CWE-614를 대상으로 하였다. 동일 테스트 파일에서 동일 CWE가 여러 규칙으로 탐지된 경우 `(테스트 ID, CWE)` 단위로 중복을 제거하였다. 정답 CWE와 상이한 CWE로 탐지한 사례도 FP로 계수하여 교차 CWE 분류 성능을 평가하였다.

CWE 정책 적용 결과는 원시 심각도 기준선과 비교하였다. 기준선은 Semgrep `ERROR` 또는 Gitleaks 탐지 레코드가 한 건 이상이면 차단하고, 그 밖의 경우 통과하는 이진 규칙으로 정의하였다. 비교 항목은 저장소별 차단 여부와 함께 정책 범위, CWE 재등급, 승인 상태 및 판정 근거의 제공 여부로 구성하였다.

### 4.3 취약점 탐지 유형 및 측정 결과

표 3은 원천 산출물 완전성 기준을 충족한 16개 대표 실행의 측정 결과이다. `Raw`는 원시 탐지 결과에서 엔진 생성 파일 `.localci/workflow.yml`의 레코드를 분리한 저장소 파일 기준 레코드 수이다. `In`은 16종 정책에 매핑된 레코드 수이고, `Out`은 정책 범위 외 레코드 수이다. C/H/M/L은 정책 등급별 탐지 레코드 수를 나타낸다. 표 3의 수치는 도구가 생성한 탐지 레코드를 의미하며, 확정 취약점 판정과 구분한다. 실행 작업 공간을 포함한 집계는 4.4절의 민감도 분석에 제시한다.

**표 3. 저장소별 보안성 측정 결과**

| ID | Raw | In | Out | C/H/M/L | 점수 | 게이트 판정 |
|---|---:|---:|---:|---:|---:|---|
| A1 | 107 | 86 | 21 | 81/0/5/0 | 0.0 | block |
| A2 | 32 | 13 | 19 | 7/6/0/0 | 0.0 | block |
| A3 | 23 | 11 | 12 | 2/2/7/0 | 40.0 | block |
| A4 | 198 | 58 | 140 | 42/6/2/8 | 0.0 | block |
| A5 | 19 | 6 | 13 | 2/1/3/0 | 40.0 | block |
| A6 | 48 | 8 | 40 | 3/0/1/4 | 38.2 | block |
| A7 | 3,245 | 1,633 | 1,612 | 852/1/744/36 | 0.0 | block |
| A8 | 9 | 3 | 6 | 2/0/1/0 | 40.0 | block |
| DT8 | 5 | 1 | 4 | 1/0/0/0 | 40.0 | block |
| DT9 | 5 | 1 | 4 | 1/0/0/0 | 40.0 | block |
| DT10 | 69 | 24 | 45 | 16/1/7/0 | 0.0 | block |
| DT11 | 23 | 8 | 15 | 6/0/2/0 | 0.0 | block |
| DT12 | 0 | 0 | 0 | 0/0/0/0 | 100.0 | pass |
| DT13 | 15 | 7 | 8 | 0/7/0/0 | 81.0 | block_pending_approval |
| DT14 | 46 | 24 | 22 | 4/0/20/0 | 16.0 | block |
| C1 | 7 | 2 | 5 | 0/1/1/0 | 94.0 | block_pending_approval |

표 3에서 그룹 A의 8개 저장소는 모두 `block`으로 판정되었다. 디지털트윈 집단에서는 DT8, DT9, DT10, DT11 및 DT14가 `block`, DT13과 C1이 `block_pending_approval`, DT12가 `pass`로 판정되었다. C1은 보조 점수 94점과 High 등급 탐지 레코드를 함께 기록하였으며, 게이트는 High 등급 계층 규칙에 따라 승인 대기 판정을 수행하였다. 이 결과는 보조 점수와 게이트 판정이 서로 다른 역할을 수행하는 구조를 보여준다.

**표 4. 그룹별 집계**

| 그룹 | 분석 저장소 | Raw | In | Out | 정책 범위 외 비율 | 저장소별 비율 중앙값 | 게이트 판정 분포 |
|---|---:|---:|---:|---:|---:|---:|---|
| A: 취약 웹앱 | 8 | 3,681 | 1,818 | 1,863 | 50.6% | 63.0% | block 8 |
| B: 공개 DT | 7 | 163 | 65 | 98 | 60.1% | 65.2% | block 5, block_pending_approval 1, pass 1 |
| C: 수소추진선박 DT | 1 | 7 | 2 | 5 | 71.4% | 71.4% | block_pending_approval 1 |
| 전체 | 16 | 3,851 | 1,885 | 1,966 | 51.1% | 65.2% | block 13, block_pending_approval 2, pass 1 |

표 4는 그룹별 정책 범위와 게이트 판정 결과를 보여준다. 엔진 생성 파일을 제외한 저장소 파일에서 관찰된 원시 탐지 레코드 3,851건 중 1,885건이 정책 범위에 포함되었고, 1,966건(51.1%)은 정책 범위 외 결과로 분리되었다. 본 연구에서 정의한 16종 정책에 따른 게이트 판정 결과는 `block` 13개, `block_pending_approval` 2개 및 `pass` 1개이다. `pass`는 해당 분석 커밋, 보안 도구 규칙 및 정책 범위에서 차단 대상 탐지 레코드가 0건임을 의미한다.

저장소별 비율 중앙값은 Raw가 0건인 DT12를 제외하고 계산하였다. DT12는 원시 탐지 레코드 0건과 `pass` 게이트 판정을 별도로 유지하였다.

A7은 전체 원시 탐지 레코드의 84.3%를 차지하였다. 본 논문은 대규모 저장소의 영향을 함께 제시하기 위해 전체 비율과 저장소별 비율 중앙값을 병기하였다. 공개 디지털트윈 7개와 수소추진선박 디지털트윈 저장소 1개에서 수집된 원시 탐지 레코드는 170건이며, 이 중 67건이 정책 범위에 포함되고 103건이 정책 범위 외 결과로 분류되었다. 디지털트윈 집단의 정책 범위 외 비율은 60.6%이다.

### 4.4 분석

#### 입력 탐지 성능

제안 기법에 입력되는 자동 탐지 결과의 성능을 평가하기 위해 A7 fork에 포함된 `expectedresults-1.2.csv`와 16종 정책이 공통으로 포함하는 6개 CWE를 비교하였다. 정답 CWE와 상이한 CWE로 분류된 사례도 FP에 포함하였다. 표 5는 CWE별 TP, FP, FN, 정밀도, 재현율 및 F1을 나타낸다.

**표 5. A7 Benchmark v1.2 정답 집합 기반 탐지 성능**

| CWE | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| CWE-22 | 120 | 106 | 13 | 0.531 | 0.902 | 0.669 |
| CWE-78 | 117 | 109 | 9 | 0.518 | 0.929 | 0.665 |
| CWE-79 | 202 | 108 | 44 | 0.652 | 0.821 | 0.727 |
| CWE-89 | 253 | 170 | 19 | 0.598 | 0.930 | 0.728 |
| CWE-327 | 0 | 0 | 130 | 0.000 | 0.000 | 0.000 |
| CWE-614 | 36 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| Micro(동일 CWE) | 728 | 493 | 215 | 0.596 | 0.772 | 0.673 |
| Micro(교차 CWE 오분류 146건을 FP 포함) | 728 | 639 | 215 | 0.533 | 0.772 | 0.630 |

대표 결과는 교차 CWE 분류 146건을 FP에 포함한 마지막 행이다. 이 기준에서 TP는 728건, FP는 639건, FN은 215건으로 집계되었다. 정책 입력 탐지의 정밀도는 0.533, 재현율은 0.772, F1은 0.630이다. 이 값은 A7의 고정 스냅샷과 정책 중첩 6개 CWE에 대한 Semgrep 기반 입력 탐지 성능을 나타낸다.

CWE-614는 정밀도와 재현율이 모두 1.000으로 나타났고, CWE-327은 해당 실행의 규칙 집합에서 TP가 0건으로 나타났다. 이 결과는 CWE별 규칙 범위가 탐지 성능에 미치는 영향을 보여준다. 그룹 A의 나머지 7개 프로젝트는 탐지 절차의 작동과 적용 결과를 확인하는 데 사용하였다. 기계 판독 정답표를 이용한 정량 탐지 성능은 A7을 기준으로 산출하였다.

#### 웹 기반 디지털트윈의 CWE 분포

원천 산출물 완전성 기준을 충족한 디지털트윈 저장소 8개에서는 CWE-22(Path Traversal) 25건, CWE-798(Hardcoded Secret) 24건, CWE-319(Cleartext Transmission) 9건, CWE-79(XSS) 5건 및 CWE-78(Command Injection) 4건이 관찰되었다. 저장소 기준으로는 CWE-798이 5개 저장소, CWE-319와 CWE-79가 각각 3개 저장소, CWE-22가 2개 저장소, CWE-78이 1개 저장소에서 보고되었다. 이 분포는 보안 도구가 보고한 정책 항목별 탐지 레코드 빈도이며, 개별 레코드의 실제 취약점 여부와 구분하여 해석한다.

#### CWE 정책 적용 결과

CWE 정책 적용에 따른 게이트 판정 범위와 등급 표현의 변화를 분석하였다. 엔진 생성 파일을 제외한 16개 저장소 파일에서 수집된 원시 탐지 레코드는 3,851건이고, 정책 범위에 포함된 레코드는 1,885건이다. 정책 범위 외 1,966건은 원시 보고서와 정규화 결과에 유지하였다. 따라서 원시 탐지 레코드의 51.1%가 정책 범위 외 결과로 분리되었으며, 입력 탐지 성능은 표 5의 정밀도·재현율·F1로 평가하였다.

정책 등급 재분류 결과도 함께 분석하였다. 원시 Semgrep 심각도를 ERROR→High, WARNING→Medium, INFO→Low로 대응한 뒤 정책 등급과 비교하였다. 정책 범위 Semgrep 탐지 레코드 1,772건 중 1,261건인 71.2%에서 등급 표현이 변경되었다. Gitleaks 탐지 레코드 113건은 잠재 Hardcoded Secret을 나타내는 Critical 등급 CWE-798 정책 레코드로 매핑되었다. 이는 제안 기법이 보안 도구별 심각도를 공통 CWE 정책 등급으로 변환하는 과정을 보여준다.

원시 ERROR 또는 Gitleaks 탐지를 차단 조건으로 사용하는 원시 심각도 기준선과 제안 기법의 이진 게이트 판정은 모두 15개 차단과 1개 통과로 나타났다. 제안 기법은 Critical 등급 탐지 레코드가 0건이고 미승인 High 등급 탐지 레코드가 1건 이상인 저장소 2개를 승인 대기 상태로 구분하였다. 또한 게이트 판정 대상 CWE, 정책 등급 및 게이트 판정 사유를 함께 기록하였다. 따라서 본 실험에서 확인된 정책 효과는 게이트 판정 범위의 구분, CWE 기반 재등급 및 승인 상태와 근거의 제공이다.

#### 수소추진선박 디지털트윈 적용 사례

제안 기법의 실제 적용 과정을 분석하기 위해 수소추진선박용 Unity 3D·센서 웹 저장소를 디지털트윈 적용 대상으로 선정하였다. 대표 실행 `run-20260604-008`은 `hydrogen-ship-LBTS`의 커밋 `7a34c897a485f70a92d8ed7c22a339b05a4c3b97`을 분석하였다. Gitleaks 탐지 레코드는 0건이고 Semgrep 탐지 레코드는 7건이다. 이 중 High 등급 CWE-319(Cleartext Transmission) 1건과 Medium 등급 CWE-79(XSS) 1건이 정책 범위에 포함되었다.

보조 점수는 94점으로 산출되었다. 게이트는 점수보다 High 등급 계층 규칙을 우선 적용하여 `block_pending_approval`로 판정하였다. 이에 따라 빌드와 배포 단계는 건너뜀 상태(`skipped`)로 기록되었다. 이 결과는 높은 보조 점수와 승인 대기 판정이 서로 다른 측정 의미를 갖는다는 것을 보여준다.

CWE-319 탐지 레코드는 `frontend/public/unities/uipa/Build/BuildWeb.framework.js`의 생성된 Unity/Emscripten 런타임에서 보고되었다. 제안 기법은 이 레코드를 High 등급으로 재분류하고 빌드 이전 승인 대기 판정을 수행하였다. 본 사례는 생성된 Unity WebGL 파일의 Cleartext WebSocket 사용 가능성에 CWE-319 정책을 적용한 과정을 보여준다.

#### 실행시간

제안 기법의 실행 특성은 대표 실행의 단계별 소요 시간을 기준으로 분석하였다. 그룹 A의 전체 실행시간은 평균 123.6초, 중앙값 71.5초이다. DT12는 총 590초가 기록되었으며, 여기에는 `build` 84초와 `deploy` 단계 362초가 포함된다. DT12의 게이트 판정은 `pass`였으며, 후속 `deploy` 단계 실패로 전체 파이프라인 상태는 `failed`로 기록되었다.

수소추진선박 실행은 총 115초이며 Semgrep 단계에 101초가 소요되었다. 보안 게이트는 JSON의 초 단위 기록에서 0초로 나타났다. 이는 게이트 계산이 1초 기록 해상도 이내에 완료되었음을 의미한다. 본 결과는 저장소·워크플로별 단일 실행의 기술통계이며, 반복 실행을 전제로 하는 성능 오버헤드와 구분한다.

#### 타당성 검토

구성 타당성 측면에서 본 논문의 보안성 측정은 16종 CWE 정책 범위에서 정적으로 관찰한 코드, 비밀정보 및 배포 설정의 측정치로 한정된다. 보조 점수와 게이트 판정은 해당 정책 범위의 저장소 상태를 표현하며, 런타임 상태, 의존성 취약점 및 물리 영향도를 포함한 전체 시스템 보안성을 의미하지 않는다. 또한 16종 CWE의 선택, 등급 및 감점값은 웹 기반 디지털트윈의 공격 표면을 기준으로 구성한 연구자 정의 운영 정책이다.

내적 타당성 측면에서 원시 보고서는 Semgrep 1.157.0과 OSS 엔진 사용을 기록한다. 실행 로그의 `auto` 규칙 묶음은 A·C 그룹 1,059개와 B 그룹 1,074개로 확인되어 그룹 간 Raw 절대값에는 실행 시점의 규칙 차이가 반영된다. 16개 Semgrep 보고서의 `errors` 배열에는 PartialParsing 100건, Timeout 26건, Syntax error 20건, Other syntax error 17건 및 Internal matching error 4건 등 총 167건이 기록되었다. 따라서 저장소별 결과는 적용된 규칙 묶음과 분석 오류 정보를 함께 고려하여 해석한다. Gitleaks 탐지 레코드는 잠재 Hardcoded Secret 정책 레코드로 일괄 매핑하므로, 실제 자격증명의 유효성과는 구분한다.

DT8~DT14의 작업 공간 포함 Semgrep 결과에는 엔진이 생성한 `.localci/workflow.yml`의 정책 범위 외 탐지 레코드가 저장소별 6건씩 총 42건 존재하였다. 표 3과 표 4는 이 레코드를 제외한 저장소 파일 기준 집계이며, 작업 공간 포함 집계는 Raw 3,893건, In 1,885건 및 Out 2,008건으로 나타났다. 42건은 모두 정책 범위 외 결과이므로 점수와 게이트 판정은 동일하게 유지되었다.

수소추진선박 디지털트윈 적용 사례의 CWE-319 탐지 레코드는 생성 코드에서 보고되었으며, 원시 규칙의 confidence와 likelihood는 모두 LOW이다. 또한 해당 실행에는 Timeout 3건과 PartialParsing 1건이 기록되었다. 따라서 이 결과는 실제 선박 텔레메트리 취약점의 확정이 아니라, 생성된 Unity WebGL 파일의 Cleartext WebSocket 사용 가능성에 대한 정책 적용 및 승인 대기 판정 사례로 해석한다.

외적 타당성 측면에서 정량 분석 대상은 원천 산출물 완전성 기준을 충족한 디지털트윈 8개로 구성된다. DT1~DT7은 정량 집계에서 제외되었으며, 일부 분석 대상은 upstream이 아닌 실험용 fork이다. 이에 따라 결과의 직접적인 적용 범위는 표 2에 기재된 고정 커밋과 본 연구의 도구·규칙·정책 조건으로 한정된다.

결론 타당성 측면에서 A7은 엔진 생성 파일을 제외한 전체 원시 탐지 레코드의 84.3%를 차지한다. 본 논문은 합계와 저장소별 비율 중앙값을 함께 제시하여 대규모 저장소의 영향을 구분하였다. 다만 코드 규모에 따른 정규화가 적용되지 않았으므로 탐지 레코드 절대 건수를 저장소 간 보안 수준의 우열로 해석하지 않는다. 실행시간도 저장소별 단일 실행의 기술통계로 제시하며 성능 오버헤드 지표로 사용하지 않는다.

## 5. 결론 및 향후 연구

본 논문은 웹 기반 디지털트윈 SW에 대한 보안성 측정의 부재를 문제로 정의하였다. 이 문제는 웹 클라이언트, 서버 API, 3차원 시각화 코드, 자산·센서 데이터 채널, 자격증명 및 배포 설정을 반영하여 디지털트윈의 보안성을 평가할 특화 측정 기준·지표·체계가 충분히 정립되지 않은 상태를 의미한다. 이를 해결하기 위해 웹 기반 디지털트윈의 공격 표면을 네 영역으로 구조화하고, Gitleaks와 Semgrep의 탐지 레코드를 16종 CWE 정책 카탈로그에 매핑하여 정책 범위, 등급별 건수, 보조 점수 및 게이트 판정을 산출하는 기법을 제안하였다. 또한 CI/CD 파이프라인을 통해 제안 절차를 프로젝트별 워크플로에 반복 적용하고 실행 근거를 JSON 산출물로 보존하였다.

원천 산출물 완전성 기준을 충족한 16개 저장소에서 엔진 생성 파일을 제외한 저장소 파일을 분석한 결과, 원시 탐지 레코드 3,851건 중 1,885건이 정책 범위에 포함되었다. 디지털트윈 8개에서는 원시 탐지 레코드 170건 중 67건이 정책 범위에 포함되었으며, 5개는 `block`, 2개는 `block_pending_approval`, 1개는 `pass`로 판정되었다. A7에 포함된 Benchmark 정답표의 정책 중첩 6개 CWE에 대한 입력 탐지는 정밀도 0.533, 재현율 0.772 및 F1 0.630을 보였다. 수소추진선박 디지털트윈 적용 사례에서는 High 등급 CWE-319(Cleartext Transmission)과 Medium 등급 CWE-79(XSS) 탐지 레코드가 정책 범위에 포함되었으며, 보조 점수 94점과 함께 승인 대기 판정이 수행되었다.

실험 결과, 제안 기법은 서로 다른 보안 도구의 탐지 레코드를 디지털트윈 공격 표면을 반영한 CWE 정책 단위로 변환하였다. 또한 원시 결과와 게이트 판정 대상을 구분하고, Critical 등급 탐지 레코드 0건과 미승인 High 등급 탐지 레코드 1건 이상을 기록한 저장소를 승인 대기 상태로 판정하였다. 이를 통해 측정 기준, 저장소 단위 지표 및 빌드·배포 통제가 하나의 측정 체계에서 연결됨을 확인하였다.

향후 연구에서는 DT1~DT7을 동일한 원천 산출물 기준으로 재실행하여 후보군 23개 전체로 분석 범위를 확장한다. Semgrep 규칙 revision, Gitleaks 버전, 엔진 커밋, 정책 hash, 워크플로 및 실행 환경 스냅샷을 함께 보존하고, 코드 규모 또는 분석 파일 수를 이용한 정규화 지표를 추가한다. 생성 코드 분석 범위의 민감도 평가와 수작업 판독을 통해 탐지 레코드를 확정 취약점, 잠재 위험 및 비운용 탐지로 세분화한다. 또한 SCA, DAST, 컨테이너 이미지 검사와 런타임 네트워크 추적을 결합하고, 전문가 평가와 민감도 분석을 통해 16종 정책의 등급 및 감점 체계를 검증한다.

---

## 참고문헌

[1] J. Voas et al., “Security and Trust Considerations for Digital Twin Technology,” NIST IR 8356, 2025. https://doi.org/10.6028/NIST.IR.8356

[2] M. Hearn and S. Rix, “Cybersecurity Considerations for Digital Twin Implementations,” *IIC Journal of Innovation*, 2019. https://www.iiconsortium.org/news-pdf/joi-articles/2019-November-JoI-Cybersecurity-Considerations-for-Digital-Twin-Implementations.pdf

[3] D. Holmes et al., “Digital Twins and Cyber Security—Solution or Challenge?,” in *Proc. SEEDA-CECNSM*, 2021. https://doi.org/10.1109/SEEDA-CECNSM53056.2021.9566277

[4] M. Eckhart and A. Ekelhart, “Digital Twins for Cyber-Physical Systems Security: State of the Art and Outlook,” 2019. https://doi.org/10.1007/978-3-030-25312-7_14

[5] C. Gehrmann and M. Gunnarsson, “A Digital Twin Based Industrial Automation and Control System Security Architecture,” *IEEE Transactions on Industrial Informatics*, 2020. https://doi.org/10.1109/TII.2019.2938885

[6] N. Kuštelega et al., “Privacy and Security Challenges of the Digital Twin: Systematic Literature Review,” *Journal of Universal Computer Science*, 2024. https://doi.org/10.3897/jucs.114607

[7] M. Souppaya, K. Scarfone, and D. Dodson, “Secure Software Development Framework (SSDF) Version 1.1,” NIST SP 800-218, 2022. https://doi.org/10.6028/NIST.SP.800-218

[8] R. Chandramouli et al., “Strategies for the Integration of Software Supply Chain Security in DevSecOps CI/CD Pipelines,” NIST SP 800-204D, 2024. https://doi.org/10.6028/NIST.SP.800-204D

[9] R. N. Rajapakse et al., “Challenges and Solutions When Adopting DevSecOps: A Systematic Review,” *Information and Software Technology*, vol. 141, 2022. https://doi.org/10.1016/j.infsof.2021.106700

[10] OWASP Foundation, “OWASP Benchmark.” https://owasp.org/www-project-benchmark/

[11] MITRE, “Common Weakness Enumeration.” https://cwe.mitre.org/

[12] K. Schroeder, H. Trinh, and V. Pillitteri, “Measurement Guide for Information Security: Volume 1—Identifying and Selecting Measures,” NIST SP 800-55 Vol. 1, 2024. https://doi.org/10.6028/NIST.SP.800-55v1

[13] Semgrep, “Semgrep Code Overview” and “Rule Structure Syntax.” https://semgrep.dev/docs/semgrep-code/overview

[14] Gitleaks, “Gitleaks: Find Secrets with Gitleaks.” https://github.com/gitleaks/gitleaks

[15] Z. Li et al., “Comparison and Evaluation on Static Application Security Testing Tools for Java,” in *Proc. ESEC/FSE*, 2023. https://doi.org/10.1145/3611643.3616262
