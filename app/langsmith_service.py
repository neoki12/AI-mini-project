"""LangSmith 연동 — 관리자 기능(실행 기록 조회, 피드백)의 백엔드.

langsmith Client는 동기 HTTP 클라이언트라 asyncio.to_thread로 호출한다 — 관리자 화면 조회가
검토 스트리밍 같은 다른 요청의 이벤트 루프를 막지 않게 하기 위함이다.

추적이 꺼져 있거나(키 없음) LangSmith에 닿지 않으면 예외 대신 enabled/reachable=False와
원인을 돌려준다. Agent 서비스 자체는 LangSmith 없이도 동작해야 하기 때문이다.
"""
import asyncio
import logging
from datetime import timezone
from functools import cached_property
from typing import Any

from langsmith import Client
from langsmith import utils as langsmith_utils
from langsmith.utils import LangSmithNotFoundError

logger = logging.getLogger("app")


class LangSmithUnavailable(Exception):
    """추적이 꺼져 있거나 LangSmith에 연결할 수 없을 때."""


def _seconds(run) -> float | None:
    if run.start_time and run.end_time:
        return round((run.end_time - run.start_time).total_seconds(), 2)
    return None


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")


class LangSmithService:
    def __init__(self, project: str):
        self.project = project
        self._project_url: str | None = None

    @property
    def enabled(self) -> bool:
        return langsmith_utils.tracing_is_enabled()

    @cached_property
    def client(self) -> Client:
        return Client()

    def _require(self) -> Client:
        if not self.enabled:
            raise LangSmithUnavailable("LangSmith 추적이 꺼져 있습니다 (.env의 API 키·추적 설정 확인)")
        return self.client

    def _project_base_url(self) -> str | None:
        if self._project_url is None:
            try:
                self._project_url = self._require().read_project(project_name=self.project).url
            except Exception as exc:   # 프로젝트가 아직 없거나 연결 실패
                logger.info("langsmith project url unavailable: %s", exc)
                return None
        return self._project_url

    def run_url(self, run_id: str) -> str | None:
        base = self._project_base_url()
        return f"{base}/r/{run_id}" if base else None

    # ── 상태 ────────────────────────────────────────────────────────────

    def _status(self) -> dict[str, Any]:
        body = {"enabled": self.enabled, "project": self.project, "reachable": False,
                "project_url": None, "error": None}
        if not self.enabled:
            body["error"] = "추적이 꺼져 있습니다 (.env 확인)"
            return body
        try:
            body["project_url"] = self._project_base_url()
            list(self.client.list_projects(limit=1))
            body["reachable"] = True
        except Exception as exc:
            body["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return body

    async def status(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._status)

    # ── 실행 기록 ────────────────────────────────────────────────────────

    def _summary(self, run) -> dict[str, Any]:
        stats = run.feedback_stats or {}
        return {
            "id": str(run.id), "name": run.name, "status": run.status,
            "start_time": _iso(run.start_time), "latency_s": _seconds(run),
            "total_tokens": run.total_tokens or 0, "error": (run.error or "")[:300] or None,
            "tags": run.tags or [],
            "thread_id": (run.extra or {}).get("metadata", {}).get("thread_id"),
            "feedback": {k: {"n": v.get("n"), "avg": v.get("avg")} for k, v in stats.items()},
            "url": self.run_url(str(run.id)),
        }

    def _list_runs(self, limit: int, error_only: bool) -> list[dict]:
        client = self._require()
        kwargs: dict[str, Any] = {"project_name": self.project, "is_root": True, "limit": limit}
        if error_only:
            kwargs["error"] = True
        try:
            return [self._summary(r) for r in client.list_runs(**kwargs)]
        except LangSmithNotFoundError:
            return []   # 첫 실행이 기록되기 전에는 프로젝트가 아직 없다 — 오류가 아니라 빈 목록

    async def list_runs(self, limit: int = 20, error_only: bool = False) -> list[dict]:
        return await asyncio.to_thread(self._list_runs, limit, error_only)

    def _run_detail(self, run_id: str) -> dict:
        """루트 실행 + Agent(노드)별 소요 시간·토큰. LLM·MCP 호출 수도 함께 센다."""
        client = self._require()
        root = client.read_run(run_id)
        runs = list(client.list_runs(project_name=self.project, trace_id=run_id))
        by_parent: dict[str, list] = {}
        for r in runs:
            by_parent.setdefault(str(r.parent_run_id), []).append(r)
        # 루트 바로 아래 = LangGraph 노드들
        nodes = sorted(by_parent.get(str(root.id), []), key=lambda r: r.start_time)

        def descendants(run) -> list:
            out = []
            for child in by_parent.get(str(run.id), []):
                out.append(child)
                out.extend(descendants(child))
            return out

        steps = []
        for node in nodes:
            if node.name.startswith("_after_"):   # 조건부 간선 함수는 단계가 아니다
                continue
            inner = descendants(node)
            steps.append({
                "name": node.name, "status": node.status, "latency_s": _seconds(node),
                "tokens": sum((r.total_tokens or 0) for r in inner if r.run_type == "llm"),
                "llm_calls": sum(1 for r in inner if r.run_type == "llm"),
                "tool_calls": sum(1 for r in inner if r.run_type == "tool"),
                "error": (node.error or "")[:200] or None,
            })
        return {**self._summary(root), "steps": steps,
                "inputs_preview": str((root.inputs or {}).get("query", ""))[:300]}

    async def run_detail(self, run_id: str) -> dict:
        return await asyncio.to_thread(self._run_detail, run_id)

    # ── 피드백 ───────────────────────────────────────────────────────────

    def _create_feedback(self, run_id: str, score: int, comment: str | None) -> str:
        fb = self._require().create_feedback(
            run_id=run_id, key="user_rating", score=score, comment=comment,
            source_info={"source": "4m-review-ui"})
        return str(fb.id)

    async def create_feedback(self, run_id: str, score: int, comment: str | None) -> str | None:
        """LangSmith에 사용자 평가를 남긴다. 실패해도 예외를 올리지 않고 None — 로컬 저장은 유지."""
        try:
            return await asyncio.to_thread(self._create_feedback, run_id, score, comment)
        except Exception as exc:
            logger.warning("langsmith feedback failed run_id=%s: %s", run_id, exc)
            return None
