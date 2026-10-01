# 宇宙行星顧問團隊公司（bot_000）

把 `prompts/grok_manu_bot_001.md` 的「一人公司頂級 AI 專家智囊團」做成一家**可以接案、下派工作給其他公司、並管控金流**的顧問團隊公司。

- **12 行星顧問 → 6 個部門**，業主是唯一核准者（[組織章程](docs/organization.md)）
- **派工到其他公司**：關係企業、外部公司、個人工作者；支援「轉包」與「代收代付」兩種模式
- **金流引擎**：複式記帳、毛利底線、Pay-when-paid、安全準備金、保留款、營業稅與代扣繳、週現金預測（[金流設計](docs/cashflow.md)）
- **智囊團召集器**：自動分流、挑 4–6 位顧問、把公司即時財務狀態放進 Grok 的 system prompt
- 純 Python 3.10+ 標準函式庫，無外部套件

## 網頁工作台

`web/index.html`：輸入想法 → 自動分流召集 4–6 位顧問 → 星際激辯、戰略收斂、7/30/90 天藍圖、派工與金流表（自動檢查 30% 毛利底線）→ 串流產出可直接使用的最小成品（可複製／下載 .md）。

- **線上版**：發布為 claude.ai Artifact，用你的 Claude 帳號額度執行，免設定。
- **本機版**：`python -m consultancy serve` 後開 http://127.0.0.1:8066/ ，AI 呼叫轉給 Grok（需 `XAI_API_KEY`）。
- 最近 8 筆提案只存在你的瀏覽器裡。

## 快速開始

```bash
python -m consultancy org        # 組織架構
python -m consultancy demo       # 30 萬案子拆給 3 家公司，跑完整金流
python -m consultancy ask "要不要把網站專案外包？報價和現金流怎麼抓" --with-demo-books
python -m consultancy serve      # 網頁工作台（本機 Grok）
python -m unittest discover -s tests
```

`ask` 預設離線（只回召集名單與骨架）。要接 Grok：

```bash
export XAI_API_KEY=...        # xAI API 金鑰
export XAI_MODEL=grok-4       # 選用，依你帳號可用的模型調整
```

只想在 Grok Bot 平台用？把 `prompts/grok_manu_bot_001.md` 與 `prompts/company_ops_addendum.md` 依序貼進 System Prompt 即可。

## 程式用法

```python
from datetime import date
from consultancy import Company, CompanyKind, ConsultancyFirm, WOMode, to_cents

firm = ConsultancyFirm(Company("hq", "宇宙行星顧問", CompanyKind.HQ))
firm.register_company(Company("vendor", "合作公司", CompanyKind.EXTERNAL, frozenset({"web"})))
firm.inject_capital(to_cents(200_000), date(2026, 10, 1))

eng = firm.open_engagement("客戶A", "官網改版", [("交付", to_cents(100_000), date(2026, 11, 1))])
wo = firm.dispatch_work_order(eng.id, "vendor", "前端開發", to_cents(60_000), date(2026, 10, 25),
                              milestone_id=eng.milestones[0].id)   # 毛利 < 30% 會被擋
firm.mark_delivered(wo.id, date(2026, 10, 25))
main, retention = firm.accept_work_order(wo.id, date(2026, 10, 25), accepted_by="業主")
firm.approve_payment(main.id, approver="業主 王大明")
print(firm.payment_blockers(main.id, date(2026, 11, 24)))  # ['Pay-when-paid：客戶里程碑 ENG-001-M1 尚未付清', ...]
```

## 目錄

```
prompts/   grok_manu_bot_001.md（原稿）、company_ops_addendum.md（公司營運與金流附加指令）
consultancy/
  advisors.py     12 顧問、部門、公司職責
  companies.py    HQ／關係企業／外部公司登記
  engagements.py  接案、里程碑、派工單、付款申請
  firm.py         營運核心：派工、驗收、付款閘門、稅、報表、現金預測
  ledger.py       複式記帳
  council.py      分流、召集顧問、組 prompt
  llm.py          離線後端／xAI Grok 後端
  demo.py         示範情境
  web.py          網頁工作台的本機伺服器（轉接 Grok）
web/       index.html（網頁工作台，亦發布為 Artifact）
docs/      organization.md、cashflow.md
tests/     單元測試
```

> 本專案不構成法律、稅務或投資建議；稅率與扣繳規則請與會計師確認。系統只產生付款申請，不會自行轉帳。
