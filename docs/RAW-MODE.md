# DT-H30 raw モード（ホスト側 b25 復号）

みこすφ（i4M1k0SU）の DTH10-series-driver には、stream のモードが2つある。

- `device`（既定）: 本体の B-CAS カードが1番組を復号し、クリアな TS が返る
- `raw`: 放送そのままの全 TS（PSI はクリア、ES は MULTI2 スクランブル）。**地デジのみ**（衛星系には raw モードがない。DT-H30/U2 は地デジ専用機なので実用上は無関係）

raw を使うと復号はホスト側の仕事になり、Mirakurun の「チューナー＋デコーダ」構成（raw-TS 型チューナーと同じ形）にできる。

## 構成

Mirakurun の tuners.yml で、DT-H30 のエントリを次の形にする。

- command: `dth stream --socket /run/dth/dth.sock -c <channel> --mode raw`
- decoder: b25 ラッパー（本 repo の `tools/b25-decoder`）

カードは、DT-H30 内蔵スロットのものを本 repo の vicc 橋渡し経由で PC/SC リーダーとして使える。libarib25 の b25 は、B-CAS の初期設定（INITIAL_SETTING）に正しく応えた最初のリーダーを自動選択するので、カードの入っているリーダーが選ばれる。

## b25 ラッパー（tools/b25-decoder）

Mirakurun はデコーダをソケット stdio で起動するが、b25 は入出力をパスで開くため、そのままでは接続できない。ラッパーは stdin/stdout を FIFO ペアで橋渡しする。

もう1つの役割が、PC/SC スタックが冷えている間の吸収である（次節）。b25 のカード初期化が失敗しても、一定時間（90秒・最大30回）内は b25 を再起動して stream 全体を落とさない。FIFO の作業ディレクトリは /var/tmp に置く。/tmp が小さい tmpfs の環境では、テスト用 TS などで満杯になるとデコーダが詰まる事故の原因になるためである。

## pcscd のレースと対策

pcscd はアイドル時に自動終了する（`--auto-exit`）。再起動直後の数秒は仮想リーダー（vpcd）の再接続が済んでおらず、その窓で b25 を起動するとカード初期化が `code=-4` で落ちる。対策は2層にする。

1. pcscd を常駐化する（systemd drop-in で pcscd の ExecStart から `--auto-exit` を除去）
2. ラッパー側で b25 の起動失敗をリトライで吸収する

常駐化した後も、pcscd を手動で止めた直後などは初回のデコーダ起動が落ちることがあるが、Mirakurun 側のデコーダ再スポーンと合わせれば復旧する。

## 検証結果

検証ホスト（ARM 機）で確認した内容:

- Mirakurun 経由で GR27／GR22 を取得し、同期 100%・スクランブル 0（開始直後の過渡を除く）
- ライブで raw ストリームを b25 に流し続けても、全区間でスクランブル 0 を維持した。内蔵カードへの ECM 応答は vicc 経由でも実時間に足りる
- EPG も raw 経路で取得できる

device モードとの使い分けは、1番組だけ本体に復号させたいなら device、全 TS をホスト側で扱いたい（複数サービス、EPG、外部リーダーの併用など）なら raw、という形になる。
