"""전문 Agent — Supervisor 그래프(agent/graph.py)가 순서와 병렬 실행을 조율한다.

| Agent | 모델 | 역할 |
|---|---|---|
| router      | fast LLM  | 잡담(chat)과 4M 검토(review) 분기 |
| chat        | fast LLM  | 잡담 응답 (세션 기억) |
| classifier  | fast LLM  | 공장, 변경 유형, 설비·라인 식별 |
| planner     | fast LLM  | MCP Prompt 절차에 따른 조사 계획 |
| gate        | 코드      | 권위 게이트 — 필수 조사 task 강제, 잘못된 task 제거 |
| standards   | MCP       | 표준서·검사 기준 조회 (Resource) |
| field_data  | MCP + 코드 | 설비·라인 상태 조회 (Tool) + 현장 데이터 항목 판정 |
| judge       | fast LLM  | 조건부 조항·공정 간 영향 규칙이 이번 요청에 해당하는지 판정 |
| assessor    | 코드      | 검증 항목 체크리스트, 변경 등급, 초기유동관리 |
| writer      | quality LLM | 검토 보고 작성 (토큰 스트리밍) |
| validator   | 코드      | 항목 누락 탐지, 검토 상태 결정 |

LLM을 쓰는 Agent는 구조화 출력 실패(StructuredOutputError) 시 domain_4m의 규칙으로
fallback하고 그 사실을 반환해 이벤트로 남긴다.
"""
