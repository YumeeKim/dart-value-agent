import numpy as np
import pandas as pd

ALIASES={
 'revenue':['매출액','수익(매출액)','영업수익'],
 'op_income':['영업이익','영업이익(손실)'],
 'net_income':['당기순이익','당기순이익(손실)'],
 'assets':['자산총계'],
 'liabilities':['부채총계'],
 'equity':['자본총계'],
 'cash':['현금및현금성자산','현금및현금성자산(금융기관예치금 포함)'],
 'receivables':['매출채권','매출채권및기타채권'],
 'inventory':['재고자산'],
 'cfo':['영업활동으로인한현금흐름','영업활동현금흐름'],
 'capex':['유형자산의 취득','유형자산 취득'],
 'interest':['이자비용'],
}

def num(x):
    if x is None: return np.nan
    s=str(x).replace(',','').replace(' ','').replace('－','-')
    try:return float(s)
    except:return np.nan

def find_val(df, names, year):
    d=df[df['bsns_year'].astype(str)==str(year)]
    for n in names:
        z=d[d['account_nm'].astype(str).str.strip()==n]
        if not z.empty:
            return num(z.iloc[0]['thstrm_amount'])
    # loose fallback
    for n in names:
        z=d[d['account_nm'].astype(str).str.contains(n, regex=False, na=False)]
        if not z.empty:return num(z.iloc[0]['thstrm_amount'])
    return np.nan

def build_metrics(corp, annual, rf=0.03, erp=0.05, terminal_growth=0.02):
    years=sorted(pd.to_numeric(annual['bsns_year'], errors='coerce').dropna().astype(int).unique())[-3:]
    rows=[]
    for y in years:
        row={'year':y}
        for k,names in ALIASES.items(): row[k]=find_val(annual,names,y)
        rows.append(row)
    t=pd.DataFrame(rows).sort_values('year')
    latest=t.iloc[-1]

    # Market inputs: V1 keeps them explicit because DART does not provide live price/beta.
    price=np.nan
    try:
        import yfinance as yf
        code=str(corp.get('stock_code','')).zfill(6)
        if code and code!='000000':
            ticker=yf.Ticker(code+'.KS' if corp.get('corp_cls')=='Y' else code+'.KQ')
            hist=ticker.history(period='5d', auto_adjust=False)
            if not hist.empty: price=float(hist['Close'].dropna().iloc[-1])
            info=ticker.info
            beta=info.get('beta')
            shares=info.get('sharesOutstanding')
        else: beta=1.0; shares=np.nan
    except Exception:
        beta=1.0; shares=np.nan
    if not np.isfinite(beta): beta=1.0

    equity=latest['equity']; debt=max(latest['liabilities']-latest['cash'],0) if np.isfinite(latest['liabilities']) and np.isfinite(latest['cash']) else np.nan
    market_cap=price*shares if np.isfinite(price) and np.isfinite(shares) else np.nan
    E=market_cap if np.isfinite(market_cap) else equity
    D=debt if np.isfinite(debt) else 0
    kd=(latest['interest']/debt) if np.isfinite(latest['interest']) and debt>0 else rf+0.02
    ke=rf+beta*erp
    wacc=(E*ke + D*kd*(1-0.25))/(E+D) if (E+D)>0 else np.nan
    nopat=latest['op_income']*(1-0.25) if np.isfinite(latest['op_income']) else np.nan
    invested=equity+debt-latest['cash'] if np.isfinite(equity) and np.isfinite(debt) and np.isfinite(latest['cash']) else np.nan
    roic=nopat/invested if np.isfinite(nopat) and invested>0 else np.nan
    spread=roic-wacc if np.isfinite(roic) and np.isfinite(wacc) else np.nan
    pbr=market_cap/equity if np.isfinite(market_cap) and equity>0 else np.nan
    ev=market_cap+debt-latest['cash'] if np.isfinite(market_cap) and np.isfinite(debt) and np.isfinite(latest['cash']) else np.nan
    ev_ebit=ev/latest['op_income'] if np.isfinite(ev) and latest['op_income']>0 else np.nan
    fcf=latest['cfo']-abs(latest['capex']) if np.isfinite(latest['cfo']) and np.isfinite(latest['capex']) else np.nan
    fcf_yield=fcf/market_cap if np.isfinite(fcf) and np.isfinite(market_cap) and market_cap>0 else np.nan

    signals=[]; anomalies=[]
    if np.isfinite(spread):
        signals.append({'severity':'low' if spread>0.05 else 'medium' if spread>0 else 'high','text':f'ROIC-WACC 스프레드 {spread*100:.1f}%p: 자본비용 대비 수익성의 질을 확인해야 합니다.'})
    if len(t)>=2:
        rev_g=t['revenue'].pct_change().iloc[-1] if t['revenue'].iloc[-2]!=0 else np.nan
        op_g=t['op_income'].pct_change().iloc[-1] if t['op_income'].iloc[-2]!=0 else np.nan
        if np.isfinite(rev_g) and np.isfinite(op_g) and rev_g>0.1 and op_g<0:
            signals.append({'severity':'high','text':'매출은 증가하지만 영업이익이 감소하는 디커플링이 나타났습니다.'})
        if np.isfinite(rev_g) and rev_g<0 and np.isfinite(fcf_yield) and fcf_yield>0.05:
            signals.append({'severity':'medium','text':'매출 감소에도 현금창출력이 상대적으로 강합니다. 비용구조 개선/운전자본 효과를 확인하세요.'})
        if np.isfinite(latest['receivables']) and np.isfinite(latest['revenue']):
            prev=t.iloc[-2]
            if np.isfinite(prev['receivables']) and np.isfinite(prev['revenue']):
                rg=latest['receivables']/prev['receivables']-1 if prev['receivables'] else np.nan
                sg=latest['revenue']/prev['revenue']-1 if prev['revenue'] else np.nan
                if np.isfinite(rg) and np.isfinite(sg) and rg-sg>0.15:
                    anomalies.append({'severity':'medium','text':f'매출채권 증가율이 매출 증가율보다 {((rg-sg)*100):.1f}%p 높습니다. 회수조건/매출 인식 점검 권장.'})
        if np.isfinite(latest['inventory']) and np.isfinite(latest['revenue']):
            prev=t.iloc[-2]
            if np.isfinite(prev['inventory']) and np.isfinite(prev['revenue']):
                ig=latest['inventory']/prev['inventory']-1 if prev['inventory'] else np.nan
                sg=latest['revenue']/prev['revenue']-1 if prev['revenue'] else np.nan
                if np.isfinite(ig) and np.isfinite(sg) and ig-sg>0.20:
                    anomalies.append({'severity':'medium','text':'재고 증가율이 매출 증가율을 크게 상회합니다. 재고평가/수요 둔화 점검 권장.'})
    if np.isfinite(latest['cfo']) and np.isfinite(latest['net_income']) and latest['net_income']>0 and latest['cfo']<latest['net_income']*0.7:
        anomalies.append({'severity':'medium','text':'순이익 대비 영업현금흐름이 낮습니다. 발생주의 이익과 현금흐름의 차이를 확인하세요.'})

    fair_roic=np.nan
    if np.isfinite(equity) and np.isfinite(roic) and np.isfinite(wacc) and roic>0 and np.isfinite(price) and np.isfinite(shares) and shares>0:
        fair_roic=(equity*(roic/wacc))/shares if wacc>0 else np.nan
    fair_dcf=np.nan
    if np.isfinite(fcf) and np.isfinite(wacc) and wacc>terminal_growth:
        fair_equity=fcf*(1+terminal_growth)/(wacc-terminal_growth)-debt+latest['cash']
        fair_dcf=fair_equity/shares if np.isfinite(shares) and shares>0 else np.nan

    trend=t[['year','revenue','op_income','net_income','assets','equity','cfo','receivables','inventory']].copy()
    trend.columns=['연도','매출','영업이익','순이익','자산','자본','영업현금흐름','매출채권','재고']
    raw=pd.DataFrame([{'지표':'매출','값':latest['revenue']},{'지표':'영업이익','값':latest['op_income']},{'지표':'순이익','값':latest['net_income']},{'지표':'자산','값':latest['assets']},{'지표':'자본','값':latest['equity']},{'지표':'영업현금흐름','값':latest['cfo']}])
    return {'price':price,'beta':beta,'shares':shares,'roic':roic,'wacc':wacc,'roic_spread':spread,'pbr':pbr,'ev_ebit':ev_ebit,'fcf_yield':fcf_yield,'valuation':{'fair_price_roic':fair_roic,'fair_price_dcf':fair_dcf,'note':'ROIC 기반 적정가는 단순화된 V1 참고모형이며, DCF는 최근 FCF 1개년을 기초로 한 단순 영구성장모형입니다.'},'trend_table':trend,'raw_table':raw,'signals':signals,'anomalies':anomalies}

def score_company(m):
    pts=50; checks=[]
    if np.isfinite(m['roic']):
        if m['roic']>=0.15: pts+=15; checks.append({'status':'positive','text':'ROIC 15% 이상'})
        elif m['roic']<0.08: pts-=10; checks.append({'status':'negative','text':'ROIC 8% 미만'})
        else: checks.append({'status':'watch','text':'ROIC 중간 구간'})
    if np.isfinite(m['roic_spread']):
        if m['roic_spread']>0.05: pts+=15; checks.append({'status':'positive','text':'ROIC가 WACC를 5%p 이상 상회'})
        elif m['roic_spread']<0: pts-=15; checks.append({'status':'negative','text':'ROIC가 WACC보다 낮음'})
    if np.isfinite(m['pbr']):
        if m['pbr']<1: pts+=5; checks.append({'status':'positive','text':'PBR 1배 미만'})
        elif m['pbr']>5: pts-=5; checks.append({'status':'watch','text':'PBR 5배 초과'})
    if m['anomalies']: pts-=min(15,len(m['anomalies'])*5)
    pts=max(0,min(100,pts))
    label='매수 후보' if pts>=70 else '관찰' if pts>=45 else '주의'
    return {'total':pts,'label':label,'summary':'재무수익성·자본비용·가격지표·회계 리스크를 단순 합산한 V1 스코어입니다.','checks':checks}
