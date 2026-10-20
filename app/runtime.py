"""Agent 런타임 — 프로세스당 정확히 1회 생성되는 Agent 번들 (Wave 1·2·12·14).

lifespan에서 start()로 MCP 연결·LLM·그래프·저장소를 한 번만 만들고 모든 요청이 공유한다.
라우터는 이 객체에만 의존하므로(app/dependencies.py) HTTP 계층과 Agent 실행이 분리된다.

- run()    : 그래프를 끝까지 실행하고 최종 상태를 돌려준다 (POST /chat, /reviews)
- stream() : 그래프 실행 과정을 이벤트 dict로 흘려보낸다 (GET /chat/stream, Wave 3)
"""
import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict

from langsmith import utils as langsmith_utils

from agent.deps import SupervisorDeps
from agent.graph import build_graph
from agent.llm import factory as llm_factory
from agent.mcp_client import MCPClient
from agent.session_store import SqliteSessionStore
from agent.supervisor_v1 import run_v1

from .config import Settings
from .review_store import SqliteReviewStore

CREATION_COUNT = 0   # Wave 1 — 프로세스 내 Agent 번들 생성 횟수 (항상 1이어야 정상)


def build_llms(settings: Settings):
    """LLM_BACKEND=fake(기본, 결정론) | ollama(로컬 실모델) | openai(실제 OpenAI API)."""
    if settings.llm_backend == "ollama":
        return llm_factory.build_llms("ollama", settings.ollama_fast_model,
                                      settings.ollama_quality_model)
    if settings.llm_backend == "openai":
        return llm_factory.build_llms("openai", settings.openai_fast_model,
                                      settings.openai_quality_model)
    return llm_factory.build_llms("fake", "", "")


class AgentRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.deps: SupervisorDeps | None = None
        self.graph = None
        self.reviews: SqliteReviewStore | None = None
        self.instance_id: int | None = None
        self._slots = asyncio.Semaphore(settings.max_concurrent_reviews)
        self._waiting = 0

    async def start(self) -> None:
        global CREATION_COUNT
        CREATION_COUNT += 1
        mcp = MCPClient(flaky_first_tool_call=self.settings.mcp_flaky_first_call)
        await mcp.start()   # Wave 2 — MCP subprocess는 서버 수명 동안 딱 1개
        fast_llm, quality_llm = build_llms(self.settings)
        self.deps = SupervisorDeps(
            fast_llm=fast_llm,
            quality_llm=quality_llm,
            mcp=mcp,
            session_store=SqliteSessionStore(self.settings.db_path),
            version=self.settings.supervisor_version,
            features=self.settings.features,
            judge_llm=quality_llm if self.settings.judge_model == "quality" else fast_llm,
        )
        self.graph = build_graph(self.deps) if self.deps.version == "v2" else None
        self.reviews = SqliteReviewStore(self.settings.db_path)
        self.instance_id = id(self.deps)

    async def stop(self) -> None:
        if self.deps is not None:
            await self.deps.mcp.stop()
            self.deps.session_store.close()
        if self.reviews is not None:
            self.reviews.close()
        try:   # 종료 전 LangSmith 배치 전송 플러시 — kill 시 run이 pending으로 남는 것 방지
            from langchain_core.tracers.langchain import wait_for_all_tracers
            wait_for_all_tracers()
        except Exception:
            pass

    @property
    def creation_count(self) -> int:
        return CREATION_COUNT

    def _initial_state(self, message: str, thread_id: str, history: list[dict],
                       forced_route: str | None) -> dict:
        state = {"query": message, "thread_id": thread_id, "history": history,
                 "events": [], "cost_usd": 0.0, "tokens": 0}
        if forced_route:
            state["forced_route"] = forced_route
        return state

    @property
    def profile(self) -> str:
        values = set(asdict(self.settings.features).values())
        return "improved" if values == {True} else "baseline" if values == {False} else "custom"

    def _trace_config(self, thread_id: str, forced_route: str | None) -> tuple[dict, str | None]:
        """LangSmith 루트 실행의 ID·이름·태그·메타데이터를 정한다.

        실행 ID를 우리가 정해 그래프에 넘기므로 일반 검토와 스트리밍 검토 모두 검토 이력과
        LangSmith 실행이 1:1로 연결된다 — 피드백을 이 ID로 남긴다. 추적이 꺼져 있으면 None."""
        run_id = uuid.uuid4()
        config = {
            "run_id": run_id,
            "run_name": "4m_review" if forced_route == "review" else "agent_request",
            "tags": ["4m-agent", f"backend:{self.settings.llm_backend}",
                     f"profile:{self.profile}"],
            "metadata": {"thread_id": thread_id, "llm_backend": self.settings.llm_backend,
                         "supervisor_version": self.deps.version,
                         "features": asdict(self.settings.features)},
        }
        return config, (str(run_id) if langsmith_utils.tracing_is_enabled() else None)

    @property
    def slots(self) -> asyncio.Semaphore:
        """동시 실행 슬롯 — 검토·대화·평가가 함께 쓴다 (LLM 서버에 요청이 몰리지 않게)."""
        return self._slots

    async def run(self, message: str, thread_id: str,
                  forced_route: str | None = None) -> tuple[dict, str | None]:
        """그래프를 끝까지 실행한다. forced_route='review'면 라우팅 LLM을 건너뛴다.
        (최종 상태, LangSmith 실행 ID)를 돌려준다. 동시 실행 슬롯이 빌 때까지 기다린다."""
        async with self._slots:
            return await self._run(message, thread_id, forced_route)

    async def _run(self, message: str, thread_id: str,
                   forced_route: str | None) -> tuple[dict, str | None]:
        deps = self.deps
        history = await asyncio.to_thread(deps.session_store.load, thread_id)   # Wave 12
        config, run_id = self._trace_config(thread_id, forced_route)
        if deps.version == "v2":
            result = await self.graph.ainvoke(
                self._initial_state(message, thread_id, history, forced_route), config=config)
        else:
            result, run_id = await run_v1(deps, message, thread_id, history), None   # Wave 14
        await self._remember(thread_id, message, result["final"])
        return result, run_id

    async def stream(self, message: str, thread_id: str,
                     forced_route: str | None = None) -> AsyncIterator[dict]:
        """동시 실행 슬롯을 얻은 뒤 그래프 실행 과정을 내보낸다. 슬롯이 없으면 먼저 Queued
        (대기 순번)를 보낸다 — 사용자가 '멈춘 것'이 아니라 '기다리는 중'임을 알 수 있게."""
        queued = self._slots.locked()
        if queued:
            self._waiting += 1
            yield {"type": "Queued", "position": self._waiting,
                   "max_concurrent": self.settings.max_concurrent_reviews}
        try:
            await self._slots.acquire()   # 대기 중 연결이 끊기면 여기서 취소된다
        finally:
            if queued:
                self._waiting -= 1
        try:
            async for event in self._stream_graph(message, thread_id, forced_route):
                yield event
        finally:
            self._slots.release()

    async def _stream_graph(self, message: str, thread_id: str,
                            forced_route: str | None) -> AsyncIterator[dict]:
        """그래프 실행 과정을 이벤트로 내보낸다 (Wave 3).

        - NodeStarted / NodeFinished : 노드(Agent)가 시작·종료된 시점 (LangGraph "tasks" 모드)
        - 각 Agent가 남긴 결과 이벤트 (Classified, TaskCompleted, ...)  ("updates" 모드)
        - AnswerToken : Writer·Chat Agent의 토큰 ("custom" 모드)
        - FinalAnswer, 마지막으로 RunCompleted(최종 상태 — 라우터 내부용, 클라이언트로 보내지 않음)
        """
        deps = self.deps
        history = await asyncio.to_thread(deps.session_store.load, thread_id)
        config, run_id = self._trace_config(thread_id, forced_route)
        if deps.version != "v2":
            result = await run_v1(deps, message, thread_id, history)
            for ev in result["events"]:
                yield ev
            final, last_prompt, state, run_id = result["final"], None, result, None
        else:
            final, last_prompt, state = "", None, {}
            started: dict[str, float] = {}
            async for mode, payload in self.graph.astream(
                    self._initial_state(message, thread_id, history, forced_route),
                    config=config, stream_mode=["tasks", "updates", "custom", "values"]):
                if mode == "tasks":
                    if "input" in payload:          # 노드 시작
                        started[payload["id"]] = time.perf_counter()
                        yield {"type": "NodeStarted", "node": payload["name"]}
                    else:                           # 노드 종료
                        begun = started.pop(payload["id"], time.perf_counter())
                        yield {"type": "NodeFinished", "node": payload["name"],
                               "elapsed_ms": round((time.perf_counter() - begun) * 1000),
                               "error": bool(payload.get("error"))}
                elif mode == "custom":
                    yield payload
                elif mode == "values":
                    state = payload
                else:
                    for node_name, delta in payload.items():
                        delta = delta or {}
                        # events는 reducer(operator.add) 필드라 델타에는 새 이벤트만 들어 있다
                        for ev in delta.get("events") or []:
                            yield {**ev, "node": node_name}
                        if delta.get("final"):
                            final = delta["final"]
                        if delta.get("last_prompt"):
                            last_prompt = delta["last_prompt"]
        await self._remember(thread_id, message, final)
        yield {"type": "FinalAnswer", "reply": final, "prompt": last_prompt}
        yield {"type": "RunCompleted", "state": state, "run_id": run_id}

    async def _remember(self, thread_id: str, message: str, reply: str) -> None:
        """대화 이력 저장 (SQLite — 이벤트 루프를 막지 않게 작업 스레드에서)."""
        def write():
            self.deps.session_store.append(thread_id, "user", message)
            self.deps.session_store.append(thread_id, "assistant", reply)
        await asyncio.to_thread(write)

    def metadata(self, result: dict, run_id: str | None) -> dict:
        gate = next((e for e in result.get("events", []) if e["type"] == "GateApplied"), {})
        return {
            "route": result.get("route"),
            "task_count": len(result.get("tasks", [])),
            "gate_added": len(gate.get("added", [])),
            "gate_removed": gate.get("removed", 0),
            "replan_rounds": result.get("replan_rounds", 0),
            "retry_count": result.get("retry_count", 0),
            "validation_attempts": result.get("validation_attempts", 0),
            "cost_usd": result.get("cost_usd", 0.0),
            "tokens": result.get("tokens", 0),
            "features": asdict(self.settings.features),
            "llm_backend": self.settings.llm_backend,
            "supervisor_version": self.deps.version,
            "instance_id": self.instance_id,
            "langsmith_run_id": run_id,
        }
