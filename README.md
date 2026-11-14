# 珍寶投顧 | Personal CIO Desk — Public Market Dashboard

這是公開市場儀表板，只顯示總經、台美市場、籌碼、信用利差、流動性和 AI 算力指標。

## 隱私
- `public/` 僅包含公開市場資料，**不包含私人投資組合、個人交易、持股或資產淨值**。
- 私人投組 Dashboard 留在使用者裝置上，不部署到此儲存庫。
- 任何提交到公開 GitHub 儲存庫的檔案本身也是公開的；請勿將私人資料放進其他目錄。

## 部署
- GitHub Pages：Settings → Pages → Build and deployment → Source 選擇 **GitHub Actions**。
- `.github/workflows/pages.yml` 在 `main` 更新公開檔案時，先驗證資料、再只部署 `public/`。
- 預期固定網址：`https://kevintaiwan.github.io/KevinTaiwan-jenbao-dashboard/`（必須在首次部署成功後才算有效）。

## 更新
1. 完成「分析今天數據」，只選出來源可核對、允許公開的市場數據。
2. 更新 `public/market-data.json`；未知值保持 `null`，不可把私人完整 `daily-data.json` 貼入。
3. GitHub Action 會驗證公開 JSON 並重新部署；網頁每 5 分鐘檢查新版資料。
4. 首次仍須啟用 GitHub Pages 的 GitHub Actions Source。

本網站為市場研究資訊，不構成個人化投資指令。
