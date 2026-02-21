# 肘OCD（上腕骨小頭OCD）論文収集ボット: `ocd_fetcher`

PubMedを中心に、肘の離断性骨軟骨炎（capitellar OCD）関連の論文を収集し、メタデータ整理・OA PDF保存・要約生成を行うPython CLIです。

## プロジェクト構成案

```text
.
├─ ocd_fetcher/           # CLI本体
├─ config.yaml            # 検索式・上限件数・レート設定
├─ requirements.txt
├─ Makefile
├─ data/                  # CSV / JSONL
├─ pdf/                   # OA PDFのみ保存
├─ bib/                   # BibTeX / RIS
├─ summaries/             # 論文ごとの1枚サマリーMarkdown
└─ logs/                  # 実行ログ + チェックポイント
```

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 環境変数（推奨）

NCBI E-utilitiesとUnpaywall利用のため、メールアドレスを設定してください。

```bash
export NCBI_EMAIL="your-email@example.com"
```

## 実行方法

基本実行:

```bash
python -m ocd_fetcher --config config.yaml --outdir . --max 200
```

オプション:

- `--since-year 2010`
- `--until-year 2024`
- `--max 100`
- `--query-override "(独自検索式)"`
- `--download-pdf true|false`

## 収集方針

- メタデータ取得: PubMed E-utilities（`esearch` / `efetch`）
- 対象: 肘・上腕骨小頭（capitellum/capitellar）OCD中心
- OA PDF取得（オープンアクセスのみ）:
  1. PMCIDがあればPMC PDFを優先
  2. Europe PMCでOA判定 + PDF URL
  3. DOIがある場合のみUnpaywall APIで`url_for_pdf`
- 有料・ログイン必須・規約違反の迂回は行いません（URLメタデータのみ保存）

## 出力仕様

### `data/`
- `papers.csv`
- `papers.jsonl`

必須項目:
- PMID, DOI, PMCID, Title, Authors, Year, Journal, Abstract, PublicationType
- Keywords, StudyDesign（推定）, Sport（キーワード抽出）
- OA（True/False）, PDF_URL, Source

### `pdf/`
命名規則:

`YEAR_FirstAuthor_Journal_ShortTitle_PMID(or DOI).pdf`

- 既存ファイルがある場合は再DLしません
- PDF判定できないレスポンスは保存しません

### `bib/`
- `papers.bib`
- `papers.ris`

### `summaries/`
各論文ごとにMarkdownを作成:
- タイトル
- 要点
- 方法
- 主要結果
- 臨床的示唆
- 限界
- リンク（PubMed / DOI / OA PDF）

### `logs/`
- `fetch.log`: 実行ログ
- `checkpoint.json`: 処理済みPMIDと集計

## 再実行・中断復帰

- 処理済みPMIDを`logs/checkpoint.json`で管理
- 再実行時は既処理をスキップし、追記処理
- 途中失敗時もそれまでの結果を保持

## 合法・倫理・レート制限

- NCBI APIのレート制限（デフォルト3 req/sec）を順守
- 必要に応じて`config.yaml`でレート調整
- OA以外のPDF取得は実施しない
- 研究利用時は元論文・出版社ポリシーを確認

## よくあるエラーと対処

1. `RuntimeError: request failed...`
   - 一時的なAPI障害/ネットワーク失敗。再実行してください（チェックポイント復帰可）
2. OA判定が少ない
   - DOI欠損やOA未提供の可能性。メタデータは保存されます
3. PDF保存ゼロ
   - `--download-pdf false`になっていないか確認
   - OA URLがHTMLを返すケースでは保存をスキップします
4. Unpaywallが使われない
   - `NCBI_EMAIL`未設定だとUnpaywall問い合わせを行いません

## 実行例

```bash
python -m ocd_fetcher --config config.yaml --outdir . --max 20 --since-year 2015
```

出力サンプル（例）:

```text
data/papers.csv
data/papers.jsonl
bib/papers.bib
bib/papers.ris
summaries/12345678.md
logs/fetch.log
logs/checkpoint.json
pdf/2019_Smith_AmJSportsMed_Capitellar_OCD_in_Young_12345678.pdf
```
