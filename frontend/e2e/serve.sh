#!/usr/bin/env sh
# E2E용 서버 — fake LLM 백엔드가 빌드된 화면(frontend/dist)과 API를 함께 서빙한다.
# 매번 빈 DB로 시작하고 LangSmith로 추적을 보내지 않는다.
set -eu
cd "$(dirname "$0")/../.."
PY="${PYTHON:-python}"
[ -x .venv/bin/python ] && [ -z "${PYTHON:-}" ] && PY=.venv/bin/python
DB="${TMPDIR:-/tmp}/4m-e2e-$$.db"
rm -f "$DB"
export LLM_BACKEND=fake SUPERVISOR_VERSION=v2 APP_DB_PATH="$DB" \
       EMBEDDING_BACKEND=fake RAG_INDEX_DIR=memory \
       LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false
exec "$PY" -m uvicorn server:app --host 127.0.0.1 --port "${E2E_PORT:-8199}" --log-level warning
