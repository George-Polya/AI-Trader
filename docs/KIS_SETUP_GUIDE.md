# KIS Open API 설정 가이드

AI-Trader에서 한국투자증권(KIS) Open API를 사용하여 미국 주식 모의투자를 실행하기 위한 설정 가이드입니다.

## 1. 사전 준비

### 1.1 KIS 개발자센터 가입
1. [KIS 개발자센터](https://apiportal.koreainvestment.com) 접속
2. 회원가입 (한국투자증권 계좌 필요)
3. 로그인 후 API 서비스 신청

### 1.2 모의투자 신청
1. 개발자센터 → 모의투자 → 모의투자 신청
2. 해외주식 모의투자 선택
3. 신청 완료 후 모의투자 계좌번호 확인 (8자리)

### 1.3 앱 등록 및 키 발급
1. 개발자센터 → 앱 등록
2. 모의투자용 앱 등록
3. 발급된 앱키(App Key)와 앱시크릿(App Secret) 저장

## 2. 설정 파일 생성

### 2.1 템플릿 복사
```bash
cd open-trading-api
cp kis_devlp.yaml.example kis_devlp.yaml
```

### 2.2 설정값 입력
`kis_devlp.yaml` 파일을 열어 실제 값을 입력합니다:

```yaml
# 모의투자 앱 키 (PS로 시작)
paper_app: "PSxxxxxxxxxx"
paper_sec: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# 모의투자 계좌
my_paper_stock: "50123456"  # 발급받은 모의투자 계좌번호
my_prod: "01"               # 주식: 01, 선물옵션: 03

# User-Agent
my_agent: "Mozilla/5.0"
```

## 3. 환경 변수 설정

### 3.1 브로커 모드 활성화
KIS 모드로 실행하려면 `BROKER` 환경변수를 설정합니다:

```bash
# 방법 1: 환경변수 직접 설정
export BROKER=kis

# 방법 2: .env 파일에 추가
echo "BROKER=kis" >> .env
```

### 3.2 설정 파일 경로 (선택)
기본 경로가 아닌 다른 위치의 설정 파일을 사용하려면:

```bash
export KIS_CONFIG_PATH=/path/to/kis_devlp.yaml
```

## 4. 연결 테스트

### 4.1 인증 테스트
```bash
cd tests
python -m pytest test_kis_integration.py::test_auth -v
```

### 4.2 잔고 조회 테스트
```bash
python -m pytest test_kis_integration.py::test_balance -v
```

### 4.3 시세 조회 테스트
```bash
python -m pytest test_kis_integration.py::test_quote -v
```

## 5. 에이전트 실행

KIS 모드로 에이전트를 실행합니다:

```bash
BROKER=kis python main.py configs/your_config.json
```

## 6. 주의사항

### 6.1 보안
- `kis_devlp.yaml` 파일은 절대 Git에 커밋하지 마세요
- 앱키와 시크릿은 외부에 노출되지 않도록 관리하세요
- `.gitignore`에 `kis_devlp.yaml`이 포함되어 있는지 확인하세요

### 6.2 API 제한
- API 호출 제한: 초당 20회
- 토큰 유효기간: 24시간 (자동 갱신됨)
- 모의투자 예수금: 기본 1억원

### 6.3 거래 시간
- 미국 주식: 한국시간 23:30 ~ 06:00 (서머타임 시 22:30 ~ 05:00)
- 거래 시간 외에는 주문이 접수되지 않을 수 있습니다

### 6.4 모의투자 vs 실전투자
- 모의투자와 실전투자는 TR ID가 다릅니다
- 모의투자: `VTTT*`, `VTTS*` (V로 시작)
- 실전투자: `TTT*`, `TTS*`
- 현재 코드는 모의투자 전용입니다

## 7. 문제 해결

### 7.1 인증 실패
```
KIS 설정 파일이 없습니다
```
→ `kis_devlp.yaml` 파일이 올바른 경로에 있는지 확인

### 7.2 토큰 오류
```
접근토큰 발급 잔여횟수 초과
```
→ 토큰 발급은 1분당 1회 제한, 잠시 후 재시도

### 7.3 주문 실패
```
ODNO 없음
```
→ 계좌번호, 상품코드 확인 또는 거래 시간 확인

## 8. 참고 링크

- [KIS 개발자센터](https://apiportal.koreainvestment.com)
- [KIS Open API 문서](https://apiportal.koreainvestment.com/apiservice)
- [해외주식 API 가이드](https://apiportal.koreainvestment.com/apiservice/overseas-stock)
