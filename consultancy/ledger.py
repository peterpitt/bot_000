"""複式記帳總帳（每家公司一本帳）。

所有金流動作最後都落到這裡：每筆分錄借貸必須平衡、建立後不可修改，
需要更正時只能再記一筆反向分錄，以保留完整稽核軌跡。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Kind(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


# 會計科目代碼
CASH = "1100"
AR = "1200"
INPUT_VAT = "1300"
PREPAID_TAX = "1400"
AP = "2100"
RETENTION = "2150"
CONTRACT_LIAB = "2200"
PASS_THROUGH = "2300"
OUTPUT_VAT = "2400"
WHT = "2500"
CAPITAL = "3100"
SERVICE_REV = "4100"
COMMISSION_REV = "4200"
SUBCONTRACT_COST = "5100"

CHART: dict[str, tuple[str, Kind]] = {
    CASH: ("現金及銀行存款", Kind.ASSET),
    AR: ("應收帳款", Kind.ASSET),
    INPUT_VAT: ("進項稅額", Kind.ASSET),
    PREPAID_TAX: ("被扣繳稅款（可抵稅）", Kind.ASSET),
    AP: ("應付帳款", Kind.LIABILITY),
    RETENTION: ("應付保留款", Kind.LIABILITY),
    CONTRACT_LIAB: ("預收款（合約負債）", Kind.LIABILITY),
    PASS_THROUGH: ("代收款（代收代付）", Kind.LIABILITY),
    OUTPUT_VAT: ("銷項稅額", Kind.LIABILITY),
    WHT: ("代扣繳稅款", Kind.LIABILITY),
    CAPITAL: ("業主資本", Kind.EQUITY),
    SERVICE_REV: ("顧問服務收入", Kind.REVENUE),
    COMMISSION_REV: ("媒合佣金收入", Kind.REVENUE),
    SUBCONTRACT_COST: ("外包成本", Kind.EXPENSE),
}

_DEBIT_NORMAL = {Kind.ASSET, Kind.EXPENSE}


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class Line:
    account: str
    debit: int = 0
    credit: int = 0
    counterparty: str | None = None


def dr(account: str, cents: int, counterparty: str | None = None) -> Line:
    return Line(account, debit=cents, counterparty=counterparty)


def cr(account: str, cents: int, counterparty: str | None = None) -> Line:
    return Line(account, credit=cents, counterparty=counterparty)


@dataclass(frozen=True)
class Entry:
    id: int
    on: date
    memo: str
    lines: tuple[Line, ...]
    ref: str | None = None


class Ledger:
    def __init__(self, entity_id: str):
        self.entity_id = entity_id
        self._entries: list[Entry] = []

    @property
    def entries(self) -> tuple[Entry, ...]:
        return tuple(self._entries)

    def post(self, on: date, memo: str, lines: list[Line], ref: str | None = None) -> Entry:
        lines = [ln for ln in lines if ln.debit or ln.credit]
        if len(lines) < 2:
            raise LedgerError("分錄至少需要兩行")
        for ln in lines:
            if ln.account not in CHART:
                raise LedgerError(f"未知科目 {ln.account}")
            if ln.debit < 0 or ln.credit < 0 or (ln.debit and ln.credit):
                raise LedgerError("每行只能有一個非負的借方或貸方金額")
        debit = sum(ln.debit for ln in lines)
        credit = sum(ln.credit for ln in lines)
        if debit != credit:
            raise LedgerError(f"借貸不平衡：借 {debit} / 貸 {credit}")
        entry = Entry(len(self._entries) + 1, on, memo, tuple(lines), ref)
        self._entries.append(entry)
        return entry

    def balance(self, account: str, counterparty: str | None = None, as_of: date | None = None) -> int:
        """回傳科目餘額（依正常餘額方向為正）。"""
        _, kind = CHART[account]
        total = 0
        for e in self._entries:
            if as_of and e.on > as_of:
                continue
            for ln in e.lines:
                if ln.account != account:
                    continue
                if counterparty is not None and ln.counterparty != counterparty:
                    continue
                total += ln.debit - ln.credit
        return total if kind in _DEBIT_NORMAL else -total

    def trial_balance(self) -> dict[str, int]:
        return {code: self.balance(code) for code in CHART if any(
            ln.account == code for e in self._entries for ln in e.lines)}

    def is_balanced(self) -> bool:
        return sum(ln.debit - ln.credit for e in self._entries for ln in e.lines) == 0

    def by_ref(self, ref: str) -> list[Entry]:
        return [e for e in self._entries if e.ref == ref]
