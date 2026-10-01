"""星際激辯召集器：問題分流 → 挑選 4–6 位顧問 → 組合 system prompt → 呼叫 LLM。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .advisors import ADVISOR_BY_ID, ADVISORS, FALLBACK_ORDER, TOPICS, Advisor
from .llm import LLMBackend, Message, default_backend

if TYPE_CHECKING:
    from .firm import ConsultancyFirm

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
BASE_PROMPT = PROMPT_DIR / "grok_manu_bot_001.md"
OPS_ADDENDUM = PROMPT_DIR / "company_ops_addendum.md"

KEYWORDS: dict[str, tuple[str, ...]] = {
    "business_model": ("商業模式", "定位", "點子", "創業", "護城河", "變現", "business model"),
    "product": ("產品", "服務設計", "mvp", "功能", "體驗", "product"),
    "brand": ("品牌", "內容", "故事", "形象", "頻道", "brand"),
    "sales": ("銷售", "談判", "報價", "定價", "價格", "成交", "議價", "pricing", "sales"),
    "marketing": ("行銷", "流量", "集客", "廣告", "社群", "名單", "marketing", "seo"),
    "automation": ("ai", "自動化", "agent", "工具", "串接", "程式", "提示詞", "workflow"),
    "finance": ("現金", "金流", "付款", "收款", "毛利", "成本", "預算", "稅", "發票", "風險",
                "營運", "cash", "財務", "保留款", "準備金"),
    "execution": ("執行", "追蹤", "優化", "sop", "kpi", "進度", "時間表"),
    "dispatch": ("外包", "派工", "下包", "轉包", "合作公司", "供應商", "代收代付", "發包",
                 "subcontract", "outsource", "vendor", "其他公司"),
}


def triage(question: str) -> list[str]:
    """依關鍵字判斷問題類別，命中多者在前；都沒命中時視為商業模式問題。"""
    q = question.lower()
    scores = {t: sum(q.count(k) for k in kws) for t, kws in KEYWORDS.items()}
    hits = sorted((t for t, s in scores.items() if s), key=lambda t: -scores[t])
    return hits or ["business_model"]


def select_advisors(topics: list[str], minimum: int = 4, maximum: int = 6) -> list[Advisor]:
    weight = {t: len(topics) - i for i, t in enumerate(topics)}
    scored = [(sum(weight.get(t, 0) for t in a.topics), i, a) for i, a in enumerate(ADVISORS)]
    chosen = [a for s, _, a in sorted(scored, key=lambda x: (-x[0], x[1])) if s > 0][:maximum]
    if {"finance", "dispatch"} & set(topics):
        # 涉及金流或派工時，財務長與派工部負責人必定出席
        forced = [ADVISOR_BY_ID["pluto"], ADVISOR_BY_ID["polaris"]]
        chosen = (forced + [a for a in chosen if a not in forced])[:maximum]
    for fid in FALLBACK_ORDER:
        if len(chosen) >= minimum:
            break
        if ADVISOR_BY_ID[fid] not in chosen:
            chosen.append(ADVISOR_BY_ID[fid])
    return chosen


def load_base_prompt() -> str:
    text = BASE_PROMPT.read_text(encoding="utf-8")
    return re.sub(r"\s*\[cite: \d+\]", "", text)  # 移除原稿殘留的引用標記


@dataclass
class Consultation:
    topics: list[str]
    advisors: list[Advisor]
    messages: list[Message]
    answer: str


class Council:
    def __init__(self, firm: ConsultancyFirm | None = None, backend: LLMBackend | None = None):
        self.firm = firm
        self.backend = backend or default_backend()

    def build_messages(self, question: str, topics: list[str], advisors: list[Advisor]) -> list[Message]:
        parts = [load_base_prompt(), OPS_ADDENDUM.read_text(encoding="utf-8")]
        parts.append("## 本次分流\n" + "、".join(TOPICS[t] for t in topics))
        parts.append("## 本次召集顧問\n" + "\n".join(a.brief() for a in advisors))
        if self.firm is not None:
            parts.append("## 公司即時財務狀態\n" + self.firm.snapshot())
        return [{"role": "system", "content": "\n\n".join(parts)},
                {"role": "user", "content": question}]

    def consult(self, question: str) -> Consultation:
        topics = triage(question)
        advisors = select_advisors(topics)
        messages = self.build_messages(question, topics, advisors)
        return Consultation(topics, advisors, messages, self.backend.chat(messages))
