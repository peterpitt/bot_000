"""金額工具：一律以「分」(int) 儲存，避免浮點誤差。"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CURRENCY = "TWD"


def to_cents(amount: int | str | Decimal) -> int:
    """把「元」轉成「分」。接受 int / str / Decimal，不接受 float 以免誤差。"""
    if isinstance(amount, float):
        raise TypeError("金額請用 int、str 或 Decimal，不要用 float")
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d * 100)


def apply_rate(cents: int, rate: Decimal | str) -> int:
    """金額 × 比率，四捨五入到分。"""
    return int((Decimal(cents) * Decimal(str(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt(cents: int, currency: str = CURRENCY) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}{currency} {c // 100:,}.{c % 100:02d}"
