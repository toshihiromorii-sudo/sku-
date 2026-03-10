"""
アカウントプラン作成ツール
- タブ1: 基本情報
- タブ2: 現状分析
- タブ3: 目標・施策
- タブ4: 数値計画（年次プロジェクション）
"""

import streamlit as st
import pandas as pd
import numpy as np
import io
from datetime import date

st.set_page_config(page_title="アカウントプラン作成ツール", layout="wide")

st.title("📋 アカウントプラン作成ツール")
st.caption("アカウント基本情報・現状分析・年間目標・施策・数値計画をまとめて管理します。")

# ---- Session State 初期化
def _init(key, val):
    if key not in st.session_state:
        st.session_state[key] = val

# 基本情報
_init("account_name", "")
_init("client_name", "")
_init("plan_owner", "")
_init("plan_year", date.today().year)
_init("industry", "")
_init("memo", "")

# 現状分析（会社別）
companies = ["ヨドバシ.com", "MonotaRO", "ASKUL"]
for c in companies:
    _init(f"cur_sku_{c}", 0)
    _init(f"cur_rev_{c}", 0)
    _init(f"cur_gm_{c}", 0)

# 目標設定（会社別・年間追加SKU）
for c in companies:
    _init(f"tgt_add_sku_{c}", 0)
    _init(f"tgt_rps_{c}", 0.0)
    _init(f"tgt_gm_{c}", 0.0)
_init("plan_years", 3)

# 施策リスト
_init("actions", [
    {"施策": "", "担当者": "", "期限": "", "ステータス": "未着手", "備考": ""},
])

# ---- Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📋 基本情報", "📊 現状分析", "🎯 目標・施策", "📈 数値計画"])

# ===== TAB 1: 基本情報 =====
with tab1:
    st.subheader("基本情報")
    c1, c2 = st.columns(2)
    with c1:
        st.session_state.account_name = st.text_input(
            "アカウント名（自社プロジェクト名）", value=st.session_state.account_name)
        st.session_state.client_name = st.text_input(
            "顧客名", value=st.session_state.client_name)
        st.session_state.industry = st.text_input(
            "業種", value=st.session_state.industry)
    with c2:
        st.session_state.plan_owner = st.text_input(
            "プラン作成者", value=st.session_state.plan_owner)
        st.session_state.plan_year = st.number_input(
            "計画年度（開始年）", min_value=2020, max_value=2040,
            value=st.session_state.plan_year, step=1)
        st.session_state.plan_years = st.number_input(
            "計画年数", min_value=1, max_value=10,
            value=st.session_state.plan_years, step=1)

    st.session_state.memo = st.text_area(
        "備考・背景", value=st.session_state.memo, height=120)

    st.success("入力内容はリアルタイムで他のタブに反映されます。")


# ===== TAB 2: 現状分析 =====
with tab2:
    st.subheader("現状分析（会社別）")
    st.caption("現時点でのSKU数・売上・粗利を入力してください。")

    cur_rows = []
    for c in companies:
        col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
        with col1:
            st.markdown(f"**{c}**")
        with col2:
            st.session_state[f"cur_sku_{c}"] = st.number_input(
                f"現状SKU数", key=f"cur_sku_input_{c}",
                min_value=0, step=1000,
                value=st.session_state[f"cur_sku_{c}"])
        with col3:
            st.session_state[f"cur_rev_{c}"] = st.number_input(
                f"現状売上（円）", key=f"cur_rev_input_{c}",
                min_value=0, step=100_000,
                value=st.session_state[f"cur_rev_{c}"])
        with col4:
            st.session_state[f"cur_gm_{c}"] = st.number_input(
                f"現状粗利（円）", key=f"cur_gm_input_{c}",
                min_value=0, step=100_000,
                value=st.session_state[f"cur_gm_{c}"])
        cur_rows.append({
            "会社": c,
            "現状SKU数": st.session_state[f"cur_sku_{c}"],
            "現状売上（円）": st.session_state[f"cur_rev_{c}"],
            "現状粗利（円）": st.session_state[f"cur_gm_{c}"],
            "現状粗利率": (
                st.session_state[f"cur_gm_{c}"] / st.session_state[f"cur_rev_{c}"]
                if st.session_state[f"cur_rev_{c}"] > 0 else 0.0
            ),
        })

    st.markdown("---")
    st.subheader("現状サマリー")
    df_cur = pd.DataFrame(cur_rows)
    display_cur = df_cur.copy()
    display_cur["現状売上（円）"] = display_cur["現状売上（円）"].map(lambda x: f"¥{x:,}")
    display_cur["現状粗利（円）"] = display_cur["現状粗利（円）"].map(lambda x: f"¥{x:,}")
    display_cur["現状粗利率"] = display_cur["現状粗利率"].map(lambda x: f"{x*100:.1f}%")
    st.dataframe(display_cur, use_container_width=True)

    total_cur_rev = df_cur["現状売上（円）"].sum()
    total_cur_gm = df_cur["現状粗利（円）"].sum()
    total_cur_sku = df_cur["現状SKU数"].sum()
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("合計 現状SKU数", f"{total_cur_sku:,}")
    mc2.metric("合計 現状売上", f"¥{total_cur_rev:,}")
    mc3.metric("合計 現状粗利", f"¥{total_cur_gm:,}")


# ===== TAB 3: 目標・施策 =====
with tab3:
    st.subheader("年間目標設定（会社別）")
    st.caption("1年あたりの追加SKU数・1SKU売上・粗利率を設定してください。")

    tgt_rows = []
    for c in companies:
        col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
        with col1:
            st.markdown(f"**{c}**")
        with col2:
            st.session_state[f"tgt_add_sku_{c}"] = st.number_input(
                "年間追加SKU", key=f"tgt_sku_input_{c}",
                min_value=0, step=1000,
                value=st.session_state[f"tgt_add_sku_{c}"])
        with col3:
            st.session_state[f"tgt_rps_{c}"] = st.number_input(
                "1SKU売上（円）", key=f"tgt_rps_input_{c}",
                min_value=0.0, step=100.0,
                value=float(st.session_state[f"tgt_rps_{c}"]))
        with col4:
            st.session_state[f"tgt_gm_{c}"] = st.number_input(
                "粗利率", key=f"tgt_gm_input_{c}",
                min_value=0.0, max_value=1.0, step=0.001,
                value=float(st.session_state[f"tgt_gm_{c}"]))
        tgt_rows.append({
            "会社": c,
            "年間追加SKU": st.session_state[f"tgt_add_sku_{c}"],
            "1SKU売上（円）": st.session_state[f"tgt_rps_{c}"],
            "粗利率": st.session_state[f"tgt_gm_{c}"],
        })

    st.markdown("---")
    st.subheader("施策・アクションプラン")
    st.caption("具体的な施策を追加してください。行を追加・削除できます。")

    status_options = ["未着手", "進行中", "完了", "保留"]

    actions = st.session_state.actions
    num_actions = len(actions)

    # テーブル形式で施策入力
    header_cols = st.columns([3, 2, 2, 2, 3])
    header_cols[0].markdown("**施策**")
    header_cols[1].markdown("**担当者**")
    header_cols[2].markdown("**期限**")
    header_cols[3].markdown("**ステータス**")
    header_cols[4].markdown("**備考**")

    updated_actions = []
    for i, action in enumerate(actions):
        cols = st.columns([3, 2, 2, 2, 3])
        施策 = cols[0].text_input("施策", key=f"施策_{i}", value=action["施策"], label_visibility="collapsed")
        担当 = cols[1].text_input("担当者", key=f"担当_{i}", value=action["担当者"], label_visibility="collapsed")
        期限 = cols[2].text_input("期限（例：2026/06）", key=f"期限_{i}", value=action["期限"], label_visibility="collapsed")
        status_idx = status_options.index(action["ステータス"]) if action["ステータス"] in status_options else 0
        status = cols[3].selectbox("ステータス", status_options, key=f"status_{i}",
                                   index=status_idx, label_visibility="collapsed")
        備考 = cols[4].text_input("備考", key=f"備考_{i}", value=action["備考"], label_visibility="collapsed")
        updated_actions.append({"施策": 施策, "担当者": 担当, "期限": 期限, "ステータス": status, "備考": 備考})

    st.session_state.actions = updated_actions

    btn1, btn2 = st.columns([1, 5])
    with btn1:
        if st.button("➕ 行を追加"):
            st.session_state.actions.append(
                {"施策": "", "担当者": "", "期限": "", "ステータス": "未着手", "備考": ""})
            st.rerun()
    with btn2:
        if st.button("➖ 最終行を削除") and len(st.session_state.actions) > 1:
            st.session_state.actions.pop()
            st.rerun()


# ===== TAB 4: 数値計画 =====
with tab4:
    st.subheader("数値計画（年次プロジェクション）")
    plan_years = int(st.session_state.plan_years)
    start_year = int(st.session_state.plan_year)

    # 会社別の目標パラメータ収集
    tgt_add = {c: int(st.session_state[f"tgt_add_sku_{c}"]) for c in companies}
    tgt_rps = {c: float(st.session_state[f"tgt_rps_{c}"]) for c in companies}
    tgt_gm  = {c: float(st.session_state[f"tgt_gm_{c}"]) for c in companies}
    cur_sku  = {c: int(st.session_state[f"cur_sku_{c}"]) for c in companies}
    cur_rev  = {c: int(st.session_state[f"cur_rev_{c}"]) for c in companies}

    projection_rows = []
    for yr in range(1, plan_years + 1):
        year_label = f"{start_year + yr - 1}年度"
        for c in companies:
            cumulative_added_sku = tgt_add[c] * yr
            total_sku = cur_sku[c] + cumulative_added_sku
            added_rev = tgt_add[c] * yr * tgt_rps[c]
            total_rev = cur_rev[c] + added_rev
            added_gp  = added_rev * tgt_gm[c]
            projection_rows.append({
                "年度": year_label,
                "会社": c,
                "累計追加SKU": cumulative_added_sku,
                "合計SKU数": total_sku,
                "追加売上（円）": round(added_rev),
                "合計売上（円）": round(total_rev),
                "追加粗利（円）": round(added_gp),
            })

    df_proj = pd.DataFrame(projection_rows)

    # 年度別合計行を計算
    summary_rows = []
    for yr in range(1, plan_years + 1):
        year_label = f"{start_year + yr - 1}年度"
        yr_df = df_proj[df_proj["年度"] == year_label]
        total_rev = yr_df["合計売上（円）"].sum()
        added_rev = yr_df["追加売上（円）"].sum()
        added_gp  = yr_df["追加粗利（円）"].sum()
        avg_gm    = added_gp / added_rev if added_rev > 0 else 0.0
        summary_rows.append({
            "年度": year_label,
            "会社": "【合計】",
            "累計追加SKU": yr_df["累計追加SKU"].sum(),
            "合計SKU数": yr_df["合計SKU数"].sum(),
            "追加売上（円）": round(added_rev),
            "合計売上（円）": round(total_rev),
            "追加粗利（円）": round(added_gp),
        })

    df_summary = pd.DataFrame(summary_rows)
    df_combined = pd.concat([df_proj, df_summary]).sort_values(
        ["年度", "会社"], key=lambda x: x.map(
            lambda v: ("z" if v == "【合計】" else v)
        )
    ).reset_index(drop=True)

    # 表示用フォーマット
    display_proj = df_combined.copy()
    for col in ["追加売上（円）", "合計売上（円）", "追加粗利（円）"]:
        display_proj[col] = display_proj[col].map(lambda x: f"¥{x:,}")
    for col in ["累計追加SKU", "合計SKU数"]:
        display_proj[col] = display_proj[col].map(lambda x: f"{x:,}")

    st.dataframe(display_proj, use_container_width=True)

    # チャート
    import altair as alt

    chart_data = df_summary.copy()
    chart_rev = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X("年度:N", title="年度"),
        y=alt.Y("合計売上（円）:Q", title="合計売上（円）"),
        tooltip=["年度", alt.Tooltip("合計売上（円）:Q", format=",")]
    ).properties(title="年度別 合計売上", height=300)

    chart_gp = alt.Chart(chart_data).mark_bar(color="orange").encode(
        x=alt.X("年度:N", title="年度"),
        y=alt.Y("追加粗利（円）:Q", title="追加粗利（円）"),
        tooltip=["年度", alt.Tooltip("追加粗利（円）:Q", format=",")]
    ).properties(title="年度別 追加粗利", height=300)

    cc1, cc2 = st.columns(2)
    with cc1:
        st.altair_chart(chart_rev, use_container_width=True)
    with cc2:
        st.altair_chart(chart_gp, use_container_width=True)

    st.markdown("---")
    # ---- CSVダウンロード（プラン全体）
    st.subheader("プランのエクスポート")

    # 基本情報シート
    info_df = pd.DataFrame([{
        "アカウント名": st.session_state.account_name,
        "顧客名": st.session_state.client_name,
        "業種": st.session_state.industry,
        "プラン作成者": st.session_state.plan_owner,
        "計画年度（開始）": st.session_state.plan_year,
        "計画年数": st.session_state.plan_years,
        "備考": st.session_state.memo,
    }])

    # 施策リストシート
    action_df = pd.DataFrame(st.session_state.actions)

    # 現状分析シート
    cur_df = pd.DataFrame([{
        "会社": c,
        "現状SKU数": st.session_state[f"cur_sku_{c}"],
        "現状売上（円）": st.session_state[f"cur_rev_{c}"],
        "現状粗利（円）": st.session_state[f"cur_gm_{c}"],
    } for c in companies])

    # Excelファイルとして出力（複数シート）
    excel_buf = io.BytesIO()
    with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
        info_df.to_excel(writer, sheet_name="基本情報", index=False)
        cur_df.to_excel(writer, sheet_name="現状分析", index=False)
        action_df.to_excel(writer, sheet_name="施策アクションプラン", index=False)
        df_combined.to_excel(writer, sheet_name="数値計画", index=False)
    excel_buf.seek(0)

    account = st.session_state.account_name or "account"
    year = st.session_state.plan_year
    filename = f"account_plan_{account}_{year}.xlsx"

    st.download_button(
        "📥 Excelでダウンロード（全シート）",
        data=excel_buf.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # CSV個別ダウンロード
    with st.expander("CSVで個別ダウンロード"):
        st.download_button(
            "数値計画 CSV",
            data=df_combined.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"plan_projection_{account}_{year}.csv",
            mime="text/csv",
        )
        st.download_button(
            "施策リスト CSV",
            data=action_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"plan_actions_{account}_{year}.csv",
            mime="text/csv",
        )

st.markdown("---")
st.caption(f"作成日：{date.today().strftime('%Y年%m月%d日')}　| 　プラン期間：{st.session_state.plan_year}〜{int(st.session_state.plan_year) + int(st.session_state.plan_years) - 1}年度")
