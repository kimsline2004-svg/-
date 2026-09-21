# 미국주식 재무 조회기

회사명이나 티커를 입력하면 SEC EDGAR / Financial Modeling Prep에서 재무 데이터를 받아
매출·영업이익·영업활동현금흐름(OCF)·잉여현금흐름(FCF) 추이와 전년 대비 성장률을
막대그래프로 보여주는 Streamlit 앱입니다.

## 파일

| 파일 | 설명 |
|---|---|
| `app.py` | 앱 본체 |
| `requirements.txt` | 필요한 라이브러리 목록 |
| `실행.bat` | 더블클릭 실행 (Windows) |
| `진단.bat` | 실행이 안 될 때 원인 확인 |
| `.streamlit/secrets.toml.example` | FMP API 키 설정 예시 |

## 설치

1. [python.org](https://www.python.org/downloads/)에서 파이썬을 설치합니다.
   설치 첫 화면의 **Add python.exe to PATH** 체크박스를 반드시 켜세요.
   설치 후 열려 있던 창은 모두 닫습니다.
2. 이 저장소를 **Code → Download ZIP**으로 내려받아 압축을 풉니다.
   (코드를 메모장에 붙여넣어 저장하지 마세요 — 인코딩이 깨져 실행되지 않습니다.)
3. FMP를 쓸 경우 `.streamlit/secrets.toml.example`을
   `.streamlit/secrets.toml`로 이름을 바꾸고 발급받은 키를 넣습니다.
   SEC EDGAR만 쓸 거라면 건너뛰어도 됩니다.

## 실행

`실행.bat`을 더블클릭하거나, 폴더에서 PowerShell을 열고:

```
pip install -r requirements.txt
python -m streamlit run app.py --server.port 8510
```

브라우저가 자동으로 열리지 않으면 <http://localhost:8510>으로 접속합니다.

> 앱을 쓰는 동안 검은 PowerShell 창은 닫지 말고, 창 안을 마우스로 클릭하지 마세요.
> 클릭하면 "선택 모드"로 들어가 앱이 멈춥니다. 멈췄다면 그 창을 클릭하고 **Esc**를 누르세요.

## 데이터 출처

| 항목 | SEC EDGAR | FMP |
|---|---|---|
| 비용 | 무료 · API 키 불필요 | 무료 요금제 (하루 250회) |
| 조회 기간 | 최대 20개 (10년 이상) | 최대 5개 |
| 원본 | 기업이 제출한 10-K / 10-Q | 가공·정제된 데이터 |
| 시가총액 | 없음 (FMP 키로 보완) | 제공 |
| 준비물 | 연락처 이메일 입력 (SEC 요구사항) | API 키 |

SEC 분기 현금흐름표는 3개월 → 6개월 → 9개월 누적으로만 공시되므로,
앱이 앞 기간을 차감해 각 분기 금액을 복원합니다.
4분기는 연간(10-K)에서 3분기 누적을 뺀 값입니다.

## 실행이 안 될 때

먼저 `진단.bat`을 더블클릭해 어디서 막히는지 확인하세요.

| 증상 | 원인과 해결 |
|---|---|
| `SyntaxError: (unicode error) 'utf-8' codec can't decode byte` | `app.py`를 메모장에 붙여넣어 ANSI(cp949)로 저장한 경우입니다. ZIP으로 내려받은 원본 파일을 쓰세요. |
| `streamlit` 용어가 인식되지 않습니다 | PATH에 등록되지 않은 경우입니다. `python -m streamlit run app.py`처럼 앞에 `python -m`을 붙이세요. |
| `ModuleNotFoundError: No module named 'altair'` | `pip install -r requirements.txt`를 실행하세요. |
| `SSL: CERTIFICATE_VERIFY_FAILED` / self-signed certificate | 기관 네트워크나 백신이 HTTPS를 검사하는 환경입니다. `pip install truststore` 후 재실행하세요. 그래도 안 되면 사이드바 **고급 설정**에서 검증 건너뛰기. |
| SEC 403 (요청 거부) | 사이드바에 연락처 이메일을 입력하세요. 기관 방화벽이 원인이면 종목 검색만 FMP로 자동 대체됩니다. |
| 402 — `'limit'` must be between 0 and 5 | FMP 무료 요금제 한도입니다. "표시할 기간 수"를 5 이하로 두거나 SEC 출처를 쓰세요. |
| 402 — `'period'` is not available | 분기 데이터가 유료 항목인 경우입니다. 앱이 연간으로 자동 전환합니다. |
| 브라우저에서 페이지가 안 열림 | 앱이 꺼졌거나 PowerShell이 선택 모드로 멈춘 상태입니다. `http://127.0.0.1:8510`도 시도하고, 기관 프록시가 있으면 LAN 설정에서 "로컬 주소에 프록시 사용 안 함"을 켜세요. |

성장률 축 범위는 `app.py`의 `GROWTH_MIN` · `GROWTH_MAX` 두 줄만 고치면
눈금과 안내 문구까지 따라갑니다.
