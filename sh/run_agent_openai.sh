#!/usr/bin/env bash
#
# all_total — 실제 OpenAI API로 에이전트를 "기동만" 해두는 스크립트.
#
# run_openai_test.sh처럼 자동으로 요청을 보내고 검증한 뒤 끝나는 것이 아니라,
# 서버를 켠 채로 그대로 떠 있게 두어 사용자가 직접 테스트해볼 수 있게 한다:
#   - curl로 /chat, /chat/stream 호출해보기 (manual_openai.md 사용 예 1~4)
#   - web_demo_server.py를 추가로 띄워 브라우저 채팅 화면으로 써보기 (사용 예 5)
#
# ⚠️ 실제 OpenAI 계정에 과금되는 원격 API 호출이다 — run_agent_ollma.sh(로컬 추론)와
# 달리, 이 스크립트가 떠 있는 동안 보내는 요청마다 실제 비용이 청구된다.
#
# 종료하려면 이 터미널에서 Ctrl+C.
#
set -euo pipefail
cd "$(dirname "$0")/.."

# 이 머신은 plain python3/python이 alias로 다른 경로를 가리켜 venv를 무시하는
# 경우가 있어, 이 프로젝트 전용 .venv가 있으면 PATH 맨 앞에 명시적으로 꽂아둔다.
[ -x ".venv/bin/python3" ] && export PATH="$PWD/.venv/bin:$PATH"

FAST_MODEL="${OPENAI_FAST_MODEL:-gpt-4o-mini}"
QUALITY_MODEL="${OPENAI_QUALITY_MODEL:-gpt-4o}"

# ── 0) 환경 변수 ───────────────────────────────────────────────────────
if [ -f .env ]; then
    set -a; source .env; set +a
else
    # LangSmith 키가 없어도 Agent는 동작한다 — 추적(관리자 기능)만 꺼진 채로 실행
    echo "⚠️  .env가 없어 LangSmith 추적 없이 실행합니다 (켜려면: cp .env.example .env 후 키 입력)."
fi
export LANGCHAIN_PROJECT="capstone-4m-openai"   # 백엔드별로 LangSmith 프로젝트 분리

if [ -z "${OPENAI_API_KEY:-}" ] || [ "$OPENAI_API_KEY" = "sk-..." ]; then
    echo "ERROR: OPENAI_API_KEY가 비어있거나 플레이스홀더입니다 — .env에 본인 키를 채우세요 (.env.example 참고)."
    exit 1
fi

echo "LangSmith: project=$LANGCHAIN_PROJECT tracing=${LANGCHAIN_TRACING_V2:-}"
echo "모델: fast=$FAST_MODEL / quality=$QUALITY_MODEL"
echo
echo "⚠️  에이전트가 떠 있는 동안 보내는 요청마다 실제 OpenAI API가 호출되어 계정에"
echo "   비용이 청구됩니다 (결제 수단 연결 여부·키가 본인 계정 것인지 확인하세요)."
read -r -p "계속하시겠습니까? [y/N] " CONFIRM
case "$CONFIRM" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "중단합니다."; exit 1 ;;
esac

# ── 1) 이전 실행 정리 ──────────────────────────────────────────────────
lsof -ti:8100 | xargs kill -9 2>/dev/null || true
# session.db(대화 이력·검토 이력)는 재시작해도 유지한다 — 초기화하려면 직접 삭제

cleanup() {
    echo
    echo "에이전트를 종료합니다..."
    lsof -ti:8100 | xargs kill -9 2>/dev/null || true
}
trap cleanup EXIT

# ── 2) 서버 기동 (백그라운드로 띄운 뒤 준비될 때까지 대기) ─────────────
LLM_BACKEND=openai SUPERVISOR_VERSION=v2 python3 server.py &
SERVER_PID=$!
for _ in $(seq 1 40); do
    curl -s http://127.0.0.1:8100/health >/dev/null 2>&1 && break
    sleep 0.5
done

echo
curl -s http://127.0.0.1:8100/health | python3 -m json.tool --no-ensure-ascii

cat <<EOF

################################################################
 에이전트가 떠 있습니다 (http://127.0.0.1:8100, LLM_BACKEND=openai)
 ⚠️  아래 요청들은 전부 실제 과금 호출입니다.
################################################################

지금 바로 테스트해볼 수 있는 방법:

1) curl로 말 걸어보기
   curl -s -X POST localhost:8100/api/v1/reviews -H 'Content-Type: application/json' \\
     -d '{"message":"차체 대시 패널 라인 용접 로봇(BD-RB-301, BD-RB-302)의 용접 전류 조건을 변경합니다. 검토해주세요","thread_id":"t-test"}' \\
     | python3 -m json.tool --no-ensure-ascii

2) 실시간 진행 상황 보기 (스트리밍)
   curl -sN -G "localhost:8100/chat/stream" \\
     --data-urlencode "message=협력사로부터 브레이크 호스 브래킷 부품의 4M 변경 신고가 접수됐습니다. 검토해주세요" \\
     --data-urlencode "thread_id=t-test-sse"

3) 브라우저 화면 (새 터미널에서)
   bash sh/run_frontend.sh          → http://localhost:5173 (개발 서버)
   또는 bash sh/build_frontend.sh 후 → http://127.0.0.1:8100 (서버 하나로)
   API 문서: http://127.0.0.1:8100/docs

더 자세한 사용 예는 manual_openai.md 참고. 종료하려면 이 터미널에서 Ctrl+C.
EOF

wait "$SERVER_PID"
