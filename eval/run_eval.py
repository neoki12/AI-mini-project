"""Before/After 평가 CLI — 관리자 화면의 "평가"와 같은 일을 터미널에서 한다.

평가 데이터셋(eval/4m_dataset.jsonl)을 LangSmith Dataset으로 올리고, Baseline(개선 기능 전부 끔)과
Improved(전부 켬)를 같은 입력으로 실행해 LangSmith 실험으로 남긴 뒤 비교표를 출력한다.

실행 (프로젝트 루트에서):
    set -a; source .env; set +a
    LLM_BACKEND=ollama .venv/bin/python3 eval/run_eval.py                  # 전체 10건, 두 구성
    LLM_BACKEND=fake   .venv/bin/python3 eval/run_eval.py --limit 3        # 빠른 점검
    .venv/bin/python3 eval/run_eval.py --profiles improved
    LLM_BACKEND=ollama .venv/bin/python3 eval/run_eval.py --runs 3         # 3회 반복 → 평균 ± 표준편차

--runs N이면 같은 평가를 N번 돌려(회차마다 LangSmith 실험) 지표별 평균과 표준편차를 내고,
eval/results/<백엔드>-<시각>.json에 회차별 결과와 함께 저장한다. LLM 출력은 매번 달라질 수
있어 1회 측정만으로는 우연히 좋거나 나쁜 결과를 구분할 수 없다.
"""
import argparse
import asyncio
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.evaluation import METRIC_KEYS, EvaluationManager  # noqa: E402
from app.langsmith_service import LangSmithService  # noqa: E402
from app.runtime import AgentRuntime  # noqa: E402


KEYS = METRIC_KEYS + ["latency_s", "tokens"]
RESULTS_DIR = Path(__file__).resolve().parent / "results"


async def run_once(manager: EvaluationManager, profiles: list[str], limit: int | None) -> dict:
    job = manager.start(profiles, limit=limit)
    task = manager.jobs[job["id"]]["_task"]
    while not task.done():
        await asyncio.sleep(5)
        p = manager.jobs[job["id"]]["progress"]
        print(f"  진행 {p['done']}/{p['total']}", flush=True)
    return manager.get(job["id"])


def print_table(experiments: list[dict]) -> None:
    print(f"\n{'지표':24s}" + "".join(f"{e['profile']:>12s}" for e in experiments))
    for key in KEYS:
        values = [e["summary"].get(key) for e in experiments]
        print(f"{key:24s}" + "".join(f"{'-' if v is None else round(v, 3):>12}" for v in values))
    for e in experiments:
        print(f"{e['profile']}: {e['url'] or e['experiment']}")


def aggregate(runs: list[dict], profiles: list[str]) -> dict:
    """구성·지표별 회차 평균과 표준편차, 회차마다 실패한 사례 수."""
    out = {}
    for profile in profiles:
        exps = [next(e for e in r["experiments"] if e["profile"] == profile) for r in runs]
        stats = {}
        for key in KEYS:
            values = [e["summary"][key] for e in exps if e["summary"].get(key) is not None]
            if values:
                stats[key] = {"mean": statistics.mean(values),
                              "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                              "runs": values}
        out[profile] = {"metrics": stats, "experiments": [e["experiment"] for e in exps]}
    return out


async def main(profiles: list[str], limit: int | None, runs: int) -> int:
    settings = Settings.from_env()
    langsmith = LangSmithService(settings.langsmith_project)
    if not langsmith.enabled:
        print("LangSmith 추적이 꺼져 있습니다 — .env를 불러온 뒤 실행하세요 (set -a; source .env; set +a)")
        return 1
    runtime = AgentRuntime(settings)
    await runtime.start()
    results = []
    try:
        manager = EvaluationManager(runtime, langsmith, runtime.reviews)
        models = f"{runtime.deps.fast_llm.name} / {runtime.deps.quality_llm.name}"
        for i in range(1, runs + 1):
            print(f"[{i}/{runs}] 평가 시작 — 백엔드 {settings.llm_backend} ({models}), "
                  f"{len(profiles)}구성", flush=True)
            result = await run_once(manager, profiles, limit)
            if result["status"] != "completed":
                print(f"실패: {result['error']}")
                return 1
            print_table(result["experiments"])
            results.append(result)
    finally:
        await runtime.stop()

    if runs > 1:
        summary = aggregate(results, profiles)
        print(f"\n=== {runs}회 평균 ± 표준편차 ===")
        print(f"{'지표':24s}" + "".join(f"{p:>20s}" for p in profiles))
        for key in KEYS:
            cells = []
            for p in profiles:
                m = summary[p]["metrics"].get(key)
                cells.append("-" if m is None else f"{m['mean']:.3f} ± {m['std']:.3f}")
            print(f"{key:24s}" + "".join(f"{c:>20s}" for c in cells))
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"{settings.llm_backend}-{datetime.now():%Y%m%d-%H%M}.json"
        path.write_text(json.dumps({
            "llm_backend": settings.llm_backend, "models": models, "runs": runs,
            "case_count": results[0]["case_count"], "summary": summary,
            "per_run": [r["experiments"] for r in results]}, ensure_ascii=False, indent=2))
        print(f"\n저장: {path.relative_to(RESULTS_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profiles", nargs="+", default=["baseline", "improved"],
                        choices=["baseline", "improved"])
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 N건만")
    parser.add_argument("--runs", type=int, default=1, help="반복 횟수 (2 이상이면 평균 ± 표준편차)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.profiles, args.limit, args.runs)))
