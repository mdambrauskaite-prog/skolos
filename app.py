import io
import re
from datetime import datetime

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="VMI skolų dashboardas", layout="wide")

# VMI logotipo spalvos: žalia + balta. Naudojamas artimas VMI žalias atspalvis.
VMI_GREEN = "#007A3D"
VMI_DARK = "#064E2D"
VMI_LIGHT = "#EAF7EF"
VMI_GRAY = "#F4F6F5"

VMI_URLS = [
    "https://get.data.gov.lt/datasets/gov/vmi/ja_nepriemokos/NepriemokosSuma/:format/csv",
    "https://get.data.gov.lt/datasets/gov/vmi/ja_nepriemokos/NepriemokosSuma",
    "https://data.gov.lt/datasets/1202/versions/328/data/NepriemokosSuma/?format=csv",
]

BINS = [-0.01, 100, 500, 1000, 5000, 10000, 50000, 100000, 500000, float("inf")]
LABELS = [
    "0–100 €",
    "100–500 €",
    "500–1 000 €",
    "1 000–5 000 €",
    "5 000–10 000 €",
    "10 000–50 000 €",
    "50 000–100 000 €",
    "100 000–500 000 €",
    "500 000+ €",
]

st.markdown(
    f"""
    <style>
    .main .block-container {{ padding-top: 2rem; max-width: 1280px; }}
    .vmi-hero {{
        background: linear-gradient(135deg, {VMI_DARK}, {VMI_GREEN});
        padding: 26px 30px; border-radius: 22px; color: white; margin-bottom: 18px;
    }}
    .vmi-hero h1 {{ color: white; margin: 0; font-size: 2.4rem; }}
    .vmi-hero p {{ color: rgba(255,255,255,.86); margin: 8px 0 0 0; }}
    .search-box {{
        background: {VMI_LIGHT}; border: 2px solid {VMI_GREEN};
        padding: 18px 20px; border-radius: 18px; margin: 14px 0 22px 0;
    }}
    div[data-testid="stMetric"] {{
        background: white; border: 1px solid #dfe8e3; border-left: 6px solid {VMI_GREEN};
        padding: 14px 16px; border-radius: 16px; box-shadow: 0 1px 6px rgba(0,0,0,.04);
    }}
    .small-note {{ color: #637167; font-size: .92rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)


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


def euro(x):
    return f"{float(x):,.0f} €".replace(",", " ")


def euro2(x):
    return f"{float(x):,.2f} €".replace(",", " ")


def read_csv_smart(content: bytes) -> pd.DataFrame:
    for enc in ["utf-8", "utf-8-sig", "cp1257", "windows-1257", "latin1"]:
        for sep in [None, ";", ",", "\t"]:
            try:
                df = pd.read_csv(io.BytesIO(content), sep=sep, engine="python", encoding=enc)
                if len(df.columns) > 1:
                    return df
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
    date_col = low.get("atnaujinta") or low.get("sukurta") or next((c for c in df.columns if any(k in c.lower() for k in ["atnauj", "sukurta", "data"])), None)

    if not code_col or not debt_col:
        raise ValueError(f"Neradau reikalingų VMI stulpelių. Gauti stulpeliai: {', '.join(df.columns)}")

    out = pd.DataFrame()
    out["Įmonės kodas"] = df[code_col].map(clean_code)
    out["Pavadinimas"] = df[name_col].astype(str) if name_col else ""
    out["VMI skola"] = to_num(df[debt_col])
    out["Pradelsta nepriemoka"] = to_num(df[overdue_col]) if overdue_col else 0
    out["Atidėta nepriemoka"] = to_num(df[deferred_col]) if deferred_col else 0
    out["VMI duomenų data"] = df[date_col].astype(str) if date_col else ""

    out = out[out["Įmonės kodas"].ne("")]
    out = out[out["VMI skola"] > 0]
    out = out.groupby("Įmonės kodas", as_index=False).agg(
        Pavadinimas=("Pavadinimas", "first"),
        **{
            "VMI skola": ("VMI skola", "sum"),
            "Pradelsta nepriemoka": ("Pradelsta nepriemoka", "sum"),
            "Atidėta nepriemoka": ("Atidėta nepriemoka", "sum"),
            "VMI duomenų data": ("VMI duomenų data", "first"),
        },
    )
    out["Intervalas"] = pd.cut(out["VMI skola"], bins=BINS, labels=LABELS, include_lowest=True)
    return out.sort_values("VMI skola", ascending=False)


@st.cache_data(ttl=60 * 60, show_spinner="Kraunami VMI duomenys...")
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


with st.sidebar:
    st.header("Duomenys")
    if st.button("Perkrauti VMI duomenis"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Duomenys laikomi cache 1 val., kad dashboardas greičiau atsidarytų.")

try:
    df, vmi_url, loaded_at = fetch_vmi()
except Exception as e:
    st.error(str(e))
    st.stop()

vmi_dates = sorted([d for d in df["VMI duomenų data"].dropna().astype(str).unique() if d and d.lower() != "nan"])
vmi_data_text = vmi_dates[-1] if vmi_dates else "VMI faile datos stulpelis nerastas"

st.markdown(
    """
    <div class="vmi-hero">
      <h1>VMI skolų dashboardas</h1>
      <p>Bendra VMI juridinių asmenų skolų statistika, intervalai ir greita įmonės paieška pagal kodą.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="search-box">', unsafe_allow_html=True)
st.subheader("🔎 Įmonės paieška pagal kodą")
code_col, hint_col = st.columns([1.1, 1.6])
with code_col:
    code = st.text_input("Įvesk įmonės kodą", placeholder="pvz. 110504843", label_visibility="collapsed")
with hint_col:
    st.caption("Įvesk juridinio asmens kodą ir iškart matysi VMI skolą, pradelstą / atidėtą dalį ir duomenų datą.")

if code:
    res = df[df["Įmonės kodas"] == clean_code(code)]
    if res.empty:
        st.warning("Pagal šį kodą VMI skolų sąraše nerasta.")
    else:
        r = res.iloc[0]
        st.success(f"Rasta: {r['Pavadinimas']} ({r['Įmonės kodas']})")
        a, b, c, d, e = st.columns(5)
        a.metric("VMI skola", euro2(r["VMI skola"]))
        b.metric("Pradelsta", euro2(r["Pradelsta nepriemoka"]))
        c.metric("Atidėta", euro2(r["Atidėta nepriemoka"]))
        d.metric("Intervalas", str(r["Intervalas"]))
        e.metric("VMI data", str(r["VMI duomenų data"])[:10] if str(r["VMI duomenų data"]) else "—")
        st.dataframe(res, use_container_width=True, hide_index=True)
st.markdown('</div>', unsafe_allow_html=True)

st.subheader("Bendra statistika")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Įmonių su VMI skola", f"{len(df):,}".replace(",", " "))
k2.metric("Bendra VMI skola", euro(df["VMI skola"].sum()))
k3.metric("Mažiausia skola", euro2(df["VMI skola"].min()))
k4.metric("Didžiausia skola", euro2(df["VMI skola"].max()))

m1, m2, m3, m4 = st.columns(4)
m1.metric("Vidutinė skola", euro2(df["VMI skola"].mean()))
m2.metric("Mediana", euro2(df["VMI skola"].median()))
m3.metric("Pradelsta nepriemoka", euro(df["Pradelsta nepriemoka"].sum()))
m4.metric("Atidėta nepriemoka", euro(df["Atidėta nepriemoka"].sum()))

st.caption(
    f"Dashboardas duomenis atsisiuntė: {loaded_at}. VMI duomenų data faile: {vmi_data_text}. Šaltinis: {vmi_url}"
)

st.subheader("Skolų intervalai")
intervals = df.groupby("Intervalas", observed=False).agg(
    **{
        "Įmonių kiekis": ("Įmonės kodas", "count"),
        "Bendra suma": ("VMI skola", "sum"),
        "Vidutinė skola": ("VMI skola", "mean"),
        "Min skola": ("VMI skola", "min"),
        "Max skola": ("VMI skola", "max"),
    }
).reset_index()
intervals["Intervalas"] = intervals["Intervalas"].astype(str)
for col in ["Bendra suma", "Vidutinė skola", "Min skola", "Max skola"]:
    intervals[col] = intervals[col].fillna(0).round(2)

left, right = st.columns(2)
with left:
    chart_count = (
        alt.Chart(intervals)
        .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, color=VMI_GREEN)
        .encode(
            x=alt.X("Intervalas:N", sort=LABELS, title="Intervalas"),
            y=alt.Y("Įmonių kiekis:Q", title="Įmonių kiekis"),
            tooltip=["Intervalas", "Įmonių kiekis", alt.Tooltip("Bendra suma:Q", format=",.2f")],
        )
        .properties(height=360)
    )
    st.altair_chart(chart_count, use_container_width=True)
with right:
    chart_sum = (
        alt.Chart(intervals)
        .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, color=VMI_DARK)
        .encode(
            x=alt.X("Intervalas:N", sort=LABELS, title="Intervalas"),
            y=alt.Y("Bendra suma:Q", title="Bendra suma, €"),
            tooltip=["Intervalas", "Įmonių kiekis", alt.Tooltip("Bendra suma:Q", format=",.2f")],
        )
        .properties(height=360)
    )
    st.altair_chart(chart_sum, use_container_width=True)

show_intervals = intervals.copy()
for col in ["Bendra suma", "Vidutinė skola", "Min skola", "Max skola"]:
    show_intervals[col] = show_intervals[col].map(euro2)
st.dataframe(show_intervals, use_container_width=True, hide_index=True)

st.subheader("Didžiausios VMI skolos")
show_n = st.slider("Kiek eilučių rodyti", 10, 500, 50)
st.dataframe(df.head(show_n), use_container_width=True, hide_index=True)

csv = df.to_csv(index=False).encode("utf-8-sig")
st.download_button("Eksportuoti visą VMI sąrašą CSV", csv, file_name="vmi_skolos.csv", mime="text/csv")
