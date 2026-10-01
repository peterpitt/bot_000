"""LLM 後端：預設離線草稿；設定 XAI_API_KEY 後改用 Grok（xAI，OpenAI 相容 API）。"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol

Message = dict[str, str]


class LLMBackend(Protocol):
    def chat(self, messages: list[Message]) -> str: ...


class OfflineBackend:
    """不連網：回傳召集名單與標準回答骨架，方便測試流程與檢查 prompt。"""

    def chat(self, messages: list[Message]) -> str:
        system = messages[0]["content"]
        question = messages[-1]["content"]
        roster = system.split("## 本次召集顧問", 1)[-1].split("##", 1)[0].strip()
        names = [ln.split("｜")[0].strip() for ln in roster.splitlines() if "｜" in ln and not ln.startswith(" ")]
        return (
            "# 一人公司智囊團分析（離線草稿）\n\n"
            f"問題：{question}\n\n"
            f"召集顧問：{'、'.join(names)}\n\n"
            "## 結論\n- 推薦方案：（連線 Grok 後產生）\n\n"
            "## 下一步\n- [ ] 設定 XAI_API_KEY 以取得完整分析\n"
        )


class XAIChatBackend:
    def __init__(self, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None, timeout: float = 120):
        self.api_key = api_key or os.environ["XAI_API_KEY"]
        self.model = model or os.environ.get("XAI_MODEL", "grok-4")
        self.base_url = (base_url or os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")).rstrip("/")
        self.timeout = timeout

    def chat(self, messages: list[Message]) -> str:
        body = json.dumps({"model": self.model, "messages": messages}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"]


def default_backend() -> LLMBackend:
    return XAIChatBackend() if os.environ.get("XAI_API_KEY") else OfflineBackend()
