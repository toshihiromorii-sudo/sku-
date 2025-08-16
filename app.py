
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="SKU売上・粗利シミュレーター", layout="wide")

# ---- Helpers
def yen(n):
    try:
        return f"¥{int(round(n, 0)):,}"
    except:
        return "¥0"

def pct(p):
    return f"{p*100:.1f}%"

# ---- Sidebar: Inputs
st.sidebar.title("パラメータ")
baseline_sku = st.sidebar.number_input("現状SKU（ベース）", min_value=0, step=1000, value=2_000_000)
annual_add = st.sidebar.number_input("年あたり追加SKU", min_value=0, step=1000, value=1_000_000)
years = st.sidebar.number_input("年数", min_value=1, step=1, value=10)

st.sidebar.markdown("---")
st.sidebar.caption("3社の“重み”は合計100でなくてもOK（内部で正規化します）")

w_yodo = st.sidebar.number_input("ヨドバシ.com：重み", min_value=0.0, step=0.1, value=33.3333)
w_mono = st.sidebar.number_input("MonotaRO：重み", min_value=0.0, step=0.1, value=33.3333)
w_asku = st.sidebar.number_input("ASKUL：重み", min_value=0.0, step=0.1, value=33.3333)

st.sidebar.markdown("---")
st.sidebar.caption("1SKUあたり売上と粗利率（必要に応じて上書き）")

rps_yodo = st.sidebar.number_input("ヨドバシ.com：1SKU売上(円)", min_value=0.0, step=100.0, value=28_350.0)
gm_yodo  = st.sidebar.number_input("ヨドバシ.com：粗利率", min_value=0.0, max_value=1.0, step=0.001, value=0.26)
rps_mono = st.sidebar.number_input("MonotaRO：1SKU売上(円)", min_value=0.0, step=100.0, value=11_642.0)
gm_mono  = st.sidebar.number_input("MonotaRO：粗利率", min_value=0.0, max_value=1.0, step=0.001, value=0.293)
rps_asku = st.sidebar.number_input("ASKUL：1SKU売上(円)", min_value=0.0, step=100.0, value=32_476.0)
gm_asku  = st.sidebar.number_input("ASKUL：粗利率", min_value=0.0, max_value=1.0, step=0.001, value=0.26)

# ---- Derived
total_added = annual_add * years
final_sku = baseline_sku + total_added

weights = np.array([w_yodo, w_mono, w_asku], dtype=float)
wsum = weights.sum()
if wsum <= 0:
    shares = np.array([1/3, 1/3, 1/3])
else:
    shares = weights / wsum

companies = ["ヨドバシ.com", "MonotaRO", "ASKUL"]
rev_per_sku = np.array([rps_yodo, rps_mono, rps_asku], dtype=float)
gm_rate = np.array([gm_yodo, gm_mono, gm_asku], dtype=float)
gp_per_sku = rev_per_sku * gm_rate

added_by_co = total_added * shares
revenue_by_co = added_by_co * rev_per_sku
gross_by_co = added_by_co * gp_per_sku

df = pd.DataFrame({
    "会社": companies,
    "割合(%)": shares * 100,
    "追加SKU": added_by_co.round(0).astype(int),
    "1SKU売上(円)": rev_per_sku.round(0).astype(int),
    "粗利率": gm_rate,
    "1SKU粗利(円)": gp_per_sku.round(0).astype(int),
    "追加売上高(円)": revenue_by_co.round(0).astype(int),
    "追加粗利(円)": gross_by_co.round(0).astype(int),
})

totals = {
    "追加SKU": int(round(df["追加SKU"].sum(), 0)),
    "追加売上高": int(round(df["追加売上高(円)"].sum(), 0)),
    "追加粗利": int(round(df["追加粗利(円)"].sum(), 0)),
}
avg_gm = (totals["追加粗利"] / totals["追加売上高"]) if totals["追加売上高"] > 0 else 0.0

# ---- Header
st.title("SKU 売上・粗利シミュレーター（ヨドバシ／MonotaRO／ASKUL）")
st.caption("配分・単価・粗利率・増加SKUを調整すると、10年間の『追加売上』と『追加粗利』が即時計算されます。")

# ---- KPI Row
kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("合計 追加SKU", f"{totals['追加SKU']:,}", f"= 年 {annual_add:,} × {years} 年")
kpi2.metric("最終SKU（年数経過後）", f"{final_sku:,}", f"= 現状 {baseline_sku:,} + 追加 {total_added:,}")
kpi3.metric("平均粗利率（追加分）", f"{avg_gm*100:.2f}%")

# ---- Table
st.subheader("明細（会社別）")
show_pct = df.copy()
show_pct["割合(%)"] = show_pct["割合(%)"].map(lambda x: f"{x:.1f}%")
show_pct["粗利率"] = show_pct["粗利率"].map(lambda x: f"{x*100:.1f}%")
st.dataframe(show_pct, use_container_width=True)

# ---- Charts
import altair as alt

chart_rev = alt.Chart(df).mark_bar().encode(
    x=alt.X("会社:N", title="会社"),
    y=alt.Y("追加売上高(円):Q", title="追加売上高（円）"),
    tooltip=["会社", alt.Tooltip("追加売上高(円):Q", format=",")]
).properties(title="会社別 追加売上高", height=320)

chart_gp = alt.Chart(df).mark_bar().encode(
    x=alt.X("会社:N", title="会社"),
    y=alt.Y("追加粗利(円):Q", title="追加粗利（円）"),
    tooltip=["会社", alt.Tooltip("追加粗利(円):Q", format=",")]
).properties(title="会社別 追加粗利", height=320)

c1, c2 = st.columns(2)
with c1: st.altair_chart(chart_rev, use_container_width=True)
with c2: st.altair_chart(chart_gp, use_container_width=True)

# ---- Totals
st.markdown("### 合計（追加分）")
tcol1, tcol2, tcol3 = st.columns(3)
tcol1.markdown(f"- **合計 追加SKU**：{totals['追加SKU']:,}")
tcol2.markdown(f"- **合計 追加売上高**：{yen(totals['追加売上高'])}")
tcol3.markdown(f"- **合計 追加粗利**：{yen(totals['追加粗利'])}（平均粗利率 {pct(avg_gm)}）")

# ---- Download
csv = df.to_csv(index=False).encode("utf-8-sig")
st.download_button("CSVダウンロード（会社別明細）", data=csv, file_name="sku_simulator.csv", mime="text/csv")

st.markdown("---")
st.caption("注）初期値は公開情報ベースの概算です。必要に応じて 1SKU売上／粗利率 を上書きしてご利用ください。")
