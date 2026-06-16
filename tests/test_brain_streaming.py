import pytest

from app.config import Settings
from app.services.brain_client import BrainClient


@pytest.mark.asyncio
async def test_mock_stream_tokens():
    client = BrainClient(Settings(mock_mode=True))
    tokens = []
    async for token in client.stream_complete("hello"):
        tokens.append(token)
    assert "".join(tokens) == "Mock voice response to: hello"
    assert len(tokens) > 1


def test_parse_openai_stream_delta():
    from app.services.brain_client import token_from_openai_sse_line

    line = 'data: {"choices":[{"delta":{"content":"hello"}}]}'
    assert token_from_openai_sse_line(line) == "hello"
    assert token_from_openai_sse_line("data: [DONE]") is None
    assert token_from_openai_sse_line("") is None
