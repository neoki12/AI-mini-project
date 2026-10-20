"""Wave 2 — MCP 서버 여러 개를 subprocess(stdio)로 1회씩 기동해 재사용하는 클라이언트.

Wave 1의 교훈대로 서버(lifespan)에서 한 번만 연결을 만들고 모든 요청이 공유한다.
Wave 9 데모용으로, 프로세스 최초의 get_equipment_status 호출 1회는 일부러
asyncio.TimeoutError를 던진다(transient) — with_retry가 backoff 후 복구해야 한다.
Before/After 측정 때는 retry 횟수가 왜곡되므로 flaky_first_tool_call=False로 끈다
(server.py의 MCP_FLAKY_FIRST_CALL=0).

연결 대상은 "ops"(mcp_server.py — 4M 설비·라인 tool + 표준서 resource + prompt, 실제
사용)와 "docs"(mcp_server_docs.py — API 문서 resource만 제공, agent는 사용하지 않는
decoy) 두 서버다. resource/prompt를 요청할 때는 어느 서버가 그걸 들고 있는지 미리
알고 있지 않다고 가정하고, find_resource_template()/find_prompt()로 연결된 서버들을
순서대로 조회(list)해 이름이 맞는 걸 찾은 뒤에야 그 서버로 read_resource/get_prompt를
보낸다.

운영 규약
- 모든 요청에 시간 제한(request_timeout)을 건다. 초과하면 asyncio.TimeoutError — with_retry가
  일시 오류로 보고 재시도한다 (Wave 9).
- 도구가 is_error로 응답하면 MCPToolError로 바꾼다 (입력 오류·데이터 소스 장애). 호출한
  Agent가 그 항목만 "조회 실패"로 처리하고 검토는 계속한다.
- 요청 직렬화 잠금은 두지 않는다. ClientSession은 요청 ID로 응답을 구분하므로 동시에 여러
  요청을 보낼 수 있다 — 잠금이 있으면 병렬 조사(Wave 10b)가 사실상 순차 실행된다.
- 자동 재연결: 서버마다 연결을 전담하는 백그라운드 작업(_Connection)을 둔다. anyio 기반 stdio
  연결은 연 작업에서 닫아야 하므로, 요청 처리 중 끊긴 연결을 그 자리에서 다시 열 수 없다 — 전담
  작업을 새로 띄워 교체한다. 연결 끊김을 감지하면 한 번 재연결한 뒤 같은 요청을 다시 보낸다.
"""
import asyncio
import contextlib
import json
import logging
import os
import sys
from pathlib import Path

import anyio
from langsmith import traceable
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

try:   # mcp SDK 2.x는 MCPError, 1.x는 McpError
    from mcp.shared.exceptions import MCPError as McpError
except ImportError:
    from mcp.shared.exceptions import McpError

SERVER_DIR = Path(__file__).parent.parent
DEFAULT_SERVER_SCRIPTS = {
    "ops": SERVER_DIR / "mcp_server.py",
    "docs": SERVER_DIR / "mcp_server_docs.py",
}


def _attr(obj, *names):
    """mcp SDK 버전에 따라 pydantic 필드명이 camelCase(예: resourceTemplates,
    uriTemplate, 구버전 1.x)와 snake_case(예: resource_templates, uri_template,
    신버전 2.x)로 갈린다 — 이 프로젝트 안에도 시스템 python3(mcp 1.28.1, camelCase)와
    .venv(mcp 2.2.0, snake_case)가 섞여 있어 실행 환경마다 바뀐다. 둘 다 시도해서
    설치된 버전과 무관하게 동작하게 한다."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AttributeError(f"{type(obj).__name__!r} has none of {names!r}")


class MCPToolError(Exception):
    """MCP 도구가 is_error로 응답했을 때 (입력 형식 위반, 데이터 소스 장애 등)."""

    def __init__(self, tool: str, message: str):
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message


# 개별 MCP 요청이 실패한 것으로 보는 예외 — Agent는 그 항목만 실패 처리하고 계속 진행한다
MCP_REQUEST_ERRORS = (MCPToolError, McpError, asyncio.TimeoutError)


class MCPToolError(Exception):
    """MCP 도구가 is_error로 응답했을 때 (입력 형식 위반, 데이터 소스 장애 등)."""

    def __init__(self, tool: str, message: str):
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message


# 개별 MCP 요청이 실패한 것으로 보는 예외 — Agent는 그 항목만 실패 처리하고 계속 진행한다
MCP_REQUEST_ERRORS = (MCPToolError, McpError, asyncio.TimeoutError)

logger = logging.getLogger("agent")


def _is_disconnect(exc: BaseException) -> bool:
    """연결이 끊겨 재연결로 복구할 수 있는 오류인가 (도구 오류·시간 초과는 아님)."""
    if isinstance(exc, (anyio.ClosedResourceError, anyio.BrokenResourceError,
                        anyio.EndOfStream, ConnectionError, BrokenPipeError)):
        return True
    return isinstance(exc, McpError) and "closed" in str(exc).lower()


class _Connection:
    """MCP 서버 하나와의 stdio 연결을 전담하는 백그라운드 작업."""

    def __init__(self, name: str, script: Path, startup_timeout: float):
        self.name = name
        self.script = script
        self.startup_timeout = startup_timeout
        self.session: ClientSession | None = None
        self.info: dict = {}
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._ready: asyncio.Future | None = None

    async def open(self) -> dict:
        self._stop = asyncio.Event()
        self._ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run(), name=f"mcp-{self.name}")
        try:
            return await asyncio.wait_for(asyncio.shield(self._ready), self.startup_timeout)
        except BaseException:
            await self.close()
            raise

    async def _run(self) -> None:
        params = StdioServerParameters(command=sys.executable, args=[str(self.script)],
                                       env={**os.environ, "FASTMCP_LOG_LEVEL": "ERROR"})
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    info = _attr(init, "server_info", "serverInfo")
                    self.info = {"name": info.name, "version": info.version}
                    self.session = session
                    if not self._ready.done():
                        self._ready.set_result(self.info)
                    await self._stop.wait()
        except BaseException as exc:
            if not self._ready.done():
                if isinstance(exc, asyncio.CancelledError):
                    self._ready.cancel()
                else:
                    self._ready.set_exception(exc)
            elif not isinstance(exc, asyncio.CancelledError):
                logger.warning("mcp connection %s lost: %s", self.name, exc)
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            self.session = None

    async def close(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None and not self._task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 5.0)
            except BaseException:
                self._task.cancel()
                with contextlib.suppress(BaseException):
                    await self._task
        self.session = None


class MCPClient:
    def __init__(self, flaky_first_tool_call: bool = False,
                 server_scripts: dict[str, Path] | None = None,
                 flaky_tool: str = "get_equipment_status",
                 request_timeout: float = 15.0, startup_timeout: float = 30.0):
        self._server_scripts = server_scripts or DEFAULT_SERVER_SCRIPTS
        self._conns: dict[str, _Connection] = {}
        self._reconnect_locks: dict[str, asyncio.Lock] = {}
        self.server_info: dict[str, dict] = {}
        self.reconnects = 0
        self._flaky_pending = flaky_first_tool_call   # Wave 9 시뮬레이션
        self._flaky_tool = flaky_tool
        self.request_timeout = request_timeout
        self.startup_timeout = startup_timeout   # subprocess 기동은 요청보다 오래 걸린다

    @property
    def sessions(self) -> dict[str, ClientSession]:
        return {name: conn.session for name, conn in self._conns.items() if conn.session}

    async def start(self) -> None:
        """서버들을 기동한다. 하나라도 실패하면 이미 띄운 subprocess를 정리하고 오류를 올린다
        (정리하지 않으면 남은 subprocess 때문에 프로세스 종료가 멈춘다)."""
        try:
            for name, script in self._server_scripts.items():
                conn = _Connection(name, script, self.startup_timeout)
                self.server_info[name] = await conn.open()
                self._conns[name] = conn
                self._reconnect_locks[name] = asyncio.Lock()
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        for conn in list(self._conns.values()):
            await conn.close()
        self._conns = {}

    async def _reconnect(self, server: str, broken: _Connection | None) -> None:
        async with self._reconnect_locks[server]:
            if broken is not None and self._conns.get(server) is not broken:
                return   # 다른 요청이 이미 재연결했다
            old = self._conns[server]
            await old.close()
            conn = _Connection(server, self._server_scripts[server], self.startup_timeout)
            self.server_info[server] = await conn.open()
            self._conns[server] = conn
            self.reconnects += 1
            logger.warning("mcp server %s reconnected (총 %d회)", server, self.reconnects)

    async def _call(self, server: str, make):
        """요청을 보낸다. 연결이 끊겨 있으면 한 번 재연결한 뒤 다시 보낸다."""
        for attempt in (1, 2):
            conn = self._conns[server]
            try:
                if conn.session is None:
                    raise anyio.ClosedResourceError()
                return await asyncio.wait_for(make(conn.session), self.request_timeout)
            except Exception as exc:
                if attempt == 1 and _is_disconnect(exc):
                    await self._reconnect(server, conn)
                    continue
                raise

    async def ping(self) -> dict[str, bool]:
        """서버별 연결 상태 (헬스 체크용). 응답이 없으면 한 번 재연결을 시도한다."""
        status = {}
        for server in list(self._conns):
            try:
                await self._call(server, lambda s: asyncio.wait_for(s.send_ping(), 3.0))
                status[server] = True
            except Exception:
                try:
                    await self._reconnect(server, None)
                    status[server] = True
                except Exception:
                    status[server] = False
        return status

    @traceable(run_type="tool", name="mcp.call_tool")
    async def call_tool(self, name: str, arguments: dict, server: str = "ops") -> dict:
        if self._flaky_pending and name == self._flaky_tool:
            self._flaky_pending = False
            raise asyncio.TimeoutError("simulated transient timeout (Wave 9 demo)")
        result = await self._call(server, lambda s: s.call_tool(name, arguments))
        text = result.content[0].text if result.content else ""
        if _attr(result, "is_error", "isError"):
            raise MCPToolError(name, text or "unknown error")
        structured = _attr(result, "structured_content", "structuredContent")
        return structured if structured is not None else json.loads(text)

    @traceable(run_type="tool", name="mcp.list_resource_templates")
    async def list_resource_templates(self, server: str) -> list:
        result = await self._call(server, lambda s: s.list_resource_templates())
        return _attr(result, "resource_templates", "resourceTemplates")

    @traceable(run_type="tool", name="mcp.find_resource_template")
    async def find_resource_template(self, template_name: str) -> tuple[str, str]:
        """연결된 서버들을 순서대로 조회해 template_name을 제공하는 서버를 찾는다."""
        for server_name in self._conns:
            templates = await self.list_resource_templates(server_name)
            matched = next((t for t in templates if t.name == template_name), None)
            if matched is not None:
                return server_name, _attr(matched, "uri_template", "uriTemplate")
        raise ValueError(
            f"MCP resource template not found on any connected server: {template_name}")

    @traceable(run_type="tool", name="mcp.read_resource")
    async def read_resource(self, uri: str, server: str) -> str:
        result = await self._call(server, lambda s: s.read_resource(uri))
        return result.contents[0].text

    @traceable(run_type="tool", name="mcp.list_prompts")
    async def list_prompts(self, server: str) -> list:
        result = await self._call(server, lambda s: s.list_prompts())
        return result.prompts

    @traceable(run_type="tool", name="mcp.find_prompt")
    async def find_prompt(self, prompt_name: str) -> str:
        """연결된 서버들을 순서대로 조회해 prompt_name을 제공하는 서버를 찾는다."""
        for server_name in self._conns:
            prompts = await self.list_prompts(server_name)
            if any(p.name == prompt_name for p in prompts):
                return server_name
        raise ValueError(
            f"MCP prompt not found on any connected server: {prompt_name}")

    @traceable(run_type="tool", name="mcp.get_prompt")
    async def get_prompt(self, name: str, arguments: dict, server: str = "ops") -> str:
        result = await self._call(server, lambda s: s.get_prompt(name, arguments))
        return result.messages[0].content.text
