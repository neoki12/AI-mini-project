"""Before/After 평가 CLI — 관리자 화면의 "평가"와 같은 일을 터미널에서 한다.

평가 데이터셋(eval/4m_dataset.jsonl)을 LangSmith Dataset으로 올리고, Baseline(개선 기능 전부 끔)과
Improved(전부 켬)를 같은 입력으로 실행해 LangSmith 실험으로 남긴 뒤 비교표를 출력한다.

실행 (프로젝트 루트에서):
    set -a; source .env; set +a
    LLM_BACKEND=ollama .venv/bin/python3 eval/run_eval.py                  # 전체 10건, 두 구성
    LLM_BACKEND=fake   .venv/bin/python3 eval/run_eval.py --limit 3        # 빠른 점검
    .venv/bin/python3 eval/run_eval.py --profiles improved
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.evaluation import METRIC_KEYS, EvaluationManager  # noqa: E402
from app.langsmith_service import LangSmithService  # noqa: E402
from app.runtime import AgentRuntime  # noqa: E402


async def main(profiles: list[str], limit: int | None) -> int:
    settings = Settings.from_env()
    langsmith = LangSmithService(settings.langsmith_project)
    if not langsmith.enabled:
        print("LangSmith 추적이 꺼져 있습니다 — .env를 불러온 뒤 실행하세요 (set -a; source .env; set +a)")
        return 1
    runtime = AgentRuntime(settings)
    await runtime.start()
    try:
        manager = EvaluationManager(runtime, langsmith, runtime.reviews)
        job = manager.start(profiles, limit=limit)
        print(f"평가 {job['id']} 시작 — {job['case_count']}건 × {len(profiles)}구성, "
              f"백엔드 {settings.llm_backend} ({runtime.deps.fast_llm.name} / {runtime.deps.quality_llm.name})")
        task = manager.jobs[job["id"]]["_task"]
        while not task.done():
            await asyncio.sleep(5)
            p = manager.jobs[job["id"]]["progress"]
            print(f"  진행 {p['done']}/{p['total']}", flush=True)
        result = manager.get(job["id"])
    finally:
        await runtime.stop()

    if result["status"] != "completed":
        print(f"실패: {result['error']}")
        return 1
    experiments = result["experiments"]
    print(f"\n{'지표':24s}" + "".join(f"{e['profile']:>12s}" for e in experiments))
    for key in METRIC_KEYS + ["latency_s", "tokens"]:
        values = [e["summary"].get(key) for e in experiments]
        print(f"{key:24s}" + "".join(f"{'-' if v is None else round(v, 3):>12}" for v in values))
    for e in experiments:
        print(f"\n{e['profile']}: {e['url'] or e['experiment']}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profiles", nargs="+", default=["baseline", "improved"],
                        choices=["baseline", "improved"])
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 N건만")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.profiles, args.limit)))
