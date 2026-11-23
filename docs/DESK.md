# みこす CFW 試行 — 机上フェーズ（2026-11-23）

対象: GitHub `i4M1k0SU/DTH10-series-driver` の `dth` CLI を 検証ホスト（armv7 Linux）の DT-H30/U2（0411:0128）で動かす試行の机上準備。
範囲: 机上のみ。**実機には触っていない。**

## 0. ブロッカー（先に読むこと）

- 新規 clone した内容が実行リスクチェックに引っかかったため、**ビルドは未実施**。このリポジトリのビルドは build.rs（dth30-core が nested cargo で dth30-fw をビルドする等）のコード実行を伴うので、ユーザーの明示的な go-ahead が出るまで進めない。読み取り（ソース精読・棚卸し・手順設計）は本書のとおり完了済み。
- ビルド承認が出れば §2 の手順をそのまま実行できる状態にある。

## 1. バージョン

- 最新タグ: `v1.1.0`（16f1e5dc11daafd890961aee1175ce91addb732e）
- master HEAD: **`ef207fcdc3f143ae1f6b1e6e05ad7742fcd1fe37`**（2026-11-22 21:37 JST、"Merge pull request #59 from i4M1k0SU/feat/dth30u2-verified"、v1.1.0 から +107 コミット）
- 採用は master HEAD。理由: DT-H30/U2 検証済み化の変更（PR #59）がタグ v1.1.0 より後に入っている。
- GitHub 側は 2026-11-22 以降更新がなく、監査用 clone（`cfw-audit/driver/`）と同一コミットだった。新規 clone は `mikosu/driver/` に作成し、監査用 clone は当時の状態のまま不変。
- ワークスペース version は 1.1.0（`dth --version` の表示はビルド後に確認）。

## 2. ビルド計画（未実施 — 承認後に実施）

実施場所: ビルドホスト（x86_64）。成果物は `mikosu/artifacts/` へ回収する。

### 2.1 前提（ソースから）
- `rust-toolchain.toml`: channel = stable、components = ["rust-src"]、targets に `armv7-unknown-linux-musleabihf` を含む（rustup が自動で揃える）。
- ワークスペース `rust-version = "1.100"`、`edition = "2024"`。
- Linux 向けは `.cargo/config.toml` で linker = `rust-lld` を指定。クロス C ツールチェーン不要（C コードなし）。
- dth30-core の build.rs が dth30-fw（MIPS カスタムターゲット `mipsel-xcode2`）を nested cargo build し、`RUSTC_BOOTSTRAP=1` を nested 側だけに付けて `core` を自前ビルド（rust-src が必須）。生成イメージを flatten して `OUT_DIR/dth30-fw.bin` に置き、`Firmware::own()` が `include_bytes!` で組み込む。`DTH30_NO_OWN_FIRMWARE=1` で組み込みを無効化できる（今回は使わない）。

### 2.2 ビルドホスト の実測（2026-11-23、読み取り確認のみ）
- rustup 管理の stable ツールチェーンあり。`rustup target list --installed` に `armv7-unknown-linux-musleabihf` が含まれる。
- 要再確認（ビルド時）: cargo の正確な場所と `rustc --version`（1.100 以上か）、`rust-src` コンポーネントの有無（無ければ `rustup component add rust-src`）。

### 2.3 コマンド（README の Linux armv7 行）
```
cargo build --release -p dth-cli -p dth10-diag -p dth30-diag --target armv7-unknown-linux-musleabihf
```
生成物: `target/armv7-unknown-linux-musleabihf/release/{dth, dth10-diag, dth30-diag}`

### 2.4 生成物の確認項目（ビルド後に実施）
- 互換ファームの組み込み: バイナリ内に `dth30-fw.bin` 相当が入っていること。目安はイメージ先頭 +0x100 の magic **"DTH3"（0x33485444 LE）** と +0x104 の version の存在をバイナリ全体から探すこと。補強として `dth30-diag fw`（オフライン実行、後述）で内蔵 FW のサイズ・SHA256・ベクタ表が表示できる。
- 静的リンク: `file` で "statically linked" を確認（musl + rust-lld のため静的のはず）。検証ホスト へコピーしてそのまま実行できる前提の確認。
- サイズと SHA256 を記録し、`mikosu/artifacts/` にバイナリと一緒に置く。

## 3. カード系コマンドの棚卸し

**結論: 汎用 APDU 素通しコマンドは存在しない。** `dth`、`dth30-diag`、ファームのホストプロトコルのいずれにも、任意 APDU を運ぶ口はない。カード処理は彼の互換ファーム内部で完結し、ホストに見えるのは「復号済み TS」「カードイベント」「カードリセット要求」だけ。

### 3.1 `dth`（crates/dth-cli/src/main.rs）
サブコマンドは `list` / `info` / `tune` / `serve` / `stream` / `status` のみ。カード専用コマンドはない。
- `tune` の `--mode device`（既定）が内蔵 B-CAS カードによる復号。`--mode raw` は復号なし全 TS。
- DTH30 series では `--firmware <FILE>` で純正 BufFsUSB.sys（またはイメージ）を指定可能。未指定なら組み込みの互換ファーム。
- `info` は DTH30 では endpoints / board / FW source を表示するが、**チップリセットを伴う**（§4.2）。カード ID・状態の表示はない。

### 3.2 `dth30-diag`（crates/dth30-diag/src/main.rs）
サブコマンドは `list` / `info` / `probe` / `fw` / `bring-up` / `i2c-read` / `i2c-write` / `tune` / `record`。カード/APDU コマンドはない。
- `fw`: オフラインで FW ソースを検証しベクタ表を表示（デバイス不変）。
- `info`: NET2280 レジスタ読みのみ（変更なし）。`probe`: NET2280 初期化＋BAR 割当て＋チップ ID 読み（FW なし）。
- `record --cas plain|drm`: CAS モード選択。ただし彼の互換ファームでは drm（bit5）も plain（bit4）扱いで、再暗号化は未対応（cas.rs の open 実装）。

### 3.3 ファームのホストプロトコル（crates/dth30-fw/src/main.rs のディスパッチ）
純正と同じ MMR ドアベル方式（0x3020、スロット +0x0C = コマンド ID）。コマンドは固定機能のみ:
- 0 = ping、8 = ストリーム open（Raw / Program）、9 = close、10 = flush、24 = TS 入力設定、27 = OTP 署名（ドアベル直通）
- 11 = CAS オブジェクトへの入力: **対応するのはカードリセット要求だけ**（+0xA0 bit16、+0xB8 bit4、+0x1BC bit0 → `card.request_reset()`。それ以外は無視して OK を返す。cas.rs）
- 25 = CAS オブジェクト open（payload +0x08 の mode bit4 = B-CAS）、26 = close

### 3.4 カードの扱い（FW 内完結）
- INITIAL_SETTING・ECM・EMM は FW 内（card.rs / cas.rs / program.rs）が生成・消費する。ECM の鍵応答は Program ストリーム処理にだけ渡り、ホストへは出ない。
- ホストに見えるカード情報は CAS イベントブロック（EP 0x82 の generic ブロック、ヘッダ 0x1EC）のフラグのみ: **INSERTED 0x2000 / REMOVED 0x4000 / ACTIVATED 0x8000 / INIT done 0x800000**、INIT done 時は +0x1BC にカードのリターンコード（解析済みの値で、生の APDU 応答ではない）。純正の push 型経路と同じ意味論。
- ホスト側の流れ（dth30-backend）: device モードの初回 tune で CAS オブジェクトを開いてカードリセットを発行し、ACTIVATED を最大 5 秒待つ。以後 close まで開いたままでイベントを監視し、未活性化なら定期的にリセットを再要求する（FW は自発的にはカードをリセットしないため）。
- つまり「カードリーダーとして使う」用途では、彼の方式でも **Mode Q のような任意 APDU の口は得られない**。得られるのは復号 TS とカード状態イベントまで。

## 4. 実機手順の設計（検証ホスト、次フェーズ用）

### 4.1 前提と競合
- 現在の実機は 検証ホスト 上で**純正ファーム起動＋セッション中**（当プロジェクトの replay スタックで起動した状態）。
- 彼のスタック（dth30-usb / nusb）の列挙まわり（ソース確認済み）: **USB リセットなし、再列挙なし、CLEAR_FEATURE なし**。configuration は「別の config が active な場合のみ」config 1 を選択し、全インターフェースを alt 0 で claim する。通常は現行 config のままなので set_configuration は発行されない見込み。
- 当プロジェクトの replay スクリプトは常駐しないので、実行していなければ claim 競合は起きない。hw 系スクリプトの実行中に `dth` を叩かないこと。検証ホスト の Mirakurun / GV-MACTV は別デバイスで無関係。
- 権限: 検証ホスト では **root** で実行する（usbfs ノード `/dev/bus/usb/BBB/DDD` の読み書き＋インターフェース claim が必要）。
- 配置案: `/srv/dth30-lab/mikosu/` に `dth` / `dth30-diag` を置く。state dir は既定で「書ける /var/lib/dth、無ければ exe の隣」なので、置き場所を固定して運用する。

### 4.2 デバイス状態の遷移（コマンドごと、ソース確認済み）
| コマンド | デバイスへの作用 | 現在の純正セッション |
|---|---|---|
| `dth list` | 列挙のみ（ディスクリプタ読み） | 不変 |
| `dth30-diag fw` | オフライン検証のみ | 不変 |
| `dth30-diag info` | NET2280 レジスタ読みのみ | 不変 |
| `dth info`（DTH30） | claim + NET2280 hw_init + board ID 読み = **チップリセット相当**（probe の doc 明記） | **失われる** |
| `dth30-diag probe` | NET2280 初期化＋BAR 割当て（FW なし） | **失われる** |
| `dth tune` / `dth serve` / `dth30-diag bring-up` 以降 | open → bring_up: **SDRAM メモリ初期化＋FW ダウンロード＋MIPS 起動＋ハンドシェイク**（失敗時最大10回リトライ）→ DMA/I2C/GPIO 初期化→OTP 読み（コマンド27） | **丸ごと置き換わる** |

- bring_up は「既に FW が動いているか」の確認をせず、無条件にメモリ初期化からやり直す。既定では彼の互換ファームが起動し、`--firmware BufFsUSB.sys` 指定時は純正イメージで起動し直す。
- `tune` の終了時: Program/Raw/CAS を純正の順序で close し standby 書き込み＋ランプ idle。**チップ上には彼のファームが起動したまま残る**（電源断か次の bring_up まで）。
- USB リセットが出ないため列挙は維持され、ユニット名 `DTH30-0128-<bus>-<ports>` は変わらない。

### 4.3 試行コマンド列（案）
1. `dth list` — ユニット名（`DTH30-0128-…`）の確認。
2. `dth30-diag fw` — 内蔵 FW のオフライン確認（サイズ・SHA256・ベクタ）。
3. ここから先は状態遷移を伴う段。`dth tune -c 27 -t 10 -o trial27.ts --stats -v`（device モード既定）— 復号確認は出力 TS の scrambled パケットが 0 であること（彼の diag record と同じ物差し）。
4. 対照が必要なら `dth tune -c 27 --mode raw -t 10 -o trial27raw.ts`。
5. 復帰（§4.4）。

### 4.4 純正ブートへの復帰
- 既存の hw22 replay を使う: USB リセット → Stage A（純正 FW 再ダウンロード）→ Stage B（セッション開始）。
- 復帰確認は従来基準: ハンドシェイク 5→0、Stage B の TS が同期 100% でベースライン同等。
- 彼のツール側に「純正へ戻す」機能はない（`--firmware` で純正イメージ起動はできるが、それは彼のスタック上での純正 FW 起動であって、当プロジェクトの replay セッションとは別物）。

### 4.5 検証構成の一致
- README で DT-H30/U2 は検証 ✅（PID 0x0128）。device.rs には "Checked on a DT-H30/U2 (board 0xB3, MJ100 kit)" とあり、うちの個体の実測 board 0xB3 と一致する。
- 一方 vixs/mod.rs のモジュール doc には "None of this is verified on hardware" とも書かれている（dth30-core 単体の観点）。実機試行はこの差を意識して小さく始める。

## 5. 残件
1. **ビルド実施**（要ユーザー承認 — §0）。承認後: §2.2 の再確認 → §2.3 実行 → §2.4 の確認（DTH3 magic・静的リンク・サイズ/SHA256）→ 成果物を `mikosu/artifacts/` へ。
2. 実機試行は §4 の手順で別途承認を取ってから。
