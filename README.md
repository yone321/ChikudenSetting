# chikuden

家庭用蓄電池の「遠隔モニタリングサービス」にログインし、蓄電動作モードを設定するGitHub Actionsプログラムです。
`docs/index.html` のWEBページから、グリーンモード／経済モードをボタン一つで設定できます。

## 仕組み

WEBページのボタン → GitHub API（workflow_dispatch）→ GitHub Actions `Battery Setup Automation` → Playwrightで設定

| ボタン | 渡す inputs | 動作 |
|---|---|---|
| グリーンモード | `mode=green` | 充電時間は月に応じて自動（4〜9月 06:00〜16:00 / 10〜3月 06:30〜15:30）。画面に時刻欄が無い場合は時刻設定をスキップ |
| 経済モード | `mode=economy`, `start_hour`, `start_minute`, `end_hour`, `end_minute` | コンボボックスで選んだ時刻で設定 |

## セットアップ

1. リポジトリのSecretsに `KP_USER` / `KP_PASS` / `SMTP_USER` / `SMTP_PASS` / `MAIL_TO`（通知メールの送信先アドレス）を登録
2. GitHub の Settings → Pages で、Source を「Deploy from a branch」、Branch を `main` / `/docs` に設定
3. Fine-grained personal access token を作成（Repository access はこのリポジトリのみ、Permissions は **Actions: Read and write**）
4. 公開された `https://<ユーザー名>.github.io/<リポジトリ名>/` を開き、「接続設定」にリポジトリ名とトークンを入力
   （トークンはその端末のブラウザにのみ保存されます）

`docs/index.html` はローカルで直接開いても動作します。

## JEPX価格グラフ

ページ下部に、JEPX中部エリアの30分コマ価格グラフを表示します。

- 翌日分が公表済みなら翌日、未公表なら当日のグラフを表示（見出しに日付を表示）
- 13円/kWh未満のコマは緑、それ以外は青
- グラフをクリックすると、そのコマの時刻と価格を表示し、経済モードのコンボボックスに入力
  - 開始 = クリックしたコマの開始時刻の10分前（蓄電池の設定時間を見込む。0:00より前にはしない。`index.html` の `START_OFFSET_MIN` で変更可）
  - 終了 = クリックしたコマ以降で13円未満となる最後のコマの終了時刻（上限23:30）
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

Actions タブ → Battery Setup Automation → Run workflow からも、モードと時刻を指定して実行できます。
