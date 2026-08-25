import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import requests
import streamlit as st
from openai import OpenAI
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://opendart.fss.or.kr/api"

class DartConnectionError(RuntimeError):
    pass

def secret(name, default=""):
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default

def validate_dart_key(key):
    key = (key or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", key):
        raise ValueError("DART_API_KEY 형식 오류: Streamlit Secrets에 40자리 인증키 값만 넣어주세요.")
    return key

def make_session():
    s = requests.Session()
    retry = Retry(
        total=3, connect=3, read=2, backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]), raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "DART-Value-Agent/1.2"})
    return s

@st.cache_data(ttl=86400, show_spinner=False)
def corp_codes_cached(key):
    s = make_session()
    try:
        r = s.get(f"{BASE}/corpCode.xml", params={"crtfc_key": key}, timeout=(15, 90))
        r.raise_for_status()
    except requests.RequestException as e:
        raise DartConnectionError(
            "OpenDART 서버 연결에 실패했습니다. API 키 재발급 문제가 아니라 네트워크/서버 연결 문제일 수 있습니다."
        ) from e
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml = z.read(z.namelist()[0])
        root = ET.fromstring(xml)
        return pd.DataFrame([{x.tag: x.text for x in c} for c in root.findall("list")])
    except Exception as e:
        raise ValueError("OpenDART 기업코드 파일을 해석하지 못했습니다.") from e

class DartClient:
    def __init__(self, key):
        self.key = validate_dart_key(key)
        self.s = make_session()

    def _get(self, path, params):
        try:
            r = self.s.get(
                f"{BASE}/{path}",
                params={"crtfc_key": self.key, **params},
                timeout=(15, 60),
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            raise DartConnectionError("OpenDART 서버 연결에 실패했습니다. 잠시 후 다시 시도해주세요.") from e
        except ValueError as e:
            raise ValueError("OpenDART 응답을 읽지 못했습니다.") from e
        if data.get("status") and data["status"] != "000":
            raise ValueError(data.get("message", f"OpenDART 오류 코드 {data['status']}"))
        return data

    def resolve_company(self, q):
        df = corp_codes_cached(self.key)
        q = q.strip().upper()
        exact = df[
            (df["corp_name"].fillna("").str.upper() == q) |
            (df["stock_code"].fillna("").str.upper() == q)
        ]
        if exact.empty:
            exact = df[df["corp_name"].fillna("").str.contains(q, case=False, regex=False)].head(5)
        if exact.empty:
            raise ValueError(f"기업을 찾지 못했습니다: {q}")
        return self._get("company.json", {"corp_code": exact.iloc[0]["corp_code"]})

    def annual_financials(self, corp_code, years=3):
        current = pd.Timestamp.today().year
        out = []
        for y in range(current - 1, current - years - 2, -1):
            try:
                data = self._get("fnlttSinglAcntAll.json", {
                    "corp_code": corp_code, "bsns_year": y,
                    "reprt_code": "11011", "fs_div": "CFS"
                })
                if data.get("list"):
                    out.extend(data["list"])
                if len(set(x.get("bsns_year") for x in out)) >= years:
                    break
            except ValueError:
                continue
        if not out:
            raise ValueError("최근 사업보고서 연결재무제표를 가져오지 못했습니다.")
        return pd.DataFrame(out)

ALIASES = {
    "revenue": ["매출액", "수익(매출액)", "영업수익"],
    "op_income": ["영업이익", "영업이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)"],
    "assets": ["자산총계"], "liabilities": ["부채총계"], "equity": ["자본총계"],
    "cash": ["현금및현금성자산", "현금및현금성자산(금융기관예치금 포함)"],
    "receivables": ["매출채권", "매출채권및기타채권"],
    "inventory": ["재고자산"],
    "cfo": ["영업활동으로인한현금흐름", "영업활동현금흐름"],
    "capex": ["유형자산의 취득", "유형자산 취득"],
    "interest": ["이자비용"],
}

def num(x):
    try:
        return float(str(x).replace(",", "").replace(" ", "").replace("－", "-"))
    except Exception:
        return np.nan

def find_val(df, names, year):
    d = df[df["bsns_year"].astype(str) == str(year)]
    for n in names:
        z = d[d["account_nm"].astype(str).str.strip() == n]
        if not z.empty:
            return num(z.iloc[0]["thstrm_amount"])
    for n in names:
        z = d[d["account_nm"].astype(str).str.contains(n, regex=False, na=False)]
        if not z.empty:
            return num(z.iloc[0]["thstrm_amount"])
    return np.nan

def build_metrics(corp, annual, rf, erp, terminal_growth):
    years = sorted(pd.to_numeric(annual["bsns_year"], errors="coerce").dropna().astype(int).unique())[-3:]
    rows = []
    for y in years:
        row = {"year": y}
        for k, names in ALIASES.items():
            row[k] = find_val(annual, names, y)
        rows.append(row)
    t = pd.DataFrame(rows).sort_values("year")
    latest = t.iloc[-1]

    price = shares = np.nan
    beta = 1.0
    try:
        import yfinance as yf
        code = str(corp.get("stock_code", "") or "").zfill(6)
        if code != "000000":
            suffix = ".KS" if corp.get("corp_cls") == "Y" else ".KQ"
            ticker = yf.Ticker(code + suffix)
            hist = ticker.history(period="5d", auto_adjust=False)
            if not hist.empty:
                price = float(hist["Close"].dropna().iloc[-1])
            info = ticker.info or {}
            beta = float(info.get("beta") or 1.0)
            shares = float(info.get("sharesOutstanding") or np.nan)
    except Exception:
        pass

    equity = latest["equity"]
    debt = max(latest["liabilities"] - latest["cash"], 0) if np.isfinite(latest["liabilities"]) and np.isfinite(latest["cash"]) else np.nan
    market_cap = price * shares if np.isfinite(price) and np.isfinite(shares) else np.nan
    E = market_cap if np.isfinite(market_cap) else equity
    D = debt if np.isfinite(debt) else 0
    kd = latest["interest"] / debt if np.isfinite(latest["interest"]) and debt > 0 else rf + 0.02
    ke = rf + beta * erp
    wacc = (E * ke + D * kd * 0.75) / (E + D) if np.isfinite(E) and (E + D) > 0 else np.nan
    nopat = latest["op_income"] * 0.75 if np.isfinite(latest["op_income"]) else np.nan
    invested = equity + debt - latest["cash"] if np.isfinite(equity) and np.isfinite(debt) and np.isfinite(latest["cash"]) else np.nan
    roic = nopat / invested if np.isfinite(nopat) and invested > 0 else np.nan
    spread = roic - wacc if np.isfinite(roic) and np.isfinite(wacc) else np.nan
    pbr = market_cap / equity if np.isfinite(market_cap) and equity > 0 else np.nan
    ev = market_cap + debt - latest["cash"] if np.isfinite(market_cap) and np.isfinite(debt) and np.isfinite(latest["cash"]) else np.nan
    ev_ebit = ev / latest["op_income"] if np.isfinite(ev) and latest["op_income"] > 0 else np.nan
    fcf = latest["cfo"] - abs(latest["capex"]) if np.isfinite(latest["cfo"]) and np.isfinite(latest["capex"]) else np.nan
    fcf_yield = fcf / market_cap if np.isfinite(fcf) and np.isfinite(market_cap) and market_cap > 0 else np.nan

    signals, anomalies = [], []
    if np.isfinite(spread):
        signals.append({"severity": "low" if spread > .05 else "medium" if spread > 0 else "high",
                        "text": f"ROIC-WACC 스프레드 {spread*100:.1f}%p"})
    if len(t) >= 2:
        prev = t.iloc[-2]
        def growth(a, b):
            return a / b - 1 if np.isfinite(a) and np.isfinite(b) and b != 0 else np.nan
        rev_g = growth(latest["revenue"], prev["revenue"])
        op_g = growth(latest["op_income"], prev["op_income"])
        if np.isfinite(rev_g) and np.isfinite(op_g) and rev_g > .1 and op_g < 0:
            signals.append({"severity": "high", "text": "매출 증가에도 영업이익이 감소했습니다."})
        rg, sg = growth(latest["receivables"], prev["receivables"]), rev_g
        if np.isfinite(rg) and np.isfinite(sg) and rg - sg > .15:
            anomalies.append({"severity": "medium", "text": "매출채권 증가율이 매출 증가율을 크게 상회합니다."})
        ig = growth(latest["inventory"], prev["inventory"])
        if np.isfinite(ig) and np.isfinite(sg) and ig - sg > .20:
            anomalies.append({"severity": "medium", "text": "재고 증가율이 매출 증가율을 크게 상회합니다."})
    if np.isfinite(latest["cfo"]) and np.isfinite(latest["net_income"]) and latest["net_income"] > 0 and latest["cfo"] < latest["net_income"] * .7:
        anomalies.append({"severity": "medium", "text": "순이익 대비 영업현금흐름이 낮습니다."})

    fair_roic = (equity * (roic / wacc)) / shares if all(np.isfinite(x) for x in [equity, roic, wacc, shares]) and wacc > 0 and shares > 0 else np.nan
    fair_dcf = np.nan
    if all(np.isfinite(x) for x in [fcf, wacc, debt, latest["cash"], shares]) and wacc > terminal_growth and shares > 0:
        fair_dcf = (fcf * (1 + terminal_growth) / (wacc - terminal_growth) - debt + latest["cash"]) / shares

    trend = t[["year","revenue","op_income","net_income","assets","equity","cfo","receivables","inventory"]].copy()
    trend.columns = ["연도","매출","영업이익","순이익","자산","자본","영업현금흐름","매출채권","재고"]
    return {
        "price": price, "roic": roic, "wacc": wacc, "roic_spread": spread,
        "pbr": pbr, "ev_ebit": ev_ebit, "fcf_yield": fcf_yield,
        "valuation": {"fair_price_roic": fair_roic, "fair_price_dcf": fair_dcf},
        "trend_table": trend, "signals": signals, "anomalies": anomalies,
    }

def score_company(m):
    pts, checks = 50, []
    if np.isfinite(m["roic"]):
        if m["roic"] >= .15:
            pts += 15; checks.append(("positive", "ROIC 15% 이상"))
        elif m["roic"] < .08:
            pts -= 10; checks.append(("negative", "ROIC 8% 미만"))
    if np.isfinite(m["roic_spread"]):
        if m["roic_spread"] > .05:
            pts += 15; checks.append(("positive", "ROIC가 WACC를 5%p 이상 상회"))
        elif m["roic_spread"] < 0:
            pts -= 15; checks.append(("negative", "ROIC가 WACC보다 낮음"))
    if np.isfinite(m["pbr"]) and m["pbr"] < 1:
        pts += 5; checks.append(("positive", "PBR 1배 미만"))
    pts -= min(15, len(m["anomalies"]) * 5)
    pts = max(0, min(100, pts))
    return {"total": pts, "label": "매수 후보" if pts >= 70 else "관찰" if pts >= 45 else "주의", "checks": checks}

def ai_analysis(api_key, model, corp, metrics, score):
    def clean(x):
        if isinstance(x, pd.DataFrame): return x.to_dict(orient="records")
        if isinstance(x, (np.floating, float)): return None if not np.isfinite(x) else float(x)
        if isinstance(x, (np.integer,)): return int(x)
        if isinstance(x, dict): return {k: clean(v) for k, v in x.items()}
        if isinstance(x, list): return [clean(v) for v in x]
        return x
    payload = clean({"company": corp, "metrics": metrics, "score": score})
    prompt = """너는 한국 상장기업 가치평가 리서치 AI다. 아래 계산 결과를 과장 없이 해석하라.
1) 한 줄 결론 2) 가치평가 3) 숨은 신호 4) 회계 이상징후
5) 숫자로 측정 가능한 매수 조건 3개 6) 매도/회피 조건 3개
7) 추가 확인사항 5개 8) 최종 판단(공격적 매수/분할매수/관찰/회피).
이상징후를 분식회계로 단정하지 말고 마지막에 투자 참고용임을 명시하라.

DATA:
""" + json.dumps(payload, ensure_ascii=False, default=str)
    return OpenAI(api_key=api_key).responses.create(model=model, input=prompt).output_text

def fmt_pct(v): return "-" if v is None or not np.isfinite(v) else f"{v*100:.1f}%"
def fmt_x(v): return "-" if v is None or not np.isfinite(v) else f"{v:.2f}x"
def money(v): return "-" if v is None or not np.isfinite(v) else f"{v:,.0f}원"

st.set_page_config(page_title="DART Value Agent", page_icon="📊", layout="wide")
st.title("📊 DART Value Agent — V1.2")
st.caption("단일 app.py 버전: 모듈 간 ImportError가 나지 않도록 DART·계산·AI 코드를 한 파일에 통합했습니다.")

dart_key = secret("DART_API_KEY")
openai_key = secret("OPENAI_API_KEY")
model = secret("OPENAI_MODEL", "gpt-5.6")

with st.sidebar:
    st.header("⚙️ 분석 설정")
    st.success("DART API Key 연결됨") if dart_key else st.error("DART_API_KEY 미설정")
    st.success("OpenAI API Key 연결됨") if openai_key else st.warning("OPENAI_API_KEY 미설정")
    rf = st.number_input("무위험수익률 (%)", value=3.0, step=0.1) / 100
    erp = st.number_input("주식위험프리미엄 (%)", value=5.0, step=0.1) / 100
    tg = st.number_input("영구성장률 (%)", value=2.0, step=0.1) / 100

company = st.text_input("기업명 또는 종목코드", placeholder="예: 삼성전자 / 005930")
if st.button("🔎 분석 시작", type="primary"):
    if not dart_key:
        st.error("Streamlit Settings → Secrets에 DART_API_KEY를 등록해주세요."); st.stop()
    if not company.strip():
        st.error("기업명을 입력해주세요."); st.stop()
    try:
        client = DartClient(dart_key)
        with st.spinner("DART 공시와 재무 데이터를 불러오는 중..."):
            corp = client.resolve_company(company)
            annual = client.annual_financials(corp["corp_code"], 3)
        metrics = build_metrics(corp, annual, rf, erp, tg)
        score = score_company(metrics)
    except (DartConnectionError, ValueError) as e:
        st.error(str(e)); st.stop()
    except Exception:
        st.error("분석 중 예상하지 못한 오류가 발생했습니다. Streamlit의 Manage app → Logs에서 상세 오류를 확인해주세요.")
        st.stop()

    st.success(f"{corp['corp_name']} ({corp.get('stock_code','-')}) 분석 완료")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("종합점수", f"{score['total']}/100")
    c2.metric("ROIC", fmt_pct(metrics["roic"]))
    c3.metric("WACC", fmt_pct(metrics["wacc"]))
    c4.metric("PBR", fmt_x(metrics["pbr"]))

    tabs = st.tabs(["종합", "가치평가", "재무추세", "이상징후", "AI Agent"])
    with tabs[0]:
        st.subheader(score["label"])
        for status, text in score["checks"]:
            st.write(("🟢 " if status=="positive" else "🔴 ") + text)
    with tabs[1]:
        a,b,c,d = st.columns(4)
        a.metric("현재주가", money(metrics["price"]))
        b.metric("ROIC 참고가", money(metrics["valuation"]["fair_price_roic"]))
        c.metric("DCF 참고가", money(metrics["valuation"]["fair_price_dcf"]))
        d.metric("FCF Yield", fmt_pct(metrics["fcf_yield"]))
        st.caption("적정가는 단순화된 참고모형이며 실제 투자판단에는 추가 검증이 필요합니다.")
    with tabs[2]:
        st.dataframe(metrics["trend_table"], use_container_width=True, hide_index=True)
    with tabs[3]:
        st.subheader("숨은 신호")
        for x in metrics["signals"]: st.write("• " + x["text"])
        st.subheader("회계 이상징후")
        if metrics["anomalies"]:
            for x in metrics["anomalies"]: st.write("• " + x["text"])
        else:
            st.write("현재 규칙에서 포착된 주요 이상징후 없음")
    with tabs[4]:
        if not openai_key:
            st.warning("OPENAI_API_KEY가 없어 AI 분석은 실행하지 않습니다.")
        else:
            try:
                with st.spinner("AI Agent 분석 중..."):
                    st.markdown(ai_analysis(openai_key, model, corp, metrics, score))
            except Exception as e:
                st.error(f"AI 분석 호출 실패: {type(e).__name__}. OpenAI 키/모델/결제 상태를 확인해주세요.")

st.divider()
st.caption("본 앱은 투자 참고용이며 매수·매도를 보장하지 않습니다.")
