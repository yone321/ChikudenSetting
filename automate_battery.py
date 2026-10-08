import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))

MODE_LABELS = {
    "green": "グリーンモード",
    "economy": "経済モード",
}


def get_green_default_times():
    """グリーンモードの充電開始/終了時刻（太陽光の想定発電時間帯）を月で決める。
    4〜9月: 06:00〜16:00 / 10〜3月: 06:30〜15:30
    """
    month = datetime.now(JST).month
    if 4 <= month <= 9:
        return ("06", "00", "16", "00")
    return ("06", "30", "15", "30")


def get_settings():
    """環境変数(GitHub Actionsのinputs)から設定内容を取得して検証する。"""
    mode = (os.environ.get("MODE") or "economy").strip().lower()
    if mode not in MODE_LABELS:
        raise ValueError(f"MODE は green または economy を指定してください: {mode!r}")

    sh = (os.environ.get("START_HOUR") or "").strip()
    sm = (os.environ.get("START_MINUTE") or "").strip()
    eh = (os.environ.get("END_HOUR") or "").strip()
    em = (os.environ.get("END_MINUTE") or "").strip()

    if mode == "green" and not (sh and sm and eh and em):
        # 時刻の指定がなければ月ごとの発電時間帯を自動設定
        sh, sm, eh, em = get_green_default_times()
    elif mode == "economy" and not (sh and sm and eh and em):
        raise ValueError("経済モードでは充電開始・終了の時と分をすべて指定してください。")

    # 2桁ゼロ埋めに揃えて検証
    sh, sm, eh, em = (v.zfill(2) for v in (sh, sm, eh, em))
    for name, v, hi in (("充電開始の時", sh, 23), ("充電開始の分", sm, 59),
                        ("充電終了の時", eh, 23), ("充電終了の分", em, 59)):
        if not v.isdigit() or not (0 <= int(v) <= hi):
            raise ValueError(f"{name} の値が不正です: {v!r}")

    if (int(sh), int(sm)) >= (int(eh), int(em)):
        raise ValueError(f"充電終了時刻は開始時刻より後にしてください: {sh}:{sm} - {eh}:{em}")

    return mode, sh, sm, eh, em


def set_time_row(page, row_label, hour, minute):
    """「充電開始時刻」「充電終了時刻」行の時・分セレクトを設定する。"""
    try:
        row = page.locator("tr").filter(has_text=row_label)
        row.locator("select").nth(0).select_option(label=hour, timeout=2000)
    except Exception:
        # 行(tr)が見つからない場合は、ラベルとselectを含む一番内側の枠を特定する
        row = page.locator("div").filter(has_text=row_label).filter(has=page.locator("select")).last
    row.locator("select").nth(0).select_option(label=hour)
    row.locator("select").nth(1).select_option(label=minute)


def run_automation():
    user_id = os.environ.get("KP_USER")
    password = os.environ.get("KP_PASS")

    mode, sh, sm, eh, em = get_settings()
    mode_label = MODE_LABELS[mode]
    print(f"設定内容: {mode_label} / 充電 {sh}:{sm} - {eh}:{em}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # ログインページへアクセス
            page.goto("https://ctrl.kp-net.com/settingcontrol/login")

            page.locator("input[type='text']").fill(user_id)
            page.locator("input[type='password']").fill(password)
            page.locator("input[type='password']").press("Enter")
            page.wait_for_timeout(2000)

            # まだログインページに留まっている場合は、ボタンを明示的に探してクリック
            if "login" in page.url:
                try:
                    page.locator("a, button, input[type='submit'], input[type='button'], input[type='image']").filter(has_text="ログイン").first.click(timeout=3000)
                except:
                    try:
                        page.locator("input[value*='ログイン']").first.click(timeout=3000)
                    except:
                        page.get_by_text("ログイン", exact=True).first.click(timeout=3000)

            page.wait_for_timeout(5000)

            # １．「機器の管理」をクリック
            try:
                page.locator("a, button").filter(has_text="機器の管理").first.click(timeout=5000)
            except:
                page.get_by_text("機器の管理", exact=True).first.click()
            page.wait_for_timeout(3000)

            # ２．「マルチ蓄電」の「選択」をクリック
            try:
                page.locator("tr").filter(has_text="マルチ蓄電").get_by_text("選択", exact=False).first.click(timeout=3000)
            except:
                # マルチ蓄電と選択ボタンの両方を含む一番内側の枠を特定する
                target_div = page.locator("div").filter(has_text="マルチ蓄電").filter(has_text="選択").last
                target_div.get_by_text("選択", exact=False).first.click()
            page.wait_for_timeout(3000)

            # ３．「蓄電池設定」をクリック
            try:
                page.locator("a, button").filter(has_text="蓄電池設定").first.click(timeout=5000)
            except:
                page.get_by_text("蓄電池設定", exact=True).first.click()
            page.wait_for_timeout(2000)

            # ４．「現在値の取得」をクリック
            try:
                page.locator("a, button").filter(has_text="現在値の取得").first.click(timeout=5000)
            except:
                page.get_by_text("現在値の取得", exact=True).first.click()

            # 処理中表示が消えるのを待つ
            loading = page.get_by_text("処理中", exact=False)
            if loading.count() > 0 and loading.first.is_visible():
                loading.first.wait_for(state="hidden", timeout=60000)
            page.wait_for_timeout(1000)

            # ５．蓄電動作モード行の「候補値の取得」をクリック
            try:
                mode_row = page.locator("tr").filter(has_text="蓄電動作モード")
                mode_row.get_by_text("候補値の取得", exact=False).first.click(timeout=3000)
            except:
                # 蓄電動作モードと候補値の取得の両方を含む一番内側の枠を特定する
                mode_row = page.locator("div").filter(has_text="蓄電動作モード").filter(has_text="候補値の取得").last
                mode_row.get_by_text("候補値の取得", exact=False).first.click()

            # ６．処理中表示が消えるのを待って、選択されたモードを設定
            if loading.count() > 0 and loading.first.is_visible():
                loading.first.wait_for(state="hidden", timeout=60000)
            page.wait_for_timeout(1000)

            try:
                # エラーログから判明した一意のIDを直接狙い撃ち
                page.locator("#batteryOperatingMode").select_option(label=mode_label, timeout=3000)
            except:
                # 万が一IDが見つからない場合の予備ルート
                mode_row = page.locator("div").filter(has_text="蓄電動作モード").filter(has=page.locator("select")).last
                mode_row.locator("select").first.select_option(label=mode_label)
            page.wait_for_timeout(1000)

            # ７・８．充電開始/終了時刻の設定
            has_time_fields = True
            if mode == "green":
                # グリーンモードで時刻欄が表示されない画面構成の場合は設定をスキップ
                try:
                    page.get_by_text("充電開始時刻").first.wait_for(state="visible", timeout=3000)
                except Exception:
                    has_time_fields = False
                    print("グリーンモードでは充電時刻欄が表示されないため、時刻設定をスキップします。")

            if has_time_fields:
                set_time_row(page, "充電開始時刻", sh, sm)
                set_time_row(page, "充電終了時刻", eh, em)

            # ９．「次に進む」をクリック
            try:
                page.locator("a, button").filter(has_text="次に進む").first.click(timeout=5000)
            except:
                page.get_by_text("次に進む", exact=True).first.click()
            page.wait_for_timeout(2000)

            # １０．「設定」をクリック
            try:
                page.locator("a, button").filter(has_text="設定").first.click(timeout=5000)
            except:
                page.get_by_text("設定", exact=True).first.click()

            # １１．処理中待機後、「ログアウト」をクリック
            if loading.count() > 0 and loading.first.is_visible():
                loading.first.wait_for(state="hidden", timeout=60000)
            page.wait_for_timeout(2000)
            try:
                page.locator("a, button").filter(has_text="ログアウト").first.click(timeout=5000)
            except:
                page.get_by_text("ログアウト", exact=True).first.click()

            if has_time_fields:
                summary = f"蓄電池の設定（{mode_label}、{sh}:{sm}-{eh}:{em}）が正常に完了しました。"
            else:
                summary = f"蓄電池の設定（{mode_label}）が正常に完了しました。"
            with open("result_summary.txt", "w", encoding="utf-8") as f:
                f.write(summary)
            print("全ての設定が正常に完了しました。")
            print(summary)

        except Exception as e:
            try:
                page.screenshot(path="error_screenshot.png", full_page=True)
                with open("error_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
            except:
                pass

            error_details = traceback.format_exc()
            with open("error_log.txt", "w", encoding="utf-8") as f:
                f.write(f"自動化スクリプト実行中にエラーが発生しました。（{mode_label} {sh}:{sm}-{eh}:{em}）\n\n{error_details}")
            print("エラーが発生したため中断しました。")
            raise e
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        run_automation()
    except ValueError as ve:
        # 入力値の不正（ブラウザ起動前）
        with open("error_log.txt", "w", encoding="utf-8") as f:
            f.write(f"入力値エラー: {ve}")
        print(f"入力値エラー: {ve}")
        sys.exit(1)
