"""蓄電池設定の予約管理（標準ライブラリのみ）。

予約は docs/reservations/<id>.json に1件1ファイルで保存する（同時に追加しても衝突しないため）。

使い方（環境変数で値を渡す）:
  python reservation.py add     RES_MODE / RES_START_HOUR / RES_START_MINUTE / RES_END_HOUR / RES_END_MINUTE / RES_RUN_AT
  python reservation.py cancel  RES_ID
  python reservation.py due     実行予定時刻を過ぎた最も古い予約を1件選び、GITHUB_OUTPUT に出力する
  python reservation.py finish  RES_ID / RES_RESULT(success|failure)

status: pending(予約中) / running(実行中) / done(完了) / failed(失敗) / canceled(取消) / expired(失効)
"""
import json
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
RES_DIR = Path(os.environ.get("RES_DIR", "docs/reservations"))

GRACE_MIN = 120        # 実行予定時刻からこの分数を過ぎた予約は実行せず「失効」にする
MAX_AHEAD_DAYS = 3     # これより先の予約は受け付けない
KEEP_DAYS = 7          # 終了した予約ファイルを残す日数

MODES = {"green": "グリーンモード", "economy": "経済モード"}
FINISHED = {"done", "failed", "canceled", "expired"}
ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")


def now():
    return datetime.now(JST)


def env(name):
    return (os.environ.get(name) or "").strip()


def fmt(dt):
    return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M")


def parse_run_at(text):
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"実行日時の形式が不正です: {text!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def validate_times(mode, sh, sm, eh, em):
    """時刻を検証して2桁に揃えて返す。グリーンモードで全て空なら空のまま（実行時に月で自動決定）。"""
    vals = [sh, sm, eh, em]
    if not any(vals):
        if mode == "economy":
            raise ValueError("経済モードでは充電開始・終了の時と分をすべて指定してください。")
        return "", "", "", ""
    if not all(vals):
        raise ValueError("充電開始・終了の時と分は、すべて指定するか、すべて空にしてください。")
    sh, sm, eh, em = (v.zfill(2) for v in vals)
    for name, v, hi in (("充電開始の時", sh, 23), ("充電開始の分", sm, 59),
                        ("充電終了の時", eh, 23), ("充電終了の分", em, 59)):
        if not v.isdigit() or not (0 <= int(v) <= hi):
            raise ValueError(f"{name} の値が不正です: {v!r}")
    if (int(sh), int(sm)) >= (int(eh), int(em)):
        raise ValueError(f"充電終了時刻は開始時刻より後にしてください: {sh}:{sm} - {eh}:{em}")
    return sh, sm, eh, em


def path_of(rid):
    if not ID_RE.match(rid or ""):
        raise ValueError(f"予約IDが不正です: {rid!r}")
    return RES_DIR / f"{rid}.json"


def load(rid):
    p = path_of(rid)
    if not p.exists():
        raise ValueError(f"予約が見つかりません: {rid}")
    return json.loads(p.read_text(encoding="utf-8"))


def save(rec):
    RES_DIR.mkdir(parents=True, exist_ok=True)
    path_of(rec["id"]).write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_all():
    items = []
    for p in sorted(RES_DIR.glob("*.json")):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            print(f"読み込めない予約ファイルをスキップ: {p}")
    return items


def purge_old():
    """終了してから KEEP_DAYS 日を過ぎた予約ファイルを削除する。"""
    limit = now() - timedelta(days=KEEP_DAYS)
    for rec in load_all():
        if rec.get("status") in FINISHED:
            try:
                if parse_run_at(rec["run_at"]) < limit:
                    path_of(rec["id"]).unlink()
                    print(f"古い予約を削除: {rec['id']}")
            except Exception as e:  # noqa: BLE001
                print(f"削除スキップ({rec.get('id')}): {e}")


def set_output(**kw):
    line = "".join(f"{k}={v}\n" for k, v in kw.items())
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    print(line, end="")


# ---------- コマンド ----------

def cmd_add():
    mode = env("RES_MODE").lower()
    if mode not in MODES:
        raise ValueError(f"RES_MODE は green または economy を指定してください: {mode!r}")
    sh, sm, eh, em = validate_times(mode, env("RES_START_HOUR"), env("RES_START_MINUTE"),
                                    env("RES_END_HOUR"), env("RES_END_MINUTE"))
    run_at = parse_run_at(env("RES_RUN_AT"))
    n = now()
    if run_at < n - timedelta(minutes=1):
        raise ValueError(f"実行日時が過去です: {fmt(run_at)}（現在 {fmt(n)}）")
    if run_at > n + timedelta(days=MAX_AHEAD_DAYS):
        raise ValueError(f"実行日時は {MAX_AHEAD_DAYS} 日以内で指定してください: {fmt(run_at)}")

    rid = f"{run_at:%Y%m%d-%H%M}-{mode}-{secrets.token_hex(2)}"
    rec = {
        "id": rid, "status": "pending", "mode": mode,
        "start_hour": sh, "start_minute": sm, "end_hour": eh, "end_minute": em,
        "run_at": run_at.isoformat(timespec="minutes"),
        "created": n.isoformat(timespec="seconds"),
    }
    save(rec)
    purge_old()
    print(f"予約を追加しました: {rid} / {MODES[mode]} / 実行予定 {fmt(run_at)}")


def cmd_cancel():
    rec = load(env("RES_ID"))
    if rec.get("status") != "pending":
        raise ValueError(f"取り消せません（現在の状態: {rec.get('status')}）: {rec['id']}")
    rec["status"] = "canceled"
    rec["finished_at"] = now().isoformat(timespec="seconds")
    save(rec)
    print(f"予約を取り消しました: {rec['id']}")


def cmd_due():
    n = now()
    pending = sorted((r for r in load_all() if r.get("status") == "pending"), key=lambda r: r["run_at"])
    expired, picked = [], None
    for rec in pending:
        run_at = parse_run_at(rec["run_at"])
        if run_at > n:
            continue
        if n - run_at > timedelta(minutes=GRACE_MIN):
            rec["status"] = "expired"
            rec["finished_at"] = n.isoformat(timespec="seconds")
            rec["message"] = f"実行予定から{GRACE_MIN}分以上経過していたため実行しませんでした"
            save(rec)
            expired.append(rec)
            continue
        if picked is None:
            picked = rec          # 実行するのは1回につき1件（残りは次回の確認で実行）

    if expired:
        lines = [f"実行予定時刻から{GRACE_MIN}分以上過ぎていたため、次の予約は実行しませんでした。", ""]
        lines += [f"- {fmt(parse_run_at(r['run_at']))} {MODES[r['mode']]}" for r in expired]
        Path("expired_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    set_output(expired="true" if expired else "false")

    if picked is None:
        set_output(found="false")
        print("実行する予約はありません。")
        purge_old()
        return
    picked["status"] = "running"
    picked["started_at"] = n.isoformat(timespec="seconds")
    save(picked)
    set_output(found="true", id=picked["id"], mode=picked["mode"],
               start_hour=picked["start_hour"], start_minute=picked["start_minute"],
               end_hour=picked["end_hour"], end_minute=picked["end_minute"],
               run_at=fmt(parse_run_at(picked["run_at"])))
    purge_old()


def cmd_finish():
    rec = load(env("RES_ID"))
    ok = env("RES_RESULT") == "success"
    rec["status"] = "done" if ok else "failed"
    rec["finished_at"] = now().isoformat(timespec="seconds")
    if not ok:
        rec["message"] = "蓄電池の設定に失敗しました（Actionsのログを確認してください）"
    save(rec)
    print(f"予約を{'完了' if ok else '失敗'}として記録しました: {rec['id']}")


COMMANDS = {"add": cmd_add, "cancel": cmd_cancel, "due": cmd_due, "finish": cmd_finish}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in COMMANDS:
        print(f"使い方: python reservation.py [{'|'.join(COMMANDS)}]", file=sys.stderr)
        sys.exit(2)
    try:
        COMMANDS[cmd]()
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
