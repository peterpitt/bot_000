"""本機網頁伺服器：python -m consultancy serve

提供 web/index.html，並把頁面的 AI 呼叫轉給 Grok（需設定 XAI_API_KEY）。
同一份頁面發布成 claude.ai Artifact 時，改用 viewer 的 Claude 帳號，不經過這裡。
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .council import OPS_ADDENDUM, load_base_prompt
from .llm import LLMBackend, XAIChatBackend

INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"
MAX_PROMPT_BYTES = 256 * 1024
SKELETON_HEAD = (
    '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    "<style>[hidden]{display:none!important}body{margin:0}img{max-width:100%}</style></head><body>"
)


def default_backend_factory() -> LLMBackend | None:
    return XAIChatBackend() if os.environ.get("XAI_API_KEY") else None


class Handler(BaseHTTPRequestHandler):
    backend_factory = staticmethod(default_backend_factory)

    def log_message(self, fmt: str, *args) -> None:  # 安靜一點，只留錯誤
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            page = SKELETON_HEAD + INDEX.read_text(encoding="utf-8") + "</body></html>"
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif path == "/api/health":
            backend = self.backend_factory()
            self._json(200, {"ok": backend is not None, "model": getattr(backend, "model", None)})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/sample":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_PROMPT_BYTES * 2:
            self._json(413, {"error": "prompt too large"})
            return
        try:
            prompt = str(json.loads(self.rfile.read(length) or b"{}").get("prompt", ""))
        except (ValueError, AttributeError):
            self._json(400, {"error": "invalid json"})
            return
        if not prompt or len(prompt.encode()) > MAX_PROMPT_BYTES:
            self._json(400, {"error": "prompt missing or too large"})
            return
        backend = self.backend_factory()
        if backend is None:
            self._json(503, {"error": "未設定 XAI_API_KEY"})
            return
        system = load_base_prompt() + "\n\n" + OPS_ADDENDUM.read_text(encoding="utf-8")
        try:
            text = backend.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}])
        except Exception as e:  # 上游錯誤回給頁面顯示
            self._json(502, {"error": f"{type(e).__name__}: {e}"})
            return
        self._json(200, {"text": text})


def serve(host: str = "127.0.0.1", port: int = 8066) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"星際智囊團工作台：http://{host}:{port}/  （Ctrl+C 結束）")
    if not os.environ.get("XAI_API_KEY"):
        print("提醒：尚未設定 XAI_API_KEY，頁面只會顯示範例。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
