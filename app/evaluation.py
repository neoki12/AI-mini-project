"""LangSmith 평가 — 평가 데이터셋으로 Baseline과 Improved를 같은 입력에 돌려 비교한다.

- 데이터셋: eval/4m_dataset.jsonl 10건 → LangSmith Dataset "4m-review-eval" (없거나 바뀌면 다시 올림)
- 실험: 구성(profile)마다 aevaluate 실험 1개. 같은 서버의 MCP 연결·LLM을 쓰고, 기능 스위치만
  바꾼 그래프를 따로 만든다 (서버 설정은 그대로 둔다)
- 평가자: eval/metrics.py의 채점 — recall, precision, f1, 층별 recall, 등급·분류 정확도
  + 선택: LLM-as-a-Judge(eval/llm_judge.py) — 보고서 근거 충실도·실무 유용성 (judge_llm을 주면)
- 실행 시간이 길어(실모델 10건 × 약 35초 × 구성 수) 백그라운드 작업으로 돌리고 진행률을 조회한다

CLI(eval/run_eval.py)와 관리자 API(/api/v1/admin/evaluations)가 같은 EvaluationManager를 쓴다.

작업 상태는 시작·진행·종료 때마다 DB에 남긴다. 서버가 평가 도중 재시작되면 그 작업은 다시
이어서 돌릴 수 없으므로, 기동 시 queued/running으로 남은 작업을 interrupted로 바꿔 둔다
(영원히 '진행 중'으로 보이거나 새 평가를 막지 않게).
"""
import asyncio
import dataclasses
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langsmith import aevaluate

from agent.deps import Features
from agent.graph import build_graph
from eval.llm_judge import make_evaluator, sources_text
from eval.metrics import mean, score

from .config import PROJECT_DIR
from .langsmith_service import LangSmithService

logger = logging.getLogger("app")

DATASET_NAME = "4m-review-eval"
DATASET_PATH = PROJECT_DIR / "eval" / "4m_dataset.jsonl"
PROFILES: dict[str, Features] = {"baseline": Features.baseline(), "improved": Features()}
INTERRUPTED_MESSAGE = "서버가 재시작되어 평가가 중단되었습니다. 다시 실행하세요."
METRIC_KEYS = ["recall", "precision", "f1", "recall_required", "recall_document",
               "recall_field", "recall_downstream", "grade_correct", "classification_correct",
               "retrieval_recall"]
JUDGE_KEYS = ["judge_faithfulness", "judge_usefulness"]


def load_cases_from(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_cases(path: Path = DATASET_PATH) -> list[dict]:
    return load_cases_from(path)


# ── 평가자 (inputs/outputs/reference_outputs 형식) ───────────────────────

def _score(outputs: dict, reference_outputs: dict) -> dict:
    return score(set(outputs.get("checklist_ids", [])), reference_outputs)


def ev_recall(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "recall", "score": _score(outputs, reference_outputs)["recall"]}


def ev_precision(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "precision", "score": _score(outputs, reference_outputs)["precision"]}


def ev_f1(outputs: dict, reference_outputs: dict) -> dict:
    s = _score(outputs, reference_outputs)
    return {"key": "f1", "score": s["f1"],
            "comment": f"missing={s['missing']} extra={s['extra']}"}


def ev_layers(outputs: dict, reference_outputs: dict) -> dict:
    """층별 recall — 정답에 그 층 항목이 있는 경우만 점수를 낸다 (여러 점수는 results로 묶는다)."""
    layers = _score(outputs, reference_outputs)["recall_by_layer"]
    return {"results": [{"key": f"recall_{name}", "score": value}
                        for name, value in layers.items() if value is not None]}


def ev_grade(outputs: dict, reference_outputs: dict) -> dict:
    ok = outputs.get("grade") == reference_outputs["change_grade"]
    return {"key": "grade_correct", "score": int(ok),
            "comment": f"{outputs.get('grade')} (정답 {reference_outputs['change_grade']})"}


def ev_classification(outputs: dict, reference_outputs: dict) -> dict:
    ok = (outputs.get("shop") == reference_outputs["shop"]
          and outputs.get("change_types") == reference_outputs["change_types"])
    return {"key": "classification_correct", "score": int(ok)}


def ev_retrieval(outputs: dict, reference_outputs: dict) -> dict:
    """관련 문서 Recall — 정답 relevant_docs(공통 규정 제외) 중 조사한 문서에 들어온 비율."""
    relevant = [d for d in reference_outputs["relevant_docs"] if not d.startswith("QS-CM")]
    got = set(outputs.get("retrieved_docs", []))
    value = sum(d in got for d in relevant) / len(relevant) if relevant else None
    return {"key": "retrieval_recall", "score": value}


EVALUATORS = [ev_recall, ev_precision, ev_f1, ev_layers, ev_grade, ev_classification,
              ev_retrieval]


# ── 실행 관리 ────────────────────────────────────────────────────────────

class EvaluationManager:
    def __init__(self, runtime, langsmith: LangSmithService, store=None, judge_llm=None):
        self.runtime = runtime
        self.judge_llm = judge_llm      # LLM-as-a-Judge 평가 모델 (None이면 규칙 채점만)
        self.langsmith = langsmith
        self.store = store              # 결과 영속화 (SqliteReviewStore.save_evaluation)
        self.jobs: dict[str, dict] = {}
        self._lock = asyncio.Lock()     # 평가는 한 번에 하나만 (LLM 자원 독점 방지)
        if store is not None:
            interrupted = store.mark_unfinished_evaluations(INTERRUPTED_MESSAGE)
            if interrupted:
                logger.warning("evaluations interrupted by restart: %s", interrupted)

    async def _persist(self, job: dict) -> None:
        if self.store is not None:
            await asyncio.to_thread(self.store.save_evaluation, self.public(job))

    # 데이터셋 ---------------------------------------------------------------
    def _sync_dataset(self, cases: list[dict]) -> str:
        """LangSmith Dataset을 eval/4m_dataset.jsonl과 맞춘다. 같으면 그대로 쓴다."""
        client = self.langsmith._require()
        if client.has_dataset(dataset_name=DATASET_NAME):
            existing = {ex.metadata.get("case_id"): ex.outputs
                        for ex in client.list_examples(dataset_name=DATASET_NAME)}
            if existing == {c["id"]: c["expected"] for c in cases}:
                return "unchanged"
            client.delete_dataset(dataset_name=DATASET_NAME)
        client.create_dataset(DATASET_NAME,
                              description="완성차 공장 4M 변경 검토 평가 10건 (교육용 가상 데이터)")
        client.create_examples(dataset_name=DATASET_NAME, examples=[
            {"inputs": {"message": c["input"]}, "outputs": c["expected"],
             "metadata": {"case_id": c["id"], "trap": c.get("trap")}} for c in cases])
        return "uploaded"

    # 대상 함수 -------------------------------------------------------------
    def _target(self, profile: str):
        deps = dataclasses.replace(self.runtime.deps, features=PROFILES[profile])
        graph = build_graph(deps)

        async def target(inputs: dict) -> dict:
            async with self.runtime.slots:   # 사용자 검토와 같은 동시 실행 슬롯을 쓴다
                return await run_case(inputs)

        async def run_case(inputs: dict) -> dict:
            started = time.perf_counter()
            state = await graph.ainvoke(
                {"query": inputs["message"], "thread_id": f"eval-{uuid.uuid4().hex[:8]}",
                 "history": [], "events": [], "cost_usd": 0.0, "tokens": 0,
                 "forced_route": "review"},
                config={"tags": ["4m-eval", f"profile:{profile}"]})
            c = state.get("classification", {})
            return {"checklist_ids": [i["id"] for i in state.get("checklist", [])],
                    "grade": (state.get("grading") or {}).get("grade"),
                    "shop": c.get("shop"), "change_types": c.get("change_types", []),
                    "review_status": state.get("review_status"),
                    "retrieved_docs": sorted({d["doc_id"] for d in state.get("documents", [])
                                              if d.get("found")}),
                    "clauses_read": sum(len(d.get("clauses", []))
                                        for d in state.get("documents", []) if d.get("found")),
                    "latency_s": round(time.perf_counter() - started, 2),
                    "tokens": state.get("tokens", 0),
                    # LLM-as-a-Judge 입력 — 최종 보고서와 시스템이 실제로 본 출처
                    "report": state.get("final", ""),
                    "sources": sources_text(state.get("documents", []),
                                            state.get("findings", []),
                                            state.get("checklist", []))}
        return target

    # 작업 ------------------------------------------------------------------
    def start(self, profiles: list[str], limit: int | None = None) -> dict:
        unknown = [p for p in profiles if p not in PROFILES]
        if unknown:
            raise ValueError(f"알 수 없는 구성: {unknown} (가능: {list(PROFILES)})")
        if any(j["status"] in ("queued", "running") for j in self.jobs.values()):
            raise RuntimeError("이미 실행 중인 평가가 있습니다")
        cases = load_cases()[:limit] if limit else load_cases()
        job = {"id": f"ev-{uuid.uuid4().hex[:10]}", "status": "queued",
               "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "profiles": profiles, "case_count": len(cases),
               "llm_backend": self.runtime.settings.llm_backend,
               "progress": {"done": 0, "total": len(cases) * len(profiles)},
               "dataset": DATASET_NAME, "experiments": [], "error": None}
        self.jobs[job["id"]] = job
        job["_task"] = asyncio.create_task(self._run(job, cases))
        return self.public(job)

    async def _run(self, job: dict, cases: list[dict]) -> None:
        await self._persist(job)   # queued
        async with self._lock:
            job["status"] = "running"
            try:
                await self._persist(job)
                job["dataset_sync"] = await asyncio.to_thread(self._sync_dataset, cases)
                for profile in job["profiles"]:
                    job["experiments"].append(await self._experiment(job, profile, cases))
                    await self._persist(job)   # 구성 하나가 끝날 때마다
                job["status"] = "completed"
            except asyncio.CancelledError:   # 서버 종료
                job["status"], job["error"] = "interrupted", INTERRUPTED_MESSAGE
                raise
            except Exception as exc:
                logger.exception("evaluation failed job=%s", job["id"])
                job["status"], job["error"] = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
            finally:
                job["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if self.store is not None:   # 취소 중에도 남도록 동기로 저장
                    self.store.save_evaluation(self.public(job))

    async def _experiment(self, job: dict, profile: str, cases: list[dict]) -> dict:
        case_ids = {c["id"] for c in cases}
        examples = [ex for ex in await asyncio.to_thread(
            lambda: list(self.langsmith.client.list_examples(dataset_name=DATASET_NAME)))
            if ex.metadata.get("case_id") in case_ids]
        evaluators = EVALUATORS + ([make_evaluator(self.judge_llm)] if self.judge_llm else [])
        results = await aevaluate(
            self._target(profile), data=examples, evaluators=evaluators,
            experiment_prefix=f"4m-{profile}", max_concurrency=1,
            blocking=False,   # 끝날 때까지 기다리지 않고 1건씩 받아 진행률을 올린다
            metadata={"profile": profile, "features": dataclasses.asdict(PROFILES[profile]),
                      "llm_backend": self.runtime.settings.llm_backend,
                      "fast_llm": self.runtime.deps.fast_llm.name,
                      "quality_llm": self.runtime.deps.quality_llm.name,
                      "judge_llm": self.judge_llm.name if self.judge_llm else None},
            description=f"4M 검토 {profile} 구성 — 기능 스위치 {dataclasses.asdict(PROFILES[profile])}")
        rows = []
        async for row in results:
            scores = {r.key: r.score for r in row["evaluation_results"]["results"]}
            outputs = row["run"].outputs or {}
            case = {"case_id": row["example"].metadata.get("case_id"), **scores,
                    "latency_s": outputs.get("latency_s"), "tokens": outputs.get("tokens")}
            if self.judge_llm:   # 판사 근거와 채점 대상을 남겨 사람이 다시 확인할 수 있게
                case["judge_comment"] = next((r.comment for r in row["evaluation_results"]["results"]
                                              if r.key == "judge_faithfulness"), None)
                case["request"] = row["example"].inputs.get("message")
                case["report"], case["sources"] = outputs.get("report"), outputs.get("sources")
            rows.append(case)
            job["progress"]["done"] += 1
            await self._persist(job)
        experiment_name = results.experiment_name
        url = await asyncio.to_thread(self._experiment_url, experiment_name)
        keys = METRIC_KEYS + (JUDGE_KEYS if self.judge_llm else [])
        summary = {k: mean([r.get(k) for r in rows]) for k in keys}
        summary["latency_s"] = mean([r["latency_s"] for r in rows])
        summary["tokens"] = mean([r["tokens"] for r in rows])
        return {"profile": profile, "experiment": experiment_name, "url": url,
                "summary": summary, "cases": sorted(rows, key=lambda r: r["case_id"] or "")}

    def _experiment_url(self, name: str) -> str | None:
        try:
            return self.langsmith.client.read_project(project_name=name).url
        except Exception:
            return None

    def public(self, job: dict) -> dict:
        return {k: v for k, v in job.items() if not k.startswith("_")}

    def list(self) -> list[dict]:
        jobs = {j["id"]: self.public(j) for j in self.jobs.values()}
        if self.store is not None:
            for saved in self.store.list_evaluations():
                jobs.setdefault(saved["id"], saved)
        return sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)

    def get(self, job_id: str) -> dict | None:
        if job_id in self.jobs:
            return self.public(self.jobs[job_id])
        return self.store.get_evaluation(job_id) if self.store is not None else None

    async def shutdown(self) -> None:
        for job in self.jobs.values():
            task = job.get("_task")
            if task and not task.done():
                task.cancel()
