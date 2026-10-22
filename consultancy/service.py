"""公司金流服務：把 ConsultancyFirm 的動作變成可保存、可重播的事件。

每個成功的動作存成一筆事件（Supabase 的 consultancy_firm_events），
伺服器啟動時依 seq 重播，就能還原完整帳本。失敗的動作不會留下任何狀態。
"""
from __future__ import annotations

import dataclasses
import threading
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Callable

from . import ledger as L
from .companies import Company, CompanyKind
from .engagements import WOMode
from .firm import ConsultancyFirm, PolicyViolation
from .money import fmt, to_cents
from .storage import EventConflict, Store


class CommandError(ValueError):
    pass


def _d(v: Any) -> date:
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        raise CommandError(f"日期格式需為 YYYY-MM-DD：{v!r}") from None


def _cents(v: Any) -> int:
    """金額以「元」傳入（數字或字串）。"""
    if isinstance(v, bool) or v is None:
        raise CommandError("缺少金額")
    try:
        return to_cents(str(v) if isinstance(v, float) else v)
    except Exception:
        raise CommandError(f"金額格式錯誤：{v!r}") from None


def _rate(v: Any) -> Decimal | None:
    return None if v in (None, "") else Decimal(str(v))


def _req(a: dict, key: str) -> Any:
    if key not in a or a[key] in (None, ""):
        raise CommandError(f"缺少參數 {key}")
    return a[key]


def jsonable(x: Any) -> Any:
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: jsonable(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, (date, Decimal)):
        return str(x)
    if isinstance(x, (frozenset, set)):
        return sorted(jsonable(i) for i in x)
    if isinstance(x, (list, tuple)):
        return [jsonable(i) for i in x]
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    return x


# 動作名稱 → (需要日期參數 on?, 執行函式)
Command = Callable[[ConsultancyFirm, dict], Any]
COMMANDS: dict[str, tuple[bool, Command]] = {
    "inject_capital": (True, lambda f, a: f.inject_capital(_cents(_req(a, "amount")), _d(a["on"]),
                                                           a.get("memo") or "業主增資")),
    "register_company": (False, lambda f, a: f.register_company(Company(
        str(_req(a, "id")), str(_req(a, "name")), CompanyKind(a.get("kind", "external")),
        frozenset(map(str, a.get("capabilities") or [])), bool(a.get("vat_registered", True)),
        Decimal(str(a.get("withholding_rate", "0"))), int(a.get("payment_terms_days", 30)),
        float(a.get("rating", 3.0)), str(a.get("notes", ""))))),
    "open_engagement": (False, lambda f, a: f.open_engagement(
        str(_req(a, "client")), str(_req(a, "title")),
        [(str(_req(m, "title")), _cents(_req(m, "amount")), _d(_req(m, "planned_date")))
         for m in _req(a, "milestones")],
        int(a.get("client_terms_days", 14)))),
    "invoice_milestone": (True, lambda f, a: f.invoice_milestone(
        _req(a, "engagement_id"), _req(a, "milestone_id"), _d(a["on"]))),
    "receive_client_payment": (True, lambda f, a: f.receive_client_payment(
        _req(a, "engagement_id"), _req(a, "milestone_id"), _cents(_req(a, "amount")), _d(a["on"]))),
    "accept_milestone": (True, lambda f, a: f.accept_milestone(
        _req(a, "engagement_id"), _req(a, "milestone_id"), _d(a["on"]))),
    "dispatch_work_order": (True, lambda f, a: f.dispatch_work_order(
        _req(a, "engagement_id"), _req(a, "company_id"), str(_req(a, "title")), _cents(_req(a, "amount")),
        _d(_req(a, "expected_delivery")), WOMode(a.get("mode", "subcontract")),
        milestone_id=a.get("milestone_id"), retention_rate=_rate(a.get("retention_rate")),
        commission_rate=_rate(a.get("commission_rate")), override_by=a.get("override_by"), on=_d(a["on"]))),
    "cancel_work_order": (True, lambda f, a: f.cancel_work_order(
        _req(a, "work_order_id"), _d(a["on"]), str(_req(a, "reason")))),
    "mark_delivered": (True, lambda f, a: f.mark_delivered(_req(a, "work_order_id"), _d(a["on"]))),
    "reject_delivery": (True, lambda f, a: f.reject_delivery(
        _req(a, "work_order_id"), _d(a["on"]), str(_req(a, "reason")))),
    "collect_pass_through": (True, lambda f, a: f.collect_pass_through(
        _req(a, "work_order_id"), _cents(_req(a, "amount")), _d(a["on"]))),
    "accept_work_order": (True, lambda f, a: f.accept_work_order(
        _req(a, "work_order_id"), _d(a["on"]), str(_req(a, "accepted_by")))),
    "approve_payment": (False, lambda f, a: f.approve_payment(
        _req(a, "payment_id"), str(_req(a, "approver")))),
    "record_payment": (True, lambda f, a: f.record_payment(
        _req(a, "payment_id"), _d(a["on"]), str(_req(a, "bank_ref")))),
    "remit_withholding": (True, lambda f, a: f.remit_withholding(_d(a["on"]), str(_req(a, "bank_ref")))),
    "settle_vat": (True, lambda f, a: f.settle_vat(_d(a["on"]), str(_req(a, "bank_ref")))),
}


class FirmService:
    def __init__(self, store: Store, firm_id: str = "default", hq_name: str = "宇宙行星顧問",
                 today: Callable[[], date] = date.today):
        self.store = store
        self.firm_id = firm_id
        self.hq_name = hq_name
        self.today = today
        self._lock = threading.Lock()
        self.reload()

    def _fresh(self) -> ConsultancyFirm:
        return ConsultancyFirm(Company("hq", self.hq_name, CompanyKind.HQ))

    def reload(self) -> None:
        """從儲存區重播所有事件，重建帳本。"""
        firm = self._fresh()
        events = self.store.load_events(self.firm_id)
        for i, e in enumerate(events, 1):
            if e["seq"] != i:
                raise RuntimeError(f"事件序號不連續：預期 {i}，實際 {e['seq']}")
            COMMANDS[e["action"]][1](firm, e["args"])
        self.firm = firm
        self.seq = len(events)

    def execute(self, action: str, args: dict | None, actor: str | None = None) -> Any:
        if action not in COMMANDS:
            raise CommandError(f"不支援的動作 {action}，可用：{', '.join(COMMANDS)}")
        if not isinstance(args, dict) and args is not None:
            raise CommandError("args 必須是物件")
        needs_date, fn = COMMANDS[action]
        args = dict(args or {})
        if needs_date and not args.get("on"):
            args["on"] = self.today().isoformat()  # 存入事件，重播時日期才會一致
        with self._lock:
            try:
                result = fn(self.firm, args)
            except Exception:
                self.reload()  # 丟掉可能做一半的變更
                raise
            event = {"firm_id": self.firm_id, "seq": self.seq + 1, "action": action, "args": args, "actor": actor}
            try:
                self.store.append_event(event)
            except EventConflict:
                self.reload()  # 別的程序已寫入，改用最新狀態；請使用者重送
                raise
            except Exception:
                self.reload()
                raise
            self.seq += 1
        return jsonable(result)

    def snapshot(self, on: date | None = None) -> dict:
        f = self.firm
        on = on or self.today()
        with self._lock:
            balances = {code: {"name": L.CHART[code][0], "cents": v, "display": fmt(v)}
                        for code, v in f.gl.trial_balance().items()}
            return {
                "firm_id": self.firm_id, "hq": self.hq_name, "events": self.seq,
                "cash": {"cents": f.cash(), "display": fmt(f.cash())},
                "policy": jsonable(f.policy),
                "balances": balances,
                "companies": jsonable(f.companies.all()),
                "engagements": [{**jsonable(e), "report": f.engagement_report(e.id)} for e in f.engagements.values()],
                "work_orders": jsonable(list(f.work_orders.values())),
                "payments": [{**jsonable(p), "blockers": f.payment_blockers(p.id, on)} for p in f.payments.values()],
                "forecast": jsonable(f.forecast(on, 8)),
                "summary": f.snapshot(on),
            }
