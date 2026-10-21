"""LLM-as-a-Judge 민감도 점검 — 판사가 실제로 근거 오류를 잡아내는지 확인한다.

판사 점수를 믿으려면 판사부터 검증해야 한다. --judge 평가 결과(eval/results/judge-*.json)의
Improved 보고서마다 근거 오류를 일부러 넣은 사본을 만들어 원본과 함께 다시 채점한다.

- 오류 주입: 출처에 없는 조항을 인용한 문장 하나 추가 (지어낸 근거와 수치)
- 기대: 오염본의 근거 충실도가 원본보다 낮다. 낮아진 비율 = 탐지율

    set -a; source .env; set +a
    .venv/bin/python3 eval/judge_check.py eval/results/judge-ollama-<시각>.json
"""
import asyncio
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.llm_judge import build_judge_llm, judge, to_unit  # noqa: E402

FABRICATED = ("\n\n또한 QS-CM-001 Rev.D 조항 9에 따라 변경 후 30일간 전수 검사를 실시하고, "
              "결과를 공장장에게 매일 보고해야 한다.")


async def main(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    llm = build_judge_llm()
    if llm is None:
        print("OPENAI_API_KEY가 없습니다")
        return 1
    improved = next(e for e in data["per_run"][0] if e["profile"] == "improved")
    rows = []
    for case in improved["cases"]:
        if not case.get("report"):
            continue
        original = await judge(llm, case["request"], case["report"], case["sources"])
        corrupted = await judge(llm, case["request"], case["report"] + FABRICATED, case["sources"])
        caught = corrupted.faithfulness < original.faithfulness
        flagged = any("조항 9" in u or "30일" in u for u in corrupted.unsupported)
        rows.append({"case_id": case["case_id"], "original": original.faithfulness,
                     "corrupted": corrupted.faithfulness, "caught": caught, "flagged": flagged})
        print(f"{case['case_id']}: 원본 {original.faithfulness} → 오염 {corrupted.faithfulness}"
              f" {'탐지' if caught else '놓침'}{' (문장 지목)' if flagged else ''}", flush=True)
    summary = {
        "judge": llm.name, "cases": len(rows),
        "faithfulness_original": round(statistics.mean(to_unit(r["original"]) for r in rows), 3),
        "faithfulness_corrupted": round(statistics.mean(to_unit(r["corrupted"]) for r in rows), 3),
        "detection_rate": round(sum(r["caught"] for r in rows) / len(rows), 3),
        "flag_rate": round(sum(r["flagged"] for r in rows) / len(rows), 3)}
    print(json.dumps(summary, ensure_ascii=False))
    out = path.with_name(path.stem + "-check.json")
    out.write_text(json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2))
    print(f"저장: {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]))))
