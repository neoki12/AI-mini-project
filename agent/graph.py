"""v2 Supervisor — LangGraph StateGraph로 전문 Agent들을 조율하는 멀티 Agent 그래프 (4M 도메인).

route ─┬─ chat_answer                                       (잡담 직행, Wave 5)
       └─ classify → plan → gate ─┬─ standards ─┐            (병렬 조사, Wave 10b)
                                  └─ field ─────┴─ replan_check ─┬─ standards_gap (Wave 7)
                                                                 └─ judge → assess → write
                                                                    → validate ─┬─ write (Wave 8)
                                                                                └─ finalize

- 각 노드는 agent/agents/의 전문 Agent 하나를 호출하고 상태와 이벤트만 다룬다.
- 기능 스위치(deps.features)로 Baseline(전부 off)과 Improved(전부 on)를 같은 코드에서 전환한다.
- 이벤트는 reducer(operator.add)로 누적한다 — 병렬 노드가 동시에 이벤트를 남겨도 충돌하지 않는다.
- 모든 노드는 SupervisorDeps를 functools.partial로 주입받는 순수 함수다(Wave 13).
- LangSmith: LangGraph가 노드를, LangChain이 모델 호출을, MCP 클라이언트가 Tool·Resource
  호출을 자동으로 계층 기록한다. 루트 실행 ID는 app/runtime.py가 정한다 — 노드에 @traceable을
  또 붙이면 같은 단계가 두 겹(classify → classify_node)으로 기록되므로 붙이지 않는다.
"""
import operator
from functools import partial
from typing import Annotated, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph

from .agents import assessor, chat, classifier, judge, planner, research, router, validator
from .agents import writer as writer_agent
from .deps import SupervisorDeps
from .domain_4m import COMMON, EQUIPMENT, LINES, detect_injection, domain_evidence

RESOURCE_KINDS = ("standard", "inspection")
TOOL_KINDS = ("equipment", "production")


class AgentState(TypedDict, total=False):
    query: str
    thread_id: str
    history: list[dict]
    forced_route: str      # API가 경로를 지정한 경우 (POST /api/v1/reviews → "review")
    route: str
    classification: dict
    injection: list[str]     # 요청에서 찾은 지시 의심 문구 (프롬프트 인젝션)
    proposed_tasks: list
    tasks: list[dict]
    documents: list[dict]
    rag_covered: list[str]   # RAG 검색으로 대신한 문서 task id
    findings: list[dict]
    field_warnings: list[str]
    search_warnings: list[str]
    retry_count: int
    replan_rounds: int
    replan_needed: bool
    warnings: list[str]
    judged: dict
    checklist: list[dict]
    grading: dict
    draft: str
    validation_attempts: int
    validation_feedback: str | None
    missing_items: list[str]
    review_status: str
    final: str
    last_prompt: str
    cost_usd: float
    tokens: int
    events: Annotated[list[dict], operator.add]


def _spend(state: AgentState, usage: dict | None) -> dict:
    """LLM 호출 비용·토큰을 누적한다 (순차 노드에서만 호출)."""
    if not usage:
        return {}
    return {"cost_usd": round(state.get("cost_usd", 0.0) + usage["usd"], 6),
            "tokens": state.get("tokens", 0) + usage["tokens"]}


def _fallback_event(agent: str, reason: str | None) -> list[dict]:
    return [{"type": "FallbackUsed", "agent": agent, "reason": reason}] if reason else []


async def route_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Router Agent (Wave 5).

    검토 전용 엔드포인트(forced_route='review')는 잡담 분기로 보내지 않는다 — 진짜 검토 요청이
    잡담으로 오분류돼 검토 없이 끝나는 일을 막기 위함. 대신 범위 확인(scope check)을 한다:
      1) 원문에 4M 근거(공장명·설비·라인 ID·도메인 단어)가 있으면 LLM 없이 검토 진행
      2) 근거가 없으면 라우터 LLM에 묻고, LLM도 검토 요청이 아니라고 하면 out_of_scope로 끝낸다
    관련 없는 입력("오늘 점심 뭐 먹지?")에 그럴듯한 검토 보고서를 만들어 저장하지 않기 위함."""
    if state.get("forced_route") == "chat":
        return {"route": "chat",
                "events": [{"type": "RouteDecided", "route": "chat", "forced": True}]}
    if state.get("forced_route") == "review":
        evidence = domain_evidence(state["query"])
        if evidence:
            return {"route": "review",
                    "events": [{"type": "RouteDecided", "route": "review", "forced": True,
                                "evidence": evidence[:5]}]}
        route, usage, fallback = await router.decide_route(deps.fast_llm, state["query"])
        decided = "review" if route == "review" else "out_of_scope"
        return {"route": decided, **_spend(state, usage),
                "events": [{"type": "RouteDecided", "route": decided, "forced": True,
                            "evidence": []}] + _fallback_event("router", fallback)}
    route, usage, fallback = await router.decide_route(deps.fast_llm, state["query"])
    return {"route": route, **_spend(state, usage),
            "events": [{"type": "RouteDecided", "route": route}]
            + _fallback_event("router", fallback)}


async def chat_answer_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Chat Agent — 히스토리 기반 응답 (Wave 12 세션 증명 지점).

    get_stream_writer()는 /chat/stream처럼 custom 모드로 소비될 때만 실제로 전송되고,
    /chat(ainvoke)에서는 자동으로 no-op이 된다."""
    writer = get_stream_writer()
    reply, usage = await chat.answer(
        deps.fast_llm, state["query"], state.get("history", []),
        on_token=lambda piece: writer({"type": "AnswerToken", "delta": piece}))
    return {"final": reply, "last_prompt": usage.get("prompt"), **_spend(state, usage),
            "events": [{"type": "Finalize", "pipeline": "chat-direct"}]}


async def classify_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Classifier Agent — 공장, 변경 유형, 설비·라인 식별."""
    result, usage, fallback = await classifier.classify(deps.fast_llm, state["query"])
    injection = detect_injection(state["query"])
    events = [{"type": "Classified", **result}] + _fallback_event("classifier", fallback)
    if injection:
        events.append({"type": "InjectionSuspected", "phrases": injection})
    return {"classification": result, "injection": injection, **_spend(state, usage),
            "events": events}


async def plan_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Planner Agent (Wave 4). Wave 2의 MCP Prompt(4m_review)가 표준 절차를 깔아준다.
    prompt도 어느 서버가 들고 있는지 가정하지 않고 find_prompt()로 먼저 찾는다."""
    c = state["classification"]
    prompt_server = await deps.mcp.find_prompt("4m_review")
    procedure = await deps.mcp.get_prompt(
        "4m_review", {"shop": c.get("shop") or COMMON, "request": state["query"]},
        server=prompt_server)
    proposed, usage, fallback = await planner.plan(deps.fast_llm, state["query"], c, procedure)
    return {"proposed_tasks": proposed, **_spend(state, usage),
            "events": [{"type": "PlanCreated", "task_count": len(proposed),
                        "shop": c.get("shop"), "change_types": c["change_types"],
                        "targets": [f"{k}:{t}" for k, t in proposed]}]
            + _fallback_event("planner", fallback)}


async def gate_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """권위 게이트 (Wave 6) — LLM 계획에서 빠진 필수 조사를 코드가 채우고 잘못된 task를 버린다."""
    tasks, added, removed = planner.enforce(state["proposed_tasks"], state["classification"],
                                            deps.features.gate_4m)
    return {"tasks": tasks,
            "events": [{"type": "GateApplied", "added": added, "removed": removed}]}


async def standards_node(state: AgentState, deps: SupervisorDeps,
                         allow_rag: bool = True) -> dict:
    """Standards Agent — 아직 읽지 않은 문서 task를 처리한다.

    - 키워드 방식: 공통 규정·공장 표준·검사 기준을 MCP Resource로 통째로 읽는다
    - RAG 방식(features.rag): 공통 규정만 통째로 읽고(등급·현장 데이터 규칙의 근거), 공장 문서는
      search_standards로 요청과 가까운 조항만 가져온다
    - 재조사(standards_gap)는 allow_rag=False — 검색으로 부족했던 공정 표준은 원문 전체를 읽는다"""
    done = {d["task_id"] for d in state.get("documents", [])} | set(state.get("rag_covered", []))
    pending = [t for t in state["tasks"] if t["kind"] in RESOURCE_KINDS and t["id"] not in done]
    if not pending:
        return {"events": [{"type": "ResearchSkipped", "agent": "standards"}]}
    use_rag = allow_rag and deps.features.rag
    to_read = [t for t in pending if not use_rag or t["target"] == COMMON]
    to_search = [t for t in pending if use_rag and t["target"] != COMMON]
    documents, events = (await research.fetch_documents(deps.mcp, to_read)) if to_read else ([], [])
    update: dict = {}
    if to_search:
        found, search_events, warning = await research.search_documents(
            deps.mcp, state["query"], state["classification"])
        documents += found
        events += search_events
        update["rag_covered"] = state.get("rag_covered", []) + [t["id"] for t in to_search]
        if warning:   # field 노드와 병렬 실행되므로 field_warnings와 다른 키에 쓴다
            update["search_warnings"] = [warning]
    return {**update, "documents": state.get("documents", []) + documents, "events": events}


async def field_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Field Data Agent — 설비·라인 상태를 MCP Tool로 조회한다 (Wave 9 재시도 포함)."""
    pending = [t for t in state["tasks"] if t["kind"] in TOOL_KINDS]
    if not pending:
        return {"findings": [], "events": [{"type": "ResearchSkipped", "agent": "field"}]}
    findings, retries, events, warnings = await research.fetch_field_data(deps.mcp, pending)
    return {"findings": findings, "field_warnings": warnings,
            "retry_count": state.get("retry_count", 0) + retries, "events": events}


def _infer_shop(state: AgentState) -> str | None:
    """분류에서 공장을 못 정했으면 조회한 설비·라인 데이터의 공장으로 추정한다."""
    shop = state["classification"].get("shop")
    if shop:
        return shop
    for f in state.get("findings", []):
        source = EQUIPMENT.get(f["target"]) or LINES.get(f["target"]) or {}
        if source.get("shop"):
            return source["shop"]
    return None


async def replan_check_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 7 — 1차 조사 결과 평가. 해당 공장의 공정 표준이 없으면 gap task를 추가해 재조사.
    재조사 후에도 없으면 Partial Result로 경고를 남긴다(최종 상태 "추가 확인 필요")."""
    shop = _infer_shop(state)
    rounds = state.get("replan_rounds", 0)
    has_standard = any(d["found"] and d["doc_type"] == "standard" and d["target"] == shop
                       for d in state.get("documents", []))
    if shop and not has_standard and rounds < 1:
        gap = {"id": f"task-gap-{rounds}", "kind": "standard", "target": shop}
        return {"tasks": state["tasks"] + [gap], "replan_rounds": rounds + 1,
                "replan_needed": True,
                "events": [{"type": "ReplanCheck", "round": rounds, "is_sufficient": False,
                            "gap_task": gap["id"], "target": shop}]}
    warnings = list(state.get("search_warnings", [])) + list(state.get("field_warnings", []))
    documents = state.get("documents", [])
    read_ok = {(d["doc_type"], d["target"]) for d in documents if d["found"]}
    warnings += [f"{d['target']} {'공정 표준' if d['doc_type'] == 'standard' else '검사 기준'} "
                 f"문서를 조회하지 못했습니다." for d in documents
                 if d.get("error") and (d["doc_type"], d["target"]) not in read_ok]
    if not shop:
        warnings.append("요청에 공장·설비·라인이 없어 변경이 일어나는 공장을 특정하지 못했습니다. "
                        "공장(프레스·차체·도장·의장)이나 설비를 적어 다시 요청해 주세요.")
    elif not has_standard:
        warnings.append(f"{shop} 공장의 공정 표준을 찾지 못했습니다.")
    if state.get("injection"):
        warnings.append("요청에 Agent에게 판단을 지시하는 듯한 문구가 있어 조건 판정을 규칙으로 대체했습니다"
                        f" ({', '.join(state['injection'])}). 결과를 직접 확인하세요.")
    if state["classification"].get("change_types_source") == "기본값":
        warnings.append("변경 유형(작업자·설비·재료·공법)을 특정하지 못했습니다.")
    classification = {**state["classification"], "shop": shop}
    return {"replan_needed": False, "warnings": list(dict.fromkeys(warnings)),
            "classification": classification,
            "events": [{"type": "ReplanCheck", "round": rounds, "is_sufficient": True}]}


async def judge_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Judge Agent — 조건부 조항과 공정 간 영향 규칙의 해당 여부 판정."""
    documents = [d for d in state.get("documents", []) if d["found"]]
    result = await judge.judge(deps.fast_llm, state["query"], state["classification"],
                               documents, enabled=deps.features.judge_conditions,
                               flow_enabled=deps.features.flow_impact,
                               distrust_llm=bool(state.get("injection")))
    event = {"type": "ConditionsJudged", "candidates": result["candidate_count"],
             "applicable_items": [c["id"] for c in result["items"]],
             "applicable_flows": [r["id"] for r in result["flows"]],
             "safety_forced": result.get("safety_forced", []),
             "reasons": {i: r for i, r in result.get("reasons", {}).items()
                         if i in {c["id"] for c in result["items"]}
                         | {f["id"] for f in result["flows"]}},
             "unanswered": result.get("unanswered", [])}
    return {"judged": result, **_spend(state, result["usage"]),
            "events": [event] + _fallback_event("judge", result["fallback"])}


async def assess_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Assessor — 체크리스트(①②③+영향), 변경 등급, 초기유동관리."""
    c = state["classification"]
    documents = [d for d in state.get("documents", []) if d["found"]]
    field = (research.field_items(state.get("findings", []), c, documents)
             if deps.features.judge_conditions else [])
    checklist = assessor.build_checklist(c, state["judged"], field,
                                         gate_4m=deps.features.gate_4m)
    grading = assessor.grade(c, checklist)
    layers = {}
    for item in checklist:
        layers[item["layer"]] = layers.get(item["layer"], 0) + 1
    return {"checklist": checklist, "grading": grading,
            "events": [{"type": "ImpactAssessed", "grade": grading["grade"],
                        "item_count": len(checklist), "layers": layers}]}


async def write_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Writer Agent (Wave 8/10a) — 고품질 모델로 보고 작성, 토큰 스트리밍.

    토큰마다 attempt 번호를 실어 보낸다 — validate가 반려해 재작성될 때 프론트가 새
    말풍선으로 끊어서 보여줄 수 있게 하기 위함."""
    attempt = state.get("validation_attempts", 0) + 1
    writer = get_stream_writer()
    user = writer_agent.build_user_message(
        state["query"], state["classification"], state["grading"], state["checklist"],
        [d for d in state.get("documents", []) if d["found"]], state.get("findings", []),
        state.get("validation_feedback"))
    draft, usage = await writer_agent.write(
        deps.quality_llm, user,
        on_token=lambda piece: writer({"type": "AnswerToken", "attempt": attempt,
                                       "delta": piece}))
    return {"draft": draft, "last_prompt": usage.get("prompt"), **_spend(state, usage),
            "events": [{"type": "DraftWritten", "attempt": attempt, "length": len(draft)}]}


async def validate_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Validator — 항목 누락 탐지 (Wave 8). 반려 시 피드백과 함께 재작성."""
    attempts = state.get("validation_attempts", 0) + 1
    result = validator.validate(state["draft"], state["checklist"], state.get("warnings", []),
                                attempts, validator_4m=deps.features.validator_4m)
    return {"validation_attempts": attempts, "validation_feedback": result["feedback"],
            "missing_items": result["missing"], "review_status": result["review_status"],
            "events": [{"type": "Validation", "attempt": attempts, "verdict": result["verdict"],
                        "missing": result["missing"]}]}


async def finalize_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """추가 확인이 필요하면 보고서 맨 위에 경고를 붙인다 (Partial Result는 숨기지 않는다)."""
    final = state["draft"]
    if state.get("review_status") == validator.NEEDS_CHECK:
        reasons = list(state.get("warnings", []))
        if state.get("missing_items"):
            reasons.append(f"보고서에 빠진 검증 항목: {', '.join(state['missing_items'])}")
        final = f"⚠️ 추가 확인 필요 — {' / '.join(reasons)}\n\n{final}"
    return {"final": final,
            "events": [{"type": "Finalize", "pipeline": "4m-review-v2",
                        "review_status": state.get("review_status")}]}


OUT_OF_SCOPE_MESSAGE = (
    "4M 변경 요청이 아닌 것 같아 검토를 시작하지 않았어요. 어떤 공장에서 무엇(작업자·설비·재료·공법)을 "
    "어떻게 바꾸는지 적어 주세요. 예: '차체 대시 패널 라인 용접 로봇의 용접 전류 조건을 변경합니다.'")


async def out_of_scope_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """검토 범위 밖 요청 — 보고서를 만들지 않고 안내만 남긴다."""
    return {"final": OUT_OF_SCOPE_MESSAGE,
            "events": [{"type": "Finalize", "pipeline": "out-of-scope"}]}


def _after_route(state: AgentState) -> str:
    return {"chat": "chat_answer", "out_of_scope": "out_of_scope"}.get(state["route"], "classify")


def _after_replan_check(state: AgentState) -> str:
    return "standards_gap" if state.get("replan_needed") else "judge"


def _after_validate(state: AgentState) -> str:
    return "finalize" if state.get("validation_feedback") is None else "write"


def build_graph(deps: SupervisorDeps):
    g = StateGraph(AgentState)
    node = lambda fn: partial(fn, deps=deps)   # Wave 13 — 명시적 의존성 주입
    for name, fn in [("route", route_node), ("chat_answer", chat_answer_node),
                     ("out_of_scope", out_of_scope_node),
                     ("classify", classify_node), ("plan", plan_node), ("gate", gate_node),
                     ("standards", standards_node), ("field", field_node),
                     ("standards_gap", partial(standards_node, allow_rag=False)),
                     ("replan_check", replan_check_node), ("judge", judge_node),
                     ("assess", assess_node), ("write", write_node),
                     ("validate", validate_node), ("finalize", finalize_node)]:
        g.add_node(name, node(fn))

    g.set_entry_point("route")
    g.add_conditional_edges("route", _after_route,
                            {"chat_answer": "chat_answer", "classify": "classify",
                             "out_of_scope": "out_of_scope"})
    g.add_edge("chat_answer", END)
    g.add_edge("out_of_scope", END)
    g.add_edge("classify", "plan")
    g.add_edge("plan", "gate")
    g.add_edge("gate", "standards")      # 두 조사 Agent를 같은 단계에서 병렬 실행
    g.add_edge("gate", "field")
    g.add_edge(["standards", "field"], "replan_check")   # 둘 다 끝나야 진행
    # 재조사는 별도 노드로 — 합류 간선은 field까지 기다리므로 standards로 되돌리면 멈춘다
    g.add_conditional_edges("replan_check", _after_replan_check,
                            {"standards_gap": "standards_gap", "judge": "judge"})
    g.add_edge("standards_gap", "replan_check")
    g.add_edge("judge", "assess")
    g.add_edge("assess", "write")
    g.add_edge("write", "validate")
    g.add_conditional_edges("validate", _after_validate,
                            {"finalize": "finalize", "write": "write"})
    g.add_edge("finalize", END)
    return g.compile()
