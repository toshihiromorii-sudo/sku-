"""
Google Calendar API クライアント

必要な準備:
  1. Google Cloud Console でサービスアカウントを作成し JSON キーをダウンロード
  2. Google Workspace 管理コンソールで「ドメイン全体の委任」を有効化
     読み取り: https://www.googleapis.com/auth/calendar.readonly
     書き込み: https://www.googleapis.com/auth/calendar
  3. このファイルをプロジェクトルートに置き、認証 JSON パスを指定する
"""

import re
import datetime
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

JST = ZoneInfo("Asia/Tokyo")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
_BLOCK_RE = re.compile(r"ブロック|[Bb]lock")


def get_service(credentials_path: str, impersonate_email: str):
    """
    ユーザーを偽装（impersonate）して Calendar サービスを返す。
    サービスアカウントにドメイン全体の委任が必要。
    """
    creds = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=SCOPES,
    ).with_subject(impersonate_email)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def fetch_events(service, date_from: datetime.date, date_to: datetime.date) -> list:
    """指定期間のイベントをページネーションしながら全件取得する。"""
    time_min = datetime.datetime(
        date_from.year, date_from.month, date_from.day, 0, 0, 0, tzinfo=JST
    ).isoformat()
    time_max = datetime.datetime(
        date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=JST
    ).isoformat()

    all_events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        ).execute()
        all_events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return all_events


def parse_events(raw_events: list) -> list:
    """
    Google Calendar API の生イベントを内部形式に変換する。

    返す辞書のキー:
      summary   (str)  : 予定タイトル
      start     (datetime, JST aware)
      end       (datetime, JST aware)
      is_all_day (bool): 終日予定かどうか
      is_block  (bool) : タイトルに「ブロック」「Block」を含むかどうか
    """
    parsed = []
    for ev in raw_events:
        # キャンセル済みは除外
        if ev.get("status") == "cancelled":
            continue

        summary = ev.get("summary", "")
        is_block = bool(_BLOCK_RE.search(summary))

        # フリー（透明）イベントはブロック以外スキップ
        if ev.get("transparency") == "transparent" and not is_block:
            continue

        start_raw = ev.get("start", {})
        end_raw = ev.get("end", {})
        is_all_day = "dateTime" not in start_raw

        if is_all_day:
            start_dt = datetime.datetime.fromisoformat(
                start_raw.get("date", "1970-01-01")
            ).replace(tzinfo=JST)
            end_dt = datetime.datetime.fromisoformat(
                end_raw.get("date", "1970-01-01")
            ).replace(tzinfo=JST)
        else:
            start_dt = datetime.datetime.fromisoformat(
                start_raw["dateTime"]
            ).astimezone(JST)
            end_dt = datetime.datetime.fromisoformat(
                end_raw["dateTime"]
            ).astimezone(JST)

        parsed.append(
            {
                "summary": summary,
                "start": start_dt,
                "end": end_dt,
                "is_all_day": is_all_day,
                "is_block": is_block,
            }
        )
    return parsed


# ── 書き込み用（イベント作成） ──────────────────────────────────────

WRITE_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_write_service(credentials_path: str, organizer_email: str):
    """
    イベント作成・更新用の Calendar サービスを返す。
    主催者のメールアドレスを impersonate する。
    """
    creds = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=WRITE_SCOPES,
    ).with_subject(organizer_email)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def create_event(
    service,
    title: str,
    start: datetime.datetime,
    end: datetime.datetime,
    attendee_emails: list,
    description: str = "",
) -> dict:
    """
    カレンダーにイベントを作成し、参加者全員に通知メールを送る。

    Args:
        service          : get_write_service() で取得したサービス
        title            : イベントタイトル
        start / end      : 開始・終了日時（JST aware datetime）
        attendee_emails  : 参加者のメールアドレスリスト
        description      : イベント本文（任意）

    Returns:
        作成されたイベントの dict（htmlLink キーに URL が入る）
    """
    body = {
        "summary": title,
        "description": description,
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": "Asia/Tokyo",
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": "Asia/Tokyo",
        },
        "attendees": [{"email": e} for e in attendee_emails],
        "reminders": {"useDefault": True},
    }
    return (
        service.events()
        .insert(calendarId="primary", body=body, sendUpdates="all")
        .execute()
    )


def parse_slot_text(text: str) -> list:
    """
    貼り付けられたテキストから日程スロットを解析する。

    対応フォーマット:
      3/12（水）10:00〜11:00
      3月12日（水）10:00 ～ 11:00
      2026/3/12 10:00-11:00

    Returns:
        [{"start": datetime (JST), "end": datetime (JST)}, ...]
    """
    today = datetime.date.today()
    pattern = re.compile(
        r"(?:(\d{4})[/年])?"          # 年（省略可）
        r"(\d{1,2})[/月]"              # 月
        r"(\d{1,2})日?"                # 日
        r"(?:[（(][^\)）]*[）)])?"      # 曜日（省略可）
        r"\s*"
        r"(\d{1,2}):(\d{2})"           # 開始時刻
        r"\s*[〜～~\-ー－]+\s*"         # 区切り
        r"(\d{1,2}):(\d{2})"           # 終了時刻
    )
    results = []
    for line in text.strip().split("\n"):
        m = pattern.search(line.strip())
        if not m:
            continue
        year = int(m.group(1)) if m.group(1) else today.year
        month, day = int(m.group(2)), int(m.group(3))
        sh, sm = int(m.group(4)), int(m.group(5))
        eh, em = int(m.group(6)), int(m.group(7))
        try:
            date = datetime.date(year, month, day)
            # 年未指定かつ過去日なら翌年とみなす
            if not m.group(1) and date < today:
                date = datetime.date(today.year + 1, month, day)
        except ValueError:
            continue
        results.append(
            {
                "start": datetime.datetime(
                    date.year, date.month, date.day, sh, sm, tzinfo=JST
                ),
                "end": datetime.datetime(
                    date.year, date.month, date.day, eh, em, tzinfo=JST
                ),
            }
        )
    return results
