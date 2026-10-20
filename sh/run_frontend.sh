#!/usr/bin/env bash
#
# 4M 변경 영향 검토 — Vue 프론트엔드 개발 서버(Vite, http://localhost:5173)를 띄운다.
#
# /api 요청은 백엔드(http://127.0.0.1:8100)로 프록시되므로 먼저 백엔드를 띄워야 한다:
#   bash sh/run_agent_ollma.sh   (로컬 Ollama)
#   bash sh/run_agent_openai.sh  (OpenAI API, 과금)
#   LLM_BACKEND=fake .venv/bin/python3 server.py   (결정론 fake, LLM 없음)
#
# 운영처럼 서버 하나로 쓰려면: bash sh/build_frontend.sh 후 http://127.0.0.1:8100 접속.
# 기존 단일 HTML 채팅 화면(web_chat.html)은 python3 web_demo_server.py (8600)로 그대로 쓸 수 있다.
#
# 종료하려면 이 터미널에서 Ctrl+C.
#
set -euo pipefail
cd "$(dirname "$0")/../frontend"

command -v npm >/dev/null 2>&1 \
    || { echo "ERROR: Node.js(npm)가 필요합니다. https://nodejs.org 에서 설치하세요."; exit 1; }

if ! curl -s --max-time 2 http://127.0.0.1:8100/api/v1/health >/dev/null 2>&1; then
    echo "⚠️  백엔드(http://127.0.0.1:8100)가 응답하지 않습니다 — 화면은 뜨지만 요청은 실패합니다."
fi

[ -d node_modules ] || npm install --no-audit --no-fund
lsof -ti:5173 | xargs kill -9 2>/dev/null || true

echo "프론트엔드: http://localhost:5173"
npm run dev
