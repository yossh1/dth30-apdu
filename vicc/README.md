# vicc — DT-H30 の B-CAS カードを PC/SC リーダーとして公開する橋渡し

`dth serve` の APDU ソケットを backend にし、vsmartcard の vicc/vpcd を
介して DT-H30 の内蔵カードを標準 PC/SC リーダーとして見せるためのブリッジです。

- **ライセンス: GPL-3.0-or-later**（このディレクトリのみ。LICENSE 参照）
- 依存: pcscd、vpcd、python3-virtualsmartcard（vsmartcard 0.8 で検証）、
  および driver-apdu の `dth serve`（APDU ソケット）
- 配置例: `dth_vicc.py` を `/usr/local/lib/dth-vicc/` に置き、
  `dth-vicc.service` を systemd に登録します。在席はブリッジ側がポーリングし、
  カードがある間だけ vpcd と接続します（抜去・再挿入は PC/SC の
  REMOVED / INSERTED として伝播します）。
- 設計と詰まり修正の詳細: ../docs/VICC-DESIGN.md、../docs/VICC-FIX-REPORT.md

`pcsc_check.py` / `pcsc_monitor.py` は動作確認用、`coexist_test.sh` は
視聴ストリームとの共存確認用スクリプトです。
