import pandas as pd
import streamlit as st

from agent import analyze_with_ai
from dart_client import DartClient, DartConnectionError
from valuation import build_metrics, score_company


def fmt_pct(v):
    return "-" if v is None or pd.isna(v) else f"{v * 100:.1f}%"


def fmt_x(v):
    return "-" if v is None or pd.isna(v) else f"{v:.2f}x"


def money(v):
    return "-" if v is None or pd.isna(v) else f"{v:,.0f}원"


def secret(name, default=""):
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default


st.set_page_config(page_title="DART Value Agent", page_icon="📊", layout="wide")
st.title("📊 DART Value Agent — V1.1")
st.caption(
    "DART 공시 + 시장데이터 + 재무비율을 결합해 가치평가·숨은 신호·회계 이상징후·매수/매도 조건을 분석합니다."
)

# API keys are read ONLY from Streamlit Secrets so users never need to paste them into the app.
dart_key = secret("DART_API_KEY")
openai_key = secret("OPENAI_API_KEY")
model = secret("OPENAI_MODEL", "gpt-5.6")

with st.sidebar:
    st.header("⚙️ 분석 설정")
    st.success("DART API Key 연결됨") if dart_key else st.error("DART_API_KEY 미설정")
    st.success("OpenAI API Key 연결됨") if openai_key else st.warning("OPENAI_API_KEY 미설정")
    st.caption(f"AI Model: {model}")
    st.divider()
    st.markdown("**시장 가정**")
    rf = st.number_input("무위험수익률 (%)", value=3.0, step=0.1) / 100
    erp = st.number_input("주식위험프리미엄 (%)", value=5.0, step=0.1) / 100
    terminal_growth = st.number_input("영구성장률 (%)", value=2.0, step=0.1) / 100
    st.caption("WACC/DCF는 V1.1에서 시장 가정을 명시적으로 입력받습니다.")

company = st.text_input("기업명 또는 종목코드", placeholder="예: 삼성전자 / 005930")
run = st.button("🔎 분석 시작", type="primary")

if run:
    if not dart_key:
        st.error("Streamlit Settings → Secrets에 DART_API_KEY를 등록해주세요.")
        st.stop()
    if not company.strip():
        st.error("기업명을 입력해주세요.")
        st.stop()

    try:
        client = DartClient(dart_key)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    with st.spinner("DART 공시와 재무 데이터를 불러오는 중..."):
        try:
            corp = client.resolve_company(company.strip())
            annual = client.get_annual_financials(corp["corp_code"], years=3)
        except DartConnectionError as e:
            st.error(str(e))
            st.info("인증키를 새로 발급할 필요는 없습니다. 이 오류는 DART 서버 연결 문제입니다.")
            st.stop()
        except Exception as e:
            st.error(f"DART 데이터 조회 실패: {e}")
            st.stop()

    with st.spinner("재무지표와 가치평가를 계산하는 중..."):
        try:
            metrics = build_metrics(
                corp,
                annual,
                rf=rf,
                erp=erp,
                terminal_growth=terminal_growth,
            )
            score = score_company(metrics)
        except Exception as e:
            st.error(f"계산 실패: {e}")
            st.stop()

    st.success(f"{corp['corp_name']} ({corp.get('stock_code', '-')}) 분석 완료")
    tabs = st.tabs(
        ["📌 종합판정", "💰 가치평가", "📈 재무지표", "🚨 숨은 신호/회계 이상징후", "🤖 AI Agent"]
    )

    with tabs[0]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("종합점수", f"{score['total']}/100")
        c2.metric("ROIC", fmt_pct(metrics.get("roic")))
        c3.metric("PBR", fmt_x(metrics.get("pbr")))
        c4.metric("WACC", fmt_pct(metrics.get("wacc")))
        st.subheader("판정")
        st.markdown(f"### {score['label']}")
        st.write(score["summary"])
        st.subheader("핵심 체크")
        for x in score["checks"]:
            icon = "🟢 " if x["status"] == "positive" else "🟡 " if x["status"] == "watch" else "🔴 "
            st.write(icon + x["text"])

    with tabs[1]:
        st.subheader("가치평가")
        val = metrics.get("valuation", {})
        cols = st.columns(4)
        cols[0].metric("현재주가", money(metrics.get("price")))
        cols[1].metric("적정주가(ROIC/EV)", money(val.get("fair_price_roic")))
        cols[2].metric("DCF 참고가", money(val.get("fair_price_dcf")))
        cols[3].metric("PBR", fmt_x(metrics.get("pbr")))
        st.info(val.get("note", ""))
        st.dataframe(
            pd.DataFrame(
                [
                    {"항목": "ROIC", "값": fmt_pct(metrics.get("roic"))},
                    {"항목": "WACC", "값": fmt_pct(metrics.get("wacc"))},
                    {"항목": "ROIC-WACC Spread", "값": fmt_pct(metrics.get("roic_spread"))},
                    {"항목": "EV/EBIT", "값": fmt_x(metrics.get("ev_ebit"))},
                    {"항목": "P/B", "값": fmt_x(metrics.get("pbr"))},
                    {"항목": "FCF Yield", "값": fmt_pct(metrics.get("fcf_yield"))},
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    with tabs[2]:
        st.subheader("최근 3개년 재무 추세")
        trend = metrics.get("trend_table")
        if trend is not None and not trend.empty:
            st.dataframe(trend, use_container_width=True, hide_index=True)
        st.subheader("현재 재무 데이터")
        st.dataframe(metrics.get("raw_table", pd.DataFrame()), use_container_width=True, hide_index=True)

    with tabs[3]:
        signals = metrics.get("signals", [])
        anomalies = metrics.get("anomalies", [])
        st.subheader("산업/기업 숨은 신호")
        for s in signals:
            icon = "🟢 " if s["severity"] == "low" else "🟡 " if s["severity"] == "medium" else "🔴 "
            st.write(icon + s["text"])
        st.subheader("회계 이상징후")
        for a in anomalies:
            icon = "🔴 " if a["severity"] == "high" else "🟡 " if a["severity"] == "medium" else "ℹ️ "
            st.write(icon + a["text"])
        st.caption("주의: 이상징후는 부정행위의 증거가 아니라 추가 검토가 필요한 신호입니다.")

    with tabs[4]:
        if not openai_key:
            st.warning("AI 분석을 사용하려면 OPENAI_API_KEY를 Streamlit Secrets에 등록해주세요.")
        else:
            with st.spinner("AI Agent가 숫자와 신호를 종합하는 중..."):
                try:
                    answer = analyze_with_ai(openai_key, model, corp, metrics, score)
                    st.markdown(answer)
                except Exception as e:
                    st.error(f"AI 분석 실패: {e}")

    st.divider()
    st.caption("본 서비스는 투자판단을 위한 참고용 분석 도구이며 매수·매도를 보장하지 않습니다. 데이터 기준일과 가정을 반드시 확인하세요.")
