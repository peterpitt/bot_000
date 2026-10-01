"""接案（Engagement）、客戶里程碑、派工單（WorkOrder）與付款申請的資料模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


@dataclass
class Milestone:
    id: str
    title: str
    fee_cents: int            # 未稅金額
    planned_date: date        # 預計交付／請款日
    vat_cents: int = 0
    invoiced_on: date | None = None
    due_on: date | None = None
    paid_cents: int = 0
    accepted_on: date | None = None

    @property
    def gross_cents(self) -> int:
        return self.fee_cents + self.vat_cents

    @property
    def outstanding_cents(self) -> int:
        return self.gross_cents - self.paid_cents if self.invoiced_on else 0

    @property
    def fully_paid(self) -> bool:
        return self.invoiced_on is not None and self.paid_cents >= self.gross_cents


class EngagementStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass
class Engagement:
    id: str
    client: str
    title: str
    milestones: list[Milestone]
    client_terms_days: int = 14
    status: EngagementStatus = EngagementStatus.ACTIVE
    work_order_ids: list[str] = field(default_factory=list)

    @property
    def contract_value_cents(self) -> int:
        return sum(m.fee_cents for m in self.milestones)

    @property
    def collected_cents(self) -> int:
        return sum(m.paid_cents for m in self.milestones)

    def milestone(self, milestone_id: str) -> Milestone:
        for m in self.milestones:
            if m.id == milestone_id:
                return m
        raise KeyError(f"找不到里程碑 {milestone_id}")


class WOMode(str, Enum):
    SUBCONTRACT = "subcontract"    # 轉包：HQ 為主契約方，總額入收入，外包費入成本
    PASS_THROUGH = "pass_through"  # 代收代付：HQ 只賺佣金，代收款不屬於 HQ 收入


class WOStatus(str, Enum):
    ISSUED = "issued"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    PAID = "paid"
    CANCELLED = "cancelled"


@dataclass
class WorkOrder:
    id: str
    engagement_id: str
    company_id: str
    title: str
    # 轉包：未稅派工金額（營業稅另計）。
    # 代收代付：合作公司開給客戶的發票總額（含稅），HQ 代收後扣佣金轉付。
    amount_cents: int
    mode: WOMode
    expected_delivery: date
    milestone_id: str | None = None        # 對應的客戶里程碑（Pay-when-paid 用）
    retention_rate: Decimal = Decimal("0")
    commission_rate: Decimal = Decimal("0")  # 代收代付模式的佣金率
    status: WOStatus = WOStatus.ISSUED
    collected_cents: int = 0               # 代收代付模式：已向客戶代收的金額
    accepted_on: date | None = None
    override_by: str | None = None         # 違反毛利政策時的人工核准者
    history: list[tuple[date, str]] = field(default_factory=list)

    def log(self, on: date, event: str) -> None:
        self.history.append((on, event))


@dataclass(frozen=True)
class Bill:
    """派工驗收後的請款拆解（驗收入帳與現金預測共用同一套計算）。"""
    net: int
    vat: int
    withholding: int
    retention: int
    commission: int
    commission_vat: int

    @property
    def payable_now(self) -> int:
        """驗收後依付款條件付出的金額。"""
        return (self.net + self.vat - self.withholding - self.retention
                - self.commission - self.commission_vat)


class PaymentKind(str, Enum):
    MAIN = "main"
    RETENTION = "retention"


class PaymentStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PAID = "paid"


@dataclass
class PaymentRequest:
    id: str
    work_order_id: str
    company_id: str
    amount_cents: int
    due_on: date
    kind: PaymentKind
    status: PaymentStatus = PaymentStatus.PENDING_APPROVAL
    approved_by: str | None = None
    paid_on: date | None = None
    bank_ref: str | None = None
