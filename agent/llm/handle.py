"""LLMHandle — LangChain BaseChatModel 하나를 감싸 Agent들이 공통으로 쓰는 호출 방식을 제공한다.

- structured(): Pydantic 스키마로 구조화 출력을 받는다. 모델이 네이티브 구조화 출력을
  지원하면(ChatOllama, ChatOpenAI) with_structured_output을 쓰고, 아니면(fake) 응답에서
  JSON을 뽑아 스키마로 검증한다. 실패하면 StructuredOutputError — 각 Agent가 코드 레벨
  fallback으로 받는다(W6 정신: 모델 출력을 그대로 믿지 않는다).
- text(): 자유 텍스트. on_token이 있으면 astream으로 토큰을 즉시 흘려보낸다(Wave 3).
- 모든 호출에 시간 제한(timeout)을 건다. 구조화 출력이 시간을 넘기면 StructuredOutputError —
  Agent가 규칙으로 fallback해 검토는 계속된다. 텍스트(보고서)가 넘기면 asyncio.TimeoutError —
  API가 502(agent_failed)로 알린다.
- 구조화 출력이 최대 길이에서 잘리면(OpenAI LengthFinishReasonError — gpt-4o가 간혹 이유 필드에
  제어 문자를 끝없이 반복한다) 한 번 다시 요청하고, 그래도 잘리면 StructuredOutputError.
  내용 필터로 막힌 응답도 StructuredOutputError — 둘 다 검토 전체를 실패시키지 않는다.
- 모든 호출은 usage(model, tokens, usd)를 돌려준다. 토큰은 응답의 usage_metadata(실측)를
  쓰고, 없으면 글자 수로 추정한다. usd는 '가상 단가 × 토큰'이다(Wave 10a 비교용).
"""
import asyncio
import json
import re
from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """모델 응답을 스키마로 해석하지 못했을 때."""


# 공급사 SDK가 '응답은 왔지만 쓸 수 없다'로 올리는 예외 (openai를 직접 import하지 않고 이름으로 구분)
TRUNCATED_ERRORS = {"LengthFinishReasonError"}
UNUSABLE_ERRORS = TRUNCATED_ERRORS | {"ContentFilterFinishReasonError"}
MAX_STRUCTURED_ATTEMPTS = 2


def _extract_json(text: str) -> str:
    """```json 펜스나 앞뒤 설명이 붙은 응답에서 첫 JSON 객체를 꺼낸다."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)   # 추론 모델의 사고 과정 제거
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise StructuredOutputError(f"JSON 객체가 없음: {text[:120]!r}")
    return text[start:end + 1]


class LLMHandle:
    def __init__(self, name: str, model: BaseChatModel, usd_per_1k_tokens: float,
                 native_structured: bool, timeout: float = 120.0):
        self.name = name
        self.model = model
        self.usd_per_1k = usd_per_1k_tokens
        self.native_structured = native_structured
        self.timeout = timeout

    def _usage(self, message: AIMessage | None, prompt: str, completion: str) -> dict:
        meta = getattr(message, "usage_metadata", None) or {}
        tokens = meta.get("total_tokens") or (len(prompt) + len(completion)) // 4 + 1
        return {"model": self.name, "tokens": tokens,
                "usd": round(tokens / 1000 * self.usd_per_1k, 6)}

    async def structured(self, system: str, user: str, schema: type[T]) -> tuple[T, dict]:
        for attempt in range(1, MAX_STRUCTURED_ATTEMPTS + 1):
            try:
                return await asyncio.wait_for(self._structured(system, user, schema), self.timeout)
            except (asyncio.TimeoutError, TimeoutError) as exc:
                raise StructuredOutputError(f"시간 초과 ({self.timeout:.0f}초)") from exc
            except Exception as exc:
                name = type(exc).__name__
                if name not in UNUSABLE_ERRORS:
                    raise
                if name in TRUNCATED_ERRORS and attempt < MAX_STRUCTURED_ATTEMPTS:
                    continue   # 반복 출력은 우연이라 다시 요청하면 대개 정상
                raise StructuredOutputError(f"{name} ({attempt}회 시도)") from exc

    async def _structured(self, system: str, user: str, schema: type[T]) -> tuple[T, dict]:
        messages = [SystemMessage(system), HumanMessage(user)]
        if self.native_structured:
            runnable = self.model.with_structured_output(schema, include_raw=True)
            out = await runnable.ainvoke(messages)
            raw, parsed = out.get("raw"), out.get("parsed")
            if parsed is None:
                raise StructuredOutputError(str(out.get("parsing_error")))
            return parsed, self._usage(raw, system + user, str(getattr(raw, "content", "")))
        hint = ("\n\n반드시 다음 JSON 스키마를 따르는 JSON 객체 하나로만 답하라:\n"
                + json.dumps(schema.model_json_schema(), ensure_ascii=False))
        raw = await self.model.ainvoke([SystemMessage(system + hint), HumanMessage(user)])
        try:
            parsed = schema.model_validate_json(_extract_json(str(raw.content)))
        except ValidationError as exc:
            raise StructuredOutputError(str(exc)) from exc
        return parsed, self._usage(raw, system + user, str(raw.content))

    async def text(self, system: str, user: str, on_token=None) -> tuple[str, dict]:
        return await asyncio.wait_for(self._text(system, user, on_token), self.timeout)

    async def _text(self, system: str, user: str, on_token=None) -> tuple[str, dict]:
        messages = [SystemMessage(system), HumanMessage(user)]
        if on_token is None:
            raw = await self.model.ainvoke(messages)
            content = re.sub(r"<think>.*?</think>\s*", "", str(raw.content), flags=re.S)
            usage = self._usage(raw, system + user, content)
        else:
            chunks, last = [], None
            async for chunk in self.model.astream(messages):
                piece = str(chunk.content)
                if piece:
                    chunks.append(piece)
                    on_token(piece)
                last = chunk if getattr(chunk, "usage_metadata", None) else last
            content = "".join(chunks)
            usage = self._usage(last, system + user, content)
        usage["prompt"] = f"[SYSTEM]\n{system}\n\n[USER]\n{user}"
        return content, usage
