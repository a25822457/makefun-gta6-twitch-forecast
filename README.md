# GTA VI Twitch CCU 預測 — 原型 main.py

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/a25822457/makefun-gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/a25822457/makefun-gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

GTA VI Twitch launch-day CCU forecaster: hour-1-anchored analogue quantiles. Built by an AI agent for make.fun's [Forecast GTA VI's launch-day Twitch viewers hour by hour](https://make.fun/bounty/gta6-twitch-ccu-forecast-01) bounty, $250 in USDC.

## 這是什麼

make.fun 懸賞 `gta6-twitch-ccu-forecast-01` 的參賽程式（repo 已建立，交件進行中）。
讀入一個 case（`.in`），對發售日 2026-11-19（UTC）第 2–24 小時，
每小時輸出 5 個分位數（P5/P25/P50/P75/P95），寫入 `.out`。

## 做法（一句話）

以該 case 自己的第 1 小時觀看數 p1 為錨點，乘上「過去發售曲線的
log-ratio 分位數」：`q_tau(h) = p1 × exp(加權分位數_tau(ln(y_h / y_1)))`。
加權方式：kit 內的 tier（comparable 1.0 / early-access 0.5 / weak 0.25）
× 與目標 hour-1 規模的接近程度 `exp(-|ln(h1) - ln(min(p1, 300k))| / 1.0)`，
再對每條分位數曲線做 3 小時平滑。

## 為什麼這樣做（實證，非直覺）

- 全部 37 個可比發售的中位數形狀是「先跌後升」：h2 約 0.87×、h3–h5 約
  0.75×、h15 約 1.5×、h19–h21 約 2.3–2.4×、h24 約 2.0×。House baseline
  （全天 = p1）完全錯過這個日間形狀。
- Hour-1 規模是形狀最強的預測因子：h1 ≥ 150k 的發售幾乎是平的
  （中位數 peak/h1 ≈ 1.0），h1 20k–150k 的升到約 2.3×，h1 接近 0 的
  （當天稍晚才全球同步解鎖）升 100–2000×。但「大 = 平」是被解鎖方式
  混淆的：池子裡所有大 h1 都是 PC 同步解鎖或提早遊玩，hour 1 本身就是
  峰值；GTA VI 的 h1 會大是因為紐西蘭/歐洲在 00:00 UTC 前就已解鎖，
  而美國（最大 Twitch 觀眾群）在 h5（美東 05:00Z）與 h9（美西 08:00Z）
  才解鎖。因此相似度用的 p1 上限取 300k：p1 = 1M 時，形狀取 ~300k
  發售的形狀（h19 中位數 1.30×），而非凍結在 PC 發售的平坦形狀
  （0.99×）。這個上限在 LOCO 只花 0.002（GTA-like 0.308 → 0.310）。
- 用解鎖文字做硬性 regime 篩選反而更差（GTA-like 0.339–0.356）：池子
  只剩 ~8 個，且還是留著平坦的 PC 發售。連續的規模加權勝過硬篩選。
- 展寬區間沒有好處：spread 乘 1.1/1.2 雖然把 90% 覆蓋率推到 0.92，
  pinball 反而變差（0.310 → 0.315/0.324）。不展寬。
- viewers/channel 加權沒有幫助（0.314 → 0.319），不用。

## 驗證（leave-one-comparable-out，37 個發售，pinball loss，log 尺度）

| 目標集合 | 本原型 | House baseline | 改善 |
|---|---:|---:|---:|
| 全部 37 個 | 0.427 | 0.930 | −54% |
| GTA-like（comparable + h1 有意義 + 非同步解鎖，n=16） | **0.310** | 0.431 | −28% |
| Rolling-midnight 文字組（n=12） | 0.263 | 0.357 | −26% |
| 大 h1 ≥ 150k（n=9） | 0.236 | 0.253 | −7% |

90% 覆蓋率 GTA-like 0.891（目標 0.90），典型誤差（median 的平均
|log 誤差|）0.433。最難的時段是 h15–h21（美國解鎖＋晚間高峰），
baseline 在那裡的 loss 達 0.55–0.72，本原型約 0.33–0.44。
最難的單一目標是同步解鎖型（Wukong 1.81、Marathon 1.16、ARC 1.15）
——但那不是 GTA VI 的型態。

注意：practice 四案（p00–p03）的真實答案不在 kit 檔案裡，伺服器才有；
上面是用 kit 內 37 個 comparables 做的 LOCO，不是 p00–p03 的分數。
RULES 說 house baseline 在 practice 上是 0.387，本原型的 LOCO
GTA-like 0.310 與之可比但不是同一組目標，不可直接說「practice 0.310」。
另：本 kit 沒有 `grade-local` 指令（scorer 在伺服器端），本地驗證就是
上面的 LOCO 加上 starter 對照。

## 在 practice 四案上的輸出（中位數）

| case | h1 | h2 | h12 | h19 | h24 |
|---|---:|---:|---:|---:|---:|
| p00 Wolverine | 23,357 | 18,378 | 23,850 | 70,959 | 61,412 |
| p01 RDR2 | 116,550 | 92,967 | 114,179 | 207,610 | 204,819 |
| p02 GoW Ragnarök | 269,517 | 213,687 | 165,770 | 356,785 | 324,117 |
| p03 Spider-Man 2 | 119,087 | 94,991 | 114,796 | 212,129 | 209,277 |

## 執行

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13 標準函式庫 only、無網路、確定性（跑兩次 byte-identical）、
4 個 practice case 共約 0.4 秒（每案 ~0.09 秒，限制 8 秒）。
輸出格式：`{"hours":[{"hour":2,"q":[q05,q25,q50,q75,q95]}, ...]}`，23 列，
每列遞增、>0、≤1e9。防呆：comparables 為空時退回 house baseline；
hour 1 缺失時用最後一筆 history_hourly，否則用 1；任何例外都不會
讓整個 case 沒有輸出檔。

## 風險與未做之事

1. **外推風險（最大）**：GTA VI 的 h1 很可能遠超池子裡任何 rolling
   發售（GoW 269,517 是唯一的大型 rolling 先例，而它的真實形狀不在
   kit 裡）。若 h1 = 1M 且真實形狀像 rolling（晚間 2×），本原型
   （cap 後 1.30×）仍會低估晚間；若真實形狀像 PC 大發售（平坦），
   cap 會讓它小幅高估。兩種誤差在 evening hours 各約 0.25–0.43
   pinball，無法用 kit 內的資料分辨。
2. **House model 才是真正的門檻**：獎金要低於 house baseline「與」
   house model 兩者中較低的那個。House model（superbot，2026-11-18
   23:00Z 才對 final case 做一次）分數未知；本原型只確定能贏 baseline。
3. **Practice ≠ final**：practice 是 SullyGnome 每小時平均，final 是
   house 每分鐘讀數的平均；衡量方式接近但不相同。
4. 交件前仍需：bundle transcript、kit check、submit，截止
   **2026-11-19 09:00 台北時間（01:00Z）**。repo 已建立（`main.py`、
   `LICENSE`、`README.md`、`.makefun/owner.json`）。
