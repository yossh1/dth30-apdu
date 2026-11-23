# みこすスタック ビルド結果（2026-11-23）

対象: `i4M1k0SU/DTH10-series-driver` master HEAD `ef207fcdc3f143ae1f6b1e6e05ad7742fcd1fe37` の `dth` CLI 一式を 検証ホスト（armv7）向けにビルドする。
承認根拠: ユーザー決定（2026-11-23 09:41 JST）「今の方式（Mode Q）と彼の方式で、動作が早い方を進めたい」— 比較実測のためのビルド go-ahead。
範囲: ビルドのみ。**実機には触っていない。** 手順は DESK.md §2 が正。

## 1. 環境（ビルドホスト、ビルド前に実測）

- rustc 1.100.0 (0ef1bc386 2026-11-09) / cargo 1.100.0 — ワークスペース要件 `rust-version = "1.100"` をちょうど満たす。
- `armv7-unknown-linux-musleabihf` ターゲット: インストール済み。
- `rust-src` コンポーネント: インストール済み（追加作業なしで前提充足）。
- ソースは ビルドホスト 上に新規 clone（`~/dth30-build/driver/`、上記コミットに checkout し `git log` で一致を確認）。ローカルの監査用 clone・作業用 clone は不変。

## 2. ビルド

```
cargo build --release -p dth-cli -p dth10-diag -p dth30-diag --target armv7-unknown-linux-musleabihf
```

- 結果: **成功（exit 0）**、`Finished release profile in 2m 15s`。dth30-core の build.rs による nested な MIPS 向け dth30-fw ビルドも含め完走。
- ログ全文: `mikosu/artifacts/build.log`（ビルドホスト 側は `~/dth30-build/build.log`）。

## 3. 生成物の確認（DESK.md §2.4）

| 対象 | サイズ (B) | SHA256 |
|---|---:|---|
| dth | 3,481,516 | `816400609713792a4ad71f8ab54742d5d9a1f53802ffea251e87e9e879c1612a` |
| dth10-diag | 2,806,764 | `0b083434b848fb1bd5bfa143cd36245903ab9d28b7453c039d69738d1a3ad7ac` |
| dth30-diag | 2,498,976 | `13790663fba4eb59c72dbb35477e78d0ab0edc991a0cc0e90664fb745dacc30a` |
| dth30-fw.bin（組み込み FW イメージ） | 25,312 | `269ad601ec9211b27bea51e2b543ab3d0005ece52820a0dec6c79965257b02c6` |

- **静的リンク**: 3バイナリとも `ELF 32-bit LSB executable, ARM, EABI5, statically linked`（`file` 実測）。検証ホスト へコピーしてそのまま実行できる前提を満たす。
- **互換ファームの組み込み**: 
  - `dth30-fw.bin`（dth30-core の OUT_DIR 生成物）の +0x100 = `44 54 48 33` = **"DTH3"**、+0x104 = version `0x00000001` を実バイトで確認（build.rs 自身の magic アサートも通過）。
  - `dth` バイナリ内に当該 FW イメージ**全体が verbatim で含有**されることを照合（先頭 4KB が offset 197,992 に出現し、イメージ全体の部分一致も真）。同位置 +0x100（offset 198,248）にも "DTH3"＋version 1 を確認。
  - `dth` / `dth30-diag` / `dth10-diag` の各バイナリからも "DTH3" 文字列の存在を確認（他の出現はホスト側の magic 照合コード等）。

## 4. 成果物の置き場

- ローカル: `mikosu/artifacts/` に `dth` / `dth10-diag` / `dth30-diag` / `dth30-fw.bin` / `build.log` を回収済み。回収後の SHA256 は ビルドホスト 側の値と完全一致（転送の完全性を確認）。
- ビルドホスト 側: ソース `~/dth30-build/driver/`、生成物 `~/dth30-build/driver/target/armv7-unknown-linux-musleabihf/release/` に残置。

## 5. 次の一手

- 実機フェーズ（DESK.md §4.3 のコマンド列: `dth list` → `dth30-diag fw` → `dth tune -c 27 …`）は**別途承認を取ってから**。`dth tune` は現在の純正セッションを彼の CFW で丸ごと置き換える点に注意（復帰は hw22 replay）。
- ユーザーの比較軸（Mode Q と彼の方式の「動作の速さ」）の実測は実機フェーズの設計に含めること（例: 選局→TS 開始までの時間、復号確立までの時間、APDU 往復時間は Mode Q 側のみ等、物差しの定義が要る）。
