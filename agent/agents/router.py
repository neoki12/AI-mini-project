"""Router Agent — 잡담(chat)과 4M 검토(review)를 가른다 (Wave 5)."""
import re

from ..llm.fake_chat import REVIEW_PATTERN
from ..llm.handle import LLMHandle, StructuredOutputError
from ..prompts_4m import ROUTER_SYSTEM, request_section
from ..schemas import RouteDecision


async def decide_route(llm: LLMHandle, query: str) -> tuple[str, dict, str | None]:
    """(route, usage, fallback 사유)를 돌려준다."""
    try:
        decision, usage = await llm.structured(ROUTER_SYSTEM, request_section(query),
                                               RouteDecision)
        return decision.route, usage, None
    except StructuredOutputError as exc:
        route = "review" if re.search(REVIEW_PATTERN, query) else "chat"
        return route, {"model": llm.name, "tokens": 0, "usd": 0.0}, str(exc)[:200]
