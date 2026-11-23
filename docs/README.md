# docs/ について

調査時の設計・実装・検証の報告書群（自作文書）。公開にあたり、ホスト名・
IP アドレス・自宅固有のパスは一般化してあります。文書中の「証拠」として
触れる実験ログ・ダンプ類は本 repo には含まれません。記述中のパス
（artifacts/ 等）は、調査時の研究アーカイブ側の配置を指します。

- **FINDINGS-SUMMARY.md** — 解析で確定した事実の要約（まずこれを読むと全体像が掴めます）
- APDU-CMD-DESIGN.md — CFW への APDU コマンド（cmd 28）の設計
- APDU-IMPL-REPORT.md — cmd 28 の実装報告と実機検証
- APDU-V2-REPORT.md — serve 常駐ソケット経由の APDU 連携（v2）
- BUILD.md — 互換スタックのビルド実測
- DESK.md — 互換スタック試行の机上準備（コマンド棚卸し・デバイス状態遷移）
- VICC-DESIGN.md / VICC-REPORT.md / VICC-FIX-REPORT.md — PC/SC 橋渡しの設計・導入・詰まり修正
- cfw-audit/ — 純正ファーム監査と APDU 後付け設計の文書（Mode Q の前提資料）
