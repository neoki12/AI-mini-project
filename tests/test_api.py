"""REST API 테스트 — fake 백엔드(결정론)와 임시 DB로 실제 앱을 띄워 HTTP로 검증한다.

MCP 서버는 실제 subprocess로 기동된다(모듈당 1회). LLM 호출은 없다.

실행:
    .venv/bin/python3 -m pytest tests/test_api.py -q
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

CASE_08 = "차체 대시 패널 라인 용접 로봇(BD-RB-301, BD-RB-302)의 용접 전류 조건을 변경합니다."


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    settings = Settings(llm_backend="fake", mcp_flaky_first_call=False,
                        db_path=tmp_path_factory.mktemp("db") / "test.db")
    with TestClient(create_app(settings)) as c:
        yield c


def _sse_events(text: str) -> list:
    events = []
    for frame in text.split("\n\n"):
        if frame.startswith("data: "):
            payload = frame[len("data: "):]
            events.append(payload if payload == "[DONE]" else json.loads(payload))
    return events


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["creation_count"] >= 1
    assert body["llm_backend"] == "fake"
    assert r.headers["X-Request-ID"]


def test_request_id_is_echoed(client):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "req-test-1"})
    assert r.headers["X-Request-ID"] == "req-test-1"


def test_chat_small_talk_routes_to_chat(client):
    r = client.post("/api/v1/chat", json={"message": "안녕, 너는 누구야?", "thread_id": "t-chat"})
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"]["route"] == "chat"
    assert body["reply"]


def test_chat_remembers_session(client):
    client.post("/api/v1/chat", json={"message": "제 이름은 민수입니다", "thread_id": "t-name"})
    r = client.post("/api/v1/chat", json={"message": "제 이름이 뭐였죠?", "thread_id": "t-name"})
    assert "민수" in r.json()["reply"]


def test_create_review_returns_structured_result(client):
    r = client.post("/api/v1/reviews", json={"message": CASE_08})
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("rv-")
    assert body["shop"] == "차체"
    assert body["change_types"] == ["Method"]
    assert {d["doc_id"] for d in body["documents"]} >= {"QS-CM-001", "QS-BD-001"}
    abnormal = {f["target"] for f in body["field_findings"] if f["abnormal"]}
    assert {"BD-RB-301", "BD-RB-302"} <= abnormal
    assert body["metadata"]["route"] == "review"
    # 멀티 Agent 결과 — 체크리스트, 등급, 검토 상태
    ids = {i["id"] for i in body["checklist"]}
    assert {"COM-01", "MET-01", "EXT-BD-01", "EXT-EQ-01"} <= ids
    layers = {i["layer"] for i in body["checklist"]}
    assert layers == {"required", "document", "field"}
    assert body["grading"]["grade"] == "B"
    assert body["review_status"] == "검토 완료"
    assert body["metadata"]["features"]["gate_4m"] is True


def test_review_forces_review_route_even_for_ambiguous_text(client):
    """검토 엔드포인트는 라우팅 LLM을 건너뛰므로 잡담처럼 보이는 문장도 검토 경로를 탄다."""
    r = client.post("/api/v1/reviews", json={"message": "도어 트림 작업자 한 명 늘려요"})
    assert r.status_code == 201
    route_event = r.json()["events"][0]
    assert route_event["type"] == "RouteDecided"
    assert route_event["route"] == "review" and route_event["forced"] is True
    assert route_event["message"] == "검토 요청으로 접수했어요"


def test_review_get_and_list(client):
    created = client.post("/api/v1/reviews", json={"message": CASE_08}).json()
    got = client.get(f"/api/v1/reviews/{created['id']}")
    assert got.status_code == 200
    assert got.json() == created

    listing = client.get("/api/v1/reviews", params={"limit": 1}).json()
    assert listing["total"] >= 1
    assert listing["items"][0]["id"] == created["id"]   # 최신순


def test_review_not_found(client):
    r = client.get("/api/v1/reviews/rv-missing")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("payload", [{"message": ""}, {}, {"message": "x" * 2001},
                                     {"message": "ok", "thread_id": "bad id!"}])
def test_review_validation_error(client, payload):
    r = client.post("/api/v1/reviews", json=payload)
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"]


def test_chat_stream_emits_events_and_done(client):
    r = client.get("/api/v1/chat/stream", params={"message": CASE_08, "thread_id": "t-sse"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(r.text)
    types = [e["type"] for e in events if isinstance(e, dict)]
    assert events[0] == {**events[0], "type": "NodeStarted", "node": "route"}
    assert [t for t in types if t not in ("NodeStarted", "NodeFinished")][0] == "RouteDecided"
    assert "PlanCreated" in types and "TaskCompleted" in types
    assert types[-1] == "FinalAnswer"
    assert events[-1] == "[DONE]"


def test_legacy_routes_still_work(client):
    assert client.get("/health").status_code == 200
    assert client.get("/version").json()["supervisor_version"] == "v2"
    r = client.post("/chat", json={"message": CASE_08, "thread_id": "t-legacy"})
    assert r.status_code == 200
    assert r.json()["metadata"]["route"] == "review"


def test_openapi_lists_v1_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/v1/health", "/api/v1/chat", "/api/v1/chat/stream",
                 "/api/v1/reviews", "/api/v1/reviews/{review_id}"):
        assert path in paths


def _fail_tool_calls(client, monkeypatch):
    from agent.mcp_client import MCPToolError
    mcp = client.app.state.runtime.deps.mcp

    async def broken(name, arguments, server="ops"):
        raise MCPToolError(name, "데이터 소스를 읽을 수 없습니다 (test)")
    monkeypatch.setattr(mcp, "call_tool", broken)


def _fail_llm(client, monkeypatch):
    import httpx
    deps = client.app.state.runtime.deps

    async def down(*args, **kwargs):
        raise httpx.ConnectError("LLM down (test)")
    monkeypatch.setattr(deps.fast_llm, "structured", down)


def test_mcp_tool_failure_degrades_to_needs_check(client, monkeypatch):
    """설비 조회가 실패해도 검토는 끝나고, 상태는 '추가 확인 필요' + 경고 (조회한 척하지 않는다)."""
    _fail_tool_calls(client, monkeypatch)
    r = client.post("/api/v1/reviews", json={"message": CASE_08})
    assert r.status_code == 201
    body = r.json()
    assert body["review_status"] == "추가 확인 필요"
    assert "설비 BD-RB-301 상태를 조회하지 못했습니다." in body["warnings"]
    failed = [f for f in body["field_findings"] if f["failed"]]
    assert {f["target"] for f in failed} >= {"BD-RB-301", "BD-RB-302"}
    assert "EXT-EQ-01" not in {i["id"] for i in body["checklist"]}   # 모르는 상태로 판정하지 않음
    assert body["reply"].startswith("⚠️ 추가 확인 필요")


def test_llm_failure_returns_502(client, monkeypatch):
    _fail_llm(client, monkeypatch)
    r = client.post("/api/v1/reviews", json={"message": CASE_08})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "agent_failed"


def test_llm_failure_in_stream_sends_error_event(client, monkeypatch):
    _fail_llm(client, monkeypatch)
    r = client.get("/api/v1/chat/stream", params={"message": CASE_08, "thread_id": "t-err"})
    events = _sse_events(r.text)
    assert r.status_code == 200
    assert events[-2]["type"] == "Error" and events[-2]["code"] == "agent_failed"
    assert events[-1] == "[DONE]"


def test_health_reports_mcp_servers(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["mcp_servers"]["ops"] == {"name": "capstone-4m-ops", "version": "1.1.0",
                                          "ok": True}


def test_review_stream_shows_activity_and_saves(client):
    r = client.post("/api/v1/reviews/stream", json={"message": CASE_08})
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert events[-1] == "[DONE]"
    body = [e for e in events if isinstance(e, dict)]

    started = [e["node"] for e in body if e["type"] == "NodeStarted"]
    for node in ("classify", "plan", "gate", "standards", "field", "judge", "assess",
                 "write", "validate"):
        assert node in started
    finished = {e["node"]: e for e in body if e["type"] == "NodeFinished"}
    assert set(started) == set(finished)
    assert all(e["elapsed_ms"] >= 0 for e in finished.values())

    # 모든 활동 이벤트에 사람이 읽을 문장과 시각이 붙는다
    for e in body:
        if e["type"] not in ("AnswerToken", "FinalAnswer", "ReviewSaved", "NodeFinished"):
            assert e.get("message"), e
        if e["type"] != "ReviewSaved":
            assert isinstance(e["ts"], int)
    assert any("BD-RB-301 팁 교체 주기 초과" in e.get("message", "") for e in body)
    assert any(e["type"] == "AnswerToken" for e in body)
    assert not any(e["type"] == "RunCompleted" or "state" in e for e in body)   # 내부 상태 비노출

    saved = next(e for e in body if e["type"] == "ReviewSaved")
    review = client.get(f"/api/v1/reviews/{saved['id']}").json()
    assert review["grading"]["grade"] == "B"
    assert {"COM-01", "EXT-BD-01", "EXT-EQ-01"} <= {i["id"] for i in review["checklist"]}
    assert any(e["type"] == "NodeStarted" for e in review["events"])   # 처리 과정 보존


def test_review_detail_events_have_messages(client):
    created = client.post("/api/v1/reviews", json={"message": CASE_08}).json()
    messages = [e.get("message") for e in created["events"]]
    assert messages and all(messages)
