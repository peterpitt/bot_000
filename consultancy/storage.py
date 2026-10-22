"""資料保存：Supabase（PostgREST，純標準函式庫）或記憶體（本機／測試）。

Supabase 用 secret key（或舊版 service_role key）從伺服器端存取；
資料表開啟 RLS 且沒有任何 policy，所以瀏覽器端的 publishable／anon key 讀不到。
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Protocol

PROPOSALS = "consultancy_proposals"
EVENTS = "consultancy_firm_events"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
PROPOSAL_FIELDS = ("idea", "input", "topics", "advisors", "result", "mvp_text", "engine", "created_by")


class StorageError(RuntimeError):
    pass


class EventConflict(StorageError):
    """同一個 seq 已被別的程序寫入（多個容器同時寫同一家公司）。"""


class Store(Protocol):
    kind: str

    def save_proposal(self, proposal: dict) -> dict: ...
    def list_proposals(self, limit: int = 20) -> list[dict]: ...
    def get_proposal(self, proposal_id: str) -> dict | None: ...
    def append_event(self, event: dict) -> None: ...
    def load_events(self, firm_id: str) -> list[dict]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_proposal(raw: Any, proposal_id: str) -> dict:
    """驗證並只保留允許的欄位。"""
    if not ID_RE.match(proposal_id or ""):
        raise ValueError("提案 id 格式錯誤")
    if not isinstance(raw, dict):
        raise ValueError("提案內容必須是物件")
    idea = str(raw.get("idea") or "").strip()
    if not idea or len(idea) > 5000:
        raise ValueError("想法不可空白，且不超過 5000 字")
    p = {k: raw.get(k) for k in PROPOSAL_FIELDS if k in raw}
    p["id"] = proposal_id
    p["idea"] = idea
    p["input"] = p.get("input") if isinstance(p.get("input"), dict) else {}
    p["topics"] = [str(t) for t in (p.get("topics") or [])][:20]
    p["advisors"] = [str(a) for a in (p.get("advisors") or [])][:12]
    p["mvp_text"] = str(p.get("mvp_text") or "")
    if len(json.dumps(p, ensure_ascii=False).encode()) > 512 * 1024:
        raise ValueError("提案內容超過 512 KB")
    return p


class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self._proposals: dict[str, dict] = {}
        self._events: list[dict] = []
        self._lock = threading.Lock()

    def save_proposal(self, proposal: dict) -> dict:
        with self._lock:
            now = _now()
            old = self._proposals.get(proposal["id"], {"created_at": now})
            row = {**old, **proposal, "updated_at": now}
            self._proposals[proposal["id"]] = row
            return dict(row)

    def list_proposals(self, limit: int = 20) -> list[dict]:
        rows = sorted(self._proposals.values(), key=lambda r: r["updated_at"], reverse=True)[:limit]
        return [{k: r.get(k) for k in ("id", "idea", "created_at", "updated_at")} for r in rows]

    def get_proposal(self, proposal_id: str) -> dict | None:
        row = self._proposals.get(proposal_id)
        return dict(row) if row else None

    def append_event(self, event: dict) -> None:
        with self._lock:
            if any(e["firm_id"] == event["firm_id"] and e["seq"] == event["seq"] for e in self._events):
                raise EventConflict(f"seq {event['seq']} 已存在")
            self._events.append({**event, "created_at": _now()})

    def load_events(self, firm_id: str) -> list[dict]:
        return sorted((dict(e) for e in self._events if e["firm_id"] == firm_id), key=lambda e: e["seq"])


class SupabaseStore:
    kind = "supabase"
    PAGE = 1000  # PostgREST 預設單次最多回傳筆數

    def __init__(self, url: str, key: str, timeout: float = 15):
        if not url or not key:
            raise ValueError("需要 SUPABASE_URL 與 SUPABASE_SECRET_KEY")
        self.base = url.rstrip("/") + "/rest/v1/"
        self.key = key
        self.timeout = timeout

    def _request(self, method: str, table: str, query: dict | None = None, body: Any = None,
                 prefer: str | None = None) -> Any:
        url = self.base + table + ("?" + urllib.parse.urlencode(query, safe=",.*()") if query else "")
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code == 409:
                raise EventConflict(detail) from None
            raise StorageError(f"Supabase {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise StorageError(f"無法連線 Supabase：{e.reason}") from None
        return json.loads(raw) if raw else None

    def save_proposal(self, proposal: dict) -> dict:
        rows = self._request("POST", PROPOSALS, {"on_conflict": "id"}, {**proposal, "updated_at": _now()},
                             prefer="resolution=merge-duplicates,return=representation")
        return rows[0] if rows else proposal

    def list_proposals(self, limit: int = 20) -> list[dict]:
        return self._request("GET", PROPOSALS, {
            "select": "id,idea,created_at,updated_at", "order": "updated_at.desc", "limit": str(limit)}) or []

    def get_proposal(self, proposal_id: str) -> dict | None:
        rows = self._request("GET", PROPOSALS, {"select": "*", "id": f"eq.{proposal_id}", "limit": "1"})
        return rows[0] if rows else None

    def append_event(self, event: dict) -> None:
        self._request("POST", EVENTS, None, event, prefer="return=minimal")

    def load_events(self, firm_id: str) -> list[dict]:
        events: list[dict] = []
        while True:
            page = self._request("GET", EVENTS, {
                "select": "firm_id,seq,action,args,actor,created_at", "firm_id": f"eq.{firm_id}",
                "order": "seq.asc", "limit": str(self.PAGE), "offset": str(len(events))}) or []
            events.extend(page)
            if len(page) < self.PAGE:
                return events


def store_from_env() -> Store:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if url and key:
        return SupabaseStore(url, key)
    return MemoryStore()
