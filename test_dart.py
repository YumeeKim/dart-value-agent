import re
import time
import requests
import streamlit as st

st.set_page_config(page_title="OpenDART 연결 테스트", page_icon="🧪")
st.title("🧪 OpenDART 연결 테스트")
st.write("이 페이지는 가치평가를 하지 않습니다. Streamlit Cloud에서 OpenDART 서버에 접속 가능한지만 단계별로 검사합니다.")

try:
    dart_key = str(st.secrets["DART_API_KEY"]).strip()
except Exception:
    st.error("Streamlit Secrets에서 DART_API_KEY를 찾지 못했습니다.")
    st.stop()

st.write("### 1. Secret 확인")
if re.fullmatch(r"[0-9a-fA-F]{40}", dart_key):
    st.success("DART_API_KEY 형식 정상: 40자리")
else:
    st.error(f"DART_API_KEY 형식 이상: 현재 길이 {len(dart_key)}자리")
    st.stop()

if st.button("OpenDART 연결 테스트", type="primary"):
    st.write("### 2. 기본 서버 연결")
    try:
        t = time.time()
        r = requests.get("https://opendart.fss.or.kr/", timeout=(10, 20))
        st.success(f"기본 서버 연결 성공 — HTTP {r.status_code}, {time.time()-t:.2f}초")
    except Exception as e:
        st.error(f"기본 서버 연결 실패 — {type(e).__name__}: {e}")
        st.info("여기서 실패하면 API 키/삼성전자 문제가 아니라 Streamlit Cloud → OpenDART 네트워크 연결 문제입니다.")
        st.stop()

    st.write("### 3. corpCode API 연결")
    try:
        t = time.time()
        r = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": dart_key},
            timeout=(15, 60),
        )
        elapsed = time.time() - t
        st.write(f"HTTP 상태: {r.status_code} / 응답시간: {elapsed:.2f}초 / 크기: {len(r.content):,} bytes")

        if r.status_code != 200:
            st.error("corpCode API가 HTTP 오류를 반환했습니다.")
        elif r.content[:2] == b"PK":
            st.success("corpCode API 정상: ZIP 기업목록을 받았습니다.")
            st.balloons()
        else:
            preview = r.text[:500] if "text" in r.headers.get("content-type","").lower() or len(r.content) < 5000 else "(binary response)"
            st.warning("HTTP 연결은 성공했지만 예상한 ZIP 응답이 아닙니다.")
            st.code(preview)
    except Exception as e:
        st.error(f"corpCode API 연결 실패 — {type(e).__name__}: {e}")
        st.info("기본 서버는 성공하고 여기만 실패하면 corpCode API 요청 단계의 문제로 좁혀집니다.")
