"""활동 로그 — 그래프 이벤트를 사용자가 읽을 문장으로 바꾼다.

검토에는 실모델로 30~40초가 걸린다. 그동안 "지금 어떤 Agent가 무엇을 하고 있는지"를
보여 주기 위해, 노드 시작(NodeStarted)과 각 Agent가 남긴 결과 이벤트에 message를 붙인다.
문장은 서버에서 만든다 — Vue 화면, 기존 채팅 화면, curl 어느 클라이언트든 같은 로그를 본다.
"""
from typing import Any


# 노드 → (Agent 이름, 시작할 때 보여 줄 문장)
NODES: dict[str, tuple[str, str]] = {
    "route": ("Router", "요청 유형을 판단하고 있어요"),
    "chat_answer": ("Chat", "답변을 작성하고 있어요"),
    "out_of_scope": ("Router", "검토 범위 밖 요청이에요"),
    "classify": ("Classifier", "변경 내용을 분류하고 있어요 (공장, 변경 유형, 설비·라인)"),
    "plan": ("Planner", "표준 검토 절차에 따라 조사 계획을 세우고 있어요"),
    "gate": ("권위 게이트", "필수 조사가 빠지지 않았는지 확인하고 있어요"),
    "standards": ("Standards", "공정 표준과 검사 기준을 찾고 있어요"),
    "standards_gap": ("Standards", "부족한 공정 표준을 추가로 찾고 있어요"),
    "field": ("Field Data", "설비와 라인 상태를 조회하고 있어요"),
    "replan_check": ("Supervisor", "조사 결과가 충분한지 점검하고 있어요"),
    "judge": ("Judge", "조건부 조항이 이번 변경에 해당하는지 판정하고 있어요"),
    "assess": ("Assessor", "검증 항목과 변경 등급을 정리하고 있어요"),
    "write": ("Writer", "검토 보고서를 작성하고 있어요"),
    "validate": ("Validator", "보고서에 빠진 검증 항목이 없는지 검수하고 있어요"),
    "finalize": ("Supervisor", "검토 결과를 마무리하고 있어요"),
}

CHANGE_TYPE_KO = {"Man": "작업자", "Machine": "설비", "Material": "재료", "Method": "공법"}
KIND_KO = {"standard": "공정 표준", "inspection": "검사 기준", "equipment": "설비",
           "production": "라인"}


def _task_label(spec: str) -> str:
    kind, _, target = spec.partition(":")
    return f"{target} {KIND_KO.get(kind, kind)}"


def _message(ev: dict[str, Any]) -> str | None:
    t = ev.get("type")
    if t == "RouteDecided":
        if ev.get("route") == "chat":
            return "일반 대화로 판단했어요"
        if ev.get("route") == "out_of_scope":
            return "4M 변경 요청이 아니라고 판단해 검토를 시작하지 않아요"
        if ev.get("forced") and ev.get("evidence"):
            return f"검토 요청으로 접수했어요 (근거: {', '.join(ev['evidence'])})"
        if ev.get("forced"):
            return "검토 요청으로 접수했어요 (라우터 판단)"
        return "4M 변경 검토 요청으로 판단했어요"
    if t == "Classified":
        types = ", ".join(f"{CHANGE_TYPE_KO.get(c, c)}({c})" for c in ev.get("change_types", []))
        shop = f"{ev['shop']} 공장" if ev.get("shop") else "공장 미상(요청에 공장·설비·라인 없음)"
        if str(ev.get("shop_source", "")).startswith("LLM"):
            shop += f" [{ev['shop_source']}]"
        source = {"LLM": " (LLM 판단)", "기본값": " (유형 미확정)"}.get(ev.get("change_types_source"), "")
        text = f"분류 결과: {shop} · {types}{source}"
        if ev.get("equipment_ids"):
            text += f" · 설비 {', '.join(ev['equipment_ids'])}"
        if ev.get("lines"):
            text += f" · 라인 {', '.join(ev['lines'])}"
        return text
    if t == "InjectionSuspected":
        return (f"요청에 Agent에게 지시하는 듯한 문구가 있어요 ({', '.join(ev.get('phrases', []))}) — "
                "조건 판정은 규칙으로 대체해요")
    if t == "PlanCreated":
        return f"조사 계획 {ev.get('task_count', 0)}건을 세웠어요"
    if t == "GateApplied":
        added = ev.get("added", [])
        text = (f"빠진 필수 조사 {len(added)}건을 추가했어요: "
                f"{', '.join(_task_label(a) for a in added)}" if added
                else "계획에 빠진 필수 조사가 없어요")
        if ev.get("removed"):
            text += f" · 잘못된 조사 {ev['removed']}건 제외"
        return text
    if t == "TaskCompleted":
        retry = " (일시 오류 후 재시도 성공)" if ev.get("retries") else ""
        if ev.get("source") in ("standard", "inspection"):
            if ev.get("failed"):
                return f"{ev.get('target')} {KIND_KO[ev['source']]} 문서를 조회하지 못했어요 (MCP 오류)"
            if ev.get("found") is False:
                return f"{ev.get('target')} {KIND_KO[ev['source']]} 문서를 찾지 못했어요"
            return f"읽음: {ev.get('doc_id')} Rev.{ev.get('rev')} 「{ev.get('title')}」"
        return f"{ev.get('summary') or ev.get('target')}{retry}"
    if t == "RetrievalCompleted":
        if ev.get("failed"):
            return "표준서 검색을 수행하지 못했어요 (임베딩·MCP 오류)"
        hits = ev.get("hits", [])
        return (f"표준서 검색(RAG): 조항 {ev.get('chunk_count')}개 중 관련 {len(hits)}개 — "
                f"{', '.join(hits)}" if hits else "표준서 검색(RAG): 관련 조항을 찾지 못했어요")
    if t == "ResearchSkipped":
        return "조사할 항목이 없어 건너뛰었어요"
    if t == "ReplanCheck":
        if ev.get("is_sufficient"):
            return "조사 결과가 충분해요"
        return f"{ev.get('target')} 공정 표준이 없어 추가로 찾아볼게요"
    if t == "ConditionsJudged":
        hits = ev.get("applicable_items", []) + ev.get("applicable_flows", [])
        text = (f"조건부 후보 {ev.get('candidates', 0)}건 중 {len(hits)}건이 해당돼요"
                + (f": {', '.join(hits)}" if hits else ""))
        if ev.get("reasons"):
            text += " · " + " / ".join(f"{i}: {r}" for i, r in ev["reasons"].items())
        if ev.get("safety_forced"):
            text += (f" · 안전 체결부 항목 {', '.join(ev['safety_forced'])}는 "
                     "규칙에 따라 반드시 포함했어요")
        return text
    if t == "ImpactAssessed":
        return f"검증 항목 {ev.get('item_count', 0)}건을 정리했어요 · 변경 등급 {ev.get('grade')}"
    if t == "DraftWritten":
        return f"보고서 초안을 작성했어요 (시도 {ev.get('attempt')}, {ev.get('length')}자)"
    if t == "Validation":
        missing = ev.get("missing", [])
        if ev.get("verdict") == "합격":
            return "검수 통과: 모든 검증 항목이 보고서에 들어 있어요"
        if missing and ev.get("verdict") == "불합격":
            return f"검수 반려: {len(missing)}건 누락({', '.join(missing)}) → 다시 작성할게요"
        if ev.get("verdict") == "불합격":
            return "검수 반려: 형식 기준 미달 → 다시 작성할게요"
        return f"검수 결과: {ev.get('verdict')}"
    if t == "FallbackUsed":
        return f"{ev.get('agent')} Agent 응답을 해석하지 못해 규칙 기반 판단으로 대체했어요"
    if t == "Finalize":
        status = ev.get("review_status")
        return f"검토를 마쳤어요 ({status})" if status else "답변을 마쳤어요"
    return None


def describe(event: dict[str, Any]) -> dict[str, Any]:
    """이벤트에 agent와 message를 붙여 돌려준다 (원본은 바꾸지 않는다)."""
    if event.get("type") in ("AnswerToken", "FinalAnswer"):
        return event
    node = event.get("node")
    agent = NODES.get(node, (None, None))[0] if node else None
    if event.get("type") == "NodeStarted":
        return {**event, "agent": agent, "message": NODES.get(node, (None, f"{node} 실행 중"))[1]}
    message = _message(event)
    enriched = dict(event)
    if agent:
        enriched["agent"] = agent
    if message:
        enriched["message"] = message
    return enriched
