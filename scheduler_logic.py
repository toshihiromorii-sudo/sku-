"""
日程調整ロジック

候補スロットのルール:
  - 誰も通常の予定（ブロック以外）が入っていない → 🟢 全員空き
  - 通常の予定は入っていないが、誰かに「ブロック」「Block」の予定がある
      → 🟡 候補にはなるが「※〇〇さんに確認必須」と表示
  - 誰かに通常の予定が入っている → 候補から除外
"""

import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def find_candidate_slots(
    people_events: dict,
    date: datetime.date,
    work_start: datetime.time,
    work_end: datetime.time,
    duration_min: int,
    interval_min: int = 30,
) -> list:
    """
    1 日分の候補スロットを返す。

    Args:
        people_events : {人名: [parse_events()で変換済みイベントのリスト]}
        date          : 対象日
        work_start    : 勤務開始時刻
        work_end      : 勤務終了時刻
        duration_min  : 会議時間（分）
        interval_min  : スロットの刻み幅（分）、デフォルト 30 分

    Returns:
        候補スロットのリスト。各要素は辞書:
          {
            "start"       : datetime (JST),
            "end"         : datetime (JST),
            "available"   : bool  (ブロックなし全員空き=True),
            "block_people": list  (ブロック予定を持つ人名リスト),
          }
    """
    slots = []
    slot_start = datetime.datetime.combine(date, work_start, tzinfo=JST)
    day_end = datetime.datetime.combine(date, work_end, tzinfo=JST)

    while True:
        slot_end = slot_start + datetime.timedelta(minutes=duration_min)
        if slot_end > day_end:
            break

        busy_people = []   # 通常予定が被っている人
        block_people = []  # ブロック予定が被っている人

        for person, events in people_events.items():
            for ev in events:
                ev_start = ev["start"]
                ev_end = ev["end"]

                # 終日イベントはその日の 00:00〜翌 00:00 に展開
                if ev.get("is_all_day"):
                    ev_start = datetime.datetime.combine(
                        ev_start.date(), datetime.time.min, tzinfo=JST
                    )
                    ev_end = datetime.datetime.combine(
                        ev_end.date(), datetime.time.min, tzinfo=JST
                    )

                # 重複判定: ev_start < slot_end かつ ev_end > slot_start
                if ev_start < slot_end and ev_end > slot_start:
                    if ev["is_block"]:
                        if person not in block_people:
                            block_people.append(person)
                    else:
                        if person not in busy_people:
                            busy_people.append(person)

        # 通常予定が誰も被っていなければ候補として追加
        if not busy_people:
            slots.append(
                {
                    "start": slot_start,
                    "end": slot_end,
                    "available": len(block_people) == 0,
                    "block_people": block_people,
                }
            )

        slot_start += datetime.timedelta(minutes=interval_min)

    return slots
