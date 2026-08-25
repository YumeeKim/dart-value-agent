import io, zipfile, xml.etree.ElementTree as ET
import requests
import pandas as pd
import streamlit as st

BASE='https://opendart.fss.or.kr/api'

class DartClient:
    def __init__(self, key):
        self.key=key
        self.s=requests.Session()

    def _get(self, path, params):
        p={'crtfc_key':self.key, **params}
        r=self.s.get(f'{BASE}/{path}', params=p, timeout=30)
        r.raise_for_status()
        return r.json()

    @st.cache_data(ttl=86400)
    def corp_codes(_self):
        r=_self.s.get(f'{BASE}/corpCode.xml', params={'crtfc_key':_self.key}, timeout=60)
        r.raise_for_status()
        z=zipfile.ZipFile(io.BytesIO(r.content))
        xml=z.read(z.namelist()[0])
        root=ET.fromstring(xml)
        rows=[]
        for c in root.findall('list'):
            rows.append({x.tag:x.text for x in c})
        return pd.DataFrame(rows)

    def resolve_company(self, q):
        df=self.corp_codes()
        q=q.strip().upper()
        exact=df[(df['corp_name'].str.upper()==q) | (df['stock_code'].fillna('').str.upper()==q)]
        if exact.empty:
            contains=df[df['corp_name'].str.contains(q, case=False, na=False)]
            if contains.empty:
                raise ValueError(f'기업을 찾지 못했습니다: {q}')
            exact=contains.head(5)
        row=exact.iloc[0]
        info=self._get('company.json', {'corp_code':row['corp_code']})
        if info.get('status')!='000': raise ValueError(info.get('message','기업개황 조회 실패'))
        return info

    def get_annual_financials(self, corp_code, years=3):
        current=pd.Timestamp.today().year
        out=[]
        for y in range(current-1, current-years-1, -1):
            try:
                data=self._get('fnlttSinglAcntAll.json', {'corp_code':corp_code,'bsns_year':y,'reprt_code':'11011','fs_div':'CFS'})
                if data.get('status')=='000':
                    out.extend(data.get('list',[]))
            except Exception:
                pass
        if not out:
            raise ValueError('최근 사업보고서 재무제표를 가져오지 못했습니다. 비상장사/결산기/공시 여부를 확인하세요.')
        return pd.DataFrame(out)
