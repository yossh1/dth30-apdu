# VICC-REPORT — vicc（PC/SC 橋渡し）実装報告

実施: 2026-11-23（ユーザー承認「vicc以降」）。設計は `VICC-DESIGN.md`、
証拠は `../artifacts/vicc-20261123/`。

## 1. 実装物

| 物 | 場所 |
|---|---|
| 橋渡しスクリプト | 検証ホスト `/usr/local/lib/dth-vicc/dth_vicc.py`（原本は本ディレクトリ `vicc/dth_vicc.py`） |
| systemd unit | 検証ホスト `/etc/systemd/system/dth-vicc.service`（enabled、Restart=always。本ディレクトリ `vicc/dth-vicc.service`） |
| 導入パッケージ | `pcscd` 2.3.3-1、`vsmartcard-vpcd`／`vsmartcard-vpicc`／`python3-virtualsmartcard` 3.3+dfsg-2（vicc 0.8）、`python3-pycryptodome` 3.20.0+dfsg-3、`pcsc-tools`、`python3-pyscard` 2.2.2-1 |

構成: PC/SC → pcscd → vpcd（localhost:35963）→ VirtualICC＋自作
`DthCardOS` → `/run/dth/dth.sock` の `apdu query`／`apdu data=` →
dth serve v2 → コマンド 28 → カード。上流の RelayOS と同型で、
背後だけを pyscard から dth ソケットへ差し替えた。
設計からの変更点は Debian 導入版への適応のみ（VICC-DESIGN.md §8）:
sys.path 補完、`Crypto`→`Cryptodome` エイリアス、工場生成タイプは
`iso7816`（HandlerTest.py がパッケージに無いため）。

## 2. 検証結果（すべて効果側、カード抜き差しなし）

同時期ベースライン（`dth apdu --socket`、検証直前に取得）:
ATR 13 バイト・指紋 `17c7a75e6d58307495d…`、INITIAL_SETTING
（`9030000000`）応答 61 バイト・SW 9000・指紋 `e0d3ff05912f43815b…`。

1. **OS 単体**（`vicc/os_smoke_test.py`、証拠 `os-smoke.log`）:
   QUERY 状態 0x03、getATR 13 バイト・指紋がベースラインと完全一致。
   EXCHANGE は 61 バイト・SW 9000・指紋完全一致。61 バイト APDU は
   reason 3 の写像どおり SW `6700`。
2. **PC/SC 経由**（`vicc/pcsc_check.py`、証拠 `pcsc-after-reboot.log`
   ほか）: リーダー `Virtual PCD 00 00` が現れ、在席・ATR 13 バイト・
   指紋一致。INITIAL_SETTING は 61 バイト・SW 9000・指紋一致。
   61 バイト APDU はデータなし SW `6700`（理由が PC/SC 層まで伝播）。
3. **共存**（証拠 `coexist.log`）: Mirakurun GR27 ストリーム中に
   PC/SC 経由で ATR＋INITIAL_SETTING＋61 バイト送信をすべて完了
   （指紋一致、`6700`）。TS 343,802 パケット・同期 100%・
   スクランブル 926 個は先頭 934 パケット以内の過渡のみ
   ＝ 5,000 以降 0 で復号維持。
4. **再起動復帰**（証拠 `services.log`、`pcsc-after-reboot.log`）:
   検証ホスト を実際に再起動し、dth-serve／pcscd／dth-vicc／mirakurun の
   全 active を確認。再起動後の PC/SC 一式も指紋一致で再現し、
   GR27 は 257,534 パケット・同期 100%・スクランブルは先頭 945
   以内のみ。

## 3. 残件・申し送り

- 抜去時の PC/SC 振る舞い（在席→不在の遷移、保留中 Transmit の
  帰結）は未確認。次段でユーザーの合図（抜き差し）を取って確認する。
- vpcd の第2スロット `Virtual PCD 00 01` は常時カードなし（上流既定）。
- ローカルユーザーは誰でも仮想リーダー経由で APDU を送れる
  （pcscd 既定の信頼境界。OPS.md に明記済み）。
