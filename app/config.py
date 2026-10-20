"""환경변수 기반 설정.

코드 곳곳에서 os.environ을 직접 읽지 않고, 기동 시 Settings 하나로 모아 런타임에 주입한다.
테스트에서는 Settings(...)를 직접 만들어 create_app(settings)에 넘기면 환경변수 없이도
원하는 구성(fake 백엔드, 임시 DB 등)으로 앱을 띄울 수 있다.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from agent.deps import Features

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if not value:
        return default
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    llm_backend: str = "fake"                 # fake | ollama | openai
    supervisor_version: str = "v2"            # v1(legacy) | v2
    ollama_fast_model: str = "qwen2.5:7b"     # qwen3:0.6b는 분류 정확도가 낮아 기본값에서 제외
    ollama_quality_model: str = "qwen3:8b"
    openai_fast_model: str = "gpt-4o-mini"
    openai_quality_model: str = "gpt-4o"
    mcp_flaky_first_call: bool = False        # Wave 9 데모용 강제 타임아웃 — 데모 때만 MCP_FLAKY_FIRST_CALL=1
    features: Features = field(default_factory=Features)   # Baseline/Improved 기능 스위치
    db_path: Path = PROJECT_DIR / "session.db"
    langsmith_project: str = "capstone-4m-agent"   # 관리자 화면이 조회할 LangSmith 프로젝트
    admin_token: str | None = None            # 설정하면 /api/v1/admin/*에 X-Admin-Token 필요
    cors_origins: list[str] = field(default_factory=lambda: [
        "http://localhost:5173", "http://127.0.0.1:5173",   # Vite 개발 서버 (Step 3)
        "http://localhost:8600", "http://127.0.0.1:8600",   # web_demo_server.py
    ])

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        # PIPELINE_PROFILE=baseline이면 전부 끄고, 개별 스위치(GATE_4M 등)로 덮어쓴다
        base = Features.baseline() if os.environ.get("PIPELINE_PROFILE") == "baseline" \
            else Features()
        features = Features(
            gate_4m=_bool("GATE_4M", base.gate_4m),
            judge_conditions=_bool("JUDGE_CONDITIONS", base.judge_conditions),
            flow_impact=_bool("FLOW_IMPACT", base.flow_impact),
            validator_4m=_bool("VALIDATOR_4M", base.validator_4m),
        )
        return cls(
            llm_backend=os.environ.get("LLM_BACKEND", defaults.llm_backend),
            supervisor_version=os.environ.get("SUPERVISOR_VERSION",
                                              defaults.supervisor_version),
            ollama_fast_model=os.environ.get("OLLAMA_FAST_MODEL", defaults.ollama_fast_model),
            ollama_quality_model=os.environ.get("OLLAMA_QUALITY_MODEL",
                                                defaults.ollama_quality_model),
            openai_fast_model=os.environ.get("OPENAI_FAST_MODEL", defaults.openai_fast_model),
            openai_quality_model=os.environ.get("OPENAI_QUALITY_MODEL",
                                                defaults.openai_quality_model),
            mcp_flaky_first_call=_bool("MCP_FLAKY_FIRST_CALL", defaults.mcp_flaky_first_call),
            features=features,
            db_path=Path(os.environ.get("APP_DB_PATH", str(defaults.db_path))),
            langsmith_project=(os.environ.get("LANGSMITH_PROJECT")
                               or os.environ.get("LANGCHAIN_PROJECT")
                               or defaults.langsmith_project),
            admin_token=os.environ.get("ADMIN_TOKEN") or None,
            cors_origins=_list("CORS_ORIGINS", defaults.cors_origins),
        )
