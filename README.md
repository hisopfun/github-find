# github-find

追蹤近期 GitHub 熱門項目，每天推送到 Discord 頻道。

## 資料來源

兩個來源互補，各自量的是不同東西：

| 來源 | 取得方式 | 排序依據 | 補的是什麼 |
|---|---|---|---|
| `trending` | 爬 `github.com/trending` | 今日/本週新增星數 | 正在爆紅的項目（含老專案） |
| `search` | GitHub Search API | 總星數 | 近 N 天「新建立」的項目 |

預設 `--source both`：trending 佔 70% 名額，search 佔 30%。

這個配額是刻意的。兩邊的排序軸不能互相比較 —— trending 知道「新增」星數，search 只知道「總」星數。若混在一起排序，trending 會吃光所有名額，新項目永遠不會出現。重複的項目由 trending 勝出（它多帶了新增星數）。

若 trending 頁面改版導致爬蟲失效，`both` 模式會印出警告並自動退回只用 Search API。

## 設定

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

cp .env.example .env   # 填入你的 Discord webhook URL
```

Discord webhook 取得方式：頻道設定 → 整合 → Webhook → 新增 Webhook → 複製 URL。

## 使用

```bash
# 先看看會送出什麼，不會真的發文
python -m github_find.main --dry-run

# 實際推送（需要 DISCORD_WEBHOOK_URL）
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
python -m github_find.main --limit 10

# 只看 Python、本週熱門
python -m github_find.main --language python --since weekly
```

| 參數 | 預設 | 說明 |
|---|---|---|
| `--language` | 全部 | 語言篩選，例如 `python` |
| `--since` | `daily` | `daily` / `weekly` / `monthly`（僅影響 trending） |
| `--source` | `both` | `trending` / `search` / `both` |
| `--days` | `7` | search：只找近 N 天建立的 repo |
| `--min-stars` | `10` | search：最低星數 |
| `--limit` | `10` | 最多推送幾個 |
| `--search-share` | `0.3` | `both` 模式下保留給新項目的名額比例 |
| `--dry-run` | off | 印出來就好，不發送 |

環境變數：`DISCORD_WEBHOOK_URL`（必要，除非 `--dry-run`）、`GITHUB_TOKEN`（選用，把 Search API 速率上限從 10/min 拉到 30/min）。

## 排程

`.github/workflows/trending.yml` 每天 01:00 UTC（台北 09:00）自動推送。

啟用前先到 repo 的 **Settings → Secrets and variables → Actions** 新增 secret `DISCORD_WEBHOOK_URL`。`GITHUB_TOKEN` 由 Actions 自動提供，不用自己設。

也可以在 Actions 頁面手動觸發（workflow_dispatch），支援指定語言與 dry-run。

## 測試

```bash
.venv/bin/python -m pytest -q
```

爬蟲測試用的是 `tests/fixtures/trending.html`（真實抓下來的頁面片段）。GitHub 改版時測試會失敗——這正是我們要的訊號。

## 已知限制

- Trending 頁面沒有官方 API，GitHub 隨時可能改 HTML 結構。
- 沒有做「已推送過」的去重，所以連續幾天都上榜的項目會重複出現。若需要，可加一個 state 檔記錄 `full_name`。
