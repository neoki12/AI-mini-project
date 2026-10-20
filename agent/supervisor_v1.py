"""Wave 14 — v1 (legacy) supervisor.

라우팅도, 게이트도, 재계획도, 검증도 없는 초기 선형 버전. SUPERVISOR_VERSION=v1로
기동하면 이 구현이 실행된다 — 문제가 생기면 환경변수 하나로 v2에서 즉시 롤백해
돌아오는 지점이다.
"""
from langsmith import traceable

from .agents.chat import answer
from .deps import SupervisorDeps
from .retry import with_retry


@traceable(name="supervisor_v1_legacy")
async def run_v1(deps: SupervisorDeps, query: str, thread_id: str,
                 history: list[dict]) -> dict:
    events = [{"type": "Legacy", "note": "v1: 라우팅/게이트/재계획/검증 없음"}]
    # 이름 기억 같은 단순 대화도, 장애 진단도 전부 같은 선형 경로를 탄다.
    reply, usage = await answer(deps.fast_llm, query, history)
    if "도와드릴까요" in reply and ("4M" in query or "변경" in query):
        data, retries = await with_retry(
            deps.mcp.call_tool, "get_equipment_status", {"target": "AS-1"})
        states = ", ".join(f"{e['id']} {e['status']}" for e in data["equipment"])
        reply = (f"{data['target']} 설비 상태: {states}. "
                 f"자세한 검증 항목은 품질 담당자에게 문의하세요.")
        events.append({"type": "TaskCompleted", "source": "monitoring",
                       "retries": retries})
    events.append({"type": "Finalize", "pipeline": "legacy-v1"})
    return {"final": reply, "route": "legacy", "events": events,
            "cost_usd": usage["usd"], "validation_attempts": 0,
            "replan_rounds": 0, "gate_removed": 0,
            "retry_count": next((e.get("retries", 0) for e in events
                                 if e["type"] == "TaskCompleted"), 0)}
