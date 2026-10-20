"""관리자 기능·피드백·평가 테스트 — LangSmith 없이(추적 꺼짐) 확인할 수 있는 계약을 검증한다.

실제 LangSmith 연동(실행 조회, 피드백 기록, 실험)은 네트워크와 키가 필요해 여기서 다루지 않는다.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.evaluation import EVALUATORS, EvaluationManager, ev_f1, ev_grade, ev_layers
from app.main import create_app

CASE_08 = "차체 대시 패널 라인 용접 로봇(BD-RB-301, BD-RB-302)의 용접 전류 조건을 변경합니다."
DATASET = [json.loads(line) for line in
           (Path(__file__).resolve().parent.parent / "eval" / "4m_dataset.jsonl")
           .read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    settings = Settings(llm_backend="fake", db_path=tmp_path_factory.mktemp("db") / "a.db")
    with TestClient(create_app(settings)) as c:
        yield c


def test_langsmith_status_when_tracing_disabled(client):
    body = client.get("/api/v1/admin/langsmith").json()
    assert body["enabled"] is False and body["reachable"] is False
    assert body["admin_auth"] is False


def test_runs_return_503_when_tracing_disabled(client):
    r = client.get("/api/v1/admin/runs")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "http_503"


def test_evaluation_requires_langsmith(client):
    r = client.post("/api/v1/admin/evaluations", json={"profiles": ["baseline"]})
    assert r.status_code == 503


def test_feedback_is_stored_locally_even_without_langsmith(client):
    review = client.post("/api/v1/reviews", json={"message": CASE_08}).json()
    r = client.post(f"/api/v1/reviews/{review['id']}/feedback",
                    json={"score": 0, "comment": "EXT-EQ-01 근거가 부족해요"})
    assert r.status_code == 201
    fb = r.json()
    assert fb["score"] == 0 and fb["langsmith_feedback_id"] is None   # 추적 꺼짐
    listed = client.get(f"/api/v1/reviews/{review['id']}/feedback").json()
    assert [f["id"] for f in listed] == [fb["id"]]
    admin = client.get("/api/v1/admin/feedback").json()
    assert admin[0]["id"] == fb["id"] and admin[0]["request"] == CASE_08


@pytest.mark.parametrize("payload", [{"score": 5}, {}, {"score": 1, "comment": "x" * 1001}])
def test_feedback_validation(client, payload):
    review = client.get("/api/v1/reviews", params={"limit": 1}).json()["items"][0]
    assert client.post(f"/api/v1/reviews/{review['id']}/feedback", json=payload).status_code == 422


def test_feedback_for_unknown_review_is_404(client):
    assert client.post("/api/v1/reviews/rv-nope/feedback", json={"score": 1}).status_code == 404


def test_admin_token_is_enforced(tmp_path):
    settings = Settings(llm_backend="fake", db_path=tmp_path / "t.db", admin_token="s3cret")
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/v1/admin/langsmith").status_code == 401
        assert c.get("/api/v1/admin/langsmith",
                     headers={"X-Admin-Token": "wrong"}).status_code == 401
        ok = c.get("/api/v1/admin/langsmith", headers={"X-Admin-Token": "s3cret"})
        assert ok.status_code == 200 and ok.json()["admin_auth"] is True
        assert c.get("/api/v1/health").status_code == 200   # 일반 API는 영향 없음


def test_evaluators_score_against_reference():
    ref = DATASET[7]["expected"]   # case-08
    perfect = {"checklist_ids": ref["required_items"] + ref["extra_items"] + ref["downstream_items"],
               "grade": "B", "shop": "차체", "change_types": ["Method"]}
    assert ev_f1(perfect, ref)["score"] == 1.0
    assert ev_grade(perfect, ref)["score"] == 1
    layers = {r["key"]: r["score"] for r in ev_layers(perfect, ref)["results"]}
    assert layers == {"recall_required": 1.0, "recall_document": 1.0, "recall_field": 1.0}

    sloppy = {**perfect, "checklist_ids": ["COM-01", "EXT-PR-01"], "grade": "A"}
    assert ev_f1(sloppy, ref)["score"] < 0.3
    assert ev_grade(sloppy, ref)["score"] == 0
    assert len(EVALUATORS) == 6


def test_evaluation_target_produces_scorable_outputs(client):
    """평가 대상 함수가 기능 스위치별 그래프로 실행돼 채점 가능한 출력을 낸다."""
    manager = EvaluationManager(client.app.state.runtime, client.app.state.langsmith)
    case = DATASET[7]
    # MCP 연결은 TestClient의 이벤트 루프에 묶여 있으므로 같은 루프(portal)에서 실행한다
    improved = client.portal.call(manager._target("improved"), {"message": case["input"]})
    baseline = client.portal.call(manager._target("baseline"), {"message": case["input"]})
    assert ev_f1(improved, case["expected"])["score"] == 1.0
    assert ev_f1(baseline, case["expected"])["score"] < 1.0
    assert improved["latency_s"] >= 0 and improved["review_status"] == "검토 완료"


def test_runs_of_project_without_runs_is_empty_list(monkeypatch):
    """LangSmith 프로젝트가 아직 없으면(첫 실행 전) 500이 아니라 빈 목록."""
    from langsmith.utils import LangSmithNotFoundError

    from app.langsmith_service import LangSmithService

    class FakeClient:
        def list_runs(self, **kwargs):
            raise LangSmithNotFoundError("Project not found")

    service = LangSmithService("new-project")
    monkeypatch.setattr(LangSmithService, "enabled", property(lambda self: True))
    service.__dict__["client"] = FakeClient()
    assert service._list_runs(limit=5, error_only=False) == []
