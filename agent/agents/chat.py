"""Chat Agent — 잡담 응답. 대화 이력을 넣어 세션 기억을 보여 준다 (Wave 5·12)."""
from ..llm.handle import LLMHandle
from ..prompts_4m import CHAT_SYSTEM


async def answer(llm: LLMHandle, query: str, history: list[dict],
                 on_token=None) -> tuple[str, dict]:
    rendered = "\n".join(f"{m['role']}: {m['content']}" for m in history[-10:])
    user = (f"## 지금까지의 대화\n{rendered or '(없음)'}\n\n"
            f"## 사용자의 새 메시지\n{query}")
    return await llm.text(CHAT_SYSTEM, user, on_token=on_token)
