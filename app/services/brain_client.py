from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import Settings


def token_from_openai_sse_line(line: str) -> Optional[str]:
    if not line.startswith("data: "):
        return None
    data = line[6:].strip()
    if not data or data == "[DONE]":
        return None
    payload = json.loads(data)
    return payload.get("choices", [{}])[0].get("delta", {}).get("content")


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

    async def stream_complete(self, transcript: str, prompt_preamble: Optional[str] = None) -> AsyncIterator[str]:
        if self.settings.mock_mode:
            parts = f"Mock voice response to: {transcript}".split(" ")
            for index, part in enumerate(parts):
                yield part if index == len(parts) - 1 else part + " "
            return
        messages = []
        if prompt_preamble:
            messages.append({"role": "system", "content": prompt_preamble})
        messages.append({"role": "user", "content": transcript})
        payload = {"model": self.settings.brain_served_model, "messages": messages, "stream": True}
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            async with client.stream("POST", f"{self.settings.brain_url}/v1/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    token = token_from_openai_sse_line(line)
                    if token:
                        yield token
