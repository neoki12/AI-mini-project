"""Classifier Agent — 공장, 변경 유형, 설비·라인을 식별한다.

LLM 출력은 그대로 믿지 않고 요청 원문과 대조해 보정한다 — 원문에 적힌 사실을 모델이
뒤집지 못하게 한다. (실측: qwen3:0.6b가 "의장 공장 기준"이라고 적힌 요청을 프레스로 분류하고,
요청에 없는 라인 ID를 지어내 엉뚱한 검증 항목이 붙었다.)
- 설비·라인 ID는 원문에 실제로 있는 것만 인정한다 (LLM이 빠뜨린 ID는 채운다)
- 공장은 원문 근거(공장명 직접 언급, 설비·라인 ID의 소속)가 있으면 그것을 따른다.
  원문 근거가 없을 때만 LLM 판단을 쓰고, 그것도 없으면 키워드로 추정한다
"""
from ..domain_4m import (CHANGE_TYPES, EQUIPMENT, LINES, SHOPS, find_equipment_ids,
                         guess_change_types, guess_shop)
from ..llm.handle import LLMHandle, StructuredOutputError
from ..prompts_4m import CLASSIFIER_SYSTEM, request_section
from ..schemas import ChangeClassification


def _explicit_shop(query: str, equipment: list[str], lines: list[str]) -> str | None:
    """원문에서 확정되는 공장 — 공장명 직접 언급 > 설비 소속 > 라인 소속."""
    named = [(query.index(s), s) for s in SHOPS if s in query]
    if named:
        return min(named)[1]
    if equipment:
        return EQUIPMENT[equipment[0]]["shop"]
    if lines:
        return LINES[lines[0]]["shop"]
    return None


def normalize(raw: dict, query: str) -> dict:
    equipment = find_equipment_ids(query)
    lines = [l for l in LINES if l in query]

    llm_shop = raw.get("shop") if raw.get("shop") in SHOPS else None
    shop = _explicit_shop(query, equipment, lines) or llm_shop or guess_shop(query)

    change_types = [c for c in raw.get("change_types", []) if c in CHANGE_TYPES]
    change_types = list(dict.fromkeys(change_types)) or guess_change_types(query)
    return {"shop": shop, "change_types": change_types,
            "equipment_ids": equipment, "lines": lines}


async def classify(llm: LLMHandle, query: str) -> tuple[dict, dict, str | None]:
    """(classification, usage, fallback 사유)를 돌려준다."""
    try:
        result, usage = await llm.structured(CLASSIFIER_SYSTEM, request_section(query),
                                             ChangeClassification)
        return normalize(result.model_dump(), query), usage, None
    except StructuredOutputError as exc:
        return (normalize({}, query), {"model": llm.name, "tokens": 0, "usd": 0.0},
                str(exc)[:200])
