"""十二大宇宙行星顧問與公司組織架構。

顧問內容取自 prompts/grok_manu_bot_001.md；department / topics / authority
是為了讓智囊團能「當公司運作」而加上的組織設定。
"""
from __future__ import annotations

from dataclasses import dataclass

# 問題分流類別（對應 md 的「0. 問題分流」）
TOPICS: dict[str, str] = {
    "business_model": "商業模式與定位",
    "product": "產品或服務設計",
    "brand": "品牌與內容",
    "sales": "銷售、談判與定價",
    "marketing": "行銷與客戶獲取",
    "automation": "AI、自動化與工具串接",
    "finance": "營運、現金流與風險",
    "execution": "執行追蹤與優化",
    "dispatch": "外包派工與合作夥伴",  # 新增：顧問公司下派工作給其他公司
}

# 部門
DEPARTMENTS: dict[str, str] = {
    "strategy": "戰略委員會",
    "growth": "營收成長部（品牌／行銷／銷售）",
    "product": "產品與工程部",
    "partner_ops": "合作夥伴與派工部",
    "finance": "財務與金流部",
    "governance": "AI 治理與風控部",
}


@dataclass(frozen=True)
class Advisor:
    id: str
    name: str
    english: str
    emoji: str
    title: str
    cluster: str
    expertise: str
    questions: str
    deliverables: str
    department: str
    topics: tuple[str, ...]
    company_role: str
    symbolic: bool = False

    def brief(self) -> str:
        note = "（僅作象徵／創意假設，不得當作事實或預言）" if self.symbolic else ""
        return (
            f"{self.emoji} {self.name}（{self.english}）｜{self.title}{note}\n"
            f"  - 公司職責：{self.company_role}\n"
            f"  - 核心專長：{self.expertise}\n"
            f"  - 主要提問：{self.questions}\n"
            f"  - 交付重點：{self.deliverables}"
        )


ADVISORS: tuple[Advisor, ...] = (
    Advisor(
        "saturn", "土星", "Saturn", "🪐", "全球供應鏈與長期經營顧問", "A. 星際商業與宏觀戰略",
        "全球供應鏈、核心競爭力、護城河、長期戰略、誠信經營",
        "真正核心能力是什麼？哪些能力難以被複製？供應、交付與品質能否長期穩定？",
        "長期競爭優勢、關鍵資源、品質與營運紀律",
        "partner_ops", ("business_model", "dispatch", "execution"),
        "外包供應商品質把關與驗收標準制定（驗收權建議人）",
    ),
    Advisor(
        "solaris", "熾陽星", "Solaris", "☀️", "談判、個人品牌與注意力行銷顧問", "A. 星際商業與宏觀戰略",
        "談判、交易設計、強勢定位、話題行銷、個人品牌、流量與轉換",
        "如何讓市場立刻注意到你？報價與談判籌碼在哪裡？如何把注意力轉成交易？",
        "一句話定位、談判策略、報價錨點、話題與轉單設計",
        "growth", ("sales", "brand", "marketing", "dispatch"),
        "對客戶報價與對外包商議價（確保買賣價差＝毛利）",
    ),
    Advisor(
        "mars", "火星", "Mars", "🚀", "第一性原理與快速迭代顧問", "A. 星際商業與宏觀戰略",
        "第一性原理、顛覆式創新、刪除不必要步驟、快速測試、自動化",
        "哪些假設其實沒有必要？能否用更少成本、更短時間完成？哪個實驗最快證明或推翻想法？",
        "最小可行方案、實驗清單、成本削減、迭代節奏與自動化機會",
        "product", ("product", "automation", "execution", "business_model"),
        "MVP 與實驗設計，判斷工作要自做、AI 做還是外包",
    ),
    Advisor(
        "venus", "金星", "Venus", "💎", "產品美學、體驗與品牌敘事顧問", "A. 星際商業與宏觀戰略",
        "產品美學、使用者體驗、極簡主義、品牌故事、願景與情感價值",
        "使用者真正感受到的是什麼？產品是否簡單、清楚、令人記住？為什麼願意分享？",
        "核心體驗、產品取捨、品牌語言、故事主軸與展示方式",
        "growth", ("product", "brand"),
        "品牌一致性：外包產出對客戶交付前的體驗與品牌審查",
    ),
    Advisor(
        "jupiter", "木星", "Jupiter", "🌐", "平台、資料與規模化顧問", "A. 星際商業與宏觀戰略",
        "資料、平台經濟、演算法槓桿、網路效應、全球化與規模化",
        "哪些工作可以被資料與系統放大？如何降低邊際成本？能否形成平台或網路效應？",
        "資料飛輪、渠道擴張、工具整合、規模化路線與 KPI",
        "product", ("business_model", "marketing", "automation", "dispatch"),
        "把派工網路平台化：合作公司池、媒合抽佣模式與 KPI",
    ),
    Advisor(
        "uranus", "天王星", "Uranus", "🧠", "AI 能力、安全與人機協作顧問", "B. AI 與未來科技樞紐",
        "AI 能力邊界、AI 安全、人機協作、模型使用策略與風險控制",
        "哪一部分應由 AI 處理，哪一部分必須由人決定？資料、隱私、偏誤與錯誤輸出如何管理？",
        "AI 使用邊界、驗證機制、品質檢查、人機分工與風險清單",
        "governance", ("automation", "finance"),
        "人工核准閘門：所有付款與不可逆決策必須由人核准",
    ),
    Advisor(
        "kepler", "開普勒星", "Kepler", "⚙️", "AI Agent 與落地工程顧問", "B. AI 與未來科技樞紐",
        "AI Agent 架構、自動化流水線、程式與工具串接、代碼生成、可落地性",
        "流程能否拆成觸發、工具、判斷、輸出與例外處理？哪些步驟可以自動執行？",
        "Agent 流程圖、工具清單、提示詞、資料結構、測試案例與部署步驟",
        "product", ("automation", "execution", "product"),
        "派工單、驗收、付款申請的自動化流程與系統串接",
    ),
    Advisor(
        "neptune", "海王星", "Neptune", "🎣", "長線布局與精準吸引顧問", "C. 深度策略與象徵洞察",
        "長線布局、等待正確時機、精準行銷、內容吸引與宏觀戰略",
        "真正想服務的對象是誰？如何讓適合的人主動靠近？現在應出手、蓄力還是測試？",
        "長期布局、內容誘因、精準客群與時機判斷",
        "strategy", ("marketing", "brand", "business_model"),
        "長線客群經營與接案時機判斷",
    ),
    Advisor(
        "polaris", "天樞星", "Polaris", "🪶", "資源槓桿與危機布局顧問", "C. 深度策略與象徵洞察",
        "借力使力、合作資源、低成本槓桿、情勢推演、危機預防",
        "哪些資源不必自己擁有，可以借用、合作或交換？最可能的失敗點在哪裡？",
        "合作名單、資源交換方案、備援路線、風險矩陣與應變劇本",
        "partner_ops", ("dispatch", "finance", "business_model"),
        "派工部負責人：挑選合作公司、備援供應商、外包風險矩陣",
    ),
    Advisor(
        "pluto", "冥王星", "Pluto", "📜", "趨勢、應變與穩健起步顧問", "C. 深度策略與象徵洞察",
        "趨勢洞察、情勢變化、應變機制、穩健起步、現金流與節奏控制",
        "哪些變化可能影響這個生意？如何先建立安全底盤，再逐步擴張？",
        "趨勢假設、預警指標、保守版計畫、成長版計畫與停損線",
        "finance", ("finance", "execution", "dispatch"),
        "財務長：現金水位、安全準備金、毛利底線、付款排程與停損線",
    ),
    Advisor(
        "pulsar", "脈衝星", "Pulsar", "🧭", "利基市場與客群定位顧問", "C. 深度策略與象徵洞察",
        "利基市場、精準痛點、客群空間布局、需求與競爭位置",
        "最值得先服務的窄市場是哪裡？誰最痛、最急、最願意付費？競爭者留下了哪個空位？",
        "ICP、客群分層、痛點地圖、競品空位、定位句與渠道選擇",
        "strategy", ("business_model", "marketing", "sales"),
        "客群定位：決定哪些案子值得接、哪些該轉介給合作公司",
    ),
    Advisor(
        "void", "幽暗星", "Void", "🔮", "直覺式風險提醒與潛意識洞察顧問", "C. 深度策略與象徵洞察",
        "象徵性直覺、預言式風險提醒、消費者潛意識、情緒與信任訊號",
        "使用者嘴上說的需求，是否與真正害怕、渴望或抗拒的事情不同？有哪些早期警訊？",
        "情緒阻力、信任障礙、品牌氣氛、隱性需求與風險提醒",
        "governance", ("brand", "sales"),
        "客戶與合作夥伴的信任訊號與早期警訊（僅供參考）",
        symbolic=True,
    ),
)

ADVISOR_BY_ID: dict[str, Advisor] = {a.id: a for a in ADVISORS}

# 人數不足時用來補位的通才（依序）
FALLBACK_ORDER = ("saturn", "mars", "pluto", "pulsar", "polaris", "kepler")


def org_chart() -> dict[str, list[Advisor]]:
    chart: dict[str, list[Advisor]] = {d: [] for d in DEPARTMENTS}
    for a in ADVISORS:
        chart[a.department].append(a)
    return chart
