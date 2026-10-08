"""JEPXスポット市場の中部エリアプライス(30分コマ)を取得し、docs/jepx_chubu.json に保存する。

- 取得元: https://www.jepx.jp/market/excel/spot_{西暦}.csv （暦年ごとのCSV）
  直接URLで取得できない場合は、JEPXのページからCSVリンクを探索する（JEPX-mainと同じ方針）
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
from urllib.parse import urljoin

JST = timezone(timedelta(hours=9))
OUT_PATH = os.environ.get("JEPX_OUT", "docs/jepx_chubu.json")
CSV_URL = "https://www.jepx.jp/market/excel/spot_{year}.csv"
DATA_PAGES = [
    "https://www.jepx.jp/electricpower/market-data/spot/",
    "https://www.jepx.jp/",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.8",
}


def http_get(url, timeout=30, retries=3):
    """GET（失敗時は数回リトライ）。bytesを返し、全滅なら最後の例外を送出する"""
    last_exc = None
    for i in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read()
        except Exception as e:  # noqa: BLE001
            last_exc = e
            print(f"  取得失敗({i}/{retries}) {url}: {e}")
    raise last_exc


def decode(raw):
    for enc in ("cp932", "utf-8-sig"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse(text):
    """CSV全体から {日付(YYYY-MM-DD): {コマ番号(1-48): 価格}} を返す。"""
    rows = list(csv.reader(io.StringIO(text)))
    header_idx = next((i for i, r in enumerate(rows) if any("年月日" in c for c in r)), None)
    if header_idx is None:
        raise ValueError("ヘッダー行(年月日)が見つかりません（スポットCSVではない可能性）")
    header = [c.strip() for c in rows[header_idx]]

    # 列名の判定はJEPX-mainと同じ基準（表記揺れ対応）
    i_date = next((i for i, c in enumerate(header) if "年月日" in c), None)
    i_slot = next((i for i, c in enumerate(header) if "時刻" in c or "コマ" in c), None)
    i_price = next((i for i, c in enumerate(header)
                    if "中部" in c and ("エリア" in c or "円" in c or "プライス" in c)), None)
    if None in (i_date, i_slot, i_price):
        raise ValueError(f"必要な列が見つかりません (日付列: {i_date}, 時間列: {i_slot}, 価格列: {i_price}) 列: {header}")

    data = {}
    for r in rows[header_idx + 1:]:
        if len(r) <= max(i_date, i_slot, i_price):
            continue
        m = re.match(r"^\s*(\d{4})\D+(\d{1,2})\D+(\d{1,2})", r[i_date])
        if not m:
            continue
        date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        try:
            slot = int(float(r[i_slot].replace(",", "")))
            price = float(r[i_price].replace(",", ""))
        except ValueError:
            continue  # 価格が空欄(未確定)のコマは除外
        if 1 <= slot <= 48:
            data.setdefault(date, {})[slot] = price
    return data


def load_csv(url):
    """CSVを取得して解析。妥当なスポットCSVでなければ None"""
    try:
        parsed = parse(decode(http_get(url)))
    except Exception as e:  # noqa: BLE001
        print(f"  CSV取得/解析エラー ({url}): {e}")
        return None
    print(f"CSVの取得・解析に成功しました: {url} ({len(parsed)}日分)")
    return parsed


def discover_csv_links():
    """JEPXのページからスポットCSVのリンクを探す(直接URLが外れた場合の保険)"""
    found = []
    for page in DATA_PAGES:
        try:
            html = decode(http_get(page, timeout=20, retries=2))
        except Exception as e:  # noqa: BLE001
            print(f"  ページ取得エラー {page}: {e}")
            continue
        for href in re.findall(r"""href=["']([^"']+)["']""", html):
            url = urljoin(page, href)
            low = url.lower()
            if ".csv" in low and "spot" in low and url not in found:
                found.append(url)
    return found


def get_year_data(year):
    """指定した西暦のスポットCSVを解析して返す。取得できなければ None"""
    url = CSV_URL.format(year=year)
    print(f"CSV取得試行: {url}")
    parsed = load_csv(url)
    if parsed is not None:
        return parsed
    print("直接URLで取得できなかったため、ページからCSVリンクを探索します。")
    for link in discover_csv_links():
        if str(year) not in link:
            continue
        print(f"CSV取得試行(探索): {link}")
        parsed = load_csv(link)
        if parsed is not None:
            return parsed
    return None


def load_existing():
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f).get("days", {})
    except (OSError, ValueError):
        return {}


def main(now=None):
    now = now or datetime.now(JST)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    targets = [today.isoformat(), tomorrow.isoformat()]

    # 12/31実行時は翌年のCSVも必要
    years = sorted({today.year, tomorrow.year})
    parsed = {}
    failed = []
    for y in years:
        data = get_year_data(y)
        if data is None:
            failed.append(y)
            continue
        for date, slots in data.items():
            parsed.setdefault(date, {}).update(slots)

    if not parsed:
        print(f"JEPXデータを取得できませんでした（対象年: {years}）。サイト構成変更・アクセス拒否・一時障害の可能性があります。",
              file=sys.stderr)
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

    if load_existing() == days:
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
