"""
Google Sheets API クライアント

スプレッドシートの想定フォーマット（ヘッダー行は任意）:
  A列 : 名前
  B列 : メールアドレス

例:
  | 名前   | メールアドレス         |
  |--------|------------------------|
  | 山田太郎 | yamada@example.com   |
  | 鈴木花子 | suzuki@example.com   |
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# ヘッダー行とみなすキーワード（小文字比較）
_HEADER_KEYWORDS = {"名前", "name", "氏名", "email", "メール", "メールアドレス"}


def get_service(credentials_path: str):
    """Google Sheets サービスを返す（サービスアカウント認証）。"""
    creds = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def fetch_members(
    service, spreadsheet_id: str, range_name: str = "Sheet1!A:B"
) -> list:
    """
    スプレッドシートからメンバー一覧を取得する。

    Returns:
        [{"name": str, "email": str}, ...]
    """
    resp = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )
    rows = resp.get("values", [])
    if not rows:
        return []

    # 1 行目がヘッダーかどうか判定
    first_cells = [c.strip().lower() for c in rows[0]]
    is_header = any(kw in cell for kw in _HEADER_KEYWORDS for cell in first_cells)
    data_rows = rows[1:] if is_header else rows

    members = []
    for row in data_rows:
        if len(row) >= 2:
            name = row[0].strip()
            email = row[1].strip()
            if name and "@" in email:
                members.append({"name": name, "email": email})
    return members
