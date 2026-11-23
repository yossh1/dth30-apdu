# dth30-apdu — DT-H30/U2 の B-CAS カードを汎用 APDU / PC/SC で使う

## 機器

- BUFFALO DT-H30/U2（USB 接続の地上デジタルチューナー、**ISDB-T 専用**。BS/CS は受信できません）
  - USB VID 0x0411 / PID 0x0128（0x0144 は未検証）
  - 対象は本体内蔵の B-CAS カードスロット
- ドライバ側の対応機種一覧は driver-apdu/README.md を参照してください
  （本 repo の APDU 拡張の実機検証は DT-H30/U2 のみです）

## 概要

DT-H30/U2 の内蔵 B-CAS カードは、純正ソフトウェア経由では視聴・復号専用で、
ホストから汎用カードリーダーとして使う口がありませんでした。本 repo は、
そのための経路を2つ実証し、使える形でまとめたものです。

1. **driver-apdu/** — 互換 CFW（DTH10-series-driver）に新コマンド 28 を追加し、
   ホストから汎用 APDU 交換（QUERY / EXCHANGE）ができるようにした実装。
   視聴（復号）と APDU は同じジョブキューで直列化されるため、ストリーム中でも使えます。
2. **vicc/** — 上記の APDU ソケットを backend にして、カードを標準 PC/SC
   リーダーとして公開する橋渡し。一般の PC/SC クライアントから使えます。

あわせて、純正ファーム側の解析と、もう一つの経路である Mode Q
（純正ファームへの揮発パッチ）の自作コードと資料も収めています。

## 構成

| パス | 内容 | ライセンス |
|---|---|---|
| driver-apdu/ | APDU 拡張入りドライバ（フルツリー、そのままビルド可能） | MIT |
| vicc/ | PC/SC 橋渡し（vsmartcard を実行時利用） | GPL-3.0-or-later |
| modeq/ | Mode Q ハンドラの自作コードとビルド資料 | MIT |
| docs/ | 設計・実装・検証の報告書と FINDINGS 要約 | MIT |
| tools/ | 解析・実験ハーネス（Python）のアーカイブ | MIT |
| NOTICE | 構成要素とライセンスの内訳 | — |

## 前提・必要なもの

- DT-H30/U2 本体と B-CAS カード
- Linux ホスト（検証環境は armv7 / x86_64 の Linux）
- Rust ツールチェーン（driver-apdu のビルド用。rust-toolchain.toml が
  stable + rust-src を要求します。互換 FW はビルド時に nested ビルドで生成されます）
- vicc を使う場合: pcscd、vpcd、python3-virtualsmartcard（Debian パッケージ、
  vsmartcard 0.8 で検証）を別途インストールすること
- Mode Q を使う場合: 自分自身の機器から取得した純正起動ストリーム
  （本 repo には含まれません。下記「Mode Q について」参照）

## ビルド手順

```sh
cd driver-apdu
cargo build --release -p dth-cli -p dth10-diag -p dth30-diag
```

クロスビルド（例: armv7 向け静的バイナリ）:

```sh
cargo build --release -p dth-cli -p dth10-diag -p dth30-diag \
  --target armv7-unknown-linux-musleabihf
```

生成物は `target/<target>/release/` の `dth` / `dth10-diag` / `dth30-diag` です。
互換 FW イメージはビルド時に Rust ソースから生成され、`dth` に組み込まれます
（純正ファームの blob は使っていません）。

## 使い方

デバイスの列挙と APDU（直接接続）:

```sh
dth list
dth apdu            # カード状態と ATR の照会（QUERY のみ）
dth apdu 9030000000 # APDU を1回交換（例: INITIAL_SETTING）
```

- 送信 APDU は最大 60 バイト、応答込みの合計は最大 127 バイトまでです。
- 結果は長さ・ステータスワード・SHA-256 指紋で表示されます
  （カード応答の生バイト列をログに残さない設計です）。

serve 常駐（ストリーム配信と APDU の両立）:

```sh
dth serve   # 既定のソケットは /run/dth/dth.sock（--socket で変更可）
dth apdu --socket /run/dth/dth.sock 9030000000
```

Mirakurun 等のチューナー基盤からは `dth stream --socket /run/dth/dth.sock -c <channel>`
で TS を取得できます。

PC/SC 経由（vicc）: vicc/README.md を参照してください。導入すると仮想
リーダーが現れ、通常の PC/SC クライアント（pyscard 等）からカードへ
APDU を送れます。

## Mode Q について

Mode Q は、純正ファームウェアの未使用コマンド Func 0x04 をフックし、
起動時に DDR 上へだけ当てる揮発パッチで汎用 APDU を実現する研究手法です。
modeq/ には自作ハンドラのソースとビルド手順（build_modeq.py と各 .md）だけを
収めています。**実行には利用者自身の機器から取得した純正ストリームが必要で、
本 repo はそれを提供しません**（純正ファームウェアは BUFFALO / ViXS の著作物のため）。
実用には driver-apdu の方式を推奨します。

## B-CAS に関する注意

本プロジェクトは、B-CAS カードの複製、鍵の抽出、視聴制御（アクセスコントロール）の
回避を行うものではありません。放送の復号は、利用者自身の正規契約の B-CAS カードが
機器内部で行います。本 repo の APDU 送受信機能は、カードの標準インターフェース
（ISO/IEC 7816）を用いる汎用的なもので、カードが通常応答するコマンドの範囲で
動作します。利用は、ご自身の保有機器と正規契約の範囲内で、自己の責任において
行ってください。

## ライセンス

- 自作部分（modeq/、docs/、tools/、本 README）: MIT（LICENSE）
- driver-apdu/: MIT（driver-apdu/LICENSE。upstream の著作権表示を保持し、
  自作分の表示を追記しています）
- vicc/: GPL-3.0-or-later（vicc/LICENSE）
- 構成要素の内訳は NOTICE を参照してください。

バイナリ配布について: 本 repo はソースのみで構成します。ビルド済みバイナリを
配布する場合は GitHub Releases に分ける方針です。

## 未解決の点

- 純正側のデコード系 open（Func 0x08 type 4）のリプレイ追加は未着地で
  原因未解明です（実用経路には影響しません）。詳細は docs/FINDINGS-SUMMARY.md。
