"""網頁工作台伺服器：python -m consultancy serve

- 提供 web/index.html，並把頁面的 AI 呼叫轉給 Grok（需 XAI_API_KEY）
- 提案紀錄與公司金流事件存到 Supabase（有設定 SUPABASE_URL／SUPABASE_SECRET_KEY 時），否則存在記憶體
- 設定 APP_PASSWORD 後全站需要帳密（HTTP Basic）；綁定非本機位址時強制要求

同一份頁面發布成 claude.ai Artifact 時，改用 viewer 的 Claude 帳號，不經過這裡。
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .council import OPS_ADDENDUM, load_base_prompt
from .firm import PolicyViolation
from .llm import LLMBackend, XAIChatBackend
from .service import CommandError, FirmService
from .storage import EventConflict, MemoryStore, StorageError, Store, clean_proposal, store_from_env

INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"
MAX_BODY_BYTES = 1024 * 1024
MAX_PROMPT_BYTES = 256 * 1024
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SKELETON_HEAD = (
    '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    "<style>[hidden]{display:none!important}body{margin:0}img{max-width:100%}</style></head><body>"
)


def default_backend_factory() -> LLMBackend | None:
    return XAIChatBackend() if os.environ.get("XAI_API_KEY") else None


class Handler(BaseHTTPRequestHandler):
    backend_factory = staticmethod(default_backend_factory)
    store: Store = MemoryStore()
    service: FirmService | None = None
    auth: tuple[str, str] | None = None  # (帳號, 密碼)

    def log_message(self, fmt: str, *args) -> None:
        pass

    # ------------------------------------------------------------ 回應
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("內容過大")
        return json.loads(self.rfile.read(length) or b"{}")

    # ------------------------------------------------------------ 驗證
    def _user(self) -> str | None:
        """回傳登入的帳號；未設定密碼時回傳 'local'；驗證失敗回傳 None。"""
        if self.auth is None:
            return "local"
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
            except (ValueError, UnicodeDecodeError):
                return None
            ok_user = hmac.compare_digest(user.encode(), self.auth[0].encode())
            ok_pw = hmac.compare_digest(pw.encode(), self.auth[1].encode())
            if ok_user and ok_pw:
                return user
        return None

    def _guard(self) -> str | None:
        user = self._user()
        if user is None:
            self._send(401, "需要登入".encode(), "text/plain; charset=utf-8",
                       {"WWW-Authenticate": 'Basic realm="star-council", charset="UTF-8"'})
        return user

    # ------------------------------------------------------------ 路由
    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        if path == "/healthz":  # 給 Docker healthcheck，不需登入、不洩漏設定
            self._json(200, {"status": "ok"})
            return
        if not self._guard():
            return
        if path in ("/", "/index.html"):
            page = SKELETON_HEAD + INDEX.read_text(encoding="utf-8") + "</body></html>"
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif path == "/api/health":
            backend = self.backend_factory()
            self._json(200, {"ok": backend is not None, "model": getattr(backend, "model", None),
                             "storage": self.store.kind})
        elif path == "/api/proposals":
            self._guarded(lambda: self.store.list_proposals(20))
        elif path.startswith("/api/proposals/"):
            pid = unquote(path.rsplit("/", 1)[1])
            row = self._guarded(lambda: self.store.get_proposal(pid), send=False)
            if row is not ...:
                self._json(200, row) if row else self._json(404, {"error": "找不到提案"})
        elif path == "/api/firm":
            q = parse_qs(url.query)
            try:
                on = date.fromisoformat(q["on"][0]) if q.get("on") else None
            except ValueError:
                self._json(400, {"error": "on 需為 YYYY-MM-DD"})
                return
            self._guarded(lambda: self._service().snapshot(on))
        else:
            self._json(404, {"error": "not found"})

    def do_PUT(self) -> None:
        path = urlsplit(self.path).path
        user = self._guard()
        if not user:
            return
        if not path.startswith("/api/proposals/"):
            self._json(404, {"error": "not found"})
            return
        try:
            proposal = clean_proposal(self._body(), unquote(path.rsplit("/", 1)[1]))
        except ValueError as e:
            self._json(400, {"error": str(e)})
            return
        proposal["created_by"] = user
        self._guarded(lambda: self.store.save_proposal(proposal))

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        user = self._guard()
        if not user:
            return
        if path == "/api/sample":
            self._sample()
        elif path == "/api/firm/commands":
            try:
                body = self._body()
                action, args = body.get("action"), body.get("args")
            except (ValueError, AttributeError):
                self._json(400, {"error": "invalid json"})
                return
            try:
                result = self._service().execute(str(action), args, actor=user)
            except (PolicyViolation, CommandError) as e:
                self._json(422, {"error": str(e)})
            except EventConflict:
                self._json(409, {"error": "帳本已被其他程序更新，已重新載入，請再送一次"})
            except StorageError as e:
                self._json(503, {"error": str(e)})
            except (KeyError, ValueError, TypeError, LookupError) as e:
                self._json(422, {"error": f"{type(e).__name__}: {e}"})
            else:
                self._json(200, {"result": result, "seq": self._service().seq})
        else:
            self._json(404, {"error": "not found"})

    # ------------------------------------------------------------ 細節
    def _service(self) -> FirmService:
        if self.service is None:
            raise StorageError("公司帳本尚未初始化")
        return self.service

    def _guarded(self, fn, send: bool = True):
        try:
            data = fn()
        except StorageError as e:
            self._json(503, {"error": str(e)})
            return ...
        if send:
            self._json(200, data)
        return data

    def _sample(self) -> None:
        try:
            prompt = str(self._body().get("prompt", ""))
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


def make_server(host: str, port: int, store: Store | None = None) -> ThreadingHTTPServer:
    password = os.environ.get("APP_PASSWORD", "")
    if host not in LOOPBACK and not password:
        raise SystemExit("對外開放（非 127.0.0.1）時必須設定 APP_PASSWORD，避免 API 額度與帳本被他人使用。")
    store = store or store_from_env()
    service = FirmService(store, os.environ.get("FIRM_ID", "default"), os.environ.get("FIRM_NAME", "宇宙行星顧問"))
    handler = type("ConfiguredHandler", (Handler,), {
        "store": store, "service": service,
        "auth": (os.environ.get("APP_USER", "owner"), password) if password else None,
    })
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = port or int(os.environ.get("PORT", "8066"))
    server = make_server(host, port)
    h = server.RequestHandlerClass
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"星際智囊團工作台：http://{shown}:{port}/  （Ctrl+C 結束）", flush=True)
    print(f"資料保存：{h.store.kind}；公司帳本已載入 {h.service.seq} 筆事件", flush=True)
    if not os.environ.get("XAI_API_KEY"):
        print("提醒：尚未設定 XAI_API_KEY，頁面只會顯示範例。", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
