"""公司登記：顧問總部（HQ）、自家關係企業、外部合作公司。"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class CompanyKind(str, Enum):
    HQ = "hq"              # 顧問團隊公司本身（接案、收款、派工）
    INTERNAL = "internal"  # 同一業主的關係企業：雙方帳本都會記
    EXTERNAL = "external"  # 外部合作公司或個人工作者


@dataclass
class Company:
    id: str
    name: str
    kind: CompanyKind
    capabilities: frozenset[str] = frozenset()
    vat_registered: bool = True                  # 能否開立含營業稅發票
    withholding_rate: Decimal = Decimal("0")     # 付款時須代扣繳的比率（如個人執行業務所得）
    payment_terms_days: int = 30                 # 付款條件（驗收後 N 天）
    rating: float = 3.0                          # 合作評分 0–5
    notes: str = ""
    tags: set[str] = field(default_factory=set)


class CompanyRegistry:
    def __init__(self) -> None:
        self._companies: dict[str, Company] = {}

    def add(self, company: Company) -> Company:
        if company.id in self._companies:
            raise ValueError(f"公司 {company.id} 已存在")
        if company.kind is CompanyKind.HQ and any(
                c.kind is CompanyKind.HQ for c in self._companies.values()):
            raise ValueError("只能有一家 HQ")
        self._companies[company.id] = company
        return company

    def get(self, company_id: str) -> Company:
        try:
            return self._companies[company_id]
        except KeyError:
            raise KeyError(f"找不到公司 {company_id}") from None

    @property
    def hq(self) -> Company:
        for c in self._companies.values():
            if c.kind is CompanyKind.HQ:
                return c
        raise LookupError("尚未登記 HQ")

    def all(self) -> list[Company]:
        return list(self._companies.values())

    def find(self, capability: str) -> list[Company]:
        """依能力找可派工的合作公司，評分高者優先。"""
        return sorted(
            (c for c in self._companies.values()
             if c.kind is not CompanyKind.HQ and capability in c.capabilities),
            key=lambda c: -c.rating,
        )
