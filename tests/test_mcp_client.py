"""MCP 클라이언트 테스트 — 실제 stdio subprocess로 mcp_server.py에 연결해 운영 규약을 확인한다.

- 도구 오류(is_error) → MCPToolError
- 응답 지연 → 시간 제한(asyncio.TimeoutError) → with_retry가 재시도
- 요청 직렬화 잠금 없음 → 병렬 호출이 동시에 진행
- ping → 서버별 연결 상태
- 연결 끊김 → 한 번 재연결 후 같은 요청 재시도
"""
import asyncio
import time

import pytest

from agent.mcp_client import MCPClient, MCPToolError
from agent.retry import with_retry


def run_with_client(fn, **kwargs):
    async def main():
        client = MCPClient(**kwargs)
        await client.start()
        try:
            return await fn(client)
        finally:
            await client.stop()
    return asyncio.run(main())


def test_start_records_server_info_and_ping():
    async def check(c):
        return c.server_info, await c.ping()
    info, ping = run_with_client(check)
    assert info["ops"]["name"] == "capstone-4m-ops"
    assert ping == {"ops": True, "docs": True}


def test_call_tool_returns_structured_content():
    data = run_with_client(lambda c: c.call_tool("get_equipment_status", {"target": "BD-RB-301"}))
    assert data["found"] is True and data["equipment"][0]["id"] == "BD-RB-301"


def test_tool_error_becomes_mcp_tool_error():
    async def call(c):
        with pytest.raises(MCPToolError) as exc:
            await c.call_tool("get_equipment_status", {"target": "bad id"})
        return exc.value
    err = run_with_client(call)
    assert err.tool == "get_equipment_status" and "pattern" in err.message


def test_slow_response_times_out_and_is_retried():
    async def call(c):
        session = c.sessions["ops"]
        original = session.call_tool
        calls = {"n": 0}

        async def slow_once(name, arguments):
            calls["n"] += 1
            if calls["n"] == 1:
                await asyncio.sleep(1.0)   # 시간 제한(0.2초) 초과
            return await original(name, arguments)
        session.call_tool = slow_once
        data, retries = await with_retry(c.call_tool, "get_production_status",
                                         {"line": "BD-FLOOR"}, base_delay=0.01)
        return data, retries
    data, retries = run_with_client(call, request_timeout=0.2)
    assert retries == 1 and data["status"] == "running"


def test_parallel_calls_are_not_serialized():
    """잠금이 있으면 5개 호출이 순차로 진행돼 지연이 5배가 된다."""
    async def call(c):
        session = c.sessions["ops"]
        original = session.call_tool

        async def delayed(name, arguments):
            await asyncio.sleep(0.2)
            return await original(name, arguments)
        session.call_tool = delayed
        started = time.perf_counter()
        await asyncio.gather(*(c.call_tool("get_production_status", {"line": "BD-FLOOR"})
                               for _ in range(5)))
        return time.perf_counter() - started
    assert run_with_client(call) < 0.6


def test_startup_failure_cleans_up_subprocesses(tmp_path):
    """기동이 실패하면 이미 띄운 서버까지 정리하고 오류를 올린다 (멈추지 않는다)."""
    broken = tmp_path / "broken_server.py"
    broken.write_text("import sys; sys.exit(1)\n")
    from agent.mcp_client import DEFAULT_SERVER_SCRIPTS

    async def main():
        client = MCPClient(server_scripts={"ops": DEFAULT_SERVER_SCRIPTS["ops"], "bad": broken},
                           startup_timeout=5.0)
        with pytest.raises(BaseException):
            await client.start()
        return client.sessions
    started = time.perf_counter()
    assert asyncio.run(main()) == {}
    assert time.perf_counter() - started < 15


def test_reconnects_after_server_connection_is_lost():
    """MCP 서버 연결이 끊기면 다음 요청에서 한 번 재연결한 뒤 그대로 성공한다."""
    async def call(c):
        await c._conns["ops"].close()   # 서버 subprocess 종료 = 연결 끊김
        data = await c.call_tool("get_equipment_status", {"target": "BD-RB-301"})
        return data, c.reconnects, await c.ping()
    data, reconnects, ping = run_with_client(call)
    assert data["found"] is True
    assert reconnects == 1
    assert ping == {"ops": True, "docs": True}


def test_ping_reconnects_dead_connection():
    async def call(c):
        await c._conns["docs"].close()
        return await c.ping(), c.reconnects
    ping, reconnects = run_with_client(call)
    assert ping == {"ops": True, "docs": True} and reconnects == 1
