# APDU v2 実装報告 — serve 常駐セッション経由の APDU 公開（設計 §9-9）

2026-11-23。作業ツリー `mikosu/driver-apdu/`（v1 = N-063 のコマンド 28 実装の上に追加）。
pristine な `mikosu/driver/` は無変更。**結論: 合格条件をすべて満たした。**
serve を止めずに、Mirakurun のストリーム中でもソケット経由で APDU が通り、
復号が維持されることを 検証ホスト 実機で確認した。本番バイナリの差し替えはしていない
（次段で別途判断）。

## 1. 接続形態（確定した設計）

既存の行プロトコル（`dth-proto`、stream/status と同じ1行要求→1行応答）に
第3の要求種別を追加した。stream 要求と同居し、既存の要求・応答文には一切触れていない（例外として、未知要求へのエラーメッセージ1行が `expected a stream or status request` から `… stream, status or apdu request` へ拡張されている）。

| 要求 | 応答（ok） | 応答（error） |
|---|---|---|
| `apdu [unit=<名前>] query` | `<名前> card=0x<状態> atr=<hex\|->` | daemon 側のエラー文 |
| `apdu [unit=<名前>] data=<hex>` | `<名前> apdu=<応答hex（SW含む）>` | `apdu reason=<n>`（送信時拒否）／`apdu code=<n>`（完了コード≠0） |

- クライアント形態は v1 の `dth apdu` に `--socket <PATH>` / `--connect <ADDR>` を追加
  （stream/status と同じ Target 解決、`$DTH_SOCKET` 等も同じ）。指定なしは従来どおり
  USB 直接（v1 の経路は無変更）。`--channel` / `--loop` とは併用不可（実行時エラー）。
- プロトコル層に APDU 長の上限は設けていない。61 バイトの APDU もそのまま FW に届き、
  FW の理由コード 3 が返る（異常系の検証に必要だったため意図的）。
- 同時実行: serve 経由の APDU は**ユニットあたり1件ずつ**（ユニットのセッションを
  掴んだまま完了待ちをする）。status 要求はその間もキャッシュから即答される。
  通常の待ちは約0.1秒、上限は完了待ちタイムアウト10秒（§6.1 の値）。
- 性質として明記: ソケット応答文にはカード応答の hex が載る（行プロトコルで APDU を
  公開する以上は必然）。到達範囲はソケットの権限（root:dth 0660）で区切られ、
  TS ストリームと同じ信頼境界。`dth apdu` クライアントの表示と serve のログは
  従来どおり長・SW・指紋／メタデータのみで、生バイトは出ない・残らない。

## 2. backend の待ち管理（§9-7 の backend 実装分）

- `dth-common` の `Session` トレイトに `card_query()` / `apdu_exchange()` を追加
  （既定は `Unsupported`。他バックエンド＝DT-H10 系・ダミーは無変更で従来動作）。
  戻り値は `CardInfo { status, atr }` と `ApduOutcome::{Completed{code, response}, Refused(reason)}`。
- `dth30-backend`: セッション（`Dth30Tuner`）が完了スロット（v1 の `ApduDoneSlot`）と
  **tag カウンタ**を持つ。tag は単調増加（0 は欠番、u32 を回ったら 1 に戻る）。
  送信→完了待ちは v1 と同じ core の `apdu_submit` / `wait_apdu_done` を使い、
  待ちが失効した後に届いた完了は tag 不一致で捨てられる。これが §9-7 の
  「tag↔oneshot 待ち管理」の、このコードベースの同期 Session 模型における実装形
  （1セッション同時1件なので、対応付けは tag＋単一スロットで完結する）。
- 完了ハンドラ（ID 0x10）はユニットを開くとき（`Dth30::open` 直後、CAS を開く前）に
  登録する。APDU の前には既存の `check_card()`＋`ensure_cas()` を通すので、
  カード未活性なら活性化してから送る。カードセッションは ECM と同一
  （v1 と同じ CAS オブジェクト・FW 側ジョブキュー直列化）。
- serve 側: USB エラー時は stream と同じくセッションを落とし、次回要求で開き直す。

## 3. FW 側

**無変更。** v2 バイナリに埋め込まれた DT-H30 FW イメージは v1 とバイト同一
（27,552 バイト、SHA-256 `b4832713919705568cfdc233defe46cdac7a68ff0a0416c6696f5a4f79ce8cb9`。
ビルド成果物 `dth30-fw.bin` と、バイナリ内 "DTH3" 位置からの抽出の2経路で照合）。

## 4. 変更ファイルと規模（v1 からの差分）

| ファイル | 変更 |
|---|---|
| `crates/dth-proto/src/proto.rs` | `Request::Apdu` 追加、整形/解析ヘルパ（query/exchange/error）、単体テスト2件。差分行数 196 |
| `crates/dth-common/src/session.rs` ほか | `CardInfo` / `ApduOutcome` 型とトレイト既定メソッド。差分行数 43＋4 |
| `crates/dth30-backend/src/lib.rs` | `ApduTags`、ハンドラ登録、`card_query` / `apdu_exchange` 実装、テスト1件。差分行数 86 |
| `crates/dth-cli/src/serve.rs` | ディスパッチ拡張と `serve_apdu`。差分行数 89 |
| `crates/dth-cli/src/apdu.rs` | `--socket` / `--connect` と `run_client`、引数テスト1件。+約120行（543→664行） |

（差分行数は pristine `mikosu/driver/` との diff の +/− 合計。これらのファイルは
v1 では未変更だったため、そのまま v2 の差分になる。apdu.rs のみ v1 新規ファイル。）

## 5. ビルドと単体テスト（ビルドホスト、rustc/cargo 1.100.0）

- `cargo test`: dth-proto 16 / dth30-backend 2 / dth-cli 11 / dth30-core 159 件、
  全合格。警告 0。
- リリースビルド（armv7-unknown-linux-musleabihf）: `dth` 3,638,848 バイト、
  SHA-256 `9cfc1eed56322915b1e2f67a4ed66629e1176d639fd610cd2f30f46e899bee97`。
  詳細は `artifacts/apdu-v2-20261123/build-info.txt`。

## 6. 実機検証（検証ホスト、2026-11-23 16:00〜16:06 JST）

手順: 本番 dth-serve を停止 → 本番バイナリ（v1）で同時期ベースライン取得 →
テスト serve（v2 ビルド、ソケットは本番と同じ `/run/dth/dth.sock`）を起動し
Mirakurun の相手をさせて検証 → テスト serve を停止 → 本番 serve（v1 のまま）を
再起動して復帰確認。TS 実物は 検証ホスト `/srv/dth30-lab/apdu-v2/` に残置。

1. **ベースライン**（`baseline.log`）: ATR 13 バイト・指紋 `17c7a75e…`、
   INITIAL_SETTING 応答 61 バイト・SW 9000・指紋 `e0d3ff05…`
   （見込み値と一致。照合はこの同時期値に対して行った）。
2. **アイドル時**（`idle.log`）: serve 稼働中にソケット経由 QUERY＋EXCHANGE が完了し、
   ATR・応答とも指紋がベースラインと**完全一致**。
3. **ストリーム中**（`stream-exchange.log`、`tscheck.log`）: Mirakurun 経由 GR27 を
   流して約25秒（TS 約4,890万バイト流入済み）の時点でソケット EXCHANGE を発行 →
   61 バイト・SW 9000・指紋 `e0d3ff05…` で完了（クライアント往復約0.25秒）。
   TS 解析: 487,925 パケット・同期 100%・スクランブル 945 個はすべて先頭 955
   パケット以内の過渡で、**パケット 5,000 以降のスクランブルは 0**（復号維持）。
4. **異常系**（`error-case.log`、`after-error.log`）: 別途 GR27 を流した状態で
   61 バイト APDU をソケット経由で送信 → `apdu reason=3`（長さ超過）が返り
   クライアントは理由文つきで終了コード 1。直後の通常 EXCHANGE は同一指紋で成功し、
   serve・ストリームとも継続。TS 解析: 400,362 パケット・同期 100%・
   スクランブルは先頭 966 パケット以内のみ、5,000 以降 0。
5. **復帰**（`restore-check.log`）: 本番 serve（v1 ビルド `93010d79…`）再起動後、
   Mirakurun 経由 GR27 で 174,319 パケット・同期 100%・スクランブルは先頭過渡のみ。
   dth-serve / mirakurun とも active。

証拠: `artifacts/apdu-v2-20261123/`（build-info.txt、各検証ログ、テスト serve の
ログ serve.log、TS 解析スクリプト tscheck.py）。serve.log には APDU の
メタデータ（状態・長・成否）のみが記録され、カード素材は含まれない。

## 7. 残件・次段

- 本番投入（`/usr/local/bin/dth` の v2 への差し替え）は本ラウンドの範囲外。
  差し替えれば `systemctl stop dth-serve` なしで `dth apdu --socket ...` が
  そのまま使えるようになる。テストバイナリは 検証ホスト `/srv/dth30-lab/apdu-v2/dth`
  に残置（SHA-256 は build-info.txt）。
- vicc（PC/SC 橋渡し）は従来どおり次段。ソケット経由 APDU ができたため、
  vicc はこのソケットのクライアントとして実装できる。
