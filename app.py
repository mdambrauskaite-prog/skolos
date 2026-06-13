import io
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="VMI skolų dashboardas", layout="wide")

VMI_URLS = [
    "https://get.data.gov.lt/datasets/gov/vmi/ja_nepriemokos/NepriemokosSuma/:format/csv",
    "https://data.gov.lt/datasets/1202/versions/328/data/NepriemokosSuma/?format=csv",
    "https://get.data.gov.lt/datasets/gov/vmi/ja_nepriemokos/NepriemokosSuma",
]

BINS = [-0.01, 100, 500, 1000, 5000, 10000, 50000, 100000, 500000, float("inf")]
LABELS = [
    "0–100",
    "100–500",
    "500–1 000",
    "1 000–5 000",
    "5 000–10 000",
    "10 000–50 000",
    "50 000–100 000",
    "100 000–500 000",
    "500 000+",
]


def clean_code(x):
    if pd.isna(x):
        return ""
    return re.sub(r"\D", "", str(x)).strip()


def to_num(s):
    return pd.to_numeric(
        pd.Series(s)
        .astype(str)
        .str.replace("\xa0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce",
    ).fillna(0)


def read_csv_smart(content: bytes) -> pd.DataFrame:
    for enc in ["utf-8", "utf-8-sig", "cp1257", "windows-1257", "latin1"]:
        for sep in [None, ";", ",", "\t"]:
            try:
                return pd.read_csv(io.BytesIO(content), sep=sep, engine="python", encoding=enc)
            except Exception:
                pass
    raise ValueError("Nepavyko perskaityti VMI CSV")


def normalize_vmi(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    low = {c.lower(): c for c in df.columns}

    code_col = low.get("ja_kodas") or low.get("kodas") or next((c for c in df.columns if "kodas" in c.lower()), None)
    name_col = low.get("ja_pavadinimas") or low.get("pavadinimas") or next((c for c in df.columns if "pavad" in c.lower()), None)
    debt_col = low.get("nepriemoka") or next((c for c in df.columns if "nepriemoka" in c.lower() and "pradelsta" not in c.lower() and "atideta" not in c.lower()), None)
    overdue_col = low.get("pradelsta_nepriemoka") or next((c for c in df.columns if "pradelsta" in c.lower()), None)
    deferred_col = low.get("atideta_nepriemoka") or next((c for c in df.columns if "atideta" in c.lower()), None)
    date_cols = [c for c in df.columns if any(k in c.lower() for k in ["data", "atnauj", "sukurta", "laikotarp"])]

    if not code_col or not debt_col:
        raise ValueError(f"Neradau reikalingų VMI stulpelių. Gauti stulpeliai: {', '.join(df.columns)}")

    out = pd.DataFrame()
    out["imones_kodas"] = df[code_col].map(clean_code)
    out["pavadinimas"] = df[name_col].astype(str) if name_col else ""
    out["vmi_suma"] = to_num(df[debt_col])
    out["vmi_pradelsta"] = to_num(df[overdue_col]) if overdue_col else 0
    out["vmi_atideta"] = to_num(df[deferred_col]) if deferred_col else 0
    out["vmi_data"] = df[date_cols[0]].astype(str) if date_cols else ""

    out = out[out["imones_kodas"].ne("")]
    out = out[out["vmi_suma"] > 0]
    out = out.groupby("imones_kodas", as_index=False).agg(
        pavadinimas=("pavadinimas", "first"),
        vmi_suma=("vmi_suma", "sum"),
        vmi_pradelsta=("vmi_pradelsta", "sum"),
        vmi_atideta=("vmi_atideta", "sum"),
        vmi_data=("vmi_data", "first"),
    )
    out["intervalas"] = pd.cut(out["vmi_suma"], bins=BINS, labels=LABELS, include_lowest=True)
    return out.sort_values("vmi_suma", ascending=False)


@st.cache_data(ttl=60 * 60)
def fetch_vmi():
    last_err = None
    headers = {"Accept": "text/csv,application/json,*/*", "User-Agent": "Mozilla/5.0 VMI dashboard"}
    for url in VMI_URLS:
        try:
            r = requests.get(url, timeout=90, headers=headers)
            r.raise_for_status()
            start = r.content[:300].decode("utf-8", errors="ignore").lstrip()
            if start.startswith("{") or start.startswith("["):
                js = r.json()
                rows = js.get("_data") or js.get("data") or js.get("results") or js
                df = pd.DataFrame(rows)
            else:
                df = read_csv_smart(r.content)
            return normalize_vmi(df), url, datetime.now().strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            last_err = e
    raise RuntimeError(f"VMI duomenų paimti nepavyko: {last_err}")


st.title("VMI skolų dashboardas")
st.caption("Automatiškai paima VMI juridinių asmenų nepriemokų duomenis, skaičiuoja bendrą skolą, intervalus ir leidžia patikrinti konkrečią įmonę pagal kodą.")

with st.sidebar:
    st.header("Duomenys")
    if st.button("Perkrauti VMI duomenis"):
        st.cache_data.clear()
        st.rerun()

try:
    df, vmi_url, loaded_at = fetch_vmi()
except Exception as e:
    st.error(str(e))
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Įmonių su VMI skola", f"{len(df):,}".replace(",", " "))
c2.metric("Bendra VMI skola", f"{df.vmi_suma.sum():,.0f} €".replace(",", " "))
c3.metric("Pradelsta nepriemoka", f"{df.vmi_pradelsta.sum():,.0f} €".replace(",", " "))
c4.metric("Atidėta nepriemoka", f"{df.vmi_atideta.sum():,.0f} €".replace(",", " "))

st.caption(f"Duomenys užkrauti: {loaded_at} | Šaltinis: {vmi_url}")

st.subheader("Skolų intervalai")
intervals = df.groupby("intervalas", observed=False).agg(
    imoniu=("imones_kodas", "count"),
    suma=("vmi_suma", "sum"),
    vidurkis=("vmi_suma", "mean"),
).reset_index()
intervals["suma"] = intervals["suma"].round(2)
intervals["vidurkis"] = intervals["vidurkis"].round(2)

left, right = st.columns(2)
with left:
    st.plotly_chart(
        px.bar(intervals, x="intervalas", y="imoniu", text="imoniu", title="Kiek įmonių patenka į kiekvieną skolos intervalą"),
        use_container_width=True,
    )
with right:
    st.plotly_chart(
        px.bar(intervals, x="intervalas", y="suma", title="Bendra skolos suma pagal intervalą"),
        use_container_width=True,
    )

st.dataframe(intervals, use_container_width=True)

st.subheader("Įmonės paieška pagal kodą")
code = st.text_input("Įvesk įmonės kodą", placeholder="pvz. 110504843")
if code:
    res = df[df["imones_kodas"] == clean_code(code)]
    if res.empty:
        st.warning("Pagal šį kodą VMI skolų sąraše nerasta.")
    else:
        r = res.iloc[0]
        a, b, c = st.columns(3)
        a.metric("VMI skola", f"{r.vmi_suma:,.2f} €".replace(",", " "))
        b.metric("Pradelsta", f"{r.vmi_pradelsta:,.2f} €".replace(",", " "))
        c.metric("Atidėta", f"{r.vmi_atideta:,.2f} €".replace(",", " "))
        st.dataframe(res[["imones_kodas", "pavadinimas", "vmi_suma", "vmi_pradelsta", "vmi_atideta", "vmi_data", "intervalas"]], use_container_width=True)

st.subheader("Didžiausios VMI skolos")
show_n = st.slider("Kiek eilučių rodyti", 10, 500, 50)
st.dataframe(df.head(show_n)[["imones_kodas", "pavadinimas", "vmi_suma", "vmi_pradelsta", "vmi_atideta", "vmi_data", "intervalas"]], use_container_width=True)

csv = df.to_csv(index=False).encode("utf-8-sig")
st.download_button("Eksportuoti visą VMI sąrašą CSV", csv, file_name="vmi_skolos.csv", mime="text/csv")
