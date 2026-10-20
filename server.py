"""4M 변경 영향 검토 서비스 — 실행 진입점.

실제 앱은 app/main.py의 create_app()이 만든다. sh/run_agent_*.sh가 `python3 server.py`로
기동하므로 이 파일을 진입점으로 남겨 둔다.

    LLM_BACKEND=fake python3 server.py            # http://127.0.0.1:8100/docs
    uvicorn server:app --port 8100                # 같은 앱을 uvicorn으로 직접

설정은 환경변수로 준다 (app/config.py: LLM_BACKEND, SUPERVISOR_VERSION,
MCP_FLAKY_FIRST_CALL, APP_DB_PATH, CORS_ORIGINS 등).
"""
from app.main import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
