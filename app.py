"""India Business Expansion Intelligence: Streamlit entry point.

    streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Expansion Intelligence · India", page_icon=":material/query_stats:", layout="wide",
                   initial_sidebar_state="collapsed")

from ui import theme  # noqa: E402

theme.apply()
pages = [
    st.Page("pages/home.py", title="Home", default=True),
    st.Page("pages/profile.py", title="1 · Business profile", url_path="profile"),
    st.Page("pages/eligibility.py", title="2 · Eligibility", url_path="eligibility"),
    st.Page("pages/results.py", title="3 · Results", url_path="results"),
    st.Page("pages/methods.py", title="Methods & data", url_path="methods"),
]
st.navigation(pages, position="top").run()
