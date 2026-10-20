"""MCP 서버 단위 테스트 — fastmcp 메모리 내 클라이언트로 mcp_server.py를 직접 검증한다.

subprocess 없이 Tool·Resource·Prompt의 계약(입력 스키마, 출력 스키마, 오류 규약)을 확인한다.
"""
import asyncio
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import mcp_server


def run(coro):
    return asyncio.run(coro)


async def _with_client(fn):
    async with Client(mcp_server.mcp) as client:
        return await fn(client)


def test_server_identity():
    assert mcp_server.mcp.name == "capstone-4m-ops"
    assert mcp_server.mcp.version == mcp_server.SERVER_VERSION
    assert "가상 데이터" in mcp_server.mcp.instructions


def test_tools_publish_input_output_schema_and_read_only_hint():
    tools = {t.name: t for t in run(_with_client(lambda c: c.list_tools()))}
    assert set(tools) == {"get_equipment_status", "get_production_status", "search_standards"}
    for name, tool in tools.items():
        dumped = tool.model_dump()
        schema = dumped.get("input_schema") or dumped.get("inputSchema")
        if name != "search_standards":
            param = next(iter(schema["properties"].values()))
            assert param["pattern"] == mcp_server.ID_PATTERN
        assert dumped.get("output_schema") or dumped.get("outputSchema")
        hints = dumped["annotations"]
        assert (hints.get("read_only_hint") or hints.get("readOnlyHint")) is True


def test_equipment_by_id_and_by_line():
    by_id = run(_with_client(lambda c: c.call_tool("get_equipment_status",
                                                   {"target": "BD-RB-301"}))).structured_content
    assert by_id["found"] is True
    assert by_id["equipment"][0] | {"abnormal": True, "status": "팁 교체 주기 초과"} \
        == by_id["equipment"][0]
    by_line = run(_with_client(lambda c: c.call_tool("get_equipment_status",
                                                     {"target": "BD-DASH"}))).structured_content
    assert {e["id"] for e in by_line["equipment"]} == {"BD-RB-301", "BD-RB-302"}


def test_unknown_id_is_not_an_error_but_found_false():
    """형식은 맞지만 없는 대상 → 정상 응답 + found=false (오류와 구분)."""
    eq = run(_with_client(lambda c: c.call_tool("get_equipment_status",
                                                {"target": "ZZ-NOPE-1"}))).structured_content
    assert eq == {**eq, "found": False, "equipment": []}
    line = run(_with_client(lambda c: c.call_tool("get_production_status",
                                                   {"line": "ZZ-LINE"}))).structured_content
    assert line["found"] is False and line["status"] == "unknown"


@pytest.mark.parametrize("bad", ["bad id", "bd-rb-301", "", "A" * 40, "BD-RB-301; DROP"])
def test_invalid_id_format_is_rejected(bad):
    async def call(c):
        return await c.call_tool("get_equipment_status", {"target": bad}, raise_on_error=False)
    result = run(_with_client(call))
    assert result.is_error


def test_data_source_failure_is_reported_as_tool_error(tmp_path, monkeypatch):
    """데이터 파일을 읽을 수 없으면 원인을 알리는 ToolError (내부 상세 대신 의도한 메시지)."""
    monkeypatch.setattr(mcp_server, "DATA_DIR", tmp_path)
    with pytest.raises(ToolError, match="데이터 소스를 읽을 수 없습니다: equipment.json"):
        run(_with_client(lambda c: c.call_tool("get_equipment_status", {"target": "BD-RB-301"})))


def test_production_running_line_has_body_tracking_fields():
    line = run(_with_client(lambda c: c.call_tool("get_production_status",
                                                  {"line": "BD-FLOOR"}))).structured_content
    assert line["status"] == "running" and line["wip_bodies"] == 42
    assert line["body_no_range"].startswith("B2610-")


def test_resource_templates_and_standards():
    templates = run(_with_client(lambda c: c.list_resource_templates()))
    names = {t.name for t in templates}
    assert {"get_shop_standard", "get_inspection_criteria"} <= names

    text = run(_with_client(lambda c: c.read_resource("std://shop-standard/body")))[0].text
    assert "doc_id: QS-BD-001" in text and "## 조항 3" in text
    common = run(_with_client(lambda c: c.read_resource("std://shop-standard/common")))[0].text
    assert "doc_id: QS-CM-001" in common


@pytest.mark.parametrize("uri", ["std://shop-standard/nope", "std://inspection-criteria/common"])
def test_unknown_shop_resource_is_an_error(uri):
    with pytest.raises(Exception, match="알 수 없는 공장"):
        run(_with_client(lambda c: c.read_resource(uri)))


def test_rule_resources_are_valid_json():
    rules = json.loads(run(_with_client(lambda c: c.read_resource("rule://required-items")))[0].text)
    flow = json.loads(run(_with_client(lambda c: c.read_resource("rule://process-flow")))[0].text)
    assert set(rules["rules"]) == {"Man", "Machine", "Material", "Method"}
    assert flow["flow"] == ["프레스", "차체", "도장", "의장"]


def test_review_prompt_renders_and_validates_arguments():
    prompt = run(_with_client(lambda c: c.get_prompt("4m_review",
                                                     {"shop": "차체", "request": "용접 전류 변경"})))
    text = prompt.messages[0].content.text
    assert "- 공장: 차체" in text and "검증 항목마다 [ID]" in text
    with pytest.raises(Exception, match="알 수 없는 공장"):
        run(_with_client(lambda c: c.get_prompt("4m_review", {"shop": "본사", "request": "x"})))


def test_search_standards_filters_by_shop_and_finds_conditional_clause():
    result = run(_with_client(lambda c: c.call_tool("search_standards", {
        "query": "프레스 1라인 후드 외판 드로잉 금형을 수정하려고 합니다",
        "shop": "프레스", "change_types": ["Machine"], "k": 4}))).structured_content
    assert result["chunk_count"] == 41 and len(result["hits"]) == 4
    assert {h["shop"] for h in result["hits"]} == {"프레스"}          # 다른 공장·공통 규정 제외
    assert ("QS-PR-001", "3") in {(h["doc_id"], h["clause"]) for h in result["hits"]}


@pytest.mark.parametrize("args", [{"query": ""}, {"query": "x", "k": 0}, {"query": "x", "k": 11},
                                  {"query": "x", "shop": "본사"}])
def test_search_standards_rejects_invalid_arguments(args):
    async def call(c):
        return await c.call_tool("search_standards", args, raise_on_error=False)
    assert run(_with_client(call)).is_error
