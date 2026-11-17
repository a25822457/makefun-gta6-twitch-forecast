# GTA VI Twitch CCU 預測 — v6 main.py（v2 + regime switch）

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/a25822457/makefun-gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/a25822457/makefun-gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

GTA VI Twitch launch-day CCU forecaster: hour-1-anchored analogue quantiles, with a size regime switch. Built by an AI agent for make.fun's [Forecast GTA VI's launch-day Twitch viewers hour by hour](https://make.fun/bounty/gta6-twitch-ccu-forecast-01) bounty, $250 in USDC.

## 這是什麼

make.fun 懸賞 `gta6-twitch-ccu-forecast-01` 的參賽程式 v6（v1 已於
2026-11-17 交件，practice 榜約 #1975，loss 約 0.22；v2 是針對 practice
落後做的改進，尚未交件；v6 = v2 加上 p1 ≥ 200k 時的每小時 log-h1
迴歸，準備重交）。
讀入一個 case（`.in`），對發售日 2026-11-19（UTC）第 2–24 小時，
每小時輸出 5 個分位數（P5/P25/P50/P75/P95），寫入 `.out`。

## 做法（一句話）

以該 case 自己的第 1 小時觀看數 p1 為錨點，乘上「過去發售曲線的
log-ratio 分位數」：`q_tau(h) = p1 × exp(加權分位數_tau(ln(y_h / y_1)))`。
加權方式：kit 內的 tier（comparable 1.0 / early-access 0.5 / weak 0.25）
× 與目標 hour-1 規模的接近程度 `exp(-|ln(h1) - ln(p1)| / 1.0)`
× 平台相似度（目標與可比發售的 console-only 狀態相同時 ×e^0.5，
不同時 ×e^-0.5；目標的 console-only 從 case notes 解析，四個
practice 案都正確判為 console-only），再對每條分位數曲線做 3 小時平滑。
v1 的 300k p1 上限在 v2 拿掉了（見下）。

## v6 的改動：p1 ≥ 200k 時改用每小時迴歸

當目標的 hour-1 印出值 p1 ≥ 200,000 時，分位數改由「每小時 log-h1
迴歸」產生：每小時對 `ln(y_h/y_1)` 對 `ln(h1)` 做加權迴歸（權重與
v2 分支完全相同：tier × 規模核 × console-only 核），斜率向全部小時
的 pooled 斜率收縮，收縮係數 alpha = 1.0（即不收縮——v4 測過
alpha = 0.5 / 0.75，結果相同）；中位數是迴歸線在 `ln(p1)` 的擬合值，
區間寬度取該小時殘差的加權分位數；之後一樣做 3 小時平滑、排序、
四捨五入、夾限。p1 < 200k 時與 v2 一字不改。

為什麼：迴歸在兩端（很大、很小 hour-1）贏過分位數，在中段輸；
GTA VI 的 h1 幾乎確定 ≥ 200k，所以只在大的那一端切換。LOCO（見下表）
GTA-like 0.299 → 0.292、rolling 0.251 → 0.240、practice-like
0.188 → 0.173、big-h1 0.215 → 0.200、整體 0.413 → 0.410；MID
（20k–150k）不變 0.279，因為那一端沒有切換。v4 還試過門檻
150k / 100k / 300k、迴歸中位數 + v2 區間、ramped 混合，GTA-like
最好就是 0.292；v3 的全域迴歸（不分段）GTA-like 是 0.314，比 v2 差。

已知疑慮（沒有修掉，使用者知情後仍選擇此版）：合成測試 h1 = 1M、
rolling console-only 目標時，v6 預測 h19 中位數只有 **0.88×**
（v2 為 1.25×）。迴歸斜率由大型 PC 同步發售主導——它們的 hour 1
本身就是峰值——線性外推到 1M 會把晚間壓到 hour 1 以下；但 GTA VI
的 hour 1 還不含美國觀眾（美東 h5–h6、美西 h8–h9 才加入），晚間理
應上升，且池子唯一的大型 rolling console-only 先例 The Last of Us
Part II（h1 365,019）的真實 h19/h1 是 1.31。LOCO 的進步來自 PC 大
發售的平坦形狀，不是決賽的型態。沒有加 floor、cap 或混合來「修」
這個外推，因為那會是未經測試的改動。

## 為什麼這樣做（實證，非直覺）

- 全部 37 個可比發售的中位數形狀是「先跌後升」：h2 約 0.87×、h3–h5 約
  0.75×、h15 約 1.5×、h19–h21 約 2.3–2.4×、h24 約 2.0×。House baseline
  （全天 = p1）完全錯過這個日間形狀。
- Hour-1 規模是形狀最強的預測因子：corr(log h1, log(h19/h1)) = −0.93。
  h1 ≥ 150k 的發售幾乎是平的（中位數 peak/h1 ≈ 1.0），h1 20k–150k 的
  升到約 2.3×，h1 接近 0 的（當天稍晚才全球同步解鎖）升 100–2000×。
- v1 曾把相似度用的 p1 上限取 300k，理由是池子裡所有大 h1 都是 PC
  同步解鎖或提早遊玩，hour 1 本身就是峰值；GTA VI 的 h1 會大是因為
  紐西蘭/歐洲在 00:00 UTC 前就已解鎖，而美國（最大 Twitch 觀眾群）
  在 h5（美東 05:00Z）與 h9（美西 08:00Z）才解鎖。v2 拿掉上限，因為
  加入 console-only 相似度後，上限已不改變 1M hour-1 的預測形狀
  （h19 中位數：有上限 1.30×、無上限 1.25×——console-only 發售而非
  平坦的 PC 發售主導了加權中位數），而拿掉它在 LOCO 六個子集上
  全部變好（見下表）。
- Console-only 相似度是 v2 唯一通過門檻的新特徵（強度 0.5；1.0 在
  practice-like 上反而變差）。Rolling 文字相似度沒有幫助。
- 用解鎖文字做硬性 regime 篩選反而更差（GTA-like 0.339–0.356）：池子
  只剩 ~8 個，且還是留著平坦的 PC 發售。連續的規模加權勝過硬篩選。
- 展寬區間沒有好處：spread 乘 1.1/1.2 雖然把 90% 覆蓋率推到 0.92，
  pinball 反而變差（0.310 → 0.315/0.324）。不展寬。逐小時覆蓋率已在
  0.88–1.00，loss 集中在 h13–h17 的中位數誤差（0.51–0.60），是形狀
  分散而非區間太窄。
- viewers/channel 加權沒有幫助（0.314 → 0.319），不用；log(viewers/
  channel) 與 log(h19/h1) 的相關只有 −0.15，遠低於 log(h1) 的 −0.93。

## 驗證（leave-one-comparable-out，37 個發售，pinball loss，log 尺度）

| 目標集合 | v1 | v2 | v6（本版） | House baseline |
|---|---:|---:|---:|---:|
| 全部 37 個 | 0.427 | 0.413 | **0.410** | 0.930 |
| GTA-like（comparable + h1 有意義 + 非同步解鎖，n=16） | 0.310 | 0.299 | **0.292** | 0.431 |
| Rolling-midnight 文字組（n=12） | 0.263 | 0.251 | **0.240** | 0.357 |
| Practice-like（rolling + console-only + h1 有意義，n=4） | 0.200 | 0.188 | **0.173** | — |
| 大 h1 ≥ 150k（n=9） | 0.236 | 0.215 | **0.200** | 0.253 |
| 中 h1 20k–150k（n=18） | 0.284 | 0.279 | 0.279 | — |

v6 的 LOCO 數字是直接對本版 `main.py` 完整程式（讀入真實 case 檔、
走 `forecast_case`）重跑驗證的，與 v4 實驗程式的數字在小數三位
完全一致；同樣的驗證程式對 v2 也重現了 0.413 / 0.299 / 0.251 /
0.188 / 0.215。LOCO 裡切換到迴歸分支的目標有 6 個（h1 ≥ 200k）。

90% 覆蓋率 GTA-like 0.91（目標 0.90），典型誤差（median 的平均
|log 誤差|）0.42。最難的時段是 h13–h17（下午爬升，美國解鎖時間不一），
baseline 在那裡的 loss 達 0.55–0.72，v2 約 0.37–0.41。
最難的單一目標是同步解鎖型（Wukong 1.81、Marathon 1.16、ARC 1.15）
——但那不是 GTA VI 的型態。

注意：practice 四案（p00–p03）的真實答案不在 kit 檔案裡，伺服器才有；
上面是用 kit 內 37 個 comparables 做的 LOCO，不是 p00–p03 的分數。
v1 在 practice 榜約 #1975（loss 約 0.22），與 LOCO practice-like
0.200 一致；v2 的 LOCO practice-like 是 0.188，practice 榜第一名約
0.10——池子裡的資訊不足以把任何發售的曲線預測到 0.10，v2 能做的
就是上面這張表裡的改進。RULES 說 house baseline 在 practice 上是
0.387。本 kit 沒有 `grade-local` 指令（scorer 在伺服器端），本地驗證
就是上面的 LOCO 加上 starter 對照。

## v2 試過、沒採用的東西

- **逐小時校正**（LOCO 中位數殘差，nested）：rolling 擬合、shrink 0.5
  時 GTA-like 只進步 0.005（0.310 → 0.305），且 BIG 變差
  （0.236 → 0.247）；gta-like 擬合時 GTA-like 反而變差。殘差雖有
  系統性（GTA-like 在 h19 +0.28），但用 11–16 個殘差估出的校正太吵。
- **頻寬掃描**：0.5 / 0.75 / 1.5 / 2.0 都沒有比 1.0 好（GTA-like
  0.338 / 0.324 / 0.315 / 0.323）；無頻寬（全部等權）0.390。
- **內插加權分位數、高斯核平滑分位數**：與階梯分位數幾乎相同
  （GTA-like 0.308 / 0.300），核平滑還慢 4 倍。不採用。
- **小池子**（只用 rolling+console-only 等 3–4 個可比發售）：ALL
  0.79–0.90，覆蓋率掉到 0.46。池子太小，區間整個垮掉。
- **viewers/channel 核**：見上，不採用。**Tier 權重微調**：無一勝過
  1.0 / 0.5 / 0.25。**5 小時平滑 / 不平滑**：與 3 小時相同。
- **Practice 榜第一名的 0.10**：無法用 LOCO 驗證的方法重現；practice
  四案都是 Sony/Rockstar 單人 rolling 大作，彼此形狀可能比池子裡的
  practice-like 發售更接近，但 comparables 沒有 publisher 欄位，
  無法在 LOCO 裡測試 publisher 匹配，所以不寫進程式。

## 在 practice 四案上的輸出（中位數，v6）

| case | h1 | h2 | h12 | h19 | h24 |
|---|---:|---:|---:|---:|---:|
| p00 Wolverine | 23,357 | 17,354 | 23,468 | 71,852 | 61,412 |
| p01 RDR2 | 116,550 | 90,418 | 113,128 | 242,185 | 232,838 |
| p02 GoW Ragnarök | 269,517 | 205,068 | 179,431 | 396,021 | 358,907 |
| p03 Spider-Man 2 | 119,087 | 92,387 | 115,591 | 247,457 | 237,906 |

（p00、p01、p03 與 v2 完全相同，因為 h1 < 200k、沒有切換；只有
p02（h1 269,517）走了迴歸分支，所以它的 h2/h12/h19/h24 都變了。
v2 的 p02 是 205,707 / 248,185 / 395,942 / 400,428。）

## 執行

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13 標準函式庫 only、無網路、確定性（跑兩次 byte-identical）、
4 個 practice case 共約 0.25 秒（每案 ~0.06 秒，限制 8 秒）。
輸出格式：`{"hours":[{"hour":2,"q":[q05,q25,q50,q75,q95]}, ...]}`，23 列，
每列遞增、>0、≤1e9。防呆：comparables 為空時退回 house baseline；
hour 1 缺失時用最後一筆 history_hourly，否則用 1；任何例外都不會
讓整個 case 沒有輸出檔。

## 風險與未做之事

1. **外推風險（最大）**：GTA VI 的 h1 很可能遠超池子裡任何 rolling
   發售（GoW 269,517 是唯一的大型 rolling 先例，而它的真實形狀不在
   kit 裡）。合成測試：h1 = 1M、rolling console-only 目標時，**v6 預測
   h19 中位數只有 0.88×**（v2 為 1.25×），h20 0.87×、h21 0.84×——
   晚間低於 hour 1；見「v6 的改動」一節的說明。這個疑慮沒有修掉，
   是使用者知情後的選擇。池子裡唯一的大型 rolling console-only 先例
   是 The Last of Us Part II（h1 365,019，真實 h19/h1 = 1.31），v6
   在它上面的 LOCO 是 0.174（v2 為 0.161）——單一案例的差距，在整體
   BIG 子集上 v6 較好（0.200 vs 0.215）。
2. **House model 才是真正的門檻**：獎金要低於 house baseline「與」
   house model 兩者中較低的那個。House model（superbot，2026-11-18
   23:00Z 才對 final case 做一次）分數未知；v2 只確定能贏 baseline。
3. **Practice ≠ final**：practice 是 SullyGnome 每小時平均，final 是
   house 每分鐘讀數的平均；衡量方式接近但不相同。v1 的 practice 榜
   約 #1975（loss 約 0.22）不等於決賽名次，決賽只看 11/19–11/20 的
   單一 final case。
4. v6 尚未交件：bundle transcript、kit check、submit，截止
   **2026-11-19 09:00 台北時間（01:00Z）**。repo 已建立（`main.py`、
   `LICENSE`、`README.md`、`.makefun/owner.json`），v1 的交件為
   submission 01a1e907（commit d0b2d0b）；v2（bundle v4、檢查 13 項
   全過）是上一版候選，v6 取代它成為本次重交的版本。
