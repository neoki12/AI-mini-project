"""LLMHandle.structured — 공급사가 '쓸 수 없는 응답'을 예외로 올릴 때 검토 전체가 죽지 않는가.

gpt-4o가 간혹 구조화 출력의 이유 필드에 제어 문자를 끝없이 반복해 최대 길이에서 잘린다
(OpenAI SDK의 LengthFinishReasonError). 한 번 다시 요청하고, 그래도 잘리면 StructuredOutputError로
바꿔 Agent의 규칙 fallback이 받게 한다.
"""
import asyncio

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import BaseModel

from agent.llm.handle import LLMHandle, StructuredOutputError


class LengthFinishReasonError(Exception):   # openai SDK 예외와 같은 이름
    pass


class ContentFilterFinishReasonError(Exception):
    pass


class Answer(BaseModel):
    ok: bool


def handle_failing(times: int, error=LengthFinishReasonError) -> tuple[LLMHandle, dict]:
    calls = {"n": 0}
    model = FakeListChatModel(responses=['{"ok": true}'] * 3)
    llm = LLMHandle("fake:flaky", model, 0.0, False)
    original = llm._structured

    async def flaky(system, user, schema):
        calls["n"] += 1
        if calls["n"] <= times:
            raise error("length limit reached")
        return await original(system, user, schema)
    llm._structured = flaky
    return llm, calls


def test_truncated_once_is_retried():
    llm, calls = handle_failing(1)
    parsed, _ = asyncio.run(llm.structured("s", "u", Answer))
    assert parsed.ok is True and calls["n"] == 2


def test_truncated_twice_becomes_structured_output_error():
    llm, calls = handle_failing(2)
    with pytest.raises(StructuredOutputError, match="LengthFinishReasonError"):
        asyncio.run(llm.structured("s", "u", Answer))
    assert calls["n"] == 2


def test_content_filter_is_not_retried():
    llm, calls = handle_failing(1, ContentFilterFinishReasonError)
    with pytest.raises(StructuredOutputError):
        asyncio.run(llm.structured("s", "u", Answer))
    assert calls["n"] == 1


def test_other_errors_are_not_swallowed():
    llm, _ = handle_failing(1, ConnectionError)   # 인증·네트워크 오류는 숨기지 않는다
    with pytest.raises(ConnectionError):
        asyncio.run(llm.structured("s", "u", Answer))
