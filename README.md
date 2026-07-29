# 新高値ブレイク スクリーナー

東証の全銘柄から,**52週高値更新 × 売上+10% × 営業利益率20%(通期) × ROE10%** を満たす銘柄を
自動で毎日スクリーニングし,Webアプリで表示・当日新高値をチャット通知する仕組み。

## 構成

| ファイル | 役割 |
|---|---|
| `scan.py` | データ取得・絞り込みの本体（`--full`で業績も取得） |
| `app.py` | Streamlitの画面（表・チャート） |
| `notify.py` | 通知の送信（Discord / LINE） |
| `universe.py` | 対象銘柄リストの取得 |
| `.github/workflows/daily.yml` | 毎日17:30 JSTに株価更新＋通知 |
| `.github/workflows/weekly.yml` | 毎週日曜に業績を取り直す |
| `data/` | 生成データ（自動コミットされる） |

## 仕組み

```
毎週日曜  weekly.yml → scan.py --full  → data/funda.json, margins.json（業績キャッシュ）
毎日17:30 daily.yml  → scan.py         → data/rows.json ＋ 当日新高値を通知
利用者     app.py（Streamlit Cloud）   → data/rows.json を表示、チャートはライブ取得
```

## セットアップ手順

### 1. GitHubにリポジトリを作る
1. GitHubで新規リポジトリ `newhigh-breakout` を作成（公開推奨＝Actions無制限）
2. このフォルダの中身をすべて push

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<あなた>/newhigh-breakout.git
git push -u origin main
```

### 2. 通知先を用意する（どちらか）

**A. Discord（おすすめ・無制限・簡単）**
1. Discordでサーバーを作る（自分だけでOK）→ チャンネルの「設定」→「連携サービス」→「ウェブフックを作成」→ URLをコピー
2. GitHubリポジトリの Settings → Secrets and variables → Actions → New repository secret
   - 名前 `DISCORD_WEBHOOK`,値にコピーしたURL

**B. LINE（月200通まで無料）**
1. [LINE Developers](https://developers.line.biz/) で Messaging API チャンネルを作成
2. チャンネルアクセストークンと自分のユーザーIDを取得
3. GitHub Secretsに `LINE_TOKEN` と `LINE_USER_ID` を登録
（※旧「LINE Notify」は2025年3月終了。現在はMessaging APIを使う）

### 3. 初回データを作る
GitHubの Actions タブ →「weekly-fundamentals」→ Run workflow（手動実行）で業績を取得。
続けて「daily-scan」も手動実行すると `data/rows.json` ができる。

### 4. Streamlit Cloudにデプロイ
1. [share.streamlit.io](https://share.streamlit.io/) にGitHubでログイン
2. New app → リポジトリ `newhigh-breakout`,ブランチ `main`,ファイル `app.py` を選択 → Deploy
3. 発行されたURLがスクリーナー本体

以降,毎日17:30に自動更新＋通知され,アプリを開けば常に最新が見られる。

## ローカルで試す
```bash
pip install -r requirements.txt
python scan.py --full     # 初回（20〜40分）
streamlit run app.py
```

## 注意
- 営業利益率は**通期のみ**。Yahooは日本株の四半期営業利益をほぼ提供しないため。
- 生存者バイアス・in-sample等の限界あり。スクリーニング補助であり投資助言ではない。
- Actionsの定時実行は数分遅延することがある。
