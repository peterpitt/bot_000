import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from consultancy import web


class FakeBackend:
    model = "fake-model"

    def __init__(self):
        self.messages = None

    def chat(self, messages):
        self.messages = messages
        return '{"ok": true}'


class WebServerTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBackend()
        self.backend = None
        handler = type("H", (web.Handler,), {"backend_factory": staticmethod(lambda: self.backend)})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.read().decode()

    def post(self, path, data):
        req = urllib.request.Request(self.base + path, data=json.dumps(data).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_serves_page_in_skeleton(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith("<!doctype html>"))
        self.assertIn("<title>星際智囊團工作台</title>", body)

    def test_without_key_reports_offline(self):
        self.assertEqual(json.loads(self.get("/api/health")[1]), {"ok": False, "model": None})
        status, body = self.post("/api/sample", {"prompt": "hi"})
        self.assertEqual(status, 503)

    def test_sample_forwards_with_system_prompt(self):
        self.backend = self.fake
        self.assertTrue(json.loads(self.get("/api/health")[1])["ok"])
        status, body = self.post("/api/sample", {"prompt": "想法"})
        self.assertEqual((status, body), (200, {"text": '{"ok": true}'}))
        self.assertEqual(self.fake.messages[0]["role"], "system")
        self.assertIn("金流紅線", self.fake.messages[0]["content"])
        self.assertEqual(self.fake.messages[1]["content"], "想法")

    def test_rejects_empty_prompt(self):
        self.backend = self.fake
        self.assertEqual(self.post("/api/sample", {"prompt": ""})[0], 400)


if __name__ == "__main__":
    unittest.main()
