"""
社内日程調整ツール — Streamlit アプリ

起動方法:
  streamlit run scheduler_app.py

必要な環境変数（.env ファイルまたはシェルで設定）:
  GOOGLE_CREDENTIALS_PATH : サービスアカウント JSON ファイルのパス
  SPREADSHEET_ID          : マスタスプレッドシートの ID
  SHEET_RANGE             : 読み込む範囲（例: Sheet1!A:B）
  ANTHROPIC_API_KEY       : 欄①の自然言語解析に使用（任意）
"""

import datetime
import json
import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from zoneinfo import ZoneInfo

from gcal_client import (
    create_event,
    fetch_events,
    get_service as cal_service,
    get_write_service,
    parse_events,
    parse_slot_text,
)
from gsheets_client import fetch_members, get_service as sheets_service
from scheduler_logic import find_candidate_slots, merge_consecutive_slots

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
    "Googleカレンダーと連携し、全員の空き時間を自動で洗い出します。"
    "「ブロック」「Block」付き予定は 🟡 要確認として候補に含めます。"
)


# ─────────────────────────── ユーティリティ ──────────────────────────
def clipboard_copy_button(text_to_copy: str, label: str = "📋 全候補をクリップボードにコピー"):
    """ワンクリックでテキストをクリップボードにコピーするボタンを描画する。"""
    text_json = json.dumps(text_to_copy)
    html = f"""
    <!DOCTYPE html><html><head>
    <style>
      body {{ margin:0; padding:4px; }}
      button {{
        background:#28a745; color:white; border:none;
        padding:10px 28px; border-radius:6px; cursor:pointer;
        font-size:15px; font-weight:bold; width:100%;
      }}
      button:hover {{ background:#218838; }}
    </style></head><body>
    <button id="btn" onclick="doCopy()">{label}</button>
    <script>
    const TXT = {text_json};
    function doCopy() {{
      const btn = document.getElementById('btn');
      const ok  = () => {{
        btn.textContent = '✅ コピーしました！';
        btn.style.background = '#6c757d';
        setTimeout(() => {{
          btn.textContent = '{label}';
          btn.style.background = '#28a745';
        }}, 2200);
      }};
      if (navigator.clipboard && window.isSecureContext) {{
        navigator.clipboard.writeText(TXT).then(ok).catch(fallback);
      }} else {{ fallback(); }}
      function fallback() {{
        const ta = document.createElement('textarea');
        ta.value = TXT; ta.style.opacity='0';
        document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); document.body.removeChild(ta);
        ok();
      }}
    }}
    </script></body></html>
    """
    components.html(html, height=58)


def format_copy_text(slots: list, num: int) -> str:
    """候補スロットをコピー用テキストに整形する。"""
    lines = [f"■ 候補日程（{num}件）", ""]
    labels = "①②③④⑤⑥⑦⑧⑨⑩"
    for i, s in enumerate(slots[:10]):
        d = s["start"]
        wd = WD_JA[d.weekday()]
        time_str = f"{d.strftime('%H:%M')}〜{s['end'].strftime('%H:%M')}"
        date_str = f"{d.month}/{d.day}（{wd}）"
        line = f"{labels[i]} {date_str} {time_str}"
        if s["block_people"]:
            notes = "、".join(f"※{p}さんに確認必須" for p in s["block_people"])
            line += f"　{notes}"
        lines.append(line)
    lines.append("")
    lines.append("よろしくお願いいたします。")
    return "\n".join(lines)


def run_calendar_search(
    selected_members: list,
    date_from: datetime.date,
    date_to: datetime.date,
    work_start: datetime.time,
    work_end: datetime.time,
    duration: int,
    include_weekends: bool,
    num_candidates: int,
    cred_path: str,
) -> tuple:
    """カレンダーを検索して候補スロットを返す。(slots, errors)"""
    people_events: dict = {}
    errors: list = []

    prog = st.progress(0, text="カレンダーを確認中…")
    for idx, member in enumerate(selected_members):
        prog.progress(
            (idx + 1) / len(selected_members),
            text=f"{member['name']} のカレンダーを取得中…",
        )
        try:
            svc = cal_service(cred_path, member["email"])
            raw = fetch_events(svc, date_from, date_to)
            people_events[member["name"]] = parse_events(raw)
        except Exception as exc:
            errors.append(f"{member['name']}（{member['email']}）: {exc}")
    prog.empty()

    raw_slots: list = []
    cur = date_from
    while cur <= date_to:
        if cur.weekday() < 5 or include_weekends:
            day_ev = {
                name: [e for e in evs if e["start"].date() <= cur <= e["end"].date()]
                for name, evs in people_events.items()
            }
            raw_slots.extend(
                find_candidate_slots(day_ev, cur, work_start, work_end, duration)
            )
        cur += datetime.timedelta(days=1)

    merged = merge_consecutive_slots(raw_slots)
    # 候補数を制限
    if num_candidates > 0:
        merged = merged[:num_candidates]
    return merged, errors


# ─────────────────────────── サイドバー ──────────────────────────────
with st.sidebar:
    st.header("⚙️ 接続設定")

    cred_path = st.text_input(
        "サービスアカウント JSON",
        value=os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json"),
        help="Google Cloud Console でダウンロードしたサービスアカウント JSON のパス。",
    )
    spreadsheet_id = st.text_input(
        "スプレッドシート ID",
        value=os.environ.get("SPREADSHEET_ID", ""),
        help="スプレッドシート URL 中の ID 文字列。",
    )
    sheet_range = st.text_input(
        "シート範囲",
        value=os.environ.get("SHEET_RANGE", "Sheet1!A:B"),
        help="A列=名前、B列=メールアドレス。例: Sheet1!A:B",
    )
    organizer_email = st.text_input(
        "主催者メールアドレス",
        value=os.environ.get("ORGANIZER_EMAIL", ""),
        help="カレンダーイベントを作成する人のメールアドレス（あなた自身）。",
    )

    st.divider()
    st.header("🎛️ 検索デフォルト値")
    st.caption("欄①で指示しない場合に使われる初期値です。")

    today = datetime.date.today()
    _def_from = today + datetime.timedelta(days=1)
    _def_to = today + datetime.timedelta(days=7)
    def_date_from = st.date_input("開始日", value=_def_from, key="def_date_from")
    def_date_to = st.date_input("終了日", value=_def_to, key="def_date_to")
    col1, col2 = st.columns(2)
    def_work_start = col1.time_input("始業", value=datetime.time(9, 0), key="def_ws")
    def_work_end = col2.time_input("終業", value=datetime.time(18, 0), key="def_we")
    def_duration = st.selectbox(
        "会議時間",
        [30, 60, 90, 120],
        index=1,
        format_func=lambda m: f"{m}分",
    )
    def_num_cands = st.number_input("最大候補数", min_value=1, max_value=20, value=5)
    include_weekends = st.checkbox("土日も含める", value=False)

    st.divider()
    anthropic_key = st.text_input(
        "Anthropic API キー（欄①用）",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        type="password",
        help="欄①の自然言語解析に使用。未入力の場合は欄①は使えません。",
    )
    if anthropic_key:
        os.environ["ANTHROPIC_API_KEY"] = anthropic_key

# ─────────────────────────── メンバー読み込み ────────────────────────
with st.expander("📋 メンバー読み込み", expanded=not st.session_state.get("members")):
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
                    st.error(f"読み込みエラー: {exc}")
                    st.session_state["members"] = []

    if st.session_state.get("members"):
        st.dataframe(
            pd.DataFrame(st.session_state["members"]),
            use_container_width=True,
            hide_index=True,
        )

members: list = st.session_state.get("members", [])
if not members:
    st.info("⬅️ まずサイドバーで設定し、メンバーを読み込んでください。")
    st.stop()

st.divider()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 欄①  日程調整の指示（自然言語）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("欄① 日程調整の指示")
st.caption("誰と・何個・どの週以降・何分 など自然言語で入力すると、自動で検索します。")

instruction = st.text_area(
    label="指示を入力",
    placeholder=(
        "例: 田中さんと鈴木さんで来週以降に60分の打ち合わせ。候補を3つ出して。\n"
        "例: 山田さんと最速で30分MTGしたい。\n"
        "例: 再来週以降で全員参加の1時間会議、5候補ほど。"
    ),
    height=100,
    key="instruction",
    label_visibility="collapsed",
)

col_btn, col_info = st.columns([2, 5])
with col_btn:
    nlp_clicked = st.button(
        "🤖 AIで解析して候補を探す",
        type="primary",
        disabled=not (instruction.strip() and os.environ.get("ANTHROPIC_API_KEY")),
    )
with col_info:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.caption("※ Anthropic API キーをサイドバーで設定すると欄①が使えます。")

if nlp_clicked and instruction.strip():
    from nlp_parser import parse_instruction
    with st.spinner("AIが指示を解析中…"):
        try:
            parsed = parse_instruction(instruction, members, today)
            st.session_state["nlp_parsed"] = parsed
            st.success(
                f"解析完了 — 参加者: {', '.join(parsed['participants'])} ／ "
                f"{parsed['date_from']} 〜 {parsed['date_to']} ／ "
                f"{parsed['duration_min']}分 ／ {parsed['num_candidates']}候補"
            )

            # そのままカレンダー検索も実行
            selected_members = [m for m in members if m["name"] in parsed["participants"]]
            if not selected_members:
                st.warning("参加者が特定できませんでした。手動で選択してください。")
            else:
                slots, errs = run_calendar_search(
                    selected_members,
                    parsed["date_from"],
                    parsed["date_to"],
                    def_work_start,
                    def_work_end,
                    parsed["duration_min"],
                    include_weekends,
                    parsed["num_candidates"],
                    cred_path,
                )
                for e in errs:
                    st.warning(f"⚠️ カレンダー取得失敗 — {e}")
                st.session_state["search_results"] = slots
                st.session_state["selected_members"] = selected_members
                st.session_state["searched"] = True
        except Exception as exc:
            st.error(f"解析エラー: {exc}")

st.divider()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# （手動検索）欄①を使わない場合のフォールバック
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with st.expander("🔧 手動で参加者・期間を指定して検索する", expanded=False):
    name_opts = [m["name"] for m in members]
    manual_names = st.multiselect("参加者", options=name_opts, key="manual_names")

    mc1, mc2, mc3, mc4 = st.columns(4)
    m_date_from = mc1.date_input("開始日", value=def_date_from, key="m_df")
    m_date_to = mc2.date_input("終了日", value=def_date_to, key="m_dt")
    m_duration = mc3.selectbox(
        "会議時間",
        [30, 60, 90, 120],
        index=[30, 60, 90, 120].index(def_duration),
        format_func=lambda x: f"{x}分",
        key="m_dur",
    )
    m_num = mc4.number_input("候補数上限", min_value=1, max_value=20, value=int(def_num_cands), key="m_num")

    if st.button("🔍 空き時間を検索", disabled=not manual_names):
        selected_members = [m for m in members if m["name"] in manual_names]
        slots, errs = run_calendar_search(
            selected_members,
            m_date_from,
            m_date_to,
            def_work_start,
            def_work_end,
            m_duration,
            include_weekends,
            m_num,
            cred_path,
        )
        for e in errs:
            st.warning(f"⚠️ カレンダー取得失敗 — {e}")
        st.session_state["search_results"] = slots
        st.session_state["selected_members"] = selected_members
        st.session_state["searched"] = True

st.divider()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 欄②  候補日程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("欄② 候補日程")

if not st.session_state.get("searched"):
    st.info("欄①に指示を入力して「AIで解析して候補を探す」か、手動検索を実行してください。")
else:
    results: list = st.session_state.get("search_results", [])

    if not results:
        st.warning("条件に合う候補時間が見つかりませんでした。期間や会議時間を変更してお試しください。")
    else:
        total = len(results)
        ok = sum(1 for s in results if not s["block_people"])
        blk = total - ok

        m1, m2, m3 = st.columns(3)
        m1.metric("候補数", total)
        m2.metric("🟢 全員空き", ok)
        m3.metric("🟡 要確認あり", blk)

        st.caption("🟢 = 全員空き　🟡 = ブロック予定あり（要確認）")
        st.markdown("")

        # 日付ごとに表示
        by_date: dict = {}
        for s in results:
            by_date.setdefault(s["start"].date(), []).append(s)

        for date, day_slots in sorted(by_date.items()):
            wd = WD_JA[date.weekday()]
            st.markdown(f"**{date.year}年{date.month}月{date.day}日（{wd}）**")
            for slot in day_slots:
                t = f"{slot['start'].strftime('%H:%M')}〜{slot['end'].strftime('%H:%M')}"
                if slot["block_people"]:
                    note = "　".join(f"※{p}さんに確認必須" for p in slot["block_people"])
                    st.warning(f"🟡 {t}　　{note}")
                else:
                    st.success(f"🟢 {t}")

        st.markdown("")
        # クリップボードコピーボタン
        copy_text = format_copy_text(results, total)
        clipboard_copy_button(copy_text)

        # テキスト確認用（折りたたみ）
        with st.expander("コピーされるテキストを確認"):
            st.code(copy_text, language=None)

        # CSV ダウンロード
        rows = []
        for s in results:
            wd = WD_JA[s["start"].weekday()]
            rows.append(
                {
                    "日付": f"{s['start'].year}/{s['start'].month:02d}/{s['start'].day:02d}（{wd}）",
                    "開始": s["start"].strftime("%H:%M"),
                    "終了": s["end"].strftime("%H:%M"),
                    "状態": "要確認あり" if s["block_people"] else "全員空き",
                    "備考": " / ".join(f"※{p}さんに確認必須" for p in s["block_people"]),
                }
            )
        csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 CSVダウンロード",
            data=csv_bytes,
            file_name=f"schedule_{today}.csv",
            mime="text/csv",
        )

st.divider()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 欄④  会議タイトル（③の前に入力する）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("欄④ 会議タイトル")
meeting_title = st.text_input(
    "カレンダーに登録するイベントタイトル",
    placeholder="例: 〇〇プロジェクト キックオフMTG",
    key="meeting_title",
    label_visibility="collapsed",
)

st.divider()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 欄③  確定日程をペースト → カレンダー登録
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
st.subheader("欄③ カレンダーに登録")
st.caption(
    "欄②でコピーした候補から確定した日程を貼り付けてください。"
    "複数行貼り付けると複数イベントを一括登録します。"
)

pasted_text = st.text_area(
    "確定した日程を貼り付け",
    placeholder=(
        "例:\n"
        "3/12（水）10:00〜11:00\n"
        "または\n"
        "① 3/13（木）14:00〜15:00　※田中さんに確認必須"
    ),
    height=140,
    key="pasted_text",
    label_visibility="collapsed",
)

# 登録実行
reg_disabled = not (pasted_text.strip() and meeting_title.strip() and organizer_email.strip())
if st.button(
    "📆 Googleカレンダーに登録して通知を送る",
    type="primary",
    disabled=reg_disabled,
):
    if not os.path.exists(cred_path):
        st.error(f"認証ファイルが見つかりません: {cred_path}")
    else:
        parsed_slots = parse_slot_text(pasted_text)
        if not parsed_slots:
            st.error(
                "日程を解析できませんでした。"
                "「3/12（水）10:00〜11:00」などの形式で入力してください。"
            )
        else:
            # 参加者メールアドレスを取得
            sel_members = st.session_state.get("selected_members", [])
            attendee_emails = [m["email"] for m in sel_members]

            try:
                write_svc = get_write_service(cred_path, organizer_email)
            except Exception as exc:
                st.error(f"書き込みサービスの初期化失敗: {exc}")
                st.stop()

            ok_events = []
            fail_events = []
            for slot in parsed_slots:
                try:
                    ev = create_event(
                        write_svc,
                        title=meeting_title,
                        start=slot["start"],
                        end=slot["end"],
                        attendee_emails=attendee_emails,
                    )
                    ok_events.append(ev)
                except Exception as exc:
                    fail_events.append(
                        f"{slot['start'].strftime('%m/%d %H:%M')}〜"
                        f"{slot['end'].strftime('%H:%M')}: {exc}"
                    )

            if ok_events:
                st.success(f"✅ {len(ok_events)} 件のイベントを登録しました。参加者に通知メールを送信しました。")
                for ev in ok_events:
                    link = ev.get("htmlLink", "")
                    summary = ev.get("summary", "")
                    start_str = ev.get("start", {}).get("dateTime", "")
                    st.markdown(f"- **{summary}** — [{start_str[:16]}]({link})")
            for f in fail_events:
                st.error(f"登録失敗: {f}")

elif reg_disabled and pasted_text.strip():
    if not meeting_title.strip():
        st.caption("⬆️ 欄④に会議タイトルを入力してください。")
    if not organizer_email.strip():
        st.caption("⬆️ サイドバーで主催者メールアドレスを入力してください。")
