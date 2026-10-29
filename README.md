# 理科タン v9.2

`index.html` が現行版です。外部パッケージやビルドを必要としない HTML/CSS/JavaScript のアプリで、学習履歴は同じオリジンのブラウザー内に保存します。

開発時の起動:

```sh
python3 -m http.server 8000 --bind 127.0.0.1
```

## 自動テスト

Python 3.12 と Chromium を使用します。アプリ本体への追加依存はありません。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m unittest discover -s tests -v
```

Linux でブラウザーのシステム依存がない場合は `python -m playwright install --with-deps chromium` を使用します。既存の Chromium は `CHROMIUM_PATH=/absolute/path/to/chromium` で指定できます。未指定の場合は PATH の `chromium`、それもなければ Playwright のブラウザーを使います。

テストは使い捨てのブラウザーコンテキストで、すべてのリクエストをメモリ上の HTML に置き換えます。合成データのみを使い、公開サイト、既存のブラウザープロファイル、利用者の学習履歴に接続しません。

修正前との比較（同じテストを元のコードに実行）:

```sh
RIKA_SOURCE_REF=17c1acd7c27c6cedc58e8d2970f7544149d74cd6 \
  python3 -m unittest discover -s tests -v
```

比較元の Git オブジェクトが必要です。GitHub Actions は全履歴を取得してテストします。32 テストには、全5版の問題データ部分が比較元とバイト単位で同一であること、および現行740問＋ボス4問の件数確認も含みます。

保存形式、旧版URLの変更理由、比較結果、制限は [学習履歴保護の説明](docs/history-protection.md) を参照してください。
