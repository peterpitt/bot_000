# 部署：Docker + Supabase

一個容器跑網頁工作台與 API，資料存在 Supabase：

```
瀏覽器 ──(帳密)──► Docker 容器 :8066 ──► Grok（xAI）        產生顧問建議與最小成品
                    │
                    └──(secret key)──► Supabase Postgres
                                        ├ consultancy_proposals     提案紀錄
                                        └ consultancy_firm_events   公司金流事件（只能新增）
```

## 1. Supabase（已完成）

`peterpitt's Project` 已套用 `supabase/migrations/` 的三個 migration：

| 資料表 | 內容 | 保護 |
|---|---|---|
| `consultancy_proposals` | 每次提案的輸入、顧問建議、最小成品 | RLS 開啟、無 policy；anon／authenticated 無權限 |
| `consultancy_firm_events` | 注資、接案、派工、驗收、付款等每個動作 | 同上，另有 trigger 禁止 UPDATE／DELETE（稽核軌跡） |

瀏覽器拿到的 publishable／anon key 讀不到這兩張表；只有伺服器用 **secret key** 能存取。
若要在新專案重建：用 Supabase CLI `supabase db push`，或把三個 SQL 依序貼進 SQL Editor。

## 2. 設定 `.env`

```bash
cp .env.example .env
```

| 變數 | 必填 | 說明 |
|---|---|---|
| `APP_PASSWORD` | ✅ | 網頁登入密碼（帳號預設 `owner`，可用 `APP_USER` 改）。沒設定容器會拒絕啟動 |
| `XAI_API_KEY` | ✅ | Grok 金鑰；沒設定時頁面只顯示範例 |
| `SUPABASE_URL` | ✅ | 已預填 `https://uvjastvnrzbzcssznyum.supabase.co` |
| `SUPABASE_SECRET_KEY` | ✅ | Supabase 後台 → Project Settings → API Keys → **Secret keys**（`sb_secret_...`），或舊版 `service_role` key |
| `XAI_MODEL` | | 預設 `grok-4`，依你帳號可用的模型調整 |
| `FIRM_ID` / `FIRM_NAME` | | 同一個資料庫可放多家公司的帳本 |
| `PYTHON_IMAGE` | | Docker Hub 回 429 時設 `mirror.gcr.io/library/python:3.12-slim` |

`.env` 已在 `.gitignore`，不會被提交。secret key 等同資料庫管理員權限，不要貼進網頁、聊天或 Git。

## 3. 啟動

```bash
docker compose up -d --build
docker compose logs -f        # 應看到「資料保存：supabase；公司帳本已載入 N 筆事件」
```

開 http://127.0.0.1:8066/ ，輸入帳密。左側「最近的提案」上方顯示 **存在 Supabase** 就代表已接上；若顯示「存在伺服器記憶體」表示 Supabase 變數沒讀到。

更新程式：`git pull && docker compose up -d --build`。資料在 Supabase，重建容器不會遺失。

## 4. 給其他電腦連（選用）

compose 預設只綁 `127.0.0.1`。要對外開放：

1. 把 `docker-compose.yml` 的 `"127.0.0.1:8066:8066"` 改成 `"8066:8066"`，或讓反向代理和容器在同一個網路。
2. **前面一定要加 HTTPS**，否則帳密以明文傳送。例如 Caddy（自動申請憑證）：

   ```
   council.example.com {
       reverse_proxy 127.0.0.1:8066
   }
   ```

## 5. 公司帳本 API

所有金額以「元」傳入，日期 `YYYY-MM-DD`（省略 `on` 時用今天，並記進事件）。

```bash
A='-u owner:你的密碼 -H Content-Type:application/json'
curl $A http://127.0.0.1:8066/api/firm                       # 現金、帳戶餘額、派工、付款申請、8 週現金預測
curl $A -d '{"action":"inject_capital","args":{"amount":200000}}' http://127.0.0.1:8066/api/firm/commands
curl $A -d '{"action":"register_company","args":{"id":"nova","name":"新星設計","capabilities":["design"]}}' http://127.0.0.1:8066/api/firm/commands
curl $A -d '{"action":"open_engagement","args":{"client":"晨光咖啡","title":"品牌重塑","milestones":[{"title":"交付","amount":300000,"planned_date":"2026-11-30"}]}}' http://127.0.0.1:8066/api/firm/commands
curl $A -d '{"action":"dispatch_work_order","args":{"engagement_id":"ENG-001","company_id":"nova","title":"品牌視覺","amount":90000,"expected_delivery":"2026-11-15","milestone_id":"ENG-001-M1"}}' http://127.0.0.1:8066/api/firm/commands
```

可用動作：`inject_capital`、`register_company`、`open_engagement`、`invoice_milestone`、`receive_client_payment`、`accept_milestone`、`dispatch_work_order`、`cancel_work_order`、`mark_delivered`、`reject_delivery`、`collect_pass_through`、`accept_work_order`、`approve_payment`、`record_payment`、`remit_withholding`、`settle_vat`。

- 違反金流政策（毛利低於 30%、客戶未付款就要付外包、未經具名真人核准…）回 **422**，帳本不會變動。
- 系統只記帳與產生付款申請，**不會轉帳**；匯款後用 `record_payment` 回填銀行序號。

## 6. 運作細節

- **帳本 = 事件重播**：容器啟動時依 `seq` 重播 `consultancy_firm_events`，還原所有派工、付款與分錄。要更正請新增反向動作，不能改舊事件。
- **只跑一個容器**：兩個容器同時寫同一個 `FIRM_ID` 時，後寫的會收到 **409** 並自動重新載入，再送一次即可。
- **備份**：Supabase 後台的資料庫備份即涵蓋全部資料；也可匯出這兩張表。

## 7. 疑難排解

| 狀況 | 處理 |
|---|---|
| `docker compose build` 出現 `429 Too Many Requests` | `.env` 加 `PYTHON_IMAGE=mirror.gcr.io/library/python:3.12-slim` |
| 容器馬上結束，訊息要求 `APP_PASSWORD` | `.env` 設定密碼 |
| 頁面顯示「存在伺服器記憶體」 | 檢查 `SUPABASE_URL`／`SUPABASE_SECRET_KEY` 是否填寫 |
| API 回 503「Supabase 401／403」 | secret key 錯誤或已撤銷，到後台重新產生 |
| 頁面顯示「本機伺服器未設定 XAI_API_KEY」 | 填 `XAI_API_KEY` 後 `docker compose up -d` |
