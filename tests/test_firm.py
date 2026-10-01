import contextlib
import io
import unittest
from datetime import date
from decimal import Decimal

from consultancy import ledger as L
from consultancy.companies import Company, CompanyKind
from consultancy.demo import run_demo
from consultancy.engagements import PaymentKind, PaymentStatus, WOMode, WOStatus
from consultancy.firm import ConsultancyFirm, PolicyViolation, TreasuryPolicy
from consultancy.money import to_cents

D = date(2026, 10, 1)


def make_firm(**policy) -> ConsultancyFirm:
    firm = ConsultancyFirm(Company("hq", "HQ", CompanyKind.HQ), TreasuryPolicy(**policy))
    firm.register_company(Company("ext", "外部公司", CompanyKind.EXTERNAL, frozenset({"web"}), payment_terms_days=10))
    firm.register_company(Company("sis", "關係企業", CompanyKind.INTERNAL, frozenset({"web"}), rating=5))
    firm.register_company(Company("ind", "個人", CompanyKind.EXTERNAL, vat_registered=False,
                                  withholding_rate=Decimal("0.10"), payment_terms_days=0))
    firm.inject_capital(to_cents(100_000), D)
    return firm


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.firm = make_firm()
        self.eng = self.firm.open_engagement("客戶", "網站", [("M1", to_cents(100_000), D)])

    def test_margin_guard_blocks_and_override_allows(self):
        with self.assertRaises(PolicyViolation):
            self.firm.dispatch_work_order(self.eng.id, "ext", "x", to_cents(75_000), D)
        wo = self.firm.dispatch_work_order(self.eng.id, "ext", "x", to_cents(75_000), D, override_by="業主")
        self.assertEqual(wo.override_by, "業主")
        self.assertEqual(self.firm.projected_margin(self.eng.id), Decimal("0.25"))

    def test_cancelled_orders_release_budget(self):
        wo = self.firm.dispatch_work_order(self.eng.id, "ext", "x", to_cents(70_000), D)
        self.firm.cancel_work_order(wo.id, D, "客戶改需求")
        self.firm.dispatch_work_order(self.eng.id, "ext", "y", to_cents(70_000), D)

    def test_cannot_dispatch_to_hq(self):
        with self.assertRaises(PolicyViolation):
            self.firm.dispatch_work_order(self.eng.id, "hq", "x", 100, D)

    def test_registry_find_by_capability(self):
        self.assertEqual([c.id for c in self.firm.companies.find("web")], ["sis", "ext"])


class SubcontractCashflowTest(unittest.TestCase):
    def setUp(self):
        self.firm = make_firm(min_cash_reserve_cents=to_cents(10_000))
        self.eng = self.firm.open_engagement("客戶", "網站", [("M1", to_cents(100_000), D)])
        self.ms = self.eng.milestones[0]
        self.wo = self.firm.dispatch_work_order(self.eng.id, "ext", "前端", to_cents(50_000), D,
                                                milestone_id=self.ms.id)
        self.firm.mark_delivered(self.wo.id, D)
        self.main, self.ret = self.firm.accept_work_order(self.wo.id, date(2026, 10, 5), "業主")

    def test_bill_split(self):
        # 50,000 + 5% VAT = 52,500；保留款 10% = 5,000
        self.assertEqual(self.main.amount_cents, to_cents(47_500))
        self.assertEqual(self.ret.amount_cents, to_cents(5_000))
        self.assertEqual(self.main.due_on, date(2026, 10, 15))
        self.assertEqual(self.ret.due_on, date(2026, 11, 4))
        self.assertEqual(self.firm.gl.balance(L.INPUT_VAT), to_cents(2_500))

    def test_payment_requires_named_human(self):
        with self.assertRaises(PolicyViolation):
            self.firm.approve_payment(self.main.id, "grok")
        self.assertIn("尚未經人工核准", self.firm.payment_blockers(self.main.id, D))

    def test_pay_when_paid_then_success(self):
        self.firm.approve_payment(self.main.id, "業主")
        blockers = self.firm.payment_blockers(self.main.id, date(2026, 10, 15))
        self.assertTrue(any("Pay-when-paid" in b for b in blockers))
        with self.assertRaises(PolicyViolation):
            self.firm.record_payment(self.main.id, date(2026, 10, 15), "TX1")

        self.firm.invoice_milestone(self.eng.id, self.ms.id, D)
        self.firm.receive_client_payment(self.eng.id, self.ms.id, self.ms.gross_cents, date(2026, 10, 10))
        self.firm.record_payment(self.main.id, date(2026, 10, 15), "TX1")
        self.assertEqual(self.main.status, PaymentStatus.PAID)
        self.assertEqual(self.firm.gl.balance(L.AP), 0)
        self.assertEqual(self.wo.status, WOStatus.ACCEPTED)  # 保留款未付

    def test_retention_waits_for_warranty(self):
        self.firm.invoice_milestone(self.eng.id, self.ms.id, D)
        self.firm.receive_client_payment(self.eng.id, self.ms.id, self.ms.gross_cents, D)
        self.firm.approve_payment(self.ret.id, "業主")
        self.assertTrue(any("保固期" in b for b in self.firm.payment_blockers(self.ret.id, date(2026, 10, 20))))
        self.firm.approve_payment(self.main.id, "業主")
        self.firm.record_payment(self.main.id, date(2026, 10, 15), "TX1")
        self.firm.record_payment(self.ret.id, date(2026, 11, 4), "TX2")
        self.assertEqual(self.wo.status, WOStatus.PAID)
        self.assertEqual(self.firm.gl.balance(L.RETENTION), 0)

    def test_cash_reserve_blocks_payment(self):
        firm = make_firm(min_cash_reserve_cents=to_cents(90_000), pay_when_paid=False)
        eng = firm.open_engagement("客戶", "網站", [("M1", to_cents(100_000), D)])
        wo = firm.dispatch_work_order(eng.id, "ext", "x", to_cents(20_000), D)
        firm.mark_delivered(wo.id, D)
        main, _ = firm.accept_work_order(wo.id, D, "業主")
        firm.approve_payment(main.id, "業主")
        self.assertTrue(any("安全準備金" in b for b in firm.payment_blockers(main.id, D)))

    def test_ledger_stays_balanced(self):
        self.assertTrue(self.firm.gl.is_balanced())


class WithholdingAndTaxTest(unittest.TestCase):
    def test_individual_withholding_and_vat_settlement(self):
        firm = make_firm(pay_when_paid=False, default_retention_rate=Decimal("0"))
        eng = firm.open_engagement("客戶", "文案", [("M1", to_cents(10_000), D)])
        wo = firm.dispatch_work_order(eng.id, "ind", "文案", to_cents(5_000), D)
        firm.mark_delivered(wo.id, D)
        (main,) = firm.accept_work_order(wo.id, D, "業主")
        self.assertEqual(main.amount_cents, to_cents(4_500))  # 無營業稅、扣繳 10%
        self.assertEqual(firm.gl.balance(L.WHT), to_cents(500))
        firm.approve_payment(main.id, "業主")
        firm.record_payment(main.id, D, "TX")
        self.assertEqual(firm.remit_withholding(D, "WHT"), to_cents(500))
        firm.accept_milestone(eng.id, eng.milestones[0].id, D)  # 自動開發票：銷項 500
        self.assertEqual(firm.settle_vat(D, "VAT"), to_cents(500))
        self.assertEqual(firm.gl.balance(L.OUTPUT_VAT), 0)


class PassThroughTest(unittest.TestCase):
    def setUp(self):
        self.firm = make_firm()
        self.eng = self.firm.open_engagement("客戶", "顧問", [("M1", to_cents(50_000), D)])
        self.wo = self.firm.dispatch_work_order(self.eng.id, "sis", "攝影", to_cents(21_000), D,
                                                mode=WOMode.PASS_THROUGH, commission_rate=Decimal("0.10"))
        self.firm.mark_delivered(self.wo.id, D)

    def test_never_pay_before_collected(self):
        with self.assertRaises(PolicyViolation):
            self.firm.accept_work_order(self.wo.id, D, "業主")

    def test_commission_and_intercompany_books(self):
        self.firm.collect_pass_through(self.wo.id, to_cents(21_000), D)
        (pr,) = self.firm.accept_work_order(self.wo.id, D, "業主")
        # 佣金 2,100 + 稅 105 自代收款扣除
        self.assertEqual(pr.kind, PaymentKind.MAIN)
        self.assertEqual(pr.amount_cents, to_cents(18_795))
        self.assertEqual(self.firm.gl.balance(L.COMMISSION_REV), to_cents(2_100))
        self.assertEqual(self.firm.gl.balance(L.PASS_THROUGH), 0)
        self.firm.approve_payment(pr.id, "業主")
        self.firm.record_payment(pr.id, pr.due_on, "TX")
        sis = self.firm.books["sis"]
        self.assertEqual(sis.balance(L.AR), 0)
        self.assertEqual(sis.balance(L.CASH), to_cents(18_795))
        self.assertEqual(sis.balance(L.SERVICE_REV), to_cents(20_000))
        self.assertTrue(sis.is_balanced())

    def test_overcollection_rejected(self):
        with self.assertRaises(PolicyViolation):
            self.firm.collect_pass_through(self.wo.id, to_cents(21_001), D)


class ForecastAndDemoTest(unittest.TestCase):
    def test_forecast_flags_reserve_breach(self):
        firm = make_firm(min_cash_reserve_cents=to_cents(80_000))
        eng = firm.open_engagement("客戶", "網站", [("M1", to_cents(100_000), date(2026, 12, 31))])
        firm.dispatch_work_order(eng.id, "ext", "x", to_cents(60_000), date(2026, 10, 5))
        rows = firm.forecast(D, weeks=4)
        # 10/5 交付 + 10 天付款條件 → 10/15 那週流出 60,000×1.05 − 保留款 6,000
        self.assertEqual(rows[2]["outflow"], to_cents(57_000))
        self.assertTrue(rows[2]["below_reserve"])
        self.assertIn("現金預警", firm.snapshot(D))

    def test_demo_runs_and_books_balance(self):
        with contextlib.redirect_stdout(io.StringIO()):
            firm = run_demo()
        self.assertTrue(all(b.is_balanced() for b in firm.books.values()))
        self.assertTrue(all(p.status is PaymentStatus.PAID for p in firm.payments.values()))
        self.assertEqual(firm.gl.balance(L.WHT), 0)
        self.assertEqual(firm.gl.balance(L.PASS_THROUGH), 0)


if __name__ == "__main__":
    unittest.main()
