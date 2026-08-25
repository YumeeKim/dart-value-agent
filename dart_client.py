import io
import re
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://opendart.fss.or.kr/api"


class DartConnectionError(RuntimeError):
    pass


def _validate_dart_key(key: str) -> str:
    key = (key or "").strip()
    # OpenDART keys are 40-char hexadecimal strings. This also catches the common
    # mistake of pasting the entire Secrets block into the key field.
    if not re.fullmatch(r"[0-9a-fA-F]{40}", key):
        raise ValueError(
            "DART_API_KEY 형식이 잘못되었습니다. Streamlit Secrets의 DART_API_KEY에는 "
            "40자리 인증키 값만 넣어주세요. (DART_API_KEY= 같은 문구는 넣지 않습니다.)"
        )
    return key


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": "DART-Value-Agent/1.1"})
    return s


@st.cache_data(ttl=86400, show_spinner=False)
def _corp_codes_cached(key: str) -> pd.DataFrame:
    s = _session()
    try:
        r = s.get(
            f"{BASE}/corpCode.xml",
            params={"crtfc_key": key},
            timeout=(15, 90),
        )
        r.raise_for_status()
    except requests.RequestException as e:
        # Never include the request URL because it contains the API key.
        raise DartConnectionError(
            "OpenDART 서버 연결이 지연되고 있습니다. 잠시 후 다시 시도해주세요. "
            "같은 오류가 반복되면 Streamlit 앱을 재부팅한 뒤 다시 시도하세요."
        ) from e

    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml = z.read(z.namelist()[0])
        root = ET.fromstring(xml)
    except Exception as e:
        raise ValueError("OpenDART 기업코드 파일을 해석하지 못했습니다.") from e

    rows = [{x.tag: x.text for x in c} for c in root.findall("list")]
    return pd.DataFrame(rows)


class DartClient:
    def __init__(self, key: str):
        self.key = _validate_dart_key(key)
        self.s = _session()

    def _get(self, path, params):
        p = {"crtfc_key": self.key, **params}
        try:
            r = self.s.get(f"{BASE}/{path}", params=p, timeout=(15, 60))
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            raise DartConnectionError(
                "OpenDART 서버 연결에 실패했습니다. 잠시 후 다시 시도해주세요."
            ) from e
        except ValueError as e:
            raise ValueError("OpenDART 응답을 읽지 못했습니다.") from e

        status = data.get("status")
        if status and status != "000":
            raise ValueError(data.get("message", f"OpenDART 오류 코드 {status}"))
        return data

    def corp_codes(self):
        return _corp_codes_cached(self.key)

    def resolve_company(self, q):
        df = self.corp_codes()
        q = q.strip().upper()
        exact = df[
            (df["corp_name"].str.upper() == q)
            | (df["stock_code"].fillna("").str.upper() == q)
        ]
        if exact.empty:
            contains = df[df["corp_name"].str.contains(q, case=False, na=False, regex=False)]
            if contains.empty:
                raise ValueError(f"기업을 찾지 못했습니다: {q}")
            exact = contains.head(5)
        row = exact.iloc[0]
        return self._get("company.json", {"corp_code": row["corp_code"]})

    def get_annual_financials(self, corp_code, years=3):
        current = pd.Timestamp.today().year
        out = []
        last_error = None
        for y in range(current - 1, current - years - 1, -1):
            try:
                data = self._get(
                    "fnlttSinglAcntAll.json",
                    {
                        "corp_code": corp_code,
                        "bsns_year": y,
                        "reprt_code": "11011",
                        "fs_div": "CFS",
                    },
                )
                out.extend(data.get("list", []))
            except ValueError as e:
                last_error = e
                continue
        if not out:
            if last_error:
                raise ValueError(
                    "최근 사업보고서 연결재무제표를 가져오지 못했습니다. "
                    "결산기/공시 여부 또는 DART 응답 상태를 확인해주세요."
                ) from last_error
            raise ValueError("최근 사업보고서 재무제표를 가져오지 못했습니다.")
        return pd.DataFrame(out)
