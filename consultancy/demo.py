"""示範情境：顧問公司接一個 30 萬的案子，拆給兩家公司做，並走完整金流。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from . import ledger as L
from .companies import Company, CompanyKind
from .engagements import WOMode
from .firm import ConsultancyFirm, PolicyViolation
from .money import fmt, to_cents


def build_demo_firm() -> ConsultancyFirm:
    firm = ConsultancyFirm(Company("hq", "宇宙行星顧問股份有限公司", CompanyKind.HQ))
    firm.register_company(Company(
        "kepler-lab", "開普勒自動化工作室（關係企業）", CompanyKind.INTERNAL,
        frozenset({"automation", "engineering"}), payment_terms_days=15, rating=4.5))
    firm.register_company(Company(
        "nova-design", "新星設計有限公司", CompanyKind.EXTERNAL,
        frozenset({"brand", "design"}), payment_terms_days=30, rating=4.2))
    firm.register_company(Company(
        "freelancer-lin", "林小姐（個人文案）", CompanyKind.EXTERNAL,
        frozenset({"copywriting"}), vat_registered=False,
        withholding_rate=Decimal("0.10"), payment_terms_days=7, rating=4.0))
    return firm


def run_demo() -> ConsultancyFirm:
    firm = build_demo_firm()
    d = date
    firm.inject_capital(to_cents(200_000), d(2026, 10, 1))

    eng = firm.open_engagement("晨光咖啡連鎖", "品牌重塑＋AI 客服自動化", [
        ("診斷與策略", to_cents(90_000), d(2026, 10, 10)),
        ("品牌與自動化交付", to_cents(210_000), d(2026, 11, 15)),
    ])
    m1, m2 = eng.milestones
    print(f"接案 {eng.id}：{eng.client}，合約 {fmt(eng.contract_value_cents)}")

    firm.invoice_milestone(eng.id, m1.id, d(2026, 10, 1))  # 先收訂金
    firm.receive_client_payment(eng.id, m1.id, m1.gross_cents, d(2026, 10, 8))

    # 派工給三家公司
    wo_auto = firm.dispatch_work_order(eng.id, "kepler-lab", "AI 客服 Agent 建置", to_cents(80_000),
                                       d(2026, 11, 5), milestone_id=m2.id, on=d(2026, 10, 2))
    wo_copy = firm.dispatch_work_order(eng.id, "freelancer-lin", "品牌文案", to_cents(20_000),
                                       d(2026, 10, 20), milestone_id=m1.id, on=d(2026, 10, 2))
    try:
        firm.dispatch_work_order(eng.id, "nova-design", "品牌視覺", to_cents(120_000), d(2026, 11, 1))
    except PolicyViolation as e:
        print(f"⛔ 派工被擋：{e}")
    wo_design = firm.dispatch_work_order(eng.id, "nova-design", "品牌視覺（議價後）", to_cents(90_000),
                                         d(2026, 11, 1), milestone_id=m2.id, on=d(2026, 10, 3))
    print(f"派工後預估毛利率：{firm.projected_margin(eng.id):.2%}")

    # 客戶另外直接委託的攝影：代收代付
    wo_photo = firm.dispatch_work_order(eng.id, "nova-design", "門市攝影（客戶直接委託）",
                                        to_cents(31_500), d(2026, 10, 25), mode=WOMode.PASS_THROUGH)
    firm.collect_pass_through(wo_photo.id, to_cents(31_500), d(2026, 10, 20))

    # 交付與驗收
    for wo, on in ((wo_copy, d(2026, 10, 20)), (wo_photo, d(2026, 10, 25)),
                   (wo_design, d(2026, 11, 1)), (wo_auto, d(2026, 11, 5))):
        firm.mark_delivered(wo.id, on)
        for pr in firm.accept_work_order(wo.id, on, accepted_by="土星驗收清單＋業主"):
            print(f"  付款申請 {pr.id} {wo.title} {pr.kind.value} {fmt(pr.amount_cents)} 到期 {pr.due_on}")

    print("\n本週現金預測（自 2026-11-05 起）")
    for row in firm.forecast(d(2026, 11, 5), weeks=6):
        flag = " ⚠️ 低於準備金" if row["below_reserve"] else ""
        print(f"  {row['week_start']} 流入 {fmt(row['inflow'])} 流出 {fmt(row['outflow'])} "
              f"期末 {fmt(row['closing'])}{flag}")

    # 嘗試付款：設計款要等客戶第二期付清
    design_main = next(p for p in firm.payments.values() if p.work_order_id == wo_design.id)
    firm.approve_payment(design_main.id, approver="業主 王大明")
    print(f"\n付款檢查 {design_main.id}：{firm.payment_blockers(design_main.id, d(2026, 12, 1)) or '可付款'}")

    firm.accept_milestone(eng.id, m1.id, d(2026, 10, 15))
    firm.accept_milestone(eng.id, m2.id, d(2026, 11, 15))
    firm.receive_client_payment(eng.id, m2.id, m2.gross_cents, d(2026, 11, 28))
    print(f"客戶付清第二期後：{firm.payment_blockers(design_main.id, d(2026, 12, 1)) or '可付款'}")

    for pr in list(firm.payments.values()):
        if pr.approved_by is None:
            firm.approve_payment(pr.id, approver="業主 王大明")
        pay_on = max(pr.due_on, d(2026, 12, 1))
        firm.record_payment(pr.id, pay_on, bank_ref=f"TX{pr.id[-3:]}")
    firm.remit_withholding(d(2026, 12, 10), "WHT-202612")
    firm.settle_vat(d(2027, 1, 15), "VAT-202611-12")

    print("\n案件損益與現金")
    for k, v in firm.engagement_report(eng.id).items():
        print(f"  {k}: {fmt(v) if isinstance(v, int) else v}")
    print(f"\nHQ 現金：{fmt(firm.cash())}；代收款餘額：{fmt(firm.gl.balance(L.PASS_THROUGH))}")
    print(f"關係企業 kepler-lab 現金：{fmt(firm.books['kepler-lab'].balance(L.CASH))}，"
          f"應收 HQ：{fmt(firm.books['kepler-lab'].balance(L.AR))}")
    print(f"帳本平衡：{all(b.is_balanced() for b in firm.books.values())}")
    return firm
