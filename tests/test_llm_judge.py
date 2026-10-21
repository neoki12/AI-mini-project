"""LLM-as-a-Judge 평가자 — 점수 변환, 출처 구성, 판사 실패 처리."""
import asyncio

from eval.llm_judge import JudgeVerdict, make_evaluator, sources_text, to_unit


class StubJudge:
    name = "stub"

    def __init__(self, verdict=None, error=None):
        self.verdict, self.error, self.calls = verdict, error, []

    async def structured(self, system, user, schema):
        self.calls.append(user)
        if self.error:
            raise self.error
        return self.verdict, {}


def run(coro):
    return asyncio.run(coro)


def test_to_unit_maps_rubric_to_zero_one():
    assert [to_unit(s) for s in (1, 3, 5)] == [0.0, 0.5, 1.0]


def test_sources_include_clauses_field_data_and_checklist():
    text = sources_text(
        [{"found": True, "doc_id": "QS-BD-001", "rev": "C", "title": "차체 표준",
          "clauses": [{"no": "3", "title": "용접 조건", "text": "전류 변경 시 파괴 검사"}]},
         {"found": False, "doc_id": None}],
        [{"target": "BD-RB-301", "status": "tip_overdue", "note": "타점 4,800"}],
        [{"id": "EXT-BD-01", "name": "파괴 검사", "evidence": {"doc_id": "QS-BD-001"}}])
    assert "QS-BD-001 Rev.C" in text and "조항 3 용접 조건: 전류 변경 시 파괴 검사" in text
    assert "BD-RB-301: tip_overdue 타점 4,800" in text and "[EXT-BD-01]" in text


def test_evaluator_scores_report_against_sources():
    stub = StubJudge(JudgeVerdict(faithfulness=4, usefulness=5, unsupported=["조항 9"],
                                  reason="대부분 일치"))
    out = run(make_evaluator(stub)({"message": "요청"}, {"report": "보고서", "sources": "출처"}))
    scores = {r["key"]: r["score"] for r in out["results"]}
    assert scores == {"judge_faithfulness": 0.75, "judge_usefulness": 1.0}
    assert "조항 9" in out["results"][0]["comment"]
    assert "[출처]\n출처" in stub.calls[0] and "[보고서]\n보고서" in stub.calls[0]


def test_evaluator_skips_when_no_report_and_survives_judge_failure():
    assert run(make_evaluator(StubJudge())({"message": "x"}, {"report": ""})) == {"results": []}
    out = run(make_evaluator(StubJudge(error=RuntimeError("down")))(
        {"message": "x"}, {"report": "보고서"}))
    assert out["results"][0]["score"] is None and "RuntimeError" in out["results"][0]["comment"]
