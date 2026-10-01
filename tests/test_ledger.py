import unittest
from datetime import date

from consultancy import ledger as L
from consultancy.money import apply_rate, fmt, to_cents


class MoneyTest(unittest.TestCase):
    def test_to_cents_and_format(self):
        self.assertEqual(to_cents(1234), 123400)
        self.assertEqual(to_cents("0.005"), 1)
        self.assertEqual(fmt(-123456), "-TWD 1,234.56")
        with self.assertRaises(TypeError):
            to_cents(1.1)

    def test_apply_rate_rounds_half_up(self):
        self.assertEqual(apply_rate(10, "0.05"), 1)  # 0.5 → 1
        self.assertEqual(apply_rate(9, "0.05"), 0)


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.gl = L.Ledger("hq")
        self.d = date(2026, 10, 1)

    def test_rejects_unbalanced_entry(self):
        with self.assertRaises(L.LedgerError):
            self.gl.post(self.d, "bad", [L.dr(L.CASH, 100), L.cr(L.CAPITAL, 90)])
        self.assertEqual(self.gl.entries, ())

    def test_rejects_unknown_account_and_single_line(self):
        with self.assertRaises(L.LedgerError):
            self.gl.post(self.d, "bad", [L.dr("9999", 1), L.cr(L.CAPITAL, 1)])
        with self.assertRaises(L.LedgerError):
            self.gl.post(self.d, "bad", [L.dr(L.CASH, 0), L.cr(L.CAPITAL, 0)])

    def test_balances_follow_normal_side(self):
        self.gl.post(self.d, "capital", [L.dr(L.CASH, 1000), L.cr(L.CAPITAL, 1000)])
        self.gl.post(self.d, "bill", [L.dr(L.SUBCONTRACT_COST, 300), L.cr(L.AP, 300, "v1")])
        self.assertEqual(self.gl.balance(L.CASH), 1000)
        self.assertEqual(self.gl.balance(L.CAPITAL), 1000)
        self.assertEqual(self.gl.balance(L.AP), 300)
        self.assertEqual(self.gl.balance(L.AP, counterparty="v1"), 300)
        self.assertEqual(self.gl.balance(L.AP, counterparty="v2"), 0)
        self.assertTrue(self.gl.is_balanced())

    def test_as_of_filter(self):
        self.gl.post(self.d, "a", [L.dr(L.CASH, 1), L.cr(L.CAPITAL, 1)])
        self.gl.post(date(2026, 10, 5), "b", [L.dr(L.CASH, 2), L.cr(L.CAPITAL, 2)])
        self.assertEqual(self.gl.balance(L.CASH, as_of=date(2026, 10, 2)), 1)


if __name__ == "__main__":
    unittest.main()
