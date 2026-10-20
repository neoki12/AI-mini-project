"""4M 변경 영향 검토 서비스 — FastAPI 애플리케이션 패키지.

- config.py        : 환경변수 기반 설정 (Settings)
- runtime.py       : 프로세스당 1회 생성되는 Agent 런타임 (MCP 연결, LLM, 그래프, 저장소)
- schemas.py       : REST API 요청/응답 스키마
- review_store.py  : 검토 이력 저장소 (SQLite)
- errors.py        : 에러 응답 규격과 예외 처리
- routers/         : /api/v1 라우터 (health, chat, reviews) + 기존 경로 호환
- main.py          : create_app() 팩토리
"""
