import io
import re
import zipfile
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="VMI ir Sodros skolų dashboardas", layout="wide")

VMI_URLS = [
    "https://get.data.gov.lt/datasets/gov/vmi/ja_nepriemokos/NepriemokosSuma/:format/csv",
    "https://data.gov.lt/datasets/1202/versions/328/data/NepriemokosSuma/?format=csv",
    "https://get.data.gov.lt/datasets/gov/vmi/ja_nepriemokos/NepriemokosSuma",
]
SODRA_ZIP_URL = "https://sodra.lt/Failai/Skolos.zip"

BINS = [-0.01, 0, 100, 500, 1000, 5000, 10000, 50000, 100000, float("inf")]
LABELS = ["0", "0–100", "100–500", "500–1 000", "1 000–5 000", "5 000–10 000", "10 000–50 000", "50 000–100 000", "100 000+"]


def clean_code(x):
    if pd.isna(x):
        return ""
    return re.sub(r"\D", "", str(x)).strip()


def to_num(s):
    return pd.to_numeric(
        pd.Series(s).astype(str).str.replace("\xa0", "", regex=False).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False),
        errors="coerce",
    ).fillna(0)


def read_csv_smart(content: bytes) -> pd.DataFrame:
    for enc in ["utf-8", "utf-8-sig", "cp1257", "windows-1257", "latin1"]:
        for sep in [None, ";", ",", "\t"]:
            try:
                return pd.read_csv(io.BytesIO(content), sep=sep, engine="python", encoding=enc)
            except Exception:
                pass
    raise ValueError("Nepavyko perskaityti CSV failo")


@st.cache_data(ttl=60 * 60)
def fetch_vmi():
    last_err = None
    for url in VMI_URLS:
        try:
            r = requests.get(url, timeout=60, headers={"Accept": "text/csv,application/json,*/*"})
            r.raise_for_status()
            txt = r.content[:200].decode("utf-8", errors="ignore")
            if txt.lstrip().startswith("{") or txt.lstrip().startswith("["):
                js = r.json()
                rows = js.get("_data") or js.get("data") or js.get("results") or js
                df = pd.DataFrame(rows)
            else:
                df = read_csv_smart(r.content)
            return normalize_vmi(df), url, datetime.now().strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            last_err = e
    raise RuntimeError(f"VMI duomenų paimti nepavyko: {last_err}")


def normalize_vmi(df):
    df.columns = [str(c).strip() for c in df.columns]
    low = {c.lower(): c for c in df.columns}
    code_col = low.get("ja_kodas") or low.get("kodas") or next((c for c in df.columns if "kodas" in c.lower()), None)
    name_col = low.get("ja_pavadinimas") or low.get("pavadinimas") or next((c for c in df.columns if "pavad" in c.lower()), None)
    debt_col = low.get("nepriemoka") or next((c for c in df.columns if "nepriemoka" in c.lower() and "pradelsta" not in c.lower() and "atideta" not in c.lower()), None)
    overdue_col = low.get("pradelsta_nepriemoka") or next((c for c in df.columns if "pradelsta" in c.lower()), None)
    deferred_col = low.get("atideta_nepriemoka") or next((c for c in df.columns if "atideta" in c.lower() and "pradelsta" not in c.lower()), None)
    date_cols = [c for c in df.columns if any(k in c.lower() for k in ["data", "atnauj", "sukurta", "laikotarp"])]
    out = pd.DataFrame()
    out["imones_kodas"] = df[code_col].map(clean_code) if code_col else ""
    out["pavadinimas"] = df[name_col].astype(str) if name_col else ""
    out["vmi_suma"] = to_num(df[debt_col]) if debt_col else 0
    out["vmi_pradelsta"] = to_num(df[overdue_col]) if overdue_col else 0
    out["vmi_atideta"] = to_num(df[deferred_col]) if deferred_col else 0
    out["vmi_data"] = df[date_cols[0]].astype(str) if date_cols else ""
    out = out[out["imones_kodas"].ne("")].groupby("imones_kodas", as_index=False).agg({
        "pavadinimas":"first", "vmi_suma":"sum", "vmi_pradelsta":"sum", "vmi_atideta":"sum", "vmi_data":"first"
    })
    return out


@st.cache_data(ttl=60 * 60)
def fetch_sodra():
    r = requests.get(SODRA_ZIP_URL, timeout=90)
    r.raise_for_status()
    return parse_sodra_zip(r.content), datetime.now().strftime("%Y-%m-%d %H:%M")


def parse_sodra_zip(content: bytes):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        data_name = next((n for n in names if n.lower().endswith((".csv", ".txt"))), names[0])
        raw = z.read(data_name)
    df = read_csv_smart(raw)
    return normalize_sodra(df), data_name


def normalize_sodra(df):
    df.columns = [str(c).strip() for c in df.columns]
    low = {c.lower(): c for c in df.columns}
    code_col = next((c for c in df.columns if any(k in c.lower() for k in ["kodas", "draudejo_kodas", "jar"])), df.columns[0])
    name_col = next((c for c in df.columns if any(k in c.lower() for k in ["pavad", "draudejo_pavadinimas", "vardas"])), None)
    amount_col = next((c for c in df.columns if any(k in c.lower() for k in ["skola", "suma", "debt"])), None)
    date_col = next((c for c in df.columns if any(k in c.lower() for k in ["data", "date"])), None)
    out = pd.DataFrame()
    out["imones_kodas"] = df[code_col].map(clean_code)
    out["sodra_pavadinimas"] = df[name_col].astype(str) if name_col else ""
    out["sodra_suma"] = to_num(df[amount_col]) if amount_col else 0
    out["sodra_data"] = df[date_col].astype(str) if date_col else ""
    out = out[out["imones_kodas"].ne("")].groupby("imones_kodas", as_index=False).agg({
        "sodra_pavadinimas":"first", "sodra_suma":"sum", "sodra_data":"first"
    })
    return out


def combine(vmi, sodra):
    df = vmi.merge(sodra, on="imones_kodas", how="outer")
    for c in ["vmi_suma", "vmi_pradelsta", "vmi_atideta", "sodra_suma"]:
        df[c] = df[c].fillna(0)
    for c in ["pavadinimas", "sodra_pavadinimas", "vmi_data", "sodra_data"]:
        df[c] = df[c].fillna("")
    df["pavadinimas"] = df["pavadinimas"].where(df["pavadinimas"].ne(""), df["sodra_pavadinimas"])
    df["bendra_suma"] = df["vmi_suma"] + df["sodra_suma"]
    df["saltinis"] = df.apply(lambda r: "VMI + Sodra" if r.vmi_suma > 0 and r.sodra_suma > 0 else ("VMI" if r.vmi_suma > 0 else "Sodra"), axis=1)
    df["intervalas"] = pd.cut(df["bendra_suma"], bins=BINS, labels=LABELS, include_lowest=True)
    return df.sort_values("bendra_suma", ascending=False)


st.title("VMI ir „Sodros“ skolų dashboardas")
st.caption("Automatiškai paima VMI atvirų duomenų rinkinį ir „Sodros“ Skolos.zip, sujungia pagal įmonės kodą, skaičiuoja persidengimą ir intervalus.")

with st.sidebar:
    st.header("Duomenys")
    use_upload = st.toggle("Jei „Sodra“ neatsisiunčia, naudoti įkeltą ZIP", value=False)
    uploaded_zip = st.file_uploader("Sodros Skolos.zip", type=["zip"]) if use_upload else None
    refresh = st.button("Perkrauti duomenis")
    if refresh:
        st.cache_data.clear()

try:
    vmi, vmi_url, vmi_time = fetch_vmi()
    if uploaded_zip:
        sodra, sodra_file = parse_sodra_zip(uploaded_zip.read())
        sodra_time = "įkelta ranka"
    else:
        sodra_pack, sodra_time = fetch_sodra()
        sodra, sodra_file = sodra_pack
    df = combine(vmi, sodra)
except Exception as e:
    st.error(str(e))
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("VMI įmonių su skola", f"{(df.vmi_suma > 0).sum():,}".replace(",", " "))
c2.metric("Sodros įmonių su skola", f"{(df.sodra_suma > 0).sum():,}".replace(",", " "))
c3.metric("Persidengia", f"{((df.vmi_suma > 0) & (df.sodra_suma > 0)).sum():,}".replace(",", " "))
c4.metric("Bendra suma", f"{df.bendra_suma.sum():,.0f} €".replace(",", " "))
c5.metric("Duomenys atnaujinti", vmi_time)

st.caption(f"VMI šaltinis: {vmi_url} | Sodros failas: {sodra_file} | Sodros paėmimas: {sodra_time}")

st.subheader("Dashboardas: intervalai ir persidengimas")
intervals = df.groupby("intervalas", observed=False).agg(
    imoniu=("imones_kodas", "count"),
    suma=("bendra_suma", "sum"),
    vmi_imoniu=("vmi_suma", lambda s: (s > 0).sum()),
    sodra_imoniu=("sodra_suma", lambda s: (s > 0).sum()),
    persidengia=("saltinis", lambda s: (s == "VMI + Sodra").sum()),
).reset_index()

left, right = st.columns(2)
with left:
    st.plotly_chart(px.bar(intervals, x="intervalas", y="imoniu", title="Įmonių skaičius pagal bendros skolos intervalą"), use_container_width=True)
with right:
    source_counts = df.groupby("saltinis", as_index=False).agg(imoniu=("imones_kodas", "count"), suma=("bendra_suma", "sum"))
    st.plotly_chart(px.pie(source_counts, names="saltinis", values="imoniu", title="Skolininkai pagal šaltinį"), use_container_width=True)

st.dataframe(intervals, use_container_width=True)

st.subheader("Įmonės paieška")
code = st.text_input("Įvesk įmonės kodą", placeholder="pvz. 110504843")
if code:
    res = df[df["imones_kodas"] == clean_code(code)]
    if res.empty:
        st.warning("Pagal šį kodą VMI ir Sodros skolų sąrašuose nerasta.")
    else:
        r = res.iloc[0]
        a, b, c = st.columns(3)
        a.metric("VMI skola", f"{r.vmi_suma:,.2f} €".replace(",", " "))
        b.metric("Sodros skola", f"{r.sodra_suma:,.2f} €".replace(",", " "))
        c.metric("Iš viso", f"{r.bendra_suma:,.2f} €".replace(",", " "))
        st.dataframe(res[["imones_kodas", "pavadinimas", "vmi_suma", "vmi_pradelsta", "vmi_atideta", "vmi_data", "sodra_suma", "sodra_data", "bendra_suma", "saltinis"]], use_container_width=True)

st.subheader("Didžiausios bendros skolos")
show_n = st.slider("Kiek eilučių rodyti", 10, 500, 50)
st.dataframe(df.head(show_n)[["imones_kodas", "pavadinimas", "vmi_suma", "sodra_suma", "bendra_suma", "vmi_data", "sodra_data", "saltinis", "intervalas"]], use_container_width=True)

csv = df.to_csv(index=False).encode("utf-8-sig")
st.download_button("Eksportuoti CSV", csv, file_name="vmi_sodra_skolos.csv", mime="text/csv")

buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="duomenys")
    intervals.to_excel(writer, index=False, sheet_name="intervalai")
st.download_button("Eksportuoti Excel", buf.getvalue(), file_name="vmi_sodra_skolos.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
