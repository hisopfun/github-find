# Dev Log

## 2026-07-10 — 初版：GitHub 熱門項目 → Discord

**Model:** Claude Opus 4.8 (1M context)

實作雙來源熱門項目追蹤，透過 Discord webhook 推送，GitHub Actions 每日排程。

### 決策

- **雙來源**：`github.com/trending` 爬蟲（唯一能拿到「新增星數」的地方）+ Search API（穩定、能找出近期新建的 repo）。trending 失效時自動退回 Search API。
- **Webhook 而非 bot**：不需要互動查詢，webhook 無需長駐程序。
- **解析與 HTTP 分離**：`parse_trending(html)` 是純函式，可用真實 HTML fixture 測試。

### 過程中發現並修掉的問題

1. **`--source both` 實際上等於 `trending only`**
   症狀：dry-run 顯示 10 筆全是 trending，search 結果一筆都沒進來。
   原因：`merge()` 用 `(stars_gained or 0, stars)` 排序，而 search 結果的 `stars_gained` 永遠是 `None` → 視為 0，永遠排在所有 trending 之後。兩個來源的排序軸根本不能互相比較。
   修法：新增 `combine()`，用配額（預設 search 佔 30% 名額）取代單一排序；search 名額不足時從 trending backfill，避免少貼。

2. **Actions workflow 有 shell injection**
   `${{ inputs.language }}` 直接插進 `run:` 字串。改為透過 env 傳遞 + bash 陣列 `"${args[@]}"`。

3. **`bash -e` 下 `[ -n "$X" ] && args+=(...)` 會讓 step 失敗**
   Actions 預設 shell 是 `bash -e`；條件不成立時該行回傳 1，整個 step 直接中止。改用 `if ... fi`。

### 驗證

- `pytest -q` → 16 passed。爬蟲測試跑在真實抓下來的 HTML fixture 上。
- `--dry-run` 打真實 GitHub：trending 與 search 各自可用，`both` 得到 7 + 3 的組合。
- Discord 送出路徑：起本機 HTTP server 當假 webhook，用真正的 `requests.post` 驗證 payload 結構、10-embed 上限、6000 字上限。
- Workflow 腳本：用 `bash -e` 模擬 schedule / dispatch / 注入字串三種情境。

### 尚未做

- 沒有「已推送過」的去重，連日上榜的項目會重複出現。需要的話加一個 state 檔記 `full_name`。
