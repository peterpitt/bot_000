import base64
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from consultancy import web
from consultancy.firm import PolicyViolation
from consultancy.service import CommandError, FirmService
from consultancy.storage import EventConflict, MemoryStore, SupabaseStore, clean_proposal

TODAY = date(2026, 10, 22)


def seed(svc: FirmService) -> None:
    svc.execute("inject_capital", {"amount": 200000, "on": "2026-10-01"})
    svc.execute("register_company", {"id": "ext", "name": "外部設計", "capabilities": ["design"]})
    svc.execute("open_engagement", {"client": "客戶A", "title": "官網", "milestones": [
        {"title": "交付", "amount": "100000", "planned_date": "2026-11-01"}]})
    svc.execute("dispatch_work_order", {"engagement_id": "ENG-001", "company_id": "ext", "title": "設計",
                                        "amount": 50000, "expected_delivery": "2026-10-20",
                                        "milestone_id": "ENG-001-M1"})


class FirmServiceTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.svc = FirmService(self.store, today=lambda: TODAY)
        seed(self.svc)

    def test_replay_rebuilds_identical_state(self):
        again = FirmService(self.store, today=lambda: TODAY)
        self.assertEqual(again.seq, 4)
        a, b = self.svc.snapshot(TODAY), again.snapshot(TODAY)
        self.assertEqual(a["cash"], b["cash"])
        self.assertEqual(a["work_orders"], b["work_orders"])
        self.assertEqual(b["work_orders"][0]["id"], "WO-001")

    def test_default_date_is_stored_in_event(self):
        ev = self.store.load_events("default")[3]
        self.assertEqual(ev["args"]["on"], "2026-10-22")

    def test_failed_command_leaves_no_trace(self):
        with self.assertRaises(PolicyViolation):  # 毛利只剩 20%
            self.svc.execute("dispatch_work_order", {"engagement_id": "ENG-001", "company_id": "ext",
                                                     "title": "超支", "amount": 30000,
                                                     "expected_delivery": "2026-10-25"})
        with self.assertRaises(CommandError):
            self.svc.execute("open_engagement", {"client": "x"})
        with self.assertRaises(CommandError):
            self.svc.execute("drop_tables", {})
        self.assertEqual(self.svc.seq, 4)
        self.assertEqual(len(self.store.load_events("default")), 4)
        self.assertEqual(len(self.svc.firm.work_orders), 1)

    def test_payment_flow_and_human_approval(self):
        self.svc.execute("mark_delivered", {"work_order_id": "WO-001", "on": "2026-10-20"})
        prs = self.svc.execute("accept_work_order", {"work_order_id": "WO-001", "on": "2026-10-20",
                                                     "accepted_by": "業主"})
        self.assertEqual([p["amount_cents"] for p in prs], [4_750_000, 500_000])
        with self.assertRaises(PolicyViolation):
            self.svc.execute("approve_payment", {"payment_id": "PAY-001", "approver": "grok"})
        self.svc.execute("approve_payment", {"payment_id": "PAY-001", "approver": "業主 王大明"})
        snap = self.svc.snapshot(date(2026, 11, 19))
        pay = snap["payments"][0]
        self.assertEqual(pay["status"], "approved")
        self.assertTrue(any("Pay-when-paid" in b for b in pay["blockers"]))
        json.dumps(snap, ensure_ascii=False)  # 整份快照可序列化

    def test_event_conflict_reloads(self):
        other = FirmService(self.store, today=lambda: TODAY)
        other.execute("inject_capital", {"amount": 1, "on": "2026-10-02"})
        with self.assertRaises(EventConflict):
            self.svc.execute("inject_capital", {"amount": 2, "on": "2026-10-02"})
        self.assertEqual(self.svc.seq, 5)  # 已重新載入對方寫入的事件


class CleanProposalTest(unittest.TestCase):
    def test_validation(self):
        with self.assertRaises(ValueError):
            clean_proposal({"idea": "x"}, "bad id!")
        with self.assertRaises(ValueError):
            clean_proposal({"idea": "  "}, "abcdefgh")
        p = clean_proposal({"idea": "想法", "evil": 1, "topics": ["a"], "result": {"k": 1}}, "abcdefgh")
        self.assertNotIn("evil", p)
        self.assertEqual(p["id"], "abcdefgh")


class FakePostgREST(BaseHTTPRequestHandler):
    requests: list = []
    events: list = []

    def log_message(self, *a):
        pass

    def _reply(self, status, data=None):
        body = b"" if data is None else json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        u = urlsplit(self.path)
        self.requests.append({"method": self.command, "path": u.path, "query": parse_qs(u.query),
                              "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        return u.path, parse_qs(u.query), body

    def do_POST(self):
        path, q, body = self._record()
        if path.endswith("consultancy_firm_events"):
            if any(e["seq"] == body["seq"] for e in self.events):
                return self._reply(409, {"code": "23505"})
            self.events.append(body)
            return self._reply(201)
        return self._reply(201, [body])

    def do_GET(self):
        path, q, _ = self._record()
        if path.endswith("consultancy_firm_events"):
            off, lim = int(q["offset"][0]), int(q["limit"][0])
            return self._reply(200, self.events[off:off + lim])
        return self._reply(200, [{"id": "abcdefgh", "idea": "x"}])


class SupabaseStoreTest(unittest.TestCase):
    def setUp(self):
        FakePostgREST.requests, FakePostgREST.events = [], []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakePostgREST)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.store = SupabaseStore(f"http://127.0.0.1:{self.server.server_port}", "sb_secret_test")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_headers_and_upsert(self):
        self.store.save_proposal({"id": "abcdefgh", "idea": "想法"})
        r = FakePostgREST.requests[0]
        self.assertEqual(r["path"], "/rest/v1/consultancy_proposals")
        self.assertEqual(r["query"]["on_conflict"], ["id"])
        self.assertEqual(r["headers"]["apikey"], "sb_secret_test")
        self.assertEqual(r["headers"]["authorization"], "Bearer sb_secret_test")
        self.assertIn("resolution=merge-duplicates", r["headers"]["prefer"])
        self.assertIn("updated_at", r["body"])
        self.store.get_proposal("abcdefgh")
        self.assertEqual(FakePostgREST.requests[1]["query"]["id"], ["eq.abcdefgh"])

    def test_events_conflict_and_pagination(self):
        self.store.PAGE = 2
        for i in range(1, 6):
            self.store.append_event({"firm_id": "f", "seq": i, "action": "a", "args": {}, "actor": None})
        with self.assertRaises(EventConflict):
            self.store.append_event({"firm_id": "f", "seq": 3, "action": "a", "args": {}, "actor": None})
        self.assertEqual([e["seq"] for e in self.store.load_events("f")], [1, 2, 3, 4, 5])


class DeployedServerTest(unittest.TestCase):
    def start(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "XAI_API_KEY"):
                os.environ.pop(k, None)
            self.server = web.make_server("127.0.0.1", 0, store=MemoryStore())
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None, auth=("owner", "pw")):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, json.loads(raw) if r.headers.get_content_type() == "application/json" else raw
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_password_required(self):
        self.start({"APP_PASSWORD": "pw"})
        self.assertEqual(self.call("GET", "/healthz", auth=None)[0], 200)
        self.assertEqual(self.call("GET", "/", auth=None)[0], 401)
        self.assertEqual(self.call("GET", "/api/firm", auth=("owner", "wrong"))[0], 401)
        self.assertEqual(self.call("GET", "/api/health")[1]["storage"], "memory")

    def test_refuses_public_bind_without_password(self):
        with mock.patch.dict(os.environ, {"APP_PASSWORD": ""}):
            with self.assertRaises(SystemExit):
                web.make_server("0.0.0.0", 0, store=MemoryStore())

    def test_proposals_roundtrip(self):
        self.start({"APP_PASSWORD": "pw"})
        status, row = self.call("PUT", "/api/proposals/abcdefgh-1", {"idea": "咖啡店代營運", "result": {"a": 1}})
        self.assertEqual(status, 200)
        self.assertEqual(row["created_by"], "owner")
        self.assertEqual(self.call("GET", "/api/proposals")[1][0]["id"], "abcdefgh-1")
        self.assertEqual(self.call("GET", "/api/proposals/abcdefgh-1")[1]["result"], {"a": 1})
        self.assertEqual(self.call("GET", "/api/proposals/nope-nope")[0], 404)
        self.assertEqual(self.call("PUT", "/api/proposals/abcdefgh-2", {"idea": ""})[0], 400)

    def test_firm_commands_over_http(self):
        self.start({"APP_PASSWORD": "pw"})
        s, body = self.call("POST", "/api/firm/commands",
                            {"action": "inject_capital", "args": {"amount": 1000, "on": "2026-10-01"}})
        self.assertEqual((s, body["seq"]), (200, 1))
        s, body = self.call("POST", "/api/firm/commands", {"action": "approve_payment", "args": {"payment_id": "X"}})
        self.assertEqual(s, 422)
        snap = self.call("GET", "/api/firm?on=2026-10-02")[1]
        self.assertEqual(snap["cash"]["cents"], 100000)
        self.assertEqual(self.call("GET", "/api/firm?on=bad")[0], 400)


if __name__ == "__main__":
    unittest.main()
