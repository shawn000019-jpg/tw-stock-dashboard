# 台股追蹤 Dashboard V3

這一版採用 GitHub Actions 雲端更新，解決本機瀏覽器直接抓 CMoney / 財報狗 / MOPS / Goodinfo / MoneyDJ 時的 CORS 問題。

## 資料來源
- MOPS：官方公告 / 財報來源
- 財報狗：EPS / PE / ROE
- Goodinfo：法人 / 歷史統計補充
- CMoney：熱門度 / 市場情緒
- MoneyDJ：新聞 / 產業事件

## 自動更新
GitHub Actions 每個交易日台北時間約 20:30 更新 `data/latest.json`。

## 預設追蹤
- 4556 旭然
- 7556 意德士
- 5297 廣化
- 7887 宇川精材
- 3680 家登

抓不到的資料會保留空白，不會捏造。
