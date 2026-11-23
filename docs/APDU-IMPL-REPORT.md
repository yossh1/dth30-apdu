# APDU 送信コマンド（cmd 28）実装報告 — みこす CFW（DTH10-series-driver）

実施: 2026-11-23（ユーザー承認 10:40 JST「実装フェーズ行きましょう」）
設計: `APDU-CMD-DESIGN.md`（N-062）の §9 実装フェーズ
作業ツリー: `mikosu/driver-apdu/`（pristine な `mikosu/driver/` @ ef207fcd のコピー。pristine は無変更）
証拠: `artifacts/apdu-impl-20261123/`（build-info.txt / 検証ホスト-verify.log / restore-check.txt）

## 結論（合格条件クリア）

新コマンド 28 で INITIAL_SETTING（`90 30 00 00 00`）を投げ、応答が Mode Q オラクルと完全一致した:

- **61 バイト・SW 9000・SHA-256 `8bb4ef993c4b59c17c91ea780eb7e17601d13524607619e7fc18adcbcffe7f7b`**（Mode Q オラクルの完全値と全64桁一致）
- 純正 FW＋Mode Q パッチでしか到達できなかった汎用 APDU 交換が、みこす CFW 上で通常機能として動作することを効果側で確認した。

## 実装内容（設計 §9 の項目対応）

| §9 項目 | 実装 | 場所 |
|---|---|---|
| 1. FW: ATR 保持 | `Atr::Done` 時点で rx から最大 34 B を保持。>34 B は未取得（atr_len=0）として扱う（§8 U6 の v1 案どおり） | dth30-fw `card.rs` |
| 2. FW: Job::Apdu＋submit＋完了コード | ECM と同じジョブキューへ投入し直列化。受付ゲートは ACTIVE のみ。送信 ≤60 B／送受信合計 ≤127 B の検査つき | dth30-fw `card.rs` |
| 3. FW: 消去経路の伝播 | `apdu_abort(code)` を新設し `power_cycle`（完了コード 3）・`forget`（同 1）に組み込み。保留 APDU の無言消失を禁止。`activate()` の jobs 上書き前にも同 3 を配置（ゲート上は到達不能だが仕様として明記） | dth30-fw `card.rs` |
| 4. FW: Cas::apdu＋ApduDone 送出 | cmd 28 ディスパッチ、理由コードの同期書き戻し、完了は M2H ID 0x10 で非同期送出。本体が空くまで保持・再試行し完了を捨てない | dth30-fw `cas.rs` / `main.rs` |
| 5. ホスト: 定数・ビルダ | `func::APDU=28`、`m2h::APDU_DONE=0x10`、`build_apdu_submit` / `build_apdu_query`、`Vixs::apdu_submit` / `card_query` | dth30-core `vixs/cmd.rs` / `stream.rs` |
| 6. ホスト: 完了収集 | `apdu_done_handler`（set_m2h_handler 用、ID 0x10 のみ処理）＋ `wait_apdu_done`（mips_isr を回しながら tag 一致を待つ。tag 不一致は stale として破棄） | dth30-core `vixs/cmd.rs` |
| 7. backend 連携 | **v1 では未実施**（下記「設計との差異」参照） | — |
| 8. CLI | `dth apdu [--channel NAME] [HEX]` を新設。QUERY（状態＋ATR の長・指紋）→ EXCHANGE（応答の長・SW・指紋）を表示。--channel 時は device モードでストリームを開いてから交換し、復号維持を同時計数 | dth-cli `apdu.rs`（新規 413 行） |

単体テスト 2 件追加（`apdu_payloads`: ペイロードレイアウト、`apdu_done_message_is_collected`: MockPci での完了収集）。`cargo test -p dth30-core -p dth-cli` 全通過（159＋10 件）。

## ビルド結果

- ビルドホスト でクロスビルド成功（警告 0）。`dth` sha256 `93010d79…`、`dth30-diag` 同 `755d6a37…`
- **FW イメージ: 25,312 B → 27,552 B（+2,240 B）**、sha256 `b4832713…`。"DTH3" magic・version 1 を確認し、バイナリへ verbatim に埋め込まれていることを確認。
  - 設計の見積もりは「1–2 KB 級」で、実測は上限をやや上回った（+2,240 B）。サイズ制約に触れる値ではない。

## 実機検証（検証ホスト / DT-H30、dth-serve 停止下、テストバイナリは lab 配置のみ）

本番 `/usr/local/bin/dth`（sha256 `81640060…`）は検証前後とも無変更。

1. **QUERY**: カード状態 `0x03`（present, active）。**ATR 13 バイト取得**、sha256 `17c7a75e6d58307495d8417f96a40563c0dc8de671bdd3ca617913cec0a26fc9`（生バイトは保存していない）。
2. **EXCHANGE（合格条件）**: 61 バイト・SW 9000・指紋 `8bb4ef99…` 一致（上記）。
3. **競合確認**: GR27 を device モードでストリームしながら EXCHANGE を発行し、同一指紋で完了。交換後（1 秒の猶予後 3 秒窓）**32,768 パケット中スクランブル 0** で復号維持を確認。交換前窓の 930 個のスクランブルはストリーム開始直後の過渡（鍵未ロード）で、導入時検証の先頭過渡（908 個）と同型であり交換起因ではない。
4. **異常系（物理操作なし）**: 61 バイト APDU → 理由コード **3**、0 バイト → 理由コード **3**。60 バイト APDU（境界）→ 交換完了しカードの SW 6700 を素通しで返却（FW は SW を解釈しない設計どおり）。

## 本番復帰

`dth-serve` を本番バイナリで再起動し、Mirakurun 経由 GR27 を確認: 203,262 パケット・同期 100%・スクランブルは先頭過渡 1,004 個のみ（2000 パケット以降 0）。dth-serve／mirakurun とも active。詳細は restore-check.txt。

## 設計との差異・解釈（勝手に曲げた箇所はないが、明示すべき点）

1. **§9-7（dth30-backend の tag↔oneshot 待ち管理）は v1 では dth30-core 側の待ち合わせで代替**した。設計 §6.1 自体が「待ち合わせは dth30-core の責務」と規定しており、backend/serve 連携は §9-9（v2、serve の常駐セッション共有）が前提のため。serve 経由の APDU 公開は v2 送り。
2. **program.rs は変更不要だった**: card_output の match に既存の `_ => {}` catch-all があり、ApduDone は自動的に無視される（program.rs はカード出力の購読者ではない）。
3. **host.rs は変更不要だった**: M2H ID 定数は cas.rs ローカル定数（MSG_INPUT_DONE と同じ流儀）で足りた。
4. **合計 127 B 超過の扱い**: 受信待ち（Wait）時点で「送信済み＋受信予定＋4 > 127」が判明したら内部フラグを立て、ブロック交換自体は通常経路（完遂または期限＋リトライ）で終わらせてから完了コード 2 を返す実装にした。理由: 現行 pull は mod 128 カウンタの wrap でブロック完遂自体が観測できない場合があり、その場で打ち切ると完了通知の経路まで失うため。外形（コード 2 で返る）は設計どおり。
5. **完了コード 1／3 の実機発火は未検証**: forget／power_cycle の伝播はコード上に実装したが、発火にはカード抜去やリセット操作が要るため実機では踏んでいない（下記「残件」）。

## 残件（ユーザーの合図待ち）

- **カード抜去時の伝播確認**: ストリーム中または APDU 保留中にカードを抜き、(a) 保留 APDU に完了コード 1 の ApduDone が返ること、(b) serve/Mirakurun 側が既存どおり振る舞うこと。物理操作（抜き差し）が要るため未実施。
- v2 候補（設計 §9-9）: serve 常駐セッション経由の APDU 公開、連結応答（61xx/6Cxx の自動継続、完了コード 4 の解消）。いずれも今回の範囲外。
