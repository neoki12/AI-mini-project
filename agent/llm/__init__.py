"""LangChain 채팅 모델 계층.

- handle.py    : LLMHandle — 구조화 출력·스트리밍·토큰/비용 집계를 한곳에서 처리
- factory.py   : LLM_BACKEND(fake/ollama/openai)에 맞는 fast/quality 핸들 생성
- fake_chat.py : 규칙 기반 결정론 BaseChatModel (fake 백엔드, 테스트용)
"""
