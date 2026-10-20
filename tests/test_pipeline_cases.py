"""멀티 Agent 파이프라인 회귀 테스트 — 평가 데이터셋 10건을 fake 백엔드로 끝까지 실행한다.

fake 백엔드의 판단은 키워드 규칙(agent/llm/fake_chat.py)이라 이 테스트의 통과가 실모델
성능을 뜻하지는 않는다. 확인하는 것은 파이프라인 배선이다 — 분류 → 계획 → 게이트 →
병렬 조사 → 조건 판정 → 체크리스트·등급 → 작성 → 검증이 정답 구조대로 이어지는지,
그리고 기능 스위치를 끄면(Baseline) 실제로 점수가 떨어지는지.
"""
import json
from pathlib import Path

import pytest

from agent.deps import Features
from app.config import Settings
from app.runtime import AgentRuntime
from eval.metrics import mean, score

DATASET = [json.loads(line) for line in
           (Path(__file__).resolve().parent.parent / "eval" / "4m_dataset.jsonl")
           .read_text(encoding="utf-8").splitlines() if line]


async def _run_all(tmp_path, features: Features) -> list[tuple[dict, dict]]:
    runtime = AgentRuntime(Settings(llm_backend="fake", mcp_flaky_first_call=False,
                                    features=features, db_path=tmp_path / "p.db"))
    await runtime.start()
    try:
        results = []
        for case in DATASET:
            result, _ = await runtime.run(case["input"], case["id"], forced_route="review")
            results.append((case, result))
        return results
    finally:
        await runtime.stop()


@pytest.fixture(scope="module")
def improved(tmp_path_factory):
    import asyncio
    return asyncio.run(_run_all(tmp_path_factory.mktemp("improved"), Features()))


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    import asyncio
    return asyncio.run(_run_all(tmp_path_factory.mktemp("baseline"), Features.baseline()))


@pytest.mark.parametrize("idx", range(len(DATASET)), ids=[c["id"] for c in DATASET])
def test_improved_matches_expected(improved, idx):
    case, result = improved[idx]
    exp = case["expected"]
    assert result["classification"]["shop"] == exp["shop"]
    assert result["classification"]["change_types"] == exp["change_types"]
    assert result["grading"]["grade"] == exp["change_grade"]
    predicted = {i["id"] for i in result["checklist"]}
    s = score(predicted, exp)
    assert s["missing"] == [] and s["extra"] == [], s
    assert result["review_status"] == "검토 완료"
    assert result["missing_items"] == []


def test_improved_every_item_has_evidence(improved):
    for case, result in improved:
        for item in result["checklist"]:
            assert item["evidence"], (case["id"], item["id"])
            if item["layer"] in ("document", "field"):
                assert item["evidence"]["doc_id"] and item["evidence"]["rev"]


def test_gate_fills_planner_gaps(improved):
    """fake planner는 검사 기준을 일부러 빠뜨린다 — 게이트가 채워야 한다."""
    for case, result in improved:
        gate = next(e for e in result["events"] if e["type"] == "GateApplied")
        assert any(a.startswith("inspection:") for a in gate["added"]), case["id"]


def test_writer_rewrites_after_validator_rejects(improved):
    """Wave 8 — fake writer의 1차 초안은 항목을 빠뜨리고, Validator가 반려해 재작성한다."""
    for case, result in improved:
        verdicts = [e["verdict"] for e in result["events"] if e["type"] == "Validation"]
        assert verdicts == ["불합격", "합격"], case["id"]


def test_research_agents_run_in_parallel_step(improved):
    """standards와 field 노드가 같은 단계에서 실행돼 replan_check 전에 둘 다 끝난다."""
    _, result = improved[7]   # case-08: 문서 + 설비 + 라인
    sources = {e["source"] for e in result["events"] if e["type"] == "TaskCompleted"}
    assert sources == {"standard", "inspection", "equipment", "production"}


def test_baseline_scores_lower_than_improved(improved, baseline):
    imp = [score({i["id"] for i in r["checklist"]}, c["expected"]) for c, r in improved]
    base = [score({i["id"] for i in r["checklist"]}, c["expected"]) for c, r in baseline]
    assert mean([s["f1"] for s in imp]) == 1.0
    assert mean([s["f1"] for s in base]) < mean([s["f1"] for s in imp])
    # 게이트가 없으면 규칙표 항목은 문서 본문에 적힌 것(QS-CM-001의 COM-05)만 우연히 잡힌다
    assert mean([s["recall_by_layer"]["required"] for s in base]) < 0.5
    assert mean([s["precision"] for s in base]) < 1.0                      # 조건 판정 없음


def test_safety_items_forced_even_if_judge_misses(tmp_path):
    """judge LLM이 안전 항목을 놓쳐도 안전망이 채운다 (실측: qwen2.5:7b가 브레이크 건을 놓침)."""
    import asyncio

    from agent.agents import judge as judge_agent
    from agent.llm.handle import LLMHandle
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    lazy = LLMHandle("fake:lazy", FakeListChatModel(
        responses=['{"applicable_items": [], "applicable_flows": []}']), 0.0, False)
    documents = [{"doc_id": "QS-AS-001", "rev": "F", "clauses": [
        {"no": "3", "title": "안전 체결부 변경",
         "text": "체결 토크를 전수 검사하고(EXT-AS-01), 추적성을 확보한다(EXT-AS-02)."}]}]
    result = asyncio.run(judge_agent.judge(
        lazy, "브레이크 호스 브래킷 협력사 변경", {"shop": "의장", "change_types": ["Material"]},
        documents, enabled=True, flow_enabled=True))
    assert [c["id"] for c in result["items"]] == ["EXT-AS-01", "EXT-AS-02"]
    assert result["safety_forced"] == ["EXT-AS-01", "EXT-AS-02"]


def test_structured_output_failure_falls_back(tmp_path):
    """LLM이 JSON이 아닌 답을 내면 Agent가 키워드 규칙으로 fallback한다 (W6 정신)."""
    import asyncio

    from agent.agents import classifier
    from agent.llm.handle import LLMHandle
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    broken = LLMHandle("fake:broken", FakeListChatModel(responses=["모르겠습니다"]), 0.0, False)
    result, _, fallback = asyncio.run(classifier.classify(broken, DATASET[7]["input"]))
    assert fallback
    assert result["shop"] == "차체" and result["equipment_ids"] == ["BD-RB-301", "BD-RB-302"]
