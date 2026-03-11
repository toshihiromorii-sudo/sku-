"""
自然言語の日程調整指示を Claude API で解析するモジュール。

環境変数 ANTHROPIC_API_KEY が必要。
設定されていない場合は ValueError を送出する。
"""

import datetime
import json
import os
import re

import anthropic

WD_JA = ["月", "火", "水", "木", "金", "土", "日"]


def parse_instruction(
    text: str,
    members: list,
    today: datetime.date,
) -> dict:
    """
    自然言語の指示を解析してスケジュール検索パラメータを返す。

    Args:
        text    : ユーザーが入力した自然言語テキスト
        members : [{"name": str, "email": str}, ...] のメンバー一覧
        today   : 基準日

    Returns:
        {
          "participants" : ["名前1", "名前2"],
          "num_candidates": int,
          "date_from"    : datetime.date,
          "date_to"      : datetime.date,
          "duration_min" : int,
        }

    Raises:
        ValueError: ANTHROPIC_API_KEY が未設定 or JSON 解析失敗
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY が設定されていません。"
            "サイドバーまたは環境変数で設定してください。"
        )

    client = anthropic.Anthropic(api_key=api_key)

    # 来週・再来週の月曜日を計算
    wd = today.weekday()  # 0=月
    next_mon = today + datetime.timedelta(days=(7 - wd) % 7 or 7)
    week_after_mon = next_mon + datetime.timedelta(days=7)

    member_names = [m["name"] for m in members]
    today_str = f"{today.year}年{today.month}月{today.day}日（{WD_JA[wd]}）"

    prompt = f"""今日: {today_str}
来週月曜日: {next_mon.strftime('%Y-%m-%d')}
再来週月曜日: {week_after_mon.strftime('%Y-%m-%d')}

メンバー一覧:
{chr(10).join(f'- {n}' for n in member_names)}

以下の指示を解析し、日程調整パラメータを JSON のみで返してください。

指示: 「{text}」

JSON スキーマ（キーはすべて必須）:
{{
  "participants": ["名前"],      // メンバー一覧から一致する名前を選ぶ
  "num_candidates": 3,           // 候補数（明示なければ 3）
  "date_from": "YYYY-MM-DD",     // 検索開始日
  "date_to": "YYYY-MM-DD",       // 検索終了日（最低 5 営業日分）
  "duration_min": 60             // 会議時間（分）。明示なければ 60
}}

変換ルール:
- 「最速」「できるだけ早く」→ date_from = 明日 ({today + datetime.timedelta(days=1)})
- 「今週中」→ date_from = 明日、date_to = 今週金曜日
- 「来週以降」「来週から」→ date_from = 来週月曜日、date_to = 来週金曜日
- 「再来週」→ date_from = 再来週月曜日、date_to = 再来週金曜日
- 「今月中」→ date_from = 明日、date_to = 今月末
- 「〇月〇日以降」→ その日から 2 週間分
- 候補数が「何個でも」「たくさん」→ 5
- participants に一致しない名前は含めない
JSON のみ出力すること。"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # コードブロックや余分なテキストを除去
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        raise ValueError(f"JSON を抽出できませんでした。レスポンス: {raw}")

    result = json.loads(json_match.group())

    # date 文字列 → datetime.date に変換
    result["date_from"] = datetime.date.fromisoformat(result["date_from"])
    result["date_to"] = datetime.date.fromisoformat(result["date_to"])

    # 不明な参加者名を除外
    result["participants"] = [
        p for p in result.get("participants", []) if p in member_names
    ]

    return result
