from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import Settings


@dataclass
class BrainResult:
    text: str
    first_token_ms: int
    total_ms: int


class BrainClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete(self, transcript: str, prompt_preamble: Optional[str] = None) -> BrainResult:
        start = time.perf_counter()
        if self.settings.mock_mode:
            text = f"Mock voice response to: {transcript}"
            return BrainResult(text=text, first_token_ms=0, total_ms=0)
        messages = []
        if prompt_preamble:
            messages.append({"role": "system", "content": prompt_preamble})
        messages.append({"role": "user", "content": transcript})
        payload = {"model": self.settings.brain_served_model, "messages": messages, "stream": False}
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            resp = await client.post(f"{self.settings.brain_url}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        elapsed = int((time.perf_counter() - start) * 1000)
        return BrainResult(text=text, first_token_ms=elapsed, total_ms=elapsed)
