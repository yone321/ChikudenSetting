"""JEPXスポット市場の中部エリアプライス(30分コマ)を取得し、docs/jepx_chubu.json に保存する。

- 取得元: https://www.jepx.jp/market/excel/spot_{年度}.csv (Shift_JIS)
- 保存対象: 日本時間の「今日」「明日」のうち、48コマ揃っている日のみ
- 標準ライブラリのみ使用
"""
import csv
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
OUT_PATH = os.environ.get("JEPX_OUT", "docs/jepx_chubu.json")
URL = "https://www.jepx.jp/market/excel/spot_{year}.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; chikuden-jepx-fetch/1.0)"}


def fiscal_year(d):
    return d.year if d.month >= 4 else d.year - 1


def decode(raw):
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSVの文字コードを判別できません")


def download(year):
    req = urllib.request.Request(URL.format(year=year), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as res:
        return decode(res.read())


def parse(text):
    """CSV全体から {日付(YYYY-MM-DD): {コマ番号(1-48): 価格}} を返す。"""
    rows = list(csv.reader(io.StringIO(text)))
    header_idx = next((i for i, r in enumerate(rows) if any("年月日" in c for c in r)), None)
    if header_idx is None:
        raise ValueError("ヘッダー行(年月日)が見つかりません")
    header = [c.strip() for c in rows[header_idx]]

    def find(*keywords):
        for i, c in enumerate(header):
            if all(k in c for k in keywords):
                return i
        return None

    i_date = find("年月日")
    i_slot = find("時刻コード")
    i_price = find("エリアプライス", "中部")
    if i_price is None:
        i_price = find("中部")
    if None in (i_date, i_slot, i_price):
        raise ValueError(f"必要な列が見つかりません: {header}")

    data = {}
    for r in rows[header_idx + 1:]:
        if len(r) <= max(i_date, i_slot, i_price):
            continue
        m = re.match(r"^\s*(\d{4})\D+(\d{1,2})\D+(\d{1,2})", r[i_date])
        if not m:
            continue
        date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        try:
            slot = int(r[i_slot])
            price = float(r[i_price])
        except ValueError:
            continue  # 価格が空欄(未確定)のコマは除外
        if 1 <= slot <= 48:
            data.setdefault(date, {})[slot] = price
    return data


def load_existing():
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f).get("days", {})
    except (OSError, ValueError):
        return {}


def main():
    now = datetime.now(JST)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    targets = [today.isoformat(), tomorrow.isoformat()]

    # 年度をまたぐ場合に備え、必要な年度のCSVをすべて取得
    years = sorted({fiscal_year(today), fiscal_year(tomorrow)})
    parsed = {}
    errors = []
    for y in years:
        try:
            text = download(y)
        except Exception as e:  # noqa: BLE001
            errors.append(f"spot_{y}.csv: {e}")
            continue
        try:
            for date, slots in parse(text).items():
                parsed.setdefault(date, {}).update(slots)
        except Exception as e:  # noqa: BLE001
            errors.append(f"spot_{y}.csv の解析に失敗: {e}")

    if not parsed:
        print("JEPXデータを取得できませんでした:\n" + "\n".join(errors), file=sys.stderr)
        sys.exit(1)

    days = {d: v for d, v in load_existing().items() if d >= targets[0]}
    for d in targets:
        slots = parsed.get(d, {})
        if len(slots) == 48:
            days[d] = [slots[i] for i in range(1, 49)]
        else:
            print(f"{d}: 48コマ揃っていません({len(slots)}コマ)。未公表として扱います。")

    if not days:
        print("今日・明日のデータがありません。", file=sys.stderr)
        sys.exit(1)

    old = load_existing()
    if old == days:
        print("データに変更なし。")
        return

    out = {
        "area": "中部",
        "unit": "円/kWh",
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "days": dict(sorted(days.items())),
    }
    os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"保存しました: {OUT_PATH} ({', '.join(days)})")


if __name__ == "__main__":
    main()
