# chikuden

家庭用蓄電池の「遠隔モニタリングサービス」にログインし、蓄電動作モードを設定するGitHub Actionsプログラムです。
`docs/index.html` のWEBページから、グリーンモード／経済モードをボタン一つで設定できます。

## 仕組み

WEBページのボタン → GitHub API（workflow_dispatch）→ GitHub Actions `Battery Setup Automation` → Playwrightで設定

| ボタン | 渡す inputs | 動作 |
|---|---|---|
| グリーンモード | `mode=green` | 充電時間は月に応じて自動（4〜9月 06:00〜16:00 / 10〜3月 06:30〜15:30）。画面に時刻欄が無い場合は時刻設定をスキップ |
| 経済モード | `mode=economy`, `start_hour`, `start_minute`, `end_hour`, `end_minute` | コンボボックスで選んだ時刻で設定 |

## 予約実行

ページ上部の「予約」で「予約する」にチェックを入れると、グリーンモード／経済モードのボタンは**即時には設定せず**、
リストボックスで選んだ日時の予約として登録します（ボタンの表示も「〜を予約」に変わります）。
チェックを外している間は、従来どおり即時に設定します。

- 実行日時の候補は30分刻み（現在の5分後以降〜翌日23:30）です。
- 経済モードは、予約を登録した時点のコンボボックスの時刻で設定します。グリーンモードは実行時の月に応じて自動設定します。
- 予約は「予約一覧」に表示され、予約中のものは「取消」できます。直近の実行結果（完了／失敗／失効）も5件まで表示します。

### 仕組み

WEBページ → `reservation_edit.yml`（予約の追加・取消。`docs/reservations/<id>.json` を保存してコミット）
→ `reservation_run.yml`（10分ごとに実行予定時刻を過ぎた予約を確認し、あれば `automate_battery.py` で設定）

- 予約は1件1ファイルで保存します（同時に追加しても衝突しません）。状態は `pending → running → done / failed` のように進みます。
- GitHubのcronは数十分遅れることがあるため、実行は予定時刻より遅れる場合があります。
  実行予定時刻から120分以上過ぎていた予約は、意図しない時間帯に設定しないよう実行せず「失効」とし、メールで知らせます
  （`reservation.py` の `GRACE_MIN` で変更可）。
- 実行結果は、成功・失敗ともにメールで通知します（本文に「予約実行」と実行予定時刻を記載）。
- 1回の確認で実行する予約は1件です（同時刻の予約が複数ある場合は、次の確認で順に実行）。
- 終了して7日を過ぎた予約ファイルは自動で削除します。
- 予約はリポジトリ内のファイル（`docs/reservations/`）に保存されます。リポジトリをpublicにする場合は、予約の内容（モードと時刻）も公開される点に注意してください。
- WEBページ用のトークンに必要な権限は従来と同じ **Actions: Read and write** のみです（コミットはActions側が行います）。
- `reservation_run.yml` を10分ごとに動かすため、**privateリポジトリでは無料枠（月2,000分）を超える可能性があります**
  （1回約1分の課金×1日144回）。privateで使う場合は `cron` の間隔を広げるか、外部cronサービスから
  `reservation_run.yml` の `workflow_dispatch` を呼び出してください。

## セットアップ

1. リポジトリのSecretsに `KP_USER` / `KP_PASS` / `SMTP_USER` / `SMTP_PASS` / `MAIL_TO`（通知メールの送信先アドレス）を登録
2. GitHub の Settings → Pages で、Source を「Deploy from a branch」、Branch を `main` / `/docs` に設定
3. Fine-grained personal access token を作成（Repository access はこのリポジトリのみ、Permissions は **Actions: Read and write**）
4. 公開された `https://<ユーザー名>.github.io/<リポジトリ名>/` を開き、「接続設定」にリポジトリ名とトークンを入力
   （トークンはその端末のブラウザにのみ保存されます）

`docs/index.html` はローカルで直接開いても動作します。

## JEPX価格グラフ

ページ下部に、JEPX中部エリアの30分コマ価格グラフを表示します。

- 表示範囲は**当日17:00〜翌日24:00**（30分コマ×最大62コマ）。翌日分が未公表の間は、当日17:00〜24:00のみ表示（見出しに日付を表示）
- 日付の境目に縦線を表示し、横軸の下段に日付を表示。スマートフォンでは横にスクロールできます
- 13円/kWh未満のコマは緑、それ以外は青
- グラフをクリックすると、そのコマの時刻と価格を表示し、経済モードのコンボボックスに入力
  - 開始 = クリックしたコマの開始時刻の10分前（蓄電池の設定時間を見込む。0:00より前にはしない。`index.html` の `START_OFFSET_MIN` で変更可）
  - 終了 = クリックしたコマ以降で、**同じ日の中で**13円未満となる最後のコマの終了時刻（上限23:30）。
    蓄電池の充電時間は日付をまたいで設定できないため、日またぎは考慮しません
- ブラウザから `jepx.jp` へ直接アクセスできないため、`.github/workflows/fetch_jepx.yml` が
  `fetch_jepx.py` でCSVを取得し、`docs/jepx_chubu.json` に保存・コミットします
  （日本時間 00:10 / 10:50 / 11:30 / 14:00 に自動実行。初回は Actions タブから手動実行してください）
  取得方法はJEPX-main（動作確認済み）に合わせ、暦年ごとの `spot_YYYY.csv` を直接取得し、失敗時はJEPXのページからCSVリンクを探索します。
  GitHub自身のcronは遅れることがあるため、JEPX-mainと同様に外部cronサービスから `fetch_jepx.yml` の `workflow_dispatch` を送ることもできます。

### 「価格データを再読込（JEPXから取得）」ボタン

ブラウザからは `jepx.jp` に直接アクセスできないため、ボタンを押すと次の順で処理します。

1. `fetch_jepx.yml` をGitHub APIで実行（トークンの Actions: Read and write 権限を使用）
2. 実行の完了を待つ（最大約2.5分）
3. 保存された `docs/jepx_chubu.json` をGitHub APIで読み直してグラフを再表示（Pagesの反映待ちなし）

## 手動実行

Actions タブ → Battery Setup Automation → Run workflow からも、モードと時刻を指定して即時実行できます。
予約は Reservation Edit（action=add、`run_at` は `2026-10-14T17:30:00+09:00` の形式）から登録できます。
