"""
社内日程調整ツール — Streamlit アプリ

起動方法:
  streamlit run scheduler_app.py

環境変数（オプション、.env でも設定可）:
  GOOGLE_CREDENTIALS_PATH : サービスアカウント JSON ファイルのパス
  SPREADSHEET_ID          : マスタスプレッドシートの ID
  SHEET_RANGE             : 読み込む範囲（例: Sheet1!A:B）
"""

import datetime
import os

import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo

from gcal_client import fetch_events, get_service as cal_service, parse_events
from gsheets_client import fetch_members, get_service as sheets_service
from scheduler_logic import find_candidate_slots

JST = ZoneInfo("Asia/Tokyo")
WD_JA = ["月", "火", "水", "木", "金", "土", "日"]

# ─────────────────────────── ページ設定 ──────────────────────────────
st.set_page_config(
    page_title="社内日程調整ツール",
    page_icon="📅",
    layout="wide",
)

st.title("📅 社内日程調整ツール")
st.caption(
    "Googleカレンダーと連携し、参加者全員の空き時間を自動で洗い出します。"
    "「ブロック」「Block」が入った予定は **🟡 要確認** として候補に含めます。"
)

# ─────────────────────────── サイドバー ──────────────────────────────
with st.sidebar:
    st.header("⚙️ 接続設定")

    cred_path = st.text_input(
        "サービスアカウント JSON ファイルパス",
        value=os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json"),
        help=(
            "Google Cloud Console でダウンロードしたサービスアカウントの JSON ファイルを指定。\n"
            "Google Workspace 管理コンソールでドメイン全体の委任（Domain-wide delegation）"
            "を有効にしておく必要があります。"
        ),
    )

    spreadsheet_id = st.text_input(
        "スプレッドシート ID",
        value=os.environ.get("SPREADSHEET_ID", ""),
        help="スプレッドシートの URL に含まれる長い文字列です（docs.google.com/spreadsheets/d/〈ここ〉/edit）。",
    )

    sheet_range = st.text_input(
        "シート範囲",
        value=os.environ.get("SHEET_RANGE", "Sheet1!A:B"),
        help="A列=名前、B列=メールアドレスを想定。例: Sheet1!A:B",
    )

    st.divider()
    st.header("🔍 検索条件")

    today = datetime.date.today()
    date_from = st.date_input("開始日", value=today + datetime.timedelta(days=1))
    date_to = st.date_input("終了日", value=today + datetime.timedelta(days=7))

    col1, col2 = st.columns(2)
    work_start = col1.time_input("始業", value=datetime.time(9, 0))
    work_end = col2.time_input("終業", value=datetime.time(18, 0))

    duration = st.selectbox(
        "会議時間",
        options=[30, 60, 90, 120],
        index=1,
        format_func=lambda m: f"{m}分",
    )

    st.divider()
    st.header("🎛️ 表示オプション")
    include_weekends = st.checkbox("土日も含める", value=False)
    show_block_only = st.checkbox("🟡 要確認スロットのみ表示", value=False)

# ─────────────────────────── ① メンバー読み込み ──────────────────────
st.subheader("① メンバー読み込み")

if st.button("スプレッドシートからメンバー一覧を読み込む", type="primary"):
    if not os.path.exists(cred_path):
        st.error(f"認証ファイルが見つかりません: {cred_path}")
    elif not spreadsheet_id:
        st.error("スプレッドシート ID を入力してください。")
    else:
        with st.spinner("読み込み中…"):
            try:
                svc = sheets_service(cred_path)
                members = fetch_members(svc, spreadsheet_id, sheet_range)
                st.session_state["members"] = members
                st.success(f"✅ {len(members)} 名を読み込みました。")
            except Exception as exc:
                st.error(f"スプレッドシート読み込みエラー: {exc}")
                st.session_state["members"] = []

members: list = st.session_state.get("members", [])

# ─────────────────────────── ② 参加者選択 ───────────────────────────
if members:
    st.subheader("② 参加者を選択")

    selected_names = st.multiselect(
        "参加者",
        options=[m["name"] for m in members],
        help="空き時間を確認したい参加者を選択してください。",
    )

    if selected_names:
        selected = [m for m in members if m["name"] in selected_names]

        # ─────────────────── ③ 空き時間検索 ────────────────────────
        st.subheader("③ 空き時間を検索")

        if date_from > date_to:
            st.error("終了日は開始日以降に設定してください。")
        elif work_start >= work_end:
            st.error("始業時刻は終業時刻より前に設定してください。")
        else:
            if st.button("🔍 カレンダーを確認して空き時間を探す", type="primary"):
                people_events: dict = {}
                fetch_errors: list = []

                prog = st.progress(0, text="カレンダーを確認中…")
                for idx, member in enumerate(selected):
                    prog.progress(
                        (idx + 1) / len(selected),
                        text=f"{member['name']} のカレンダーを取得中…",
                    )
                    try:
                        svc = cal_service(cred_path, member["email"])
                        raw = fetch_events(svc, date_from, date_to)
                        people_events[member["name"]] = parse_events(raw)
                    except Exception as exc:
                        fetch_errors.append(f"{member['name']}（{member['email']}）: {exc}")
                prog.empty()

                for err in fetch_errors:
                    st.warning(f"⚠️ カレンダー取得失敗 — {err}")

                # 日付ごとに候補スロットを収集
                all_slots: list = []
                cur = date_from
                while cur <= date_to:
                    is_weekend = cur.weekday() >= 5
                    if not is_weekend or include_weekends:
                        # その日に関係するイベントだけに絞る
                        day_ev = {
                            name: [
                                e for e in evs
                                if e["start"].date() <= cur <= e["end"].date()
                            ]
                            for name, evs in people_events.items()
                        }
                        all_slots.extend(
                            find_candidate_slots(
                                day_ev, cur, work_start, work_end, duration
                            )
                        )
                    cur += datetime.timedelta(days=1)

                st.session_state["search_results"] = all_slots
                st.session_state["searched"] = True

# ─────────────────────────── ④ 結果表示 ─────────────────────────────
if st.session_state.get("searched"):
    results: list = st.session_state.get("search_results", [])
    st.subheader("④ 候補時間一覧")

    if show_block_only:
        results = [s for s in results if s["block_people"]]

    if not results:
        st.info(
            "条件に合う候補時間が見つかりませんでした。"
            "検索期間・会議時間・始終業時刻を変更してお試しください。"
        )
    else:
        # サマリー
        total = len(results)
        ok_cnt = sum(1 for s in results if not s["block_people"])
        blk_cnt = total - ok_cnt

        m1, m2, m3 = st.columns(3)
        m1.metric("候補スロット（合計）", total)
        m2.metric("🟢 全員空き", ok_cnt)
        m3.metric("🟡 要確認あり", blk_cnt)

        st.caption("🟢 = 全員空き　🟡 = ブロック予定あり（要確認）")
        st.divider()

        # 日付ごとにグループ化して表示
        by_date: dict = {}
        for s in results:
            by_date.setdefault(s["start"].date(), []).append(s)

        for date, day_slots in sorted(by_date.items()):
            wd = WD_JA[date.weekday()]
            st.markdown(
                f"### {date.year}年{date.month}月{date.day}日（{wd}）"
            )

            for slot in day_slots:
                time_str = (
                    f"{slot['start'].strftime('%H:%M')}"
                    f" ～ {slot['end'].strftime('%H:%M')}"
                )
                if slot["block_people"]:
                    note = "　".join(
                        f"※{n}さんに確認必須" for n in slot["block_people"]
                    )
                    st.warning(f"🟡 {time_str}　　{note}")
                else:
                    st.success(f"🟢 {time_str}")

            st.markdown("")

        # CSV エクスポート
        rows = []
        for s in results:
            wd = WD_JA[s["start"].weekday()]
            rows.append(
                {
                    "日付": (
                        f"{s['start'].year}/"
                        f"{s['start'].month:02d}/"
                        f"{s['start'].day:02d}"
                        f"（{wd}）"
                    ),
                    "開始": s["start"].strftime("%H:%M"),
                    "終了": s["end"].strftime("%H:%M"),
                    "状態": "要確認あり" if s["block_people"] else "全員空き",
                    "備考": " / ".join(
                        f"※{n}さんに確認必須" for n in s["block_people"]
                    ),
                }
            )

        csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 候補時間を CSV でダウンロード",
            data=csv_bytes,
            file_name=f"schedule_candidates_{date_from}_{date_to}.csv",
            mime="text/csv",
        )

else:
    if not members:
        st.info(
            "⬅️ まず左サイドバーで接続設定を入力し、"
            "「スプレッドシートからメンバー一覧を読み込む」をクリックしてください。"
        )
