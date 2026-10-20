"""Classifier Agent — 공장, 변경 유형, 설비·라인을 식별한다.

원칙: 원문에 적힌 사실을 LLM이 뒤집지 못하게 하고, 원문에 없는 사실은 LLM이 지어내지 못하게 한다.
- 설비·라인 ID: 원문에 실제로 있는 것만 인정한다
- 공장: 원문 근거(공장명, 설비·라인 ID의 소속, 공장별 단어)로만 정한다. 근거가 없으면
  추측하지 않고 None — 이후 '공장을 특정하지 못함' 경고로 '추가 확인 필요'가 된다.
  (실측: 공장 단서가 없는 요청을 소형 모델이 선택지 첫 값인 '프레스'로 분류해, 엉뚱한 공장
  기준으로 검토했다)
- 변경 유형: 원문 단어(작업자·설비 교체·재료·조건)가 있으면 그것을 따르고, 없을 때만 LLM 판단을
  쓴다. 둘 다 없으면 기본값 Method로 두고 '변경 유형 미확정'으로 표시한다.
  (실측: '신입사원' 요청을 LLM이 Method로, '너트러너 교체 + 토크 변경'을 Material+Method로 분류)
"""
from ..domain_4m import (CHANGE_TYPES, LINES, SHOPS, find_equipment_ids, guess_shop,
                         keyword_change_types)
from ..llm.handle import LLMHandle, StructuredOutputError
from ..prompts_4m import CLASSIFIER_SYSTEM, request_section
from ..schemas import ChangeClassification


def normalize(raw: dict, query: str) -> dict:
    equipment = find_equipment_ids(query)
    lines = [l for l in LINES if l in query]

    shop = guess_shop(query)   # 공장명 > 설비·라인 소속 > 공장별 단어, 근거 없으면 None
    llm_shop = raw.get("shop") if raw.get("shop") in SHOPS else None

    keyword_types = keyword_change_types(query)
    llm_types = list(dict.fromkeys(c for c in raw.get("change_types", []) if c in CHANGE_TYPES))
    if keyword_types:
        change_types, types_source = keyword_types, "원문"
    elif llm_types:
        change_types, types_source = llm_types, "LLM"
    else:
        change_types, types_source = ["Method"], "기본값"
    return {"shop": shop, "shop_source": "원문" if shop else "없음", "llm_shop": llm_shop,
            "change_types": change_types, "change_types_source": types_source,
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
