"""GET /api/v1/health — 기동 상태와 Agent 번들 정보."""
from fastapi import APIRouter, Depends

from ..dependencies import get_runtime
from ..runtime import AgentRuntime
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


async def health_body(runtime: AgentRuntime) -> dict:
    reachable = await runtime.deps.mcp.ping()
    servers = {name: {**runtime.deps.mcp.server_info.get(name, {}), "ok": ok}
               for name, ok in reachable.items()}
    status = "ok" if reachable and all(reachable.values()) else "degraded"
    return {"status": status, "mcp_servers": servers, "instance_id": runtime.instance_id,
            "creation_count": runtime.creation_count,
            "supervisor_version": runtime.deps.version,
            "llm_backend": runtime.settings.llm_backend,
            "fast_llm": runtime.deps.fast_llm.name,
            "quality_llm": runtime.deps.quality_llm.name}


@router.get("/health", response_model=HealthResponse)
async def health(runtime: AgentRuntime = Depends(get_runtime)):
    return await health_body(runtime)
