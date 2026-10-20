#!/usr/bin/env bash
#
# Vue 프론트엔드를 빌드해 frontend/dist를 만든다. 빌드 후에는 백엔드(server.py, 8100)가
# / 경로에서 화면을 직접 서빙한다 — http://127.0.0.1:8100 하나로 화면과 API를 함께 쓴다.
#
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -d node_modules ] || npm install --no-audit --no-fund
npm run build
echo "빌드 완료: frontend/dist — 백엔드를 (재)기동하면 http://127.0.0.1:8100 에서 화면이 열립니다."
