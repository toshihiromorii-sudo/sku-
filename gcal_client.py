"""
Google Calendar API クライアント

必要な準備:
  1. Google Cloud Console でサービスアカウントを作成し JSON キーをダウンロード
  2. Google Workspace 管理コンソールで「ドメイン全体の委任」を有効化
     スコープ: https://www.googleapis.com/auth/calendar.readonly
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
