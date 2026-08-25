# DART Value Agent V1

DART OpenAPI + yfinance 시장데이터 + 규칙 기반 재무분석 + OpenAI AI Agent를 Streamlit으로 묶은 한국기업 가치평가 웹앱입니다.

## V1 기능
- 기업명/종목코드 입력
- DART 기업코드 자동 검색
- 최근 3개 사업연도 재무제표 조회
- ROIC / WACC / ROIC-WACC Spread / PBR / EV/EBIT / FCF Yield
- 단순 ROIC 기반 참고 적정가치 및 DCF 참고가
- 매출-이익 디커플링, 매출채권/재고 증가, 이익-현금흐름 괴리 등 숨은 신호
- 회계 이상징후 플래그
- 0~100 종합점수
- AI Agent의 종합 리서치: 매수 조건 / 매도 조건 / 추가 확인사항

## 중요한 V1 설계
DART는 기업개황·공시·재무정보를 제공하지만 실시간 주가/베타를 제공하는 API가 아니므로 시장 데이터는 yfinance를 사용합니다. WACC의 무위험수익률과 ERP는 V1에서 사용자가 입력합니다.

## Streamlit Community Cloud 배포
1. GitHub에 이 폴더 전체를 새 repository로 올립니다.
2. Streamlit Community Cloud에서 해당 repository의 `app.py`를 배포합니다.
3. App settings → Secrets에 아래 3줄을 넣습니다.

```toml
DART_API_KEY = "DART 키"
OPENAI_API_KEY = "OpenAI 키"
OPENAI_MODEL = "gpt-5.6"
```

4. 이후 사용자는 웹주소에 접속해서 기업명만 입력하면 됩니다.

## 주의
- V1의 적정가치는 단순화된 참고모형입니다.
- 회계 이상징후는 의심 신호이지 부정행위의 증거가 아닙니다.
- 투자판단 전 사업보고서 원문, 주석, 최신 공시와 시장가격을 확인해야 합니다.
