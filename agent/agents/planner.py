"""Planner Agent + 권위 게이트 — 조사 계획을 세우고, 빠진 필수 조사를 코드가 채운다.

- plan(): MCP Prompt(4m_review)가 깔아준 표준 절차와 분류 결과로 LLM이 조사 task를 제안 (Wave 4)
- enforce(): 권위 게이트 (Wave 6). 프롬프트로 부탁하는 대신 코드로 강제한다.
  · 항상: 존재하지 않는 대상, 중복 task 제거
  · gate_4m=True: 공통 규정, 해당 공장 표준·검사 기준, 요청에 나온 설비, 관련 라인 가동 상태를
    빠짐없이 조사하도록 추가
"""
from ..domain_4m import COMMON, RESEARCH_KINDS, lines_of, valid_target
from ..llm.handle import LLMHandle, StructuredOutputError
from ..prompts_4m import PLANNER_SYSTEM, classification_section, request_section
from ..schemas import ResearchPlan


def required_tasks(classification: dict) -> list[tuple[str, str]]:
    specs = [("standard", COMMON)]
    shop = classification.get("shop")
    if shop:
        specs += [("standard", shop), ("inspection", shop)]
    equipment = classification.get("equipment_ids", [])
    specs += [("equipment", eq) for eq in equipment]
    lines = lines_of(equipment, classification.get("lines", []))
    if not equipment:
        specs += [("equipment", line) for line in lines]
    specs += [("production", line) for line in lines]
    return specs


async def plan(llm: LLMHandle, query: str, classification: dict,
               procedure: str) -> tuple[list[tuple[str, str]], dict, str | None]:
    """(LLM이 제안한 (kind, target) 목록, usage, fallback 사유)."""
    user = (f"## 표준 절차\n{procedure}\n\n{request_section(query)}\n"
            f"{classification_section(classification)}")
    try:
        result, usage = await llm.structured(PLANNER_SYSTEM, user, ResearchPlan)
        return [(t.kind, t.target) for t in result.tasks], usage, None
    except StructuredOutputError as exc:
        return (required_tasks(classification), {"model": llm.name, "tokens": 0, "usd": 0.0},
                str(exc)[:200])


def enforce(proposed: list[tuple[str, str]], classification: dict,
            gate_4m: bool) -> tuple[list[dict], list[str], int]:
    """(task 목록, 게이트가 추가한 task, 제거한 task 수)."""
    kept: list[tuple[str, str]] = []
    for kind, target in proposed:
        if kind in RESEARCH_KINDS and valid_target(kind, target) and (kind, target) not in kept:
            kept.append((kind, target))
    removed = len(proposed) - len(kept)
    added = []
    if gate_4m or not kept:   # 게이트를 꺼도 계획이 통째로 비면 실행 불능이므로 복구
        for spec in required_tasks(classification):
            if spec not in kept:
                kept.append(spec)
                added.append(f"{spec[0]}:{spec[1]}")
    tasks = [{"id": f"task-{i}", "kind": kind, "target": target}
             for i, (kind, target) in enumerate(kept)]
    return tasks, added, removed
