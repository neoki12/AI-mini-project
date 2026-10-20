"""Judge Agent — 조건부 조항(②)과 공정 간 영향 규칙이 이번 변경 요청에 해당하는지 판정한다.

표준서 조항은 "외판 패널이면", "안전 체결부면"처럼 조건이 붙어 있어 규칙표로는 고를 수
없다. 이 판단이 LLM이 필요한 지점이다.

- 후보: 조사한 문서의 조항에 적힌 EXT-* 항목(현장 데이터 항목 제외) + 출발 공장·변경 유형이
        맞는 공정 흐름 규칙
- judge_conditions=False (Baseline): 판정 없이 문서에 적힌 항목 ID를 전부 나열한다
- LLM 실패 시: 후보를 전부 포함한다 — 품질 검토에서는 놓치는 쪽보다 더 확인하는 쪽이 안전하다
- 안전망: 요청에 안전 체결부 계통(QS-AS-001 조항 2)이 나오면 안전 항목은 LLM 판정과 무관하게
  포함한다. 실측에서 소형 모델이 '브레이크' 요청의 안전 항목을 놓쳐 등급이 A→B로 낮아졌다 —
  등급이 낮아지면 승인 절차를 건너뛰므로 이 판단만큼은 모델에 맡기지 않는다.
"""
import re

from ..domain_4m import (FIELD_ITEMS, ITEM_ID_PATTERN, SAFETY_ITEMS, SAFETY_SYSTEMS,
                         flow_candidates)
from ..llm.handle import LLMHandle, StructuredOutputError
from ..prompts_4m import JUDGE_SYSTEM, classification_section, request_section
from ..schemas import ConditionDecision


def document_candidates(documents: list[dict], *, all_ids: bool = False) -> list[dict]:
    """문서 조항에서 항목 ID 후보를 뽑는다. all_ids=True면 COM·현장 항목까지 전부."""
    candidates, seen = [], set()
    for d in documents:
        for c in d.get("clauses", []):
            for item_id in re.findall(rf"\(({ITEM_ID_PATTERN})\)", c["text"]):
                if item_id in seen:
                    continue
                if not all_ids and (not item_id.startswith("EXT-") or item_id in FIELD_ITEMS):
                    continue
                seen.add(item_id)
                candidates.append({"id": item_id, "doc_id": d["doc_id"], "rev": d["rev"],
                                   "clause": c["no"], "clause_title": c["title"],
                                   "text": c["text"]})
    return candidates


async def judge(llm: LLMHandle, query: str, classification: dict, documents: list[dict],
                *, enabled: bool, flow_enabled: bool) -> dict:
    """{"items": [후보 dict], "flows": [규칙 dict], "usage", "fallback", "candidates"}."""
    flows = (flow_candidates(classification.get("shop"), classification["change_types"])
             if flow_enabled else [])
    if not enabled:
        items = document_candidates(documents, all_ids=True)
        return {"items": items, "flows": flows, "usage": None, "fallback": None,
                "candidate_count": len(items) + len(flows)}

    items = document_candidates(documents)
    if not items and not flows:
        return {"items": [], "flows": [], "usage": None, "fallback": None,
                "candidate_count": 0}
    user = (request_section(query) + "\n" + classification_section(classification)
            + "\n## 조건부 항목 후보\n"
            + "\n".join(f"- {c['id']} | {c['doc_id']} Rev.{c['rev']} 조항 {c['clause']} "
                        f"{c['clause_title']} | {c['text']}" for c in items)
            + "\n\n## 공정 간 영향 후보\n"
            + "\n".join(f"- {r['id']} | {r['from_shop']} {r['change_type']} | {r['subject']}"
                        for r in flows))
    try:
        decision, usage = await llm.structured(JUDGE_SYSTEM, user, ConditionDecision)
        chosen_items = set(decision.applicable_items)
        chosen_flows = set(decision.applicable_flows)
        candidate_ids = {c["id"] for c in items}
        forced = [i for i in SAFETY_ITEMS if i in candidate_ids and i not in chosen_items] \
            if any(w in query for w in SAFETY_SYSTEMS) else []
        chosen_items.update(forced)
        return {"items": [c for c in items if c["id"] in chosen_items],
                "flows": [r for r in flows if r["id"] in chosen_flows],
                "usage": usage, "fallback": None, "safety_forced": forced,
                "candidate_count": len(items) + len(flows)}
    except StructuredOutputError as exc:
        return {"items": items, "flows": flows, "usage": None, "fallback": str(exc)[:200],
                "candidate_count": len(items) + len(flows)}
