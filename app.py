import io
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import altair as alt

st.set_page_config(page_title="VMI skolų dashboardas", page_icon="💶", layout="wide")

VMI_CSV_URL = "https://get.data.gov.lt/datasets/gov/vmi/ja_nepriemokos/NepriemokosSuma/:format/csv"
VMI_GREEN = "#007A3D"
VMI_DARK = "#064E2D"
VMI_LIGHT = "#EAF7EF"

st.markdown(f"""
<style>
.main .block-container {{ padding-top: 2rem; max-width: 1280px; }}
.vmi-hero {{ background: linear-gradient(135deg, {VMI_DARK}, {VMI_GREEN}); padding: 26px 30px; border-radius: 22px; color: white; margin-bottom: 18px; }}
.vmi-hero h1 {{ color: white; margin: 0; font-size: 2.4rem; }}
.vmi-hero p {{ color: rgba(255,255,255,.88); margin: 8px 0 0; }}
.search-box {{ background: {VMI_LIGHT}; border: 2px solid {VMI_GREEN}; padding: 18px 20px; border-radius: 18px; margin: 14px 0 22px 0; }}
div[data-testid="stMetric"] {{ background: white; border: 1px solid #dfe8e3; border-left: 6px solid {VMI_GREEN}; padding: 14px 16px; border-radius: 16px; box-shadow: 0 1px 6px rgba(0,0,0,.04); }}
.small-note {{ color:#637167; font-size:.92rem; }}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=3600, show_spinner=False)
def load_vmi():
    headers = {"User-Agent": "Mozilla/5.0 VMI-dashboard/1.0"}
    r = requests.get(VMI_CSV_URL, headers=headers, timeout=60)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    # data.gov.lt CSV usually comma-separated; sep=None handles comma/semicolon if changed
    df = pd.read_csv(io.StringIO(text), sep=None, engine="python")
    df.columns = [c.strip() for c in df.columns]

    rename = {
        "ja_kodas": "Įmonės kodas",
        "ja_pavadinimas": "Įmonės pavadinimas",
        "nepriemoka": "VMI skola",
        "pradelsta_nepriemoka": "Pradelsta nepriemoka",
        "atideta_nepriemoka": "Atidėta nepriemoka",
        "sukurta": "Įrašo sukūrimo data",
        "atnaujinta": "VMI įrašo atnaujinimo data",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    for col in ["VMI skola", "Pradelsta nepriemoka", "Atidėta nepriemoka"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0

    if "Įmonės kodas" in df.columns:
        df["Įmonės kodas"] = df["Įmonės kodas"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    if "Įmonės pavadinimas" not in df.columns:
        df["Įmonės pavadinimas"] = ""

    return df, datetime.now().strftime("%Y-%m-%d %H:%M")


def eur(x):
    try:
        return f"{float(x):,.0f} €".replace(",", " ")
    except Exception:
        return "0 €"


def make_intervals(df):
    bins = [0, 100, 500, 1000, 5000, 10000, 50000, 100000, float("inf")]
    labels = ["iki 100 €", "100–500 €", "500–1 000 €", "1 000–5 000 €", "5 000–10 000 €", "10 000–50 000 €", "50 000–100 000 €", "100 000 €+"]
    d = df[df["VMI skola"] > 0].copy()
    d["Skolos intervalas"] = pd.cut(d["VMI skola"], bins=bins, labels=labels, include_lowest=True, right=True)
    out = d.groupby("Skolos intervalas", observed=False).agg(
        **{"Įmonių skaičius": ("Įmonės kodas", "count"), "Bendra suma": ("VMI skola", "sum")}
    ).reset_index()
    return out

st.markdown("""
<div class="vmi-hero">
  <h1>VMI skolų dashboardas</h1>
  <p>Bendra juridinių asmenų VMI skolų statistika, skolos intervalai ir greita įmonės paieška pagal kodą.</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Duomenys")
    if st.button("Perkrauti VMI duomenis"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Duomenys laikinai laikomi 1 val., kad dashboardas greičiau atsidarytų.")

try:
    df, loaded_at = load_vmi()
except Exception as e:
    st.error(f"Nepavyko užkrauti VMI duomenų: {e}")
    st.stop()

st.markdown('<div class="search-box">', unsafe_allow_html=True)
st.subheader("🔎 Įmonės paieška pagal kodą")
col_search, col_hint = st.columns([1, 1.55])
with col_search:
    code = st.text_input("Įvesk įmonės kodą", value="", placeholder="Pvz. 110504843", label_visibility="collapsed")
with col_hint:
    st.caption("Įvedus kodą iškart parodoma įmonės VMI skola, pradelsta / atidėta dalis ir VMI įrašo data.")

if code.strip():
    q = code.strip()
    res = df[df["Įmonės kodas"].astype(str).str.strip() == q]
    if res.empty:
        st.warning(f"Pagal kodą {q} VMI skolų sąraše įmonės nerasta.")
    else:
        row = res.iloc[0]
        st.success(f"Rasta: {row.get('Įmonės pavadinimas', '')}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("VMI skola", eur(row["VMI skola"]))
        c2.metric("Pradelsta nepriemoka", eur(row["Pradelsta nepriemoka"]))
        c3.metric("Atidėta nepriemoka", eur(row["Atidėta nepriemoka"]))
        c4.metric("VMI įrašo data", str(row.get("VMI įrašo atnaujinimo data", row.get("Įrašo sukūrimo data", "—")))[:10])
        show_cols = [c for c in ["Įmonės kodas", "Įmonės pavadinimas", "VMI skola", "Pradelsta nepriemoka", "Atidėta nepriemoka", "Įrašo sukūrimo data", "VMI įrašo atnaujinimo data"] if c in res.columns]
        st.dataframe(res[show_cols], use_container_width=True, hide_index=True)
st.markdown('</div>', unsafe_allow_html=True)

st.subheader("Santrauka")
debt = df[df["VMI skola"] > 0].copy()
col1, col2, col3, col4 = st.columns(4)
col1.metric("Įmonių su VMI skola", f"{len(debt):,}".replace(",", " "))
col2.metric("Bendra VMI skola", eur(debt["VMI skola"].sum()))
col3.metric("Pradelsta nepriemoka", eur(debt["Pradelsta nepriemoka"].sum()))
col4.metric("Atidėta nepriemoka", eur(debt["Atidėta nepriemoka"].sum()))

c5, c6, c7, c8 = st.columns(4)
c5.metric("Mažiausia skola", eur(debt["VMI skola"].min()))
c6.metric("Didžiausia skola", eur(debt["VMI skola"].max()))
c7.metric("Vidutinė skola", eur(debt["VMI skola"].mean()))
c8.metric("Mediana", eur(debt["VMI skola"].median()))

vmi_dates = []
for dc in ["VMI įrašo atnaujinimo data", "Įrašo sukūrimo data"]:
    if dc in df.columns:
        s = pd.to_datetime(df[dc], errors="coerce")
        if s.notna().any():
            vmi_dates.append(f"{dc}: {s.max().date()}")
st.caption(f"Dashboardas atsisiuntė duomenis: {loaded_at}. " + (" | ".join(vmi_dates) if vmi_dates else "VMI datos lauko nepavyko nustatyti."))

st.subheader("Skolos intervalai")
intervals = make_intervals(df)
left, right = st.columns(2)
with left:
    chart1 = alt.Chart(intervals).mark_bar(color=VMI_GREEN).encode(
        x=alt.X("Skolos intervalas:N", title="Skolos intervalas", sort=None),
        y=alt.Y("Įmonių skaičius:Q", title="Įmonių skaičius"),
        tooltip=["Skolos intervalas", "Įmonių skaičius", alt.Tooltip("Bendra suma:Q", format=",.0f")],
    ).properties(height=360)
    st.altair_chart(chart1, use_container_width=True)
with right:
    chart2 = alt.Chart(intervals).mark_bar(color=VMI_DARK).encode(
        x=alt.X("Skolos intervalas:N", title="Skolos intervalas", sort=None),
        y=alt.Y("Bendra suma:Q", title="Suma, €"),
        tooltip=["Skolos intervalas", "Įmonių skaičius", alt.Tooltip("Bendra suma:Q", format=",.0f")],
    ).properties(height=360)
    st.altair_chart(chart2, use_container_width=True)

st.dataframe(intervals.assign(**{"Bendra suma": intervals["Bendra suma"].map(eur)}), use_container_width=True, hide_index=True)

st.subheader("TOP 20 didžiausių VMI skolų")
top = debt.sort_values("VMI skola", ascending=False).head(20)
show_cols = [c for c in ["Įmonės kodas", "Įmonės pavadinimas", "VMI skola", "Pradelsta nepriemoka", "Atidėta nepriemoka", "VMI įrašo atnaujinimo data"] if c in top.columns]
st.dataframe(top[show_cols], use_container_width=True, hide_index=True)

csv = df.to_csv(index=False).encode("utf-8-sig")
st.download_button("Atsisiųsti VMI duomenis CSV", csv, "vmi_skolos.csv", "text/csv")
