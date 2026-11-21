# 公開市場歷史資料

每項日資料以 1,000 個有效觀測日為收集目標，保留更早資料。台灣交易日以加權指數日期核對。國際市場使用各來源日期。缺值留白。

- daily.csv 的美債殖利率、SOFR、IORB、TGCR、通膨預期、Single-B OAS 採 FRED 原序列（百分比）。SOFR−IORB 為同日兩個觀測值之差，以基點表示。德國十年債為 Bundesbank 的 BBSSY.D.REN.EUR.A630.000000WT1010.A。MOVE、美元計價的 WTI 及黃金期貨採 Yahoo Finance 的 ^MOVE、CL=F 與 GC=F 日收盤。融資餘額取自證交所 MI_MARGN「今日餘額」，單位億元。
- 黃金現貨獨立保存於 data/gold-xau-usd-daily.csv，沿用 GoldPrice.dev「XAU-USD-SPOT」美元／金衡盎司日收盤。
- taiex-5m.csv 和 sp500-5m.csv 採 Yahoo Finance 指數日內 OHLC，時間戳含各交易所時差。一日內可能只取得部分五分鐘棒。正式日 K 見 public/index-ohlc-history.json。
- macro-releases.csv 依 FRED 原系列代碼與觀測期間保存月報、季報。期間標籤與首次公布日期分開解讀，檔案記錄下載時可取得的修訂值。
- scripts/refresh_extended_history.py 更新可公開的補充日資料、低頻資料與盤中紀錄；已保存的數值優先。既有日資料與盤中快照仍由原收集程式更新。
