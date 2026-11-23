# VICC-DESIGN — DT-H30 のカードを PC/SC リーダーとして見せる橋渡し

作成: 2026-11-23（ユーザー承認「vicc以降」に基づく）
一次情報: frankmorgner/vsmartcard 公式リポジトリ（master を clone して精読）、
dth 側は本プロジェクトの dth-proto／dth-cli ソース。

## 1. 構成

```
PC/SC クライアント (pyscard / opensc-tool / pcsc_scan)
  → pcscd (Debian pcscd 2.3.3)
  → vpcd (IFD ハンドラ, Debian vsmartcard-vpcd)
  → TCP localhost:35963（2バイト BE 長 + ペイロード、制御は1バイト）
  → vicc (VirtualICC, Debian vsmartcard-vpicc) + 独自 SmartcardOS
  → Unix ソケット /run/dth/dth.sock（行プロトコル、1要求1接続）
  → dth serve v2 → コマンド 28 → DT-H30 内蔵 B-CAS カード
```

## 2. 実現手段の選定（一次情報に基づく）

- vsmartcard は「仮想リーダー (vpcd) + 仮想カード (vicc)」の標準構成。
  実カードを背負う vicc は上流自身に前例がある: `cards/Relay.py` の
  `RelayOS` が `SmartcardOS` を継承し、`getATR / powerUp / powerDown /
  reset / execute` を pyscard 経由の実カードへ中継している。
  本件はこの背後を pyscard ではなく **dth serve ソケット**に差し替えた
  同型の実装とする（最も素直な手段）。
- vicc の `--type` は固定の選択肢（iso7816/cryptoflex/ePass/nPA/relay/
  handler_test）で、外部クラスの動的ロード機能はない
  （`vicc.in`、`VirtualSmartcard.py` の `VirtualICC.__init__` で確認）。
  そのため起動ランチャが `VirtualICC` を生成（vpcd への接続までを
  上流コードに任せる）し、`run()` の前に `vicc.os` を自作 OS に
  差し替える。工場生成された OS は使われない。
- 接続方向: Debian の vpcd 既定設定は `DEVICENAME /dev/null:0x8C7B` で、
  ifd-vpcd は hostname=NULL ＝**サーバモード**（35963 で待ち受け）。
  vicc は既定（非 reversed）で localhost:35963 へ接続する。上流既定どおり。
- 検証ホスト（Armbian/Debian 13 trixie, armv7l）には全て apt パッケージがある:
  `pcscd` 2.3.3-1、`vsmartcard-vpcd`、`vsmartcard-vpicc`、
  `python3-pyscard` 2.2.2-1、`pcsc-tools`。ソースビルドは不要。

## 3. 在席と ATR

- vpcd の在席判定 `vicc_present()` は「vicc へ接続でき、かつ
  `vicc_getatr()`（制御コード 4）が 1 バイト以上を返す」こと
  （vpcd.c で確認）。pcscd のポーリングのたびに ATR 要求が来る。
- 自作 OS の `getATR()` は dth ソケットへ `apdu query` を発行し、
  状態 bit0（在席）・bit1（活性化済）が立ち ATR が非空のときだけ
  ATR バイト列を返す。満たさなければ空を返し、リーダーは
  「カードなし」を報告する。
- ポーリング吸収のため QUERY 結果は最大 1 秒キャッシュする
  （serve 側の QUERY 自体もキャッシュ応答で軽い）。

## 4. APDU 中継

- `execute(msg)` は受けたバイト列をそのまま `apdu data=<hex>` で送り、
  `ok <serial> apdu=<hex>` の応答をそのまま返す。
  **61xx／6Cxx 等の連結応答はリーダー層では自動処理しない**（素通しが
  正しい。GET RESPONSE の追随は PC/SC クライアントの仕事）。
- カードへ届かなかった失敗は、実リーダーの伝送失敗に相当するので
  SW のみの応答に写像する（`execute()` で例外を上げると
  `VirtualICC.run()` に受け手がなくデーモンが死ぬため、例外は禁止）:
  - reason 3（長さ不正: 0 バイトまたは 61 バイト以上）→ `6700`
  - reason 1（活性化済カードなし）→ `6985`
  - reason 2（busy）→ 200ms 間隔で最大 5 回再試行 → `6F00`
  - reason 4、その他の error/busy 応答、完了コード≠0
    （1=抜去、2=交換失敗、3=リセット横取り、4=連結応答未対応）→ `6F00`
  - dth ソケット不達 → `6F00`
  いずれも理由はデーモンのログに残す。
- 継承する制限: 送信 APDU ≤60 バイト、送受信合計 ≤127 バイト
  （合計超過は交換自体は行われるが完了コード 4 で届けられず `6F00`）。

## 5. 電源・リセットの扱い

`powerUp / powerDown / reset` は **no-op**（ログのみ）。
実カードのセッションは dth serve が所有し、チューナーの ECM 処理と
共有している。PC/SC 側の電源操作で実カードをリセットすると視聴側を
壊すため、エミュレーションに留める（ATR は不変で再提示される）。

## 6. 常駐と信頼境界

- systemd `dth-vicc.service`（root で実行、After=pcscd.service
  dth-serve.service、Restart=on-failure）。スクリプトは
  `/usr/local/lib/dth-vicc/dth_vicc.py`。
- dth ソケットは root:dth 0660 のまま。橋渡しが root で動くことで
  アクセスする。PC/SC 側は pcscd の既定（ローカルアクセス可）に
  従うため、検証ホスト のローカルユーザーは誰でもこの仮想リーダー経由で
  60 バイトまでの任意 APDU をカードへ送れる。これは dth グループと
  同じ信頼ドメインとみなす（OPS.md に明記）。

## 7. 検証計画（カード抜き差しなし）

1. リーダー一覧に仮想リーダーが現れ、在席・ATR 13 バイト・指紋が
   同時期ベースライン（`dth apdu --socket` で取得、見込み `17c7a75e…`）
   と一致。
2. pyscard 経由で INITIAL_SETTING（`9030000000`）→ 61 バイト・
   SW 9000・指紋が同時期ベースライン（見込み `e0d3ff05…`）と一致。
3. 共存: Mirakurun GR27 ストリーム中に PC/SC 経由 APDU が完了し、
   TS は先頭過渡のみスクランブル（5,000 パケット以降 0）。
4. 61 バイト APDU が PC/SC 経由で `6700` として返る（理由の伝播）。
5. 検証後に dth-serve／Mirakurun GR27 が通常動作に戻ること。

抜去時の PC/SC 振る舞い（在席→不在の遷移）は本ラウンド対象外
（ユーザーの合図を取ってから別途確認）。

## 8. 導入時に判明した差異（2026-11-23、実物で確認）

- Debian の導入版は vicc 0.8（パッケージ 3.3+dfsg-2）。master との
  差異: `__sendToVPICC` は bytes 前提（str 連結の分岐なし）→
  `getATR()`／`execute()` は bytes を返すこと（本実装は bytes で統一）。
  run() の制御コード分岐・`handler_test` 種別・`logginglevel` 引数は
  master と同等だった。
- `python3-virtualsmartcard` のモジュール配置は
  `/usr/lib/python3/site-packages/virtualsmartcard/virtualsmartcard/` で、
  既定の sys.path に無い。ランチャ側で ImportError 時に当該パスを
  補って取り込む（unit の Environment には依存しない）。
- CryptoUtils は PyCrypto（`Crypto` 名前空間）を要求するが、Debian の
  pycryptodome は `Cryptodome` 名前空間で入る。`python3-pycryptodome`
  を追加導入し、ランチャ側で `sys.modules["Crypto"] = Cryptodome` の
  エイリアスを張って解決（フォールバック側の `import sha` は
  Python 2 専用で使えない）。
- Debian パッケージには `cards/HandlerTest.py` が含まれないため、
  工場生成タイプは `handler_test` ではなく既定の `iso7816` を使う
  （生成 OS は run() 前に差し替えるので動作に影響しない）。
- vpcd はリーダーを2スロット提示する（`Virtual PCD 00 00` /
  `00 01`）。実カードに繋がるのは 35963 側の `00 00` のみで、
  `00 01` は常時カードなしを報告する（上流既定の挙動、そのまま使う）。
