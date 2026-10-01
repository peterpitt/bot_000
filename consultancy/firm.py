"""顧問團隊公司營運核心：接案 → 派工給其他公司 → 驗收 → 付款，並管控金流。

設計原則（對應 md 的天王星／冥王星規則）：
- 系統只產生「付款申請」與記帳，不會自己轉帳；每筆付款必須有人核准，
  實際匯款後再由人回填銀行交易序號。
- 派工前先檢查毛利底線；付款前檢查人工核准、Pay-when-paid、安全準備金。
- 代收代付的錢不是公司的錢：未收到客戶款項前絕不先墊付。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from . import ledger as L
from .companies import Company, CompanyKind, CompanyRegistry
from .engagements import (
    Bill, Engagement, EngagementStatus, Milestone, PaymentKind, PaymentRequest,
    PaymentStatus, WOMode, WOStatus, WorkOrder,
)
from .money import apply_rate, fmt, to_cents


class PolicyViolation(Exception):
    """違反金流政策；訊息會說明原因與需要的人工動作。"""


@dataclass
class TreasuryPolicy:
    vat_rate: Decimal = Decimal("0.05")          # 營業稅率（台灣一般稅率 5%，實際請與會計師確認）
    min_margin_rate: Decimal = Decimal("0.30")   # 轉包模式的最低毛利率
    min_cash_reserve_cents: int = to_cents(50_000)  # 安全準備金：付款後現金不得低於此值
    pay_when_paid: bool = True                   # 客戶款未入帳前不付外包款
    default_retention_rate: Decimal = Decimal("0.10")  # 保留款比例
    warranty_days: int = 30                      # 保留款於驗收後 N 天釋放
    default_commission_rate: Decimal = Decimal("0.15")  # 代收代付抽佣率
    tax_due_day: int = 15                        # 稅款預估於次月 N 日繳納（簡化）


class ConsultancyFirm:
    def __init__(self, hq: Company, policy: TreasuryPolicy | None = None):
        if hq.kind is not CompanyKind.HQ:
            raise ValueError("ConsultancyFirm 的主體必須是 HQ")
        self.policy = policy or TreasuryPolicy()
        self.companies = CompanyRegistry()
        self.companies.add(hq)
        self.books: dict[str, L.Ledger] = {hq.id: L.Ledger(hq.id)}
        self.engagements: dict[str, Engagement] = {}
        self.work_orders: dict[str, WorkOrder] = {}
        self.payments: dict[str, PaymentRequest] = {}
        self._seq: dict[str, int] = {}

    # ------------------------------------------------------------------ 基本
    @property
    def hq(self) -> Company:
        return self.companies.hq

    @property
    def gl(self) -> L.Ledger:
        return self.books[self.hq.id]

    def _next_id(self, prefix: str) -> str:
        self._seq[prefix] = self._seq.get(prefix, 0) + 1
        return f"{prefix}-{self._seq[prefix]:03d}"

    def register_company(self, company: Company) -> Company:
        self.companies.add(company)
        if company.kind is CompanyKind.INTERNAL:
            self.books[company.id] = L.Ledger(company.id)
        return company

    def cash(self, as_of: date | None = None) -> int:
        return self.gl.balance(L.CASH, as_of=as_of)

    def inject_capital(self, amount_cents: int, on: date, memo: str = "業主增資") -> None:
        self.gl.post(on, memo, [L.dr(L.CASH, amount_cents), L.cr(L.CAPITAL, amount_cents)])

    # ------------------------------------------------------------ 客戶端金流
    def open_engagement(self, client: str, title: str,
                        milestones: list[tuple[str, int, date]],
                        client_terms_days: int = 14) -> Engagement:
        eng_id = self._next_id("ENG")
        ms = [Milestone(f"{eng_id}-M{i}", t, amt, d) for i, (t, amt, d) in enumerate(milestones, 1)]
        if not ms or any(m.fee_cents <= 0 for m in ms):
            raise ValueError("接案至少需要一個金額為正的里程碑")
        eng = Engagement(eng_id, client, title, ms, client_terms_days)
        self.engagements[eng_id] = eng
        return eng

    def invoice_milestone(self, eng_id: str, ms_id: str, on: date) -> Milestone:
        eng = self.engagements[eng_id]
        m = eng.milestone(ms_id)
        if m.invoiced_on:
            raise PolicyViolation(f"{ms_id} 已開立發票")
        m.vat_cents = apply_rate(m.fee_cents, self.policy.vat_rate)
        m.invoiced_on = on
        m.due_on = on + timedelta(days=eng.client_terms_days)
        self.gl.post(on, f"開立發票 {eng.client}：{m.title}", [
            L.dr(L.AR, m.gross_cents, eng.client),
            L.cr(L.CONTRACT_LIAB, m.fee_cents, eng.client),
            L.cr(L.OUTPUT_VAT, m.vat_cents),
        ], ref=ms_id)
        return m

    def receive_client_payment(self, eng_id: str, ms_id: str, amount_cents: int, on: date) -> Milestone:
        eng = self.engagements[eng_id]
        m = eng.milestone(ms_id)
        if not m.invoiced_on:
            raise PolicyViolation(f"{ms_id} 尚未開立發票，請先請款")
        if amount_cents <= 0 or amount_cents > m.outstanding_cents:
            raise PolicyViolation(f"收款金額需介於 0 與未收餘額 {fmt(m.outstanding_cents)} 之間")
        m.paid_cents += amount_cents
        self.gl.post(on, f"收到客戶款 {eng.client}：{m.title}", [
            L.dr(L.CASH, amount_cents), L.cr(L.AR, amount_cents, eng.client)], ref=ms_id)
        return m

    def accept_milestone(self, eng_id: str, ms_id: str, on: date) -> Milestone:
        """客戶驗收里程碑 → 認列收入（未請款者自動先開發票）。"""
        eng = self.engagements[eng_id]
        m = eng.milestone(ms_id)
        if m.accepted_on:
            raise PolicyViolation(f"{ms_id} 已驗收")
        if not m.invoiced_on:
            self.invoice_milestone(eng_id, ms_id, on)
        m.accepted_on = on
        self.gl.post(on, f"客戶驗收認列收入：{m.title}", [
            L.dr(L.CONTRACT_LIAB, m.fee_cents, eng.client),
            L.cr(L.SERVICE_REV, m.fee_cents)], ref=ms_id)
        if all(x.accepted_on for x in eng.milestones):
            eng.status = EngagementStatus.CLOSED
        return m

    # ------------------------------------------------------------ 派工（下包）
    def committed_subcontract_cents(self, eng_id: str) -> int:
        return sum(wo.amount_cents for wo in self._wos(eng_id)
                   if wo.mode is WOMode.SUBCONTRACT and wo.status is not WOStatus.CANCELLED)

    def projected_margin(self, eng_id: str, extra_cost_cents: int = 0) -> Decimal:
        value = self.engagements[eng_id].contract_value_cents
        cost = self.committed_subcontract_cents(eng_id) + extra_cost_cents
        return (Decimal(value - cost) / Decimal(value)).quantize(Decimal("0.0001"))

    def dispatch_work_order(self, eng_id: str, company_id: str, title: str, amount_cents: int,
                            expected_delivery: date, mode: WOMode = WOMode.SUBCONTRACT,
                            milestone_id: str | None = None,
                            retention_rate: Decimal | None = None,
                            commission_rate: Decimal | None = None,
                            override_by: str | None = None, on: date | None = None) -> WorkOrder:
        eng = self.engagements[eng_id]
        if eng.status is not EngagementStatus.ACTIVE:
            raise PolicyViolation(f"{eng_id} 已結案，不能再派工")
        company = self.companies.get(company_id)
        if company.kind is CompanyKind.HQ:
            raise PolicyViolation("不能派工給 HQ 自己")
        if amount_cents <= 0:
            raise ValueError("派工金額必須為正")
        if milestone_id:
            eng.milestone(milestone_id)  # 驗證存在
        if mode is WOMode.SUBCONTRACT:
            margin = self.projected_margin(eng_id, amount_cents)
            if margin < self.policy.min_margin_rate and not override_by:
                raise PolicyViolation(
                    f"派工後預估毛利率 {margin:.2%} 低於底線 {self.policy.min_margin_rate:.0%}；"
                    "請重新議價、調整範圍，或由負責人以 override_by 書面核准")
        wo = WorkOrder(
            self._next_id("WO"), eng_id, company_id, title, amount_cents, mode, expected_delivery,
            milestone_id=milestone_id,
            retention_rate=(self.policy.default_retention_rate if retention_rate is None else retention_rate)
            if mode is WOMode.SUBCONTRACT else Decimal("0"),
            commission_rate=(self.policy.default_commission_rate if commission_rate is None else commission_rate)
            if mode is WOMode.PASS_THROUGH else Decimal("0"),
            override_by=override_by,
        )
        wo.log(on or date.today(), f"派工給 {company.name}（{mode.value}）{fmt(amount_cents)}"
               + (f"；毛利例外核准：{override_by}" if override_by else ""))
        self.work_orders[wo.id] = wo
        eng.work_order_ids.append(wo.id)
        return wo

    def cancel_work_order(self, wo_id: str, on: date, reason: str) -> WorkOrder:
        wo = self.work_orders[wo_id]
        if wo.status not in (WOStatus.ISSUED, WOStatus.DELIVERED):
            raise PolicyViolation("已驗收的派工不能取消，請走退款／爭議流程")
        if wo.collected_cents:
            raise PolicyViolation("已有代收款，請先退還客戶再取消")
        wo.status = WOStatus.CANCELLED
        wo.log(on, f"取消：{reason}")
        return wo

    def mark_delivered(self, wo_id: str, on: date) -> WorkOrder:
        wo = self._require(wo_id, WOStatus.ISSUED)
        wo.status = WOStatus.DELIVERED
        wo.log(on, "合作公司交付")
        return wo

    def reject_delivery(self, wo_id: str, on: date, reason: str) -> WorkOrder:
        wo = self._require(wo_id, WOStatus.DELIVERED)
        wo.status = WOStatus.ISSUED
        wo.log(on, f"驗收退回：{reason}")
        return wo

    def collect_pass_through(self, wo_id: str, amount_cents: int, on: date) -> WorkOrder:
        """代收代付：向客戶代收合作公司的款項（HQ 只是過手）。"""
        wo = self.work_orders[wo_id]
        if wo.mode is not WOMode.PASS_THROUGH:
            raise PolicyViolation("只有代收代付派工可以代收")
        if amount_cents <= 0 or wo.collected_cents + amount_cents > wo.amount_cents:
            raise PolicyViolation("代收金額超過派工金額")
        client = self.engagements[wo.engagement_id].client
        wo.collected_cents += amount_cents
        self.gl.post(on, f"代收 {client} 款項（{wo.title}）", [
            L.dr(L.CASH, amount_cents), L.cr(L.PASS_THROUGH, amount_cents, wo.company_id)], ref=wo.id)
        wo.log(on, f"代收 {fmt(amount_cents)}")
        return wo

    def bill_for(self, wo: WorkOrder) -> Bill:
        company = self.companies.get(wo.company_id)
        net = wo.amount_cents
        if wo.mode is WOMode.PASS_THROUGH:
            # 合作公司直接開發票給客戶；HQ 對合作公司開佣金發票並從代收款扣除
            commission = apply_rate(net, wo.commission_rate)
            return Bill(net, 0, 0, 0, commission, apply_rate(commission, self.policy.vat_rate))
        vat = apply_rate(net, self.policy.vat_rate) if company.vat_registered else 0
        return Bill(net, vat, apply_rate(net, company.withholding_rate),
                    apply_rate(net, wo.retention_rate), 0, 0)

    def accept_work_order(self, wo_id: str, on: date, accepted_by: str) -> list[PaymentRequest]:
        """HQ 驗收合作公司交付 → 入應付帳款並建立待核准的付款申請。"""
        wo = self._require(wo_id, WOStatus.DELIVERED)
        company = self.companies.get(wo.company_id)
        bill = self.bill_for(wo)
        cp = company.id
        if wo.mode is WOMode.PASS_THROUGH:
            if wo.collected_cents < wo.amount_cents:
                raise PolicyViolation(
                    f"代收款僅 {fmt(wo.collected_cents)}，未滿 {fmt(wo.amount_cents)}；"
                    "代收代付不得先墊付，請先向客戶收齊")
            self.gl.post(on, f"代收代付結算 {company.name}：{wo.title}", [
                L.dr(L.PASS_THROUGH, bill.net, cp),
                L.cr(L.COMMISSION_REV, bill.commission),
                L.cr(L.OUTPUT_VAT, bill.commission_vat),
                L.cr(L.AP, bill.payable_now, cp),
            ], ref=wo.id)
        else:
            self.gl.post(on, f"驗收外包 {company.name}：{wo.title}", [
                L.dr(L.SUBCONTRACT_COST, bill.net, cp),
                L.dr(L.INPUT_VAT, bill.vat),
                L.cr(L.AP, bill.payable_now, cp),
                L.cr(L.RETENTION, bill.retention, cp),
                L.cr(L.WHT, bill.withholding),
            ], ref=wo.id)
        self._mirror_on_internal_books(wo, bill, on)
        wo.status = WOStatus.ACCEPTED
        wo.accepted_on = on
        wo.log(on, f"驗收通過（{accepted_by}）")

        requests = [self._new_payment(wo, bill.payable_now, on + timedelta(days=company.payment_terms_days),
                                      PaymentKind.MAIN)]
        if bill.retention:
            requests.append(self._new_payment(wo, bill.retention, on + timedelta(days=self.policy.warranty_days),
                                              PaymentKind.RETENTION))
        return requests

    def _mirror_on_internal_books(self, wo: WorkOrder, bill: Bill, on: date) -> None:
        """派給自家關係企業時，同步記在對方帳上，方便日後合併報表沖銷。"""
        sub = self.books.get(wo.company_id)
        if sub is None:
            return
        hq = self.hq.id
        if wo.mode is WOMode.PASS_THROUGH:
            # 關係企業對客戶開立含稅發票、款項由 HQ 代收；HQ 的佣金（含稅）從代收款扣除
            client = self.engagements[wo.engagement_id].client
            gross = bill.net
            net = gross
            if self.companies.get(wo.company_id).vat_registered:
                net = int((Decimal(gross) / (1 + self.policy.vat_rate)).quantize(Decimal("1")))
            sub.post(on, f"開立發票給 {client}（HQ 代收）", [
                L.dr(L.AR, gross, hq),
                L.cr(L.SERVICE_REV, net),
                L.cr(L.OUTPUT_VAT, gross - net),
            ], ref=wo.id)
            sub.post(on, "HQ 媒合佣金（自代收款扣除）", [
                L.dr(L.SUBCONTRACT_COST, bill.commission, hq),
                L.dr(L.INPUT_VAT, bill.commission_vat),
                L.cr(L.AR, bill.commission + bill.commission_vat, hq),
            ], ref=wo.id)
            return
        sub.post(on, f"HQ 驗收：{wo.title}", [
            L.dr(L.AR, bill.net + bill.vat - bill.withholding, hq),
            L.dr(L.PREPAID_TAX, bill.withholding),
            L.cr(L.SERVICE_REV, bill.net),
            L.cr(L.OUTPUT_VAT, bill.vat),
        ], ref=wo.id)

    # ------------------------------------------------------------ 付款閘門
    def _new_payment(self, wo: WorkOrder, amount: int, due: date, kind: PaymentKind) -> PaymentRequest:
        pr = PaymentRequest(self._next_id("PAY"), wo.id, wo.company_id, amount, due, kind)
        self.payments[pr.id] = pr
        return pr

    def approve_payment(self, pr_id: str, approver: str) -> PaymentRequest:
        """人工核准（AI 不得代為核准）。"""
        pr = self.payments[pr_id]
        if pr.status is not PaymentStatus.PENDING_APPROVAL:
            raise PolicyViolation(f"{pr_id} 狀態為 {pr.status.value}，無法核准")
        if not approver or approver.strip().lower() in {"ai", "bot", "grok", "system"}:
            raise PolicyViolation("付款必須由具名的真人核准")
        pr.status = PaymentStatus.APPROVED
        pr.approved_by = approver
        return pr

    def payment_blockers(self, pr_id: str, on: date) -> list[str]:
        pr = self.payments[pr_id]
        wo = self.work_orders[pr.work_order_id]
        eng = self.engagements[wo.engagement_id]
        reasons: list[str] = []
        if pr.status is PaymentStatus.PAID:
            return ["已付款"]
        if pr.status is not PaymentStatus.APPROVED:
            reasons.append("尚未經人工核准")
        if pr.kind is PaymentKind.RETENTION and on < pr.due_on:
            reasons.append(f"保留款保固期至 {pr.due_on} 才可釋放")
        if self.policy.pay_when_paid and wo.mode is WOMode.SUBCONTRACT:
            if wo.milestone_id and not eng.milestone(wo.milestone_id).fully_paid:
                reasons.append(f"Pay-when-paid：客戶里程碑 {wo.milestone_id} 尚未付清")
            paid_out = sum(p.amount_cents for p in self.payments.values()
                           if p.status is PaymentStatus.PAID
                           and self.work_orders[p.work_order_id].engagement_id == eng.id
                           and self.work_orders[p.work_order_id].mode is WOMode.SUBCONTRACT)
            if paid_out + pr.amount_cents > eng.collected_cents:
                reasons.append(
                    f"Pay-when-paid：本案客戶已付 {fmt(eng.collected_cents)}，"
                    f"不足以支應累計外包付款 {fmt(paid_out + pr.amount_cents)}")
        cash = self.cash()
        if cash < pr.amount_cents:
            reasons.append(f"現金不足（現有 {fmt(cash)}）")
        elif cash - pr.amount_cents < self.policy.min_cash_reserve_cents:
            reasons.append(f"付款後現金 {fmt(cash - pr.amount_cents)} 低於安全準備金 "
                           f"{fmt(self.policy.min_cash_reserve_cents)}")
        return reasons

    def record_payment(self, pr_id: str, on: date, bank_ref: str) -> PaymentRequest:
        """人工完成匯款後，回填銀行交易序號入帳。"""
        if not bank_ref:
            raise PolicyViolation("請提供銀行交易序號以利對帳")
        blockers = self.payment_blockers(pr_id, on)
        if blockers:
            raise PolicyViolation("無法付款：" + "；".join(blockers))
        pr = self.payments[pr_id]
        wo = self.work_orders[pr.work_order_id]
        liability = L.RETENTION if pr.kind is PaymentKind.RETENTION else L.AP
        self.gl.post(on, f"支付 {self.companies.get(pr.company_id).name}（{pr.kind.value}）", [
            L.dr(liability, pr.amount_cents, pr.company_id), L.cr(L.CASH, pr.amount_cents)], ref=wo.id)
        sub = self.books.get(pr.company_id)
        if sub is not None:
            sub.post(on, f"收到 HQ 款項（{pr.kind.value}）", [
                L.dr(L.CASH, pr.amount_cents), L.cr(L.AR, pr.amount_cents, self.hq.id)], ref=wo.id)
        pr.status = PaymentStatus.PAID
        pr.paid_on = on
        pr.bank_ref = bank_ref
        wo.log(on, f"付款 {fmt(pr.amount_cents)}（{bank_ref}）")
        if all(p.status is PaymentStatus.PAID for p in self.payments.values() if p.work_order_id == wo.id):
            wo.status = WOStatus.PAID
        return pr

    # ------------------------------------------------------------ 稅款
    def remit_withholding(self, on: date, bank_ref: str) -> int:
        amount = self.gl.balance(L.WHT)
        if amount > 0:
            self.gl.post(on, f"繳納代扣繳稅款（{bank_ref}）", [L.dr(L.WHT, amount), L.cr(L.CASH, amount)])
        return amount

    def settle_vat(self, on: date, bank_ref: str) -> int:
        """銷項抵進項，差額繳納；進項較多時留抵。回傳實際繳納金額。"""
        out, inp = self.gl.balance(L.OUTPUT_VAT), self.gl.balance(L.INPUT_VAT)
        offset = min(out, inp)
        due = out - offset
        lines = [L.dr(L.OUTPUT_VAT, out), L.cr(L.INPUT_VAT, offset), L.cr(L.CASH, due)]
        if out:
            self.gl.post(on, f"營業稅申報（{bank_ref}）", lines)
        return due

    # ------------------------------------------------------------ 報表
    def engagement_report(self, eng_id: str) -> dict[str, int | str]:
        eng = self.engagements[eng_id]
        wos = self._wos(eng_id)
        committed = self.committed_subcontract_cents(eng_id)
        refs = {m.id for m in eng.milestones} | {wo.id for wo in wos}
        revenue = cost = commission = cash_in = cash_out = 0
        for e in self.gl.entries:
            if e.ref not in refs:
                continue
            for ln in e.lines:
                if ln.account == L.SERVICE_REV:
                    revenue += ln.credit - ln.debit
                elif ln.account == L.COMMISSION_REV:
                    commission += ln.credit - ln.debit
                elif ln.account == L.SUBCONTRACT_COST:
                    cost += ln.debit - ln.credit
                elif ln.account == L.CASH:
                    cash_in += ln.debit
                    cash_out += ln.credit
        return {
            "engagement": eng_id,
            "client": eng.client,
            "contract_value": eng.contract_value_cents,
            "committed_subcontract": committed,
            "projected_margin": f"{self.projected_margin(eng_id):.2%}",
            "revenue_recognized": revenue,
            "commission_recognized": commission,
            "subcontract_cost_recognized": cost,
            "gross_profit_recognized": revenue + commission - cost,
            "cash_in": cash_in,
            "cash_out": cash_out,
            "net_cash": cash_in - cash_out,
        }

    def forecast(self, start: date, weeks: int = 8) -> list[dict]:
        """以週為單位的現金預測，標出低於安全準備金的週次。"""
        flows: list[tuple[date, int, str]] = []  # (日期, 金額: +流入 / -流出, 說明)
        for eng in self.engagements.values():
            for m in eng.milestones:
                if m.invoiced_on:
                    if m.outstanding_cents:
                        flows.append((m.due_on, m.outstanding_cents, f"客戶款 {m.id}"))
                else:
                    gross = m.fee_cents + apply_rate(m.fee_cents, self.policy.vat_rate)
                    flows.append((m.planned_date + timedelta(days=eng.client_terms_days), gross,
                                  f"客戶款(未請款) {m.id}"))
        for wo in self.work_orders.values():
            if wo.status is WOStatus.CANCELLED:
                continue
            if wo.mode is WOMode.PASS_THROUGH and wo.collected_cents < wo.amount_cents:
                flows.append((wo.expected_delivery, wo.amount_cents - wo.collected_cents, f"代收 {wo.id}"))
            if wo.status in (WOStatus.ISSUED, WOStatus.DELIVERED):
                bill = self.bill_for(wo)
                terms = self.companies.get(wo.company_id).payment_terms_days
                flows.append((wo.expected_delivery + timedelta(days=terms), -bill.payable_now,
                              f"外包款(預估) {wo.id}"))
                if bill.retention:
                    flows.append((wo.expected_delivery + timedelta(days=self.policy.warranty_days),
                                  -bill.retention, f"保留款(預估) {wo.id}"))
        for pr in self.payments.values():
            if pr.status is not PaymentStatus.PAID:
                flows.append((pr.due_on, -pr.amount_cents, f"應付 {pr.id}"))
        tax = self.gl.balance(L.WHT) + max(0, self.gl.balance(L.OUTPUT_VAT) - self.gl.balance(L.INPUT_VAT))
        if tax:
            nxt = (start.replace(day=1) + timedelta(days=32)).replace(day=self.policy.tax_due_day)
            flows.append((nxt, -tax, "稅款（營業稅＋代扣繳）"))

        balance = self.cash(as_of=start)
        rows = []
        for i in range(weeks):
            ws, we = start + timedelta(weeks=i), start + timedelta(weeks=i + 1)
            inside = [f for f in flows if (f[0] < we and (i == 0 or f[0] >= ws))]
            inflow = sum(a for _, a, _ in inside if a > 0)
            outflow = -sum(a for _, a, _ in inside if a < 0)
            balance += inflow - outflow
            rows.append({
                "week_start": ws, "inflow": inflow, "outflow": outflow, "closing": balance,
                "below_reserve": balance < self.policy.min_cash_reserve_cents,
                "items": [f"{d} {desc} {fmt(a)}" + (" (逾期)" if d < start else "") for d, a, desc in inside],
            })
        return rows

    def snapshot(self, on: date | None = None) -> str:
        """給智囊團的即時財務摘要（放進 system prompt）。"""
        on = on or date.today()
        pending = [p for p in self.payments.values() if p.status is not PaymentStatus.PAID]
        open_wos = [w for w in self.work_orders.values()
                    if w.status in (WOStatus.ISSUED, WOStatus.DELIVERED, WOStatus.ACCEPTED)]
        lines = [
            f"- 現金：{fmt(self.cash())}（安全準備金 {fmt(self.policy.min_cash_reserve_cents)}）",
            f"- 應收帳款：{fmt(self.gl.balance(L.AR))}；應付帳款：{fmt(self.gl.balance(L.AP))}；"
            f"應付保留款：{fmt(self.gl.balance(L.RETENTION))}；代收款：{fmt(self.gl.balance(L.PASS_THROUGH))}",
            f"- 進行中接案：{sum(e.status is EngagementStatus.ACTIVE for e in self.engagements.values())} 件；"
            f"未結派工：{len(open_wos)} 張；待付款申請：{len(pending)} 筆",
            f"- 政策：毛利底線 {self.policy.min_margin_rate:.0%}、"
            f"Pay-when-paid {'開' if self.policy.pay_when_paid else '關'}、"
            f"保留款 {self.policy.default_retention_rate:.0%}／{self.policy.warranty_days} 天",
        ]
        low = [r for r in self.forecast(on, 8) if r["below_reserve"]]
        if low:
            lines.append(f"- ⚠️ 現金預警：{low[0]['week_start']} 當週預估餘額 {fmt(low[0]['closing'])} 低於準備金")
        return "\n".join(lines)

    # ------------------------------------------------------------ 內部
    def _wos(self, eng_id: str) -> list[WorkOrder]:
        return [self.work_orders[i] for i in self.engagements[eng_id].work_order_ids]

    def _require(self, wo_id: str, status: WOStatus) -> WorkOrder:
        wo = self.work_orders[wo_id]
        if wo.status is not status:
            raise PolicyViolation(f"{wo_id} 狀態為 {wo.status.value}，需為 {status.value}")
        return wo
